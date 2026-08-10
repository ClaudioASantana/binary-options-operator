import os
import sys
import json
import asyncio
import websockets
from dotenv import load_dotenv
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.models.market import Candle, CandleDirection
from app.engines.indicators import calculate_rsi

load_dotenv()

DERIV_APP_ID = "1089"
SYMBOL = "R_100"
COUNT = 5000

async def download_history(symbol, granularity, count):
    url = f"wss://ws.binaryws.com/websockets/v3?app_id={DERIV_APP_ID}"
    async with websockets.connect(url) as ws:
        req = {
            "ticks_history": symbol,
            "style": "candles",
            "granularity": granularity,
            "count": count,
            "end": "latest"
        }
        await ws.send(json.dumps(req))
        response = json.loads(await ws.recv())
        if "error" in response:
            return []
            
        candles_raw = response.get("candles", [])
        history = []
        for c in candles_raw:
            direction = CandleDirection.BULLISH if c["close"] > c["open"] else CandleDirection.BEARISH
            if c["close"] == c["open"]:
                direction = CandleDirection.NEUTRAL
            history.append(Candle(
                epoch=c["epoch"],
                open=c["open"],
                high=c["high"],
                low=c["low"],
                close=c["close"],
                direction=direction
            ))
        return history

def run_simulation(history, consecutive_candles, rsi_oversold, rsi_overbought, max_gale, stake, payout_rate, rsi_period=14):
    balance = 0.0
    wins = 0
    losses = 0
    current_gale = 0
    current_stake = stake
    
    in_trade = False
    trade_direction = None
    
    for i in range(len(history)):
        if i < rsi_period + consecutive_candles:
            continue
            
        current_candle = history[i]
        
        if in_trade:
            won = False
            if trade_direction == "CALL" and current_candle.direction == CandleDirection.BULLISH:
                won = True
            elif trade_direction == "PUT" and current_candle.direction == CandleDirection.BEARISH:
                won = True
                
            if won:
                balance += (current_stake * payout_rate)
                wins += 1
                in_trade = False
                current_stake = stake
                current_gale = 0
            else:
                balance -= current_stake
                if current_gale < max_gale:
                    current_gale += 1
                    current_stake *= 2.0
                else:
                    losses += 1
                    in_trade = False
                    current_stake = stake
                    current_gale = 0
            continue
            
        slice_history = history[:i+1]
        last_n = slice_history[-consecutive_candles:]
        
        signal = None
        if all(c.direction == CandleDirection.BEARISH for c in last_n):
            signal = "CALL"
        elif all(c.direction == CandleDirection.BULLISH for c in last_n):
            signal = "PUT"
            
        if signal:
            rsi_val = calculate_rsi(slice_history, rsi_period)
            if signal == "CALL" and rsi_val >= rsi_oversold:
                pass
            elif signal == "PUT" and rsi_val <= rsi_overbought:
                pass
            else:
                in_trade = True
                trade_direction = signal
                
    return {
        "wins": wins,
        "losses": losses,
        "pnl": balance
    }

async def optimize():
    results = []
    print(f"Baixando histórico M5 e M1...")
    history_m5 = await download_history("R_100", 300, 5000)
    history_m1 = await download_history("R_100", 60, 5000)
    
    print("Testando configurações...")
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
                        "timeframe": timeframe_name,
                        "candles": consecutive_candles,
                        "gale": max_gale,
                        "rsi": f"{rsi_over}/{rsi_under}",
                        "wins": res['wins'],
                        "losses": res['losses'],
                        "win_rate": win_rate,
                        "pnl": res['pnl']
                    })
                    
    # Sort by PNL
    results.sort(key=lambda x: x['pnl'], reverse=True)
    
    with open("optimization_results.json", "w") as f:
        json.dump(results[:20], f, indent=4)
        
    print("Top 5 Configurações:")
    for idx, r in enumerate(results[:5]):
        print(f"{idx+1}. {r['timeframe']} | {r['candles']} Velas | Gale {r['gale']} | RSI {r['rsi']} => PnL: ${r['pnl']:.2f} (WR: {r['win_rate']:.1f}%)")

if __name__ == "__main__":
    asyncio.run(optimize())
