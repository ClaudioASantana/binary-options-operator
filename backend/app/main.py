import asyncio
import logging
import time
import os
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from app.engines.bot_instance import BotInstance
from app.engines.news import NewsFilter

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        # Defaults to watching R_100
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
            # Se a mensagem pertence a um simbolo, enviar so se o client estiver assistindo
            if msg_symbol and msg_symbol != watched_symbol:
                continue
            try:
                await connection.send_text(msg_str)
            except Exception:
                pass

manager = ConnectionManager()
news_filter = NewsFilter()
DERIV_TOKEN = os.getenv("DERIV_API_TOKEN", "").strip()

# --- SWARM STATE ---
MARKETS_TO_RUN = ["R_10", "R_25", "R_50", "R_75", "R_100", "1HZ10V", "1HZ25V", "1HZ50V", "1HZ75V", "1HZ100V", "RDBEAR", "RDBULL"]
bots: dict[str, BotInstance] = {}

watching_symbol = "R_100" # Global state for what the frontend is watching (for backward compatibility of /status)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Iniciando o ENXAME (Swarm)... Levantando 12 bots simultâneos!")
    
    start_tasks = []
    for sym in MARKETS_TO_RUN:
        bot = BotInstance(symbol=sym, token=DERIV_TOKEN, news_filter=news_filter, manager=manager)
        bots[sym] = bot
        start_tasks.append(bot.start())
        
    # Iniciar todos concorrentemente
    asyncio.gather(*start_tasks)
    
    yield
    # Shutdown
    logger.info("Desligando o ENXAME...")
    for bot in bots.values():
        bot.stop()

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
        await websocket.send_json({"event": "simulator", "symbol": watching_symbol, "data": b.paper_trader.get_state()})
    await websocket.send_json({"event": "active_symbol", "data": watching_symbol})
    
    try:
        while True:
            data = await websocket.receive_text()
            try:
                cmd = json.loads(data)
                if cmd.get("command") == "WATCH_SYMBOL" or cmd.get("command") == "SET_SYMBOL":
                    new_sym = cmd.get("symbol")
                    if new_sym and new_sym in bots:
                        manager.set_watched_symbol(websocket, new_sym)
                        watching_symbol = new_sym
                        await manager.broadcast({"event": "active_symbol", "data": new_sym})
                        # Mandar o estado mais recente desse bot pro frontend
                        b = bots[new_sym]
                        await websocket.send_json({"event": "simulator", "symbol": new_sym, "data": b.paper_trader.get_state()})
                        await websocket.send_json({"event": "catalog", "symbol": new_sym, "data": {"catalog": b.global_catalog, "active_config": b.active_config, "auto_optimize": b.auto_optimize}})
                elif cmd.get("command") == "SET_CONFIG":
                    target_symbol = cmd.get("symbol", watching_symbol)
                    if target_symbol in bots:
                        b = bots[target_symbol]
                        b.active_config["timeframe"] = cmd.get("timeframe", 300)
                        b.active_config["candles"] = cmd.get("candles", 5)
                        b.active_config["gale"] = cmd.get("gale", 3)
                        b.active_config["rsi_oversold"] = cmd.get("rsi_oversold", 30)
                        b.active_config["rsi_overbought"] = cmd.get("rsi_overbought", 70)
                        b.paper_trader.max_gale = cmd.get("gale", 3)
                        logger.info(f"[{target_symbol}] Configuração local alterada: M{b.active_config['timeframe']//60} / {b.active_config['candles']} velas / Gale {b.active_config['gale']} / RSI {b.active_config['rsi_oversold']}-{b.active_config['rsi_overbought']}")
                        await manager.broadcast({"event": "simulator", "symbol": target_symbol, "data": b.paper_trader.get_state()})
                elif cmd.get("command") == "TOGGLE_AUTO_OPTIMIZE":
                    if watching_symbol in bots:
                        b = bots[watching_symbol]
                        b.auto_optimize = not b.auto_optimize
                        logger.info(f"[{watching_symbol}] Auto-Optimize: {b.auto_optimize}")
                        await websocket.send_json({"event": "catalog", "symbol": watching_symbol, "data": {"catalog": b.global_catalog, "active_config": b.active_config, "auto_optimize": b.auto_optimize}})
                elif cmd.get("command") == "TOGGLE_AUTO_OPTIMIZE_ALL":
                    is_active = cmd.get("active", True)
                    for sym, bot_inst in bots.items():
                        bot_inst.auto_optimize = is_active
                        logger.info(f"[{sym}] Auto-Optimize Global: {bot_inst.auto_optimize}")
                    if watching_symbol in bots:
                        b = bots[watching_symbol]
                        await websocket.send_json({"event": "catalog", "symbol": watching_symbol, "data": {"catalog": b.global_catalog, "active_config": b.active_config, "auto_optimize": b.auto_optimize}})
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
        "current_candle": b.get_active_builder().current_candle,
        "closed_candles_count": len(b.get_active_builder().closed_candles),
        "active_config": b.active_config,
        "auto_optimize": b.auto_optimize,
        "simulator": b.paper_trader.get_state(),
        "news_status": news_filter.check_safety(int(time.time()))
    }

@app.get("/portfolio")
def get_portfolio():
    # Retorna o saldo global somado de todos os bots
    total_balance = sum(b.paper_trader.balance for b in bots.values())
    total_pnl = sum(b.paper_trader.get_pnl() for b in bots.values())
    return {
        "total_balance": total_balance,
        "total_pnl": total_pnl,
        "bots_count": len(bots)
    }

from pydantic import BaseModel
class OptimizeRequest(BaseModel):
    symbol: str

@app.post("/api/optimize")
async def api_optimize(req: OptimizeRequest):
    import sys
    import os
    scripts_path = os.path.join(os.path.dirname(__file__), '..', 'scripts')
    if scripts_path not in sys.path:
        sys.path.append(scripts_path)
    from optimizer import download_history, run_simulation
    
    results = []
    logger.info(f"[{req.symbol}] Baixando histórico para otimização...")
    history_m5 = await download_history(req.symbol, 300, 5000)
    history_m1 = await download_history(req.symbol, 60, 5000)
    
    for history, timeframe_name in [(history_m5, "M5"), (history_m1, "M1")]:
        if not history: continue
        for consecutive_candles in [3, 5, 7, 9]:
            for max_gale in [1, 2, 3]:
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
