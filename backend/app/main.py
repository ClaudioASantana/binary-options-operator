import asyncio
import logging
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import json
from contextlib import asynccontextmanager
from datetime import datetime
from app.services.deriv_client import DerivClient
from app.engines.candle_builder import CandleBuilder
from app.engines.strategy import evaluate_strategy
from app.models.market import Tick

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        msg_str = json.dumps(message)
        for connection in self.active_connections:
            try:
                await connection.send_text(msg_str)
            except Exception:
                pass

manager = ConnectionManager()

import os
from dotenv import load_dotenv
load_dotenv()

DERIV_APP_ID = os.getenv("DERIV_APP_ID", "1089").strip()
client = DerivClient(app_id=DERIV_APP_ID)

builder_m1 = CandleBuilder(timeframe=60)
builder_m1.max_history = 1000
builder_m5 = CandleBuilder(timeframe=300)
builder_m5.max_history = 1000
builder_m15 = CandleBuilder(timeframe=900)
builder_m15.max_history = 1000

active_config = {"timeframe": 300, "candles": 9}
auto_optimize = False
global_catalog = []

from app.engines.simulator import PaperTrader
paper_trader = PaperTrader(initial_balance=1000.0, payout_rate=0.95)

from app.engines.news import NewsFilter
news_filter = NewsFilter()

DERIV_TOKEN = os.getenv("DERIV_API_TOKEN", "").strip()

tick_count = 0
last_signal_direction = None

async def on_history(granularity: int, candles: list):
    from app.models.market import Candle
    from app.models.market import CandleDirection as Direction
    if granularity == 60: b = builder_m1
    elif granularity == 300: b = builder_m5
    else: b = builder_m15
    
    b.closed_candles = []
    for c in candles:
        direction = Direction.BULLISH if c["close"] >= c["open"] else Direction.BEARISH
        b.closed_candles.append(Candle(
            epoch=c["epoch"],
            open=c["open"],
            high=c["high"],
            low=c["low"],
            close=c["close"],
            direction=direction
        ))
    logger.info(f"Builder M{granularity//60} inicializado com {len(b.closed_candles)} velas históricas.")

