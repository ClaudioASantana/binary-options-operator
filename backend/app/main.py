"""
Binary Options Operator - Backend FastAPI com seguranca aprimorada.

Novos recursos:
- Decision Harness para fluxo de decisao unificado
- Circuit Breakers para protecao do sistema
- Confirmacao manual para conta real
- Limites absolutos de risco (hard-coded)
"""
import asyncio
import logging
import time
import os
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional

from app.engines.bot_instance import BotInstance
from app.engines.news import NewsFilter
from app.engines.circuit_breaker import get_circuit_breaker_manager, reset_circuit_breaker_manager
from app.engines.decision_harness import get_decision_harness, reset_decision_harness
from app.validators.risk_limits import AbsoluteLimits, RiskLimits

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[websocket] = "R_100"

    def set_watched_symbol(self, websocket: WebSocket, symbol: str):
        if websocket in self.active_connections:
            self.active_connections[websocket] = symbol

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            del self.active_connections[websocket]

    async def broadcast(self, message: dict):
        msg_str = json.dumps(message)
        msg_symbol = message.get("symbol")
        for connection, watched_symbol in list(self.active_connections.items()):
            if msg_symbol and msg_symbol != watched_symbol:
                continue
            try:
                await connection.send_text(msg_str)
            except Exception:
                pass


manager = ConnectionManager()
news_filter = NewsFilter()
DERIV_TOKEN = os.getenv("DERIV_API_TOKEN", "").strip()
DERIV_ENVIRONMENT = os.getenv("DERIV_ENVIRONMENT", "demo").strip()  # demo ou real

# --- SWARM STATE ---
MARKETS_TO_RUN = [
    "R_10", "R_25", "R_50", "R_75", "R_100",
    "1HZ10V", "1HZ25V", "1HZ50V", "1HZ75V", "1HZ100V",
    "RDBEAR", "RDBULL"
]
bots: dict[str, BotInstance] = {}

# Em ambiente real, exigir confirmacao manual
require_manual = (DERIV_ENVIRONMENT == "real")

watching_symbol = "R_100"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Iniciando ENXAME (Swarm) em ambiente {DERIV_ENVIRONMENT.upper()}...")
    if require_manual:
        logger.warning("⚠️ MODO REAL: Confirmacao manual OBRIGATORIA para todas as operacoes")
    
    start_tasks = []
    for sym in MARKETS_TO_RUN:
        bot = BotInstance(
            symbol=sym,
            token=DERIV_TOKEN,
            news_filter=news_filter,
            manager=manager,
            environment=DERIV_ENVIRONMENT,
            require_manual_confirmation=require_manual,
        )
        bots[sym] = bot
        start_tasks.append(bot.start())
    
    asyncio.gather(*start_tasks)
    
    yield
    
    logger.info("Desligando ENXAME...")
    for bot in bots.values():
        bot.stop()
    
    # Reset singletons
    reset_circuit_breaker_manager()
    reset_decision_harness()


