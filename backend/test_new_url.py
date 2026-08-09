import asyncio
import websockets
import json

async def test():
    url = "wss://ws.binaryws.com/websockets/v3?app_id=344lZiLwSyOnDmEOQIhak"
    try:
        print(f"Connecting to {url}")
        async with websockets.connect(url) as ws:
            print("Connected!")
            await ws.send(json.dumps({"authorize": "pat_8401e4b0c017c43a7408a1d68edaa29358fa615a161eafc5b5748d91bbdac47f"}))
            res = await ws.recv()
            print(res)
    except Exception as e:
        print("Error:", type(e), e)

asyncio.run(test())