async def on_tick(tick: Tick):
    global tick_count
    # Process on all builders
    c1 = builder_m1.process_tick(tick)
    c5 = builder_m5.process_tick(tick)
    c15 = builder_m15.process_tick(tick)
    
    # Selecionar o builder ativo para operar
    active_builder = builder_m1 if active_config["timeframe"] == 60 else (builder_m5 if active_config["timeframe"] == 300 else builder_m15)
    
    # Broadcast market data (usando a vela do timeframe ativo)
    if active_builder.current_candle:
        await manager.broadcast({
            "event": "tick",
            "data": {
                "quote": tick.quote,
                "epoch": tick.epoch,
                "candle": active_builder.current_candle.model_dump()
            }
        })
    
    tick_count += 1
    if tick_count % 50 == 0:
        logger.info(f"🔥 [Heartbeat] Recebidos {tick_count} ticks ao vivo da Deriv (última cotação: {tick.quote})")

    if c1 or c5 or c15:
        # Broadcast a new catalog calculation whenever any candle closes
        asyncio.create_task(broadcast_catalog())
        
    # Paper Trader: Checar se há alguma expiração na cotação atual
    finished_trades = paper_trader.check_expirations(tick.epoch, tick.quote)
    if finished_trades:
        await manager.broadcast({"event": "simulator", "data": paper_trader.get_state()})

    # 2. Strategy analyzes the stream (CONCORRÊNCIA MULTI-ESTRATÉGIA)
    global global_catalog
    approved_configs = []
    if auto_optimize and len(global_catalog) > 0:
        approved_configs = [c for c in global_catalog if c["stats"]["win_rate"] >= 80]
        # Se nenhuma passar no corte, usamos a melhor mesmo assim
        if not approved_configs:
            approved_configs = [max(global_catalog, key=lambda x: x["stats"]["win_rate"])]
    else:
        approved_configs = [active_config]

    from app.models.market import Signal, SignalType
    from app.engines.risk import evaluate_risk
    from app.models.market import AccountState
    from app.rag.agent import explain_signal
    global last_signal_direction

    for config in approved_configs:
        tf = config["timeframe"]
        req_candles = config["candles"]
        builder = builder_m1 if tf == 60 else (builder_m5 if tf == 300 else builder_m15)
        
        seconds_in_cycle = builder.get_seconds_in_cycle(tick)
        if seconds_in_cycle >= (tf - 2):
            if len(builder.closed_candles) >= req_candles:
                last_n = builder.closed_candles[-req_candles:]
                signal = Signal(type=SignalType.NONE, reason="")
                
                # Evitar entradas repetidas na mesma vela
                # (Não precisamos de lock complexo porque é só 1 tick por segundo)
                # Mas vamos assumir que o tick só dispara 1 vez no segundo 58 ou 59
                if all(c.direction.value == "BEARISH" for c in last_n):
                    signal = Signal(type=SignalType.CALL, reason=f"{req_candles} velas de baixa no M{tf//60}")
                elif all(c.direction.value == "BULLISH" for c in last_n):
                    signal = Signal(type=SignalType.PUT, reason=f"{req_candles} velas de alta no M{tf//60}")
                
                if signal.type.value != "NONE":
                    strategy_info = f"M{tf//60}/{req_candles}V"
                    
                    # FILTRO INSTITUCIONAL DE TENDÊNCIA (RSI)
                    from app.engines.indicators import calculate_rsi
                    rsi_val = calculate_rsi(builder.closed_candles)
                    if signal.type.value == "CALL" and rsi_val >= 35:
                        logger.warning(f"🚫 [{strategy_info}] CALL bloqueado. RSI em {rsi_val} (não está em sobrevenda < 35)")
                        signal.type = SignalType.NONE
                    elif signal.type.value == "PUT" and rsi_val <= 65:
                        logger.warning(f"🚫 [{strategy_info}] PUT bloqueado. RSI em {rsi_val} (não está em sobrecompra > 65)")
                        signal.type = SignalType.NONE
                        
                if signal.type.value != "NONE":
                    last_signal_direction = "CALL" if signal.type.value == "BUY" else "PUT"
                    # FILTRO INSTITUCIONAL ANTI-NOTÍCIA (CALENDÁRIO ECONÔMICO)
                    news_status = news_filter.check_safety(tick.epoch)
                    if not news_status["safe"]:
                        logger.warning(f"⛔ [{strategy_info}] BLOQUEADO PELO CALENDÁRIO: {news_status['reason']}")
                        signal.type = SignalType.NONE

                if signal.type.value != "NONE":
                    logger.info(f"🎯 [{strategy_info}] SIGNAL DETECTED: {signal.type.value} | Reason: {signal.reason} | RSI: {rsi_val}")
                    await manager.broadcast({"event": "signal", "data": {"type": signal.type.value, "reason": signal.reason, "strategy": strategy_info}})
                    
                    # Sincroniza o estado de risco com o PaperTrader (nosso simulador que espelha a realidade)
                    account_state = AccountState(
                        balance=paper_trader.balance, 
                        current_consecutive_losses=paper_trader.consecutive_losses, 
                        daily_pnl=paper_trader.get_pnl(),
                        current_gale_level=paper_trader.consecutive_losses, 
                        daily_stop_loss=paper_trader.daily_stop_loss, 
                        daily_stop_gain=paper_trader.daily_stop_gain,
                        max_gale=paper_trader.max_gale, 
                        stake_initial=paper_trader.stake_initial
                    )
                    risk_eval = evaluate_risk(signal, account_state)
                    
                    try:
                        explanation = await asyncio.to_thread(explain_signal, signal, risk_eval.reason)
                        await manager.broadcast({"event": "agent_message", "data": explanation})
                        
                        if risk_eval.decision.value == "BLOCKED":
                            logger.warning(f"⛔ [{strategy_info}] Trade BLOQUEADO pelo Gestor de Risco: {risk_eval.reason}")
                        else:
                            current_stake = risk_eval.stake
                            logger.info(f"🚀 [{strategy_info}] Enviando ordem automática... (Stake: ${current_stake})")
                            asyncio.create_task(client.buy_contract(direction=last_signal_direction, amount=current_stake))
                            
                            paper_trader.register_trade(
                                direction=last_signal_direction,
                                entry_price=tick.quote,
                                stake=current_stake,
                                timeframe_seconds=tf,
                                current_epoch=tick.epoch
                            )
                            # Anexar info extra no trade mais recente
                            if paper_trader.pending_trades:
                                paper_trader.pending_trades[-1]["strategy_info"] = strategy_info
                                
                            await manager.broadcast({"event": "simulator", "data": {"simulator": paper_trader.get_state(), "news_status": news_filter.check_safety(tick.epoch)}})
                            
                            with open("trade_history.log", "a", encoding="utf-8") as f:
                                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                f.write(f"[{ts}] [{strategy_info}] SIGNAL: {signal.type.value} | Stake: ${current_stake} | RAG: {explanation.replace(chr(10), ' ')}\n")
                    except Exception as e:
                        logger.error(f"Erro no processamento concorrente: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Iniciando conexão com a Deriv...")
    client.add_tick_callback(on_tick)
    client.add_history_callback(on_history)
    task = asyncio.create_task(client.connect_and_listen(token=DERIV_TOKEN, symbol="R_100"))
    yield
    # Shutdown
    client.stop()
    task.cancel()

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
    # Send initial state to the new client
    await websocket.send_json({"event": "simulator", "data": {"simulator": paper_trader.get_state(), "news_status": news_filter.check_safety(int(time.time()))}})
    await websocket.send_json({"event": "active_symbol", "data": client.symbol})
    try:
        while True:
            data = await websocket.receive_text()
            logger.info(f"WS recebido do cliente: {data}")
            try:
                cmd = json.loads(data)
                global auto_optimize
                if cmd.get("command") == "SET_CONFIG":
                    active_config["timeframe"] = cmd.get("timeframe", 300)
                    active_config["candles"] = cmd.get("candles", 9)
                    logger.info(f"🔄 MODO AUTÔNOMO RECONFIGURADO: M{active_config['timeframe']//60} / {active_config['candles']} velas")
                    await manager.broadcast({"event": "simulator", "data": {"simulator": paper_trader.get_state(), "news_status": news_filter.check_safety(int(time.time()))}})
                elif cmd.get("command") == "TOGGLE_AUTO_OPTIMIZE":
                    auto_optimize = cmd.get("enabled", False)
                    logger.info(f"🤖 Auto-Otimização Mutante alterada para: {auto_optimize}")
                elif cmd.get("command") == "SET_SYMBOL":
                    new_sym = cmd.get("symbol")
                    if new_sym:
                        builder_m1.closed_candles.clear()
                        builder_m5.closed_candles.clear()
                        builder_m15.closed_candles.clear()
                        asyncio.create_task(client.change_symbol(new_sym))
                        await manager.broadcast({"event": "active_symbol", "data": new_sym})
            except:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/status")
