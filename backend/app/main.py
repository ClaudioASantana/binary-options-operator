import asyncio
import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.services.deriv_client import DerivClient
from app.engines.candle_builder import CandleBuilder
from app.engines.strategy import evaluate_strategy
from app.models.market import Tick

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

client = DerivClient()
builder = CandleBuilder()

tick_count = 0

def on_tick(tick: Tick):
    global tick_count
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
    if signal.type != "NONE":
        logger.info(f"SIGNAL DETECTED: {signal.type} | Reason: {signal.reason}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    client.add_tick_callback(on_tick)
    task = asyncio.create_task(client.connect_and_listen("R_100"))
    yield
    # Shutdown
    client.stop()
    task.cancel()

app = FastAPI(lifespan=lifespan)

@app.get("/status")
def get_status():
    return {
        "status": "running",
        "current_candle": builder.current_candle,
        "closed_candles_count": len(builder.closed_candles)
    }
