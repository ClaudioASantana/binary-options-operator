import asyncio
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import json
from contextlib import asynccontextmanager
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

client = DerivClient()
builder = CandleBuilder()

tick_count = 0

async def on_tick(tick: Tick):
    global tick_count
    builder.process_tick(tick)
    
    # Broadcast market data
    if builder.current_candle:
        await manager.broadcast({
            "event": "tick",
            "data": {
                "quote": tick.quote,
                "epoch": tick.epoch,
                "candle": builder.current_candle.model_dump()
            }
        })
    
    tick_count += 1
    if tick_count % 50 == 0:
        logger.info(f"🔥 [Heartbeat] Recebidos {tick_count} ticks ao vivo da Deriv (última cotação: {tick.quote})")

    # This is our data pipeline
    # 1. Builder processes tick
    candle = builder.process_tick(tick)
    
    if candle:
        logger.info(f"New Candle Closed: {candle.epoch} | Close: {candle.close} | Dir: {candle.direction.value}")
    
    # 2. Strategy analyzes the stream (if we have enough closed candles)
    seconds_in_cycle = builder.get_seconds_in_cycle(tick)
    
    signal = evaluate_strategy(builder.closed_candles, seconds_in_cycle)
    if signal.type.value != "NONE":
        logger.info(f"SIGNAL DETECTED: {signal.type.value} | Reason: {signal.reason}")
        await manager.broadcast({"event": "signal", "data": {"type": signal.type.value, "reason": signal.reason}})
        
        # Avaliação de Risco (Fase A)
        from app.engines.risk import evaluate_risk
        from app.models.market import AccountState
        account_state = AccountState(balance=100.0, current_consecutive_losses=0)
        risk_eval = evaluate_risk(signal, account_state)
        logger.info(f"RISK EVALUATION: {risk_eval.action.value} | {risk_eval.reason}")
        
        # Explicação do Agente via RAG (Fase C)
        from app.rag.agent import explain_signal
        logger.info("🤖 Solicitando análise do Agente (RAG)...")
        try:
            explanation = await asyncio.to_thread(explain_signal, signal, risk_eval.reason)
            await manager.broadcast({"event": "agent_message", "data": explanation})
            logger.info(f"\n{'='*40}\n🤖 CO-PILOTO RAG DIZ:\n{explanation}\n{'='*40}")
        except Exception as e:
            logger.error(f"Erro no Agente: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    client.add_tick_callback(on_tick)
    task = asyncio.create_task(client.connect_and_listen("R_100"))
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
    try:
        while True:
            data = await websocket.receive_text()
            logger.info(f"WS recebido do cliente: {data}")
            try:
                cmd = json.loads(data)
                if cmd.get("command") == "APPROVE_TRADE":
                    logger.info("✅ TRADE APROVADO PELO OPERADOR! (Execução simulada na Fase D)")
                elif cmd.get("command") == "IGNORE_TRADE":
                    logger.info("❌ Trade ignorado pelo operador.")
            except:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/status")
def get_status():
    return {
        "status": "running",
        "current_candle": builder.current_candle,
        "closed_candles_count": len(builder.closed_candles)
    }