from fastapi.middleware.cors import CORSMiddleware
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    global watching_symbol
    
    if watching_symbol in bots:
        b = bots[watching_symbol]
        await websocket.send_json({
            "event": "simulator",
            "symbol": watching_symbol,
            "data": b.paper_trader.get_state()
        })
    await websocket.send_json({"event": "active_symbol", "data": watching_symbol})
    
    try:
        while True:
            data = await websocket.receive_text()
            try:
                cmd = json.loads(data)
                
                if cmd.get("command") in ["WATCH_SYMBOL", "SET_SYMBOL"]:
                    new_sym = cmd.get("symbol")
                    if new_sym and new_sym in bots:
                        manager.set_watched_symbol(websocket, new_sym)
                        watching_symbol = new_sym
                        await manager.broadcast({"event": "active_symbol", "data": new_sym})
                        b = bots[new_sym]
                        await websocket.send_json({
                            "event": "simulator",
                            "symbol": new_sym,
                            "data": b.paper_trader.get_state()
                        })
                        await websocket.send_json({
                            "event": "catalog",
                            "symbol": new_sym,
                            "data": {
                                "catalog": b.global_catalog,
                                "active_config": b.active_config,
                                "auto_optimize": b.auto_optimize
                            }
                        })
                
                elif cmd.get("command") == "SET_CONFIG":
                    target_symbol = cmd.get("symbol", watching_symbol)
                    if target_symbol in bots:
                        b = bots[target_symbol]
                        b.active_config["timeframe"] = cmd.get("timeframe", 300)
                        b.active_config["candles"] = cmd.get("candles", 5)
                        b.active_config["gale"] = cmd.get("gale", 3)
                        b.active_config["rsi_oversold"] = cmd.get("rsi_oversold", 30)
                        b.active_config["rsi_overbought"] = cmd.get("rsi_overbought", 70)
                        b.paper_trader.max_gale = min(cmd.get("gale", 3), 3)  # Limite absoluto
                        logger.info(f"[{target_symbol}] Config: M{b.active_config['timeframe']//60} / {b.active_config['candles']}V / Gale {b.active_config['gale']}")
                        await manager.broadcast({
                            "event": "simulator",
                            "symbol": target_symbol,
                            "data": b.paper_trader.get_state()
                        })
                
                elif cmd.get("command") == "TOGGLE_AUTO_OPTIMIZE":
                    if watching_symbol in bots:
                        b = bots[watching_symbol]
                        b.auto_optimize = not b.auto_optimize
                        logger.info(f"[{watching_symbol}] Auto-Optimize: {b.auto_optimize}")
                        await websocket.send_json({
                            "event": "catalog",
                            "symbol": watching_symbol,
                            "data": {
                                "catalog": b.global_catalog,
                                "active_config": b.active_config,
                                "auto_optimize": b.auto_optimize
                            }
                        })
                
                elif cmd.get("command") == "TOGGLE_AUTO_OPTIMIZE_ALL":
                    is_active = cmd.get("active", True)
                    for sym, bot_inst in bots.items():
                        bot_inst.auto_optimize = is_active
                        logger.info(f"[{sym}] Auto-Optimize Global: {bot_inst.auto_optimize}")
                    if watching_symbol in bots:
                        b = bots[watching_symbol]
                        await websocket.send_json({
                            "event": "catalog",
                            "symbol": watching_symbol,
                            "data": {
                                "catalog": b.global_catalog,
                                "active_config": b.active_config,
                                "auto_optimize": b.auto_optimize
                            }
                        })
                
                elif cmd.get("command") == "CONFIRM_TRADE":
                    # Confirmacao manual de trade
                    decision_id = cmd.get("decision_id")
                    confirmed = cmd.get("confirmed", False)
                    if decision_id and watching_symbol in bots:
                        b = bots[watching_symbol]
                        await b.confirm_manual_trade(decision_id, confirmed)
                
                elif cmd.get("command") == "RESET_CIRCUIT_BREAKERS":
                    # Apenas em modo demo para testes
                    if DERIV_ENVIRONMENT == "demo":
                        reset_circuit_breaker_manager()
                        logger.info("Circuit breakers resetados (demo)")
                
            except Exception as e:
                logger.error(f"Erro processando WS: {e}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/status")
def get_status():
    if watching_symbol not in bots:
        return {"status": "running_swarm", "bots_active": len(bots)}
    
    b = bots[watching_symbol]
    return {
        "status": "running",
        "watched_symbol": watching_symbol,
        "environment": DERIV_ENVIRONMENT,
        "manual_confirmation_required": require_manual,
        "current_candle": b.get_active_builder().current_candle,
        "closed_candles_count": len(b.get_active_builder().closed_candles),
        "active_config": b.active_config,
        "auto_optimize": b.auto_optimize,
        "simulator": b.paper_trader.get_state(),
        "news_status": news_filter.check_safety(int(time.time()))
    }


@app.get("/portfolio")
def get_portfolio():
    total_balance = sum(b.paper_trader.balance for b in bots.values())
    total_pnl = sum(b.paper_trader.get_pnl() for b in bots.values())
    return {
        "total_balance": total_balance,
        "total_pnl": total_pnl,
        "bots_count": len(bots)
    }


