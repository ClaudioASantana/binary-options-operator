import asyncio
import websockets
import json

async def test():
    async with websockets.connect("wss://ws.binaryws.com/websockets/v3?app_id=1089") as ws:
        await ws.send(json.dumps({"ticks": "R_100", "subscribe": 1}))
        async for msg in ws:
            print("Received:", msg[:100])
            break

asyncio.run(test())