def get_status():
    return {
        "status": "running",
        "current_candle": builder_m5.current_candle,
        "closed_candles_count": len(builder_m5.closed_candles),
        "active_config": active_config,
        "auto_optimize": auto_optimize,
        "simulator": paper_trader.get_state(),
        "news_status": news_filter.check_safety(int(time.time()))
    }

async def broadcast_catalog():
    from app.engines.cataloger import calculate_win_rate
    global global_catalog
    catalog = []
    for timeframe, b in [(60, builder_m1), (300, builder_m5), (900, builder_m15)]:
        for candles_req in [3, 5, 7, 9]:
            stats = calculate_win_rate(b.closed_candles, candles_req)
            catalog.append({
                "timeframe": timeframe,
                "candles": candles_req,
                "stats": stats
            })
            
    global_catalog = catalog
    global auto_optimize
    
    await manager.broadcast({
        "event": "catalog", 
        "data": {
            "catalog": global_catalog,
            "active_config": active_config,
            "auto_optimize": auto_optimize
        }
    })

@app.get("/force_signal")
async def force_signal_endpoint():
    from app.models.market import Signal, SignalType
    global last_signal_direction
    signal = Signal(type=SignalType.CALL, reason="Sinal de TESTE injetado manualmente.")
    last_signal_direction = "CALL"
    logger.info("🔥 FAKE SIGNAL INJECTED")
    await manager.broadcast({"event": "signal", "data": {"type": signal.type.value, "reason": signal.reason}})
    
    from app.engines.risk import evaluate_risk
    from app.models.market import AccountState
    account_state = AccountState(
        balance=100.0, 
        current_consecutive_losses=0,
        daily_pnl=0.0,
        current_gale_level=0,
        daily_stop_loss=50.0,
        daily_stop_gain=50.0,
        max_gale=2,
        stake_initial=1.0
    )
    risk_eval = evaluate_risk(signal, account_state)
    
    from app.rag.agent import explain_signal
    logger.info("🤖 Solicitando análise do Agente (RAG)...")
    try:
        explanation = await asyncio.to_thread(explain_signal, signal, risk_eval.reason)
        await manager.broadcast({"event": "agent_message", "data": explanation})
        logger.info(f"\n{'='*40}\n🤖 CO-PILOTO RAG DIZ:\n{explanation}\n{'='*40}")
        
        # --- AUTOMAÇÃO TOTAL (Force Signal) ---
        logger.info("🚀 MODO AUTÔNOMO: Enviando ordem de compra automática...")
        # Precisamos do epoch e cotação atual para injetar no simulador
        current_quote = builder_m5.current_candle.close if builder_m5.current_candle else 0
        current_epoch = builder_m5.current_candle.epoch if builder_m5.current_candle else int(datetime.now().timestamp())
        paper_trader.register_trade(
            direction=last_signal_direction,
            entry_price=current_quote,
            stake=1.0,
            timeframe_seconds=active_config["timeframe"],
            current_epoch=current_epoch
        )
        await manager.broadcast({"event": "simulator", "data": paper_trader.get_state()})
        asyncio.create_task(client.buy_contract(direction=last_signal_direction, amount=1.0))
        
        with open("trade_history.log", "a", encoding="utf-8") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] FAKE_SIGNAL: {signal.type.value} | REASON: {signal.reason} | RAG: {explanation.replace(chr(10), ' ')}\n"
            f.write(log_entry)
            
    except Exception as e:
        logger.error(f"Erro no Agente: {e}")
        
    return {"status": "ok", "message": "Sinal falso injetado e enviado ao frontend!"}
