import os
import sys
import json
import asyncio
import urllib.request
import urllib.parse
import websockets
from datetime import datetime
from dotenv import load_dotenv

# Ensure we can import app modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.models.market import Candle, CandleDirection
from app.engines.indicators import calculate_rsi

load_dotenv()

DERIV_APP_ID = "1089"
DERIV_TOKEN = os.getenv("DERIV_API_TOKEN", "")

SYMBOL = "R_50"
GRANULARITY = 300 # M5
COUNT = 5000

# Strategy params
CONSECUTIVE_CANDLES = 3
RSI_PERIOD = 14
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 65

# Money Management
INITIAL_BALANCE = 10000.0
STAKE = 10.0
PAYOUT_RATE = 0.95 # 95% payout
MARTINGALE_MULTIPLIER = 2.0
MAX_GALE = 2

async def run_backtest():
    url = f"wss://ws.binaryws.com/websockets/v3?app_id={DERIV_APP_ID}"
    print(f"🔄 Conectando na Deriv para baixar histórico de {SYMBOL} ({COUNT} velas de M{GRANULARITY//60})...")
    
    async with websockets.connect(url) as ws:
        # Request history
        req = {
            "ticks_history": SYMBOL,
            "style": "candles",
            "granularity": GRANULARITY,
            "count": COUNT,
            "end": "latest"
        }
        await ws.send(json.dumps(req))
        
        response = json.loads(await ws.recv())
        if "error" in response:
            print(f"❌ Erro da API: {response['error']}")
            return
            
        candles_raw = response.get("candles", [])
        print(f"✅ Download concluído! {len(candles_raw)} velas recebidas.")
        
        # Parse into Candle objects
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
            
    # RUN BACKTEST
    balance = INITIAL_BALANCE
    wins = 0
    losses = 0
    current_gale = 0
    current_stake = STAKE
    
    in_trade = False
    trade_direction = None
    
    print("🚀 Iniciando Simulação Institucional...")
    print("-" * 50)
    
    for i in range(len(history)):
        if i < RSI_PERIOD + CONSECUTIVE_CANDLES:
            continue
            
        current_candle = history[i]
        
        if in_trade:
            won = False
            if trade_direction == "CALL" and current_candle.direction == CandleDirection.BULLISH:
                won = True
            elif trade_direction == "PUT" and current_candle.direction == CandleDirection.BEARISH:
                won = True
                
            if won:
                profit = current_stake * PAYOUT_RATE
                balance += profit
                wins += 1
                dt = datetime.fromtimestamp(current_candle.epoch).strftime('%Y-%m-%d %H:%M')
                print(f"✅ WIN no {dt} | Lucro: +${profit:.2f} | Saldo: ${balance:.2f} (Gale {current_gale})")
                
                in_trade = False
                current_stake = STAKE
                current_gale = 0
            else:
                balance -= current_stake
                dt = datetime.fromtimestamp(current_candle.epoch).strftime('%Y-%m-%d %H:%M')
                
                if current_gale < MAX_GALE:
                    current_gale += 1
                    current_stake *= MARTINGALE_MULTIPLIER
                    print(f"⚠️ LOSS no {dt}. Aplicando Gale {current_gale} de ${current_stake:.2f} | Saldo: ${balance:.2f}")
                else:
                    losses += 1
                    print(f"❌ HIT MAX GALE no {dt} | Prejuízo da operação: Saldo: ${balance:.2f}")
                    in_trade = False
                    current_stake = STAKE
                    current_gale = 0
                    
            continue
            
        slice_history = history[:i+1]
        last_n = slice_history[-CONSECUTIVE_CANDLES:]
        
        signal = None
        if all(c.direction == CandleDirection.BEARISH for c in last_n):
            signal = "CALL"
        elif all(c.direction == CandleDirection.BULLISH for c in last_n):
            signal = "PUT"
            
        if signal:
            rsi_val = calculate_rsi(slice_history, RSI_PERIOD)
            
            if signal == "CALL" and rsi_val >= RSI_OVERSOLD:
                pass
            elif signal == "PUT" and rsi_val <= RSI_OVERBOUGHT:
                pass
            else:
                in_trade = True
                trade_direction = signal
                
    print("-" * 50)
    print("📊 RELATÓRIO FINAL DO BACKTEST")
    print(f"Ativo: {SYMBOL} | Velas: {COUNT} (M{GRANULARITY//60})")
    print(f"Estratégia: {CONSECUTIVE_CANDLES} Velas Consecutivas")
    print(f"Filtro RSI: CALL < {RSI_OVERSOLD} | PUT > {RSI_OVERBOUGHT}")
    print(f"Gale Máximo: {MAX_GALE}")
    print(f"Vitórias (Ciclos Vencedores): {wins}")
    print(f"Derrotas (Ciclos Perdidos Máximos): {losses}")
    
    total_cycles = wins + losses
    win_rate = (wins / total_cycles * 100) if total_cycles > 0 else 0
    print(f"Win Rate Real (com Gale): {win_rate:.2f}%")
    
    pnl = balance - INITIAL_BALANCE
    print(f"Saldo Inicial: ${INITIAL_BALANCE:.2f}")
    print(f"Saldo Final: ${balance:.2f}")
    print(f"Lucro Líquido (PnL): ${pnl:.2f}")

if __name__ == "__main__":
    asyncio.run(run_backtest())