@app.get("/api/risk-limits")
def get_risk_limits():
    """Retorna limites de risco efetivos (absolutos e configuraveis)."""
    absolute = AbsoluteLimits()
    risk_limits = RiskLimits()
    
    return {
        "effective": risk_limits.get_effective_limits(),
        "absolute": {
            "max_gale": absolute.MAX_GALE_ABSOLUTE,
            "max_stake_usd": absolute.MAX_STAKE_ABSOLUTE_USD,
            "max_exposure_usd": absolute.MAX_EXPOSURE_ABSOLUTE_USD,
            "max_daily_loss_usd": absolute.MAX_DAILY_LOSS_ABSOLUTE_USD,
            "max_daily_gain_usd": absolute.MAX_DAILY_GAIN_ABSOLUTE_USD,
            "max_consecutive_losses": absolute.MAX_CONSECUTIVE_LOSSES_ABSOLUTE,
            "max_trades_per_day": absolute.MAX_TRADES_PER_DAY,
        }
    }


@app.get("/api/circuit-breakers")
def get_circuit_breakers():
    """Retorna status de todos os circuit breakers."""
    cb_manager = get_circuit_breaker_manager()
    status = cb_manager.get_status()
    
    # Converter para dict serializavel
    serializable_status = {}
    for key, breaker_status in status.items():
        serializable_status[key] = {
            "state": breaker_status.state.value,
            "cooldown_remaining_seconds": breaker_status.cooldown_remaining_seconds,
            "failure_count": breaker_status.failure_count,
        }
    
    can_trade, block_reason = cb_manager.can_trade()
    
    return {
        "can_trade": can_trade,
        "blocking_reason": block_reason,
        "breakers": serializable_status,
        "last_latency_ms": cb_manager.get_last_latency(),
    }


@app.post("/api/circuit-breakers/reset")
def reset_circuit_breakers_api():
    """Reseta todos os circuit breakers (apenas demo)."""
    if DERIV_ENVIRONMENT != "demo":
        raise HTTPException(status_code=403, detail="Apenas em modo demo")
    
    reset_circuit_breaker_manager()
    return {"status": "reset", "message": "Circuit breakers resetados"}


class OptimizeRequest(BaseModel):
    symbol: str


@app.post("/api/optimize")
async def api_optimize(req: OptimizeRequest):
    import sys
    scripts_path = os.path.join(os.path.dirname(__file__), '..', 'scripts')
    if scripts_path not in sys.path:
        sys.path.append(scripts_path)
    from optimizer import download_history, run_simulation
    
    results = []
    logger.info(f"[{req.symbol}] Baixando historico para otimizacao...")
    history_m5 = await download_history(req.symbol, 300, 5000)
    history_m1 = await download_history(req.symbol, 60, 5000)
    
    for history, timeframe_name in [(history_m5, "M5"), (history_m1, "M1")]:
        if not history:
            continue
        for consecutive_candles in [3, 5, 7, 9]:
            for max_gale in [1, 2, 3]:  # Limite absoluto de 3
                for rsi_combo in [(35, 65), (30, 70), (25, 75)]:
                    rsi_over, rsi_under = rsi_combo
                    res = run_simulation(
                        history,
                        consecutive_candles,
                        rsi_over,
                        rsi_under,
                        max_gale,
                        stake=10.0,
                        payout_rate=0.95
                    )
                    total = res['wins'] + res['losses']
                    win_rate = (res['wins'] / total * 100) if total > 0 else 0
                    results.append({
                        "timeframe": 300 if timeframe_name == "M5" else 60,
                        "timeframe_label": timeframe_name,
                        "candles": consecutive_candles,
                        "gale": max_gale,
                        "rsi_oversold": rsi_over,
                        "rsi_overbought": rsi_under,
                        "rsi_label": f"{rsi_over}/{rsi_under}",
                        "wins": res['wins'],
                        "losses": res['losses'],
                        "win_rate": win_rate,
                        "pnl": res['pnl']
                    })
    
    results.sort(key=lambda x: x['pnl'], reverse=True)
    return {"results": results[:5]}
