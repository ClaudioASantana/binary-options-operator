import asyncio
import websockets
import json
import os
from dotenv import load_dotenv

load_dotenv()
token = os.getenv('DERIV_API_TOKEN', '').strip()

async def test():
    print(f"Testing token: {token}")
    async with websockets.connect("wss://ws.binaryws.com/websockets/v3?app_id=1089") as ws:
        await ws.send(json.dumps({"authorize": "pat_79e037935cd3846ed8bbaa1ad56a301fdfd63a99cbefa6c58158b4b14d4cbaf5"}))
        res = await ws.recv()
        print("App 1089 Response:", res)

asyncio.run(test())
