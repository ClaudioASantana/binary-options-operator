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
                    if watching_symbol in bots:
                        b = bots[watching_symbol]
                        b.active_config["timeframe"] = cmd.get("timeframe", 300)
                        b.active_config["candles"] = cmd.get("candles", 9)
                        logger.info(f"[{watching_symbol}] Configuração local alterada: M{b.active_config['timeframe']//60} / {b.active_config['candles']} velas")
                elif cmd.get("command") == "TOGGLE_AUTO_OPTIMIZE":
                    if watching_symbol in bots:
                        b = bots[watching_symbol]
                        b.auto_optimize = cmd.get("enabled", False)
                        logger.info(f"[{watching_symbol}] Auto-Otimização local alterada para: {b.auto_optimize}")
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
