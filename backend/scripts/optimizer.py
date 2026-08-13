import os
import sys
import json
import asyncio
import websockets
from dotenv import load_dotenv
from datetime import datetime
from typing import List, Dict, Any

# Ensure we can import app modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.models.market import Candle, CandleDirection
from app.engines.backtester import Backtester, BacktesterConfig, BacktestResult

load_dotenv()

DERIV_APP_ID = os.getenv("DERIV_APP_ID", "1089").strip()
DEFAULT_SYMBOL = "R_100"
DEFAULT_COUNT = 5000

async def download_history(symbol: str, granularity: int, count: int) -> List[Candle]:
    """Baixa historico de candles da Deriv API."""
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
            print(f"❌ Erro da API: {response['error']}")
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

async def optimize(
    symbol: str = DEFAULT_SYMBOL,
    count: int = DEFAULT_COUNT,
    initial_balance: float = 1000.0,
    stake_initial: float = 10.0,
    payout_rate: float = 0.95,
) -> List[Dict[str, Any]]:
    """
    Roda otimizacao de parametros para o simbolo especificado.
    
    Testa combinacoes de:
    - timeframe (60s, 300s)
    - consecutive_candles (3, 5, 7, 9)
    - max_gale (1, 2, 3)
    - rsi_oversold/overbought (35/65, 30/70, 25/75)
    
    Retorna lista dos melhores resultados de backtest.
    """
    all_results: List[BacktestResult] = []
    
    print(f"Baixando historico para {symbol} (M5 e M1)...")
    history_m5 = await download_history(symbol, 300, count)
    history_m1 = await download_history(symbol, 60, count)
    
    print(f"Iniciando otimizacao para {symbol}...")
    
    for history, timeframe in [(history_m5, 300), (history_m1, 60)]:
        if not history:
            continue
        
        for consecutive_candles in [3, 5, 7, 9]:
            for max_gale_config in [1, 2, 3]: # max_gale_config limitado a 3 pelo absoluto
                for rsi_oversold, rsi_overbought in [(35, 65), (30, 70), (25, 75)]:
                    
                    strategy_params = {
                        "timeframe": timeframe,
                        "consecutive_candles": consecutive_candles,
                        "rsi_oversold": rsi_oversold,
                        "rsi_overbought": rsi_overbought,
                    }
                    
                    backtester_config = BacktesterConfig(
                        initial_balance=initial_balance,
                        stake_initial=stake_initial,
                        payout_rate=payout_rate,
                        max_gale=max_gale_config,
                        apply_risk_limits=True, # Sempre aplicar limites no otimizador
                    )
                    
                    backtester = Backtester(backtester_config)
                    result = backtester.run(history, strategy_params)
                    all_results.append(result)
    
    # Sort by PnL in descending order
    all_results.sort(key=lambda x: x.total_pnl, reverse=True)
    
    print("\nTop 5 Configuracoes Otimizadas:")
    for idx, r in enumerate(all_results[:5]):
        print(f"{idx+1}. Config: M{r.config['timeframe']//60}/{r.config['consecutive_candles']} Velas/Gale {r.config['max_gale']} / RSI {r.config['rsi_oversold']}-{r.config['rsi_overbought']} => PnL: ${r.total_pnl:.2f} (WR: {r.win_rate:.1f}%)")
    
    return [r.to_dict() for r in all_results]


if __name__ == "__main__":
    asyncio.run(optimize())
