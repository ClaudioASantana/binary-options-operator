import json
import asyncio
import logging
import websockets
from typing import Callable, Any
from app.models.market import Tick

logger = logging.getLogger(__name__)

class DerivClient:
    def __init__(self, app_id: int = 1089):
        self.app_id = app_id
        self.url = f"wss://ws.binaryws.com/websockets/v3?app_id={self.app_id}"
        self.connection = None
        self.callbacks = []
        self._running = False

    def add_tick_callback(self, callback: Callable[[Tick], Any]):
        self.callbacks.append(callback)

    async def connect_and_listen(self, symbol: str = "R_100"):
        self._running = True
        while self._running:
            try:
                async with websockets.connect(self.url) as websocket:
                    self.connection = websocket
                    logger.info(f"Connected to Deriv API. Subscribing to {symbol}")
                    
                    # Subscribe to ticks
                    await websocket.send(json.dumps({
                        "ticks": symbol,
                        "subscribe": 1
                    }))
                    
                    async for message in websocket:
                        if not self._running:
                            break
                        self._handle_message(message)
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket connection closed. Reconnecting in 3s...")
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"WebSocket error: {e}. Reconnecting in 3s...")
                await asyncio.sleep(3)
                
    def stop(self):
        self._running = False

    def _handle_message(self, raw_message: str):
        data = json.loads(raw_message)
        
        if "tick" in data:
            tick_data = data["tick"]
            tick = Tick(
                epoch=tick_data["epoch"],
                quote=tick_data["quote"],
                symbol=tick_data["symbol"]
            )
            for callback in self.callbacks:
                callback(tick)
