import json
import asyncio
import inspect
import logging
import urllib.request
import websockets
from typing import Callable, Any, List
from app.models.market import Tick

logger = logging.getLogger(__name__)

class DerivClient:
    def __init__(self, app_id: str = "1089"):
        self.app_id = app_id
        self.symbol = "R_100"
        self.url = f"wss://ws.binaryws.com/websockets/v3?app_id={self.app_id}"
        self.connection = None
        self.callbacks = []
        self.history_callbacks = []
        self._running = False

    def add_tick_callback(self, callback: Callable[[Tick], Any]):
        self.callbacks.append(callback)

    def add_history_callback(self, callback: Callable[[int, List[dict]], Any]):
        self.history_callbacks.append(callback)

    def _get_ws_url(self, token: str) -> str:
        headers = {"Authorization": f"Bearer {token}", "Deriv-App-ID": self.app_id}
        req = urllib.request.Request("https://api.derivws.com/trading/v1/options/accounts", headers=headers)
        with urllib.request.urlopen(req) as res:
            accs = json.loads(res.read().decode())['data']
        req_otp = urllib.request.Request(f"https://api.derivws.com/trading/v1/options/accounts/{accs[0]['account_id']}/otp", headers=headers, method="POST")
        with urllib.request.urlopen(req_otp) as res:
            return json.loads(res.read().decode())['data']['url']

    async def connect_and_listen(self, token: str):
        self._running = True
        while self._running:
            try:
                connect_url = self.url
                if token and token.startswith("pat_"):
                    logger.info("Detectado token PAT. Resolvendo conexão via REST API...")
                    connect_url = await asyncio.to_thread(self._get_ws_url, token)
                    
                async with websockets.connect(connect_url) as websocket:
                    self.connection = websocket
                    logger.info(f"Connected to Deriv API.")
                    
                    if token and not token.startswith("pat_"):
                        logger.info("Authorizing with legacy Deriv Token...")
                        await websocket.send(json.dumps({"authorize": token}))
                    elif not token:
                        logger.warning("No API Token provided. Synthetic indices might fail.")
                        await websocket.send(json.dumps({"ticks": self.symbol, "subscribe": 1}))
                    else:
                        # For PAT tokens, authorization is already inside the OTP URL.
                        # We can subscribe directly!
                        logger.info("Autenticação via OTP concluída! Solicitando Ticks e Histórico...")
                        await websocket.send(json.dumps({"ticks": self.symbol, "subscribe": 1}))
                        # Request History for M1, M5, M15
                        for req_id, gran in [(1, 60), (5, 300), (15, 900)]:
                            await websocket.send(json.dumps({
                                "ticks_history": self.symbol,
                                "style": "candles",
                                "granularity": gran,
                                "count": 1000,
                                "end": "latest",
                                "req_id": req_id
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

    async def change_symbol(self, new_symbol: str):
        if self.symbol == new_symbol:
            return
        logger.info(f"🔄 Trocando ativo de {self.symbol} para {new_symbol}...")
        if self.connection:
            await self.connection.send(json.dumps({"forget_all": "ticks"}))
        self.symbol = new_symbol
        if self.connection:
            await self.connection.send(json.dumps({"ticks": self.symbol, "subscribe": 1}))
            for req_id, gran in [(1, 60), (5, 300), (15, 900)]:
                await self.connection.send(json.dumps({
                    "ticks_history": self.symbol,
                    "style": "candles",
                    "granularity": gran,
                    "count": 1000,
                    "end": "latest",
                    "req_id": req_id
                }))

    async def buy_contract(self, direction: str, amount: float):
        if not self.connection:
            logger.error("Cannot buy: No WebSocket connection.")
            return
        contract_type = "CALL" if direction.upper() == "CALL" else "PUT"
        req = {
            "buy": 1,
            "price": amount,
            "parameters": {
                "amount": amount,
                "basis": "stake",
                "contract_type": contract_type,
                "currency": "USD",
                "duration": 5,
                "duration_unit": "m",
                "symbol": self.symbol
            }
        }
        logger.info(f"🚀 Enviando Ordem Oficial para Deriv: {contract_type} | Stake: ${amount}")
        await self.connection.send(json.dumps(req))

    def _handle_message(self, raw_message: str):
        data = json.loads(raw_message)
        
        if "error" in data:
            logger.error(f"Deriv API Error: {data['error']}")
            return
            
        if "authorize" in data:
            logger.info(f"✅ Autenticado com sucesso na Deriv! (Conta: {data['authorize']['currency']})")
            # After authorize, subscribe to ticks
            asyncio.create_task(self.connection.send(json.dumps({
                "ticks": self.symbol,
                "subscribe": 1
            })))
            for req_id, gran in [(1, 60), (5, 300), (15, 900)]:
                asyncio.create_task(self.connection.send(json.dumps({
                    "ticks_history": self.symbol,
                    "style": "candles",
                    "granularity": gran,
                    "count": 1000,
                    "end": "latest",
                    "req_id": req_id
                })))
            return

        
        if "buy" in data:
            logger.info(f"✅ COMPRA EXECUTADA COM SUCESSO! Ticket ID: {data['buy']['contract_id']} | Saldo restante: {data['buy']['balance_after']}")
            return

        if "candles" in data:
            granularity = 0
            if data.get("req_id") == 1: granularity = 60
            elif data.get("req_id") == 5: granularity = 300
            elif data.get("req_id") == 15: granularity = 900
            
            if granularity > 0:
                logger.info(f"📊 Histórico Recebido: {len(data['candles'])} velas para M{granularity//60}")
                for callback in self.history_callbacks:
                    if inspect.iscoroutinefunction(callback):
                        asyncio.create_task(callback(granularity, data["candles"]))
                    else:
                        callback(granularity, data["candles"])
            return

        if "tick" in data:
            tick_data = data["tick"]
            tick = Tick(
                epoch=tick_data["epoch"],
                quote=tick_data["quote"],
                symbol=tick_data["symbol"]
            )
            for callback in self.callbacks:
                if inspect.iscoroutinefunction(callback):
                    asyncio.create_task(callback(tick))
                else:
                    callback(tick)
