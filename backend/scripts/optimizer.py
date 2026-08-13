import os
import sys
import json
import asyncio
import websockets
from dotenv import load_dotenv
from typing import List, Dict, Any

# Ensure we can import app modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.models.market import Candle, CandleDirection
from app.engines.backtester import BacktesterConfig
from app.engines.optimizer import StrategyOptimizer, OptimizationSummary

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
            print(f"Erro da API: {response['error']}")
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
    
    Usa o StrategyOptimizer para testar combinacoes de parametros.
    Retorna lista dos melhores resultados de backtest, formatados para o frontend.
    """
    
    print(f"Baixando historico para {symbol} (M5 e M1)...")
    history_m5 = await download_history(symbol, 300, count)
    history_m1 = await download_history(symbol, 60, count)
    
    all_optimized_results = []

    # Param grid para a estrategia de velas consecutivas (default)
    param_grid_consecutive_candles = {
        "consecutive_candles": [3, 5, 7, 9],
        "rsi_period": [14],
        "rsi_oversold": [30, 25],
        "rsi_overbought": [70, 75],
        "use_rsi_filter": [True, False],
    }
    
    print(f"Iniciando otimizacao para {symbol}...")
    
    for history_data, timeframe in [(history_m5, 300), (history_m1, 60)]:
        if not history_data:
            print(f"Historico vazio para {symbol} M{timeframe//60}, pulando.")
            continue
        
        # Otimizar estrategia de Velas Consecutivas
        backtester_config = BacktesterConfig(
            initial_balance=initial_balance,
            stake_initial=stake_initial,
            payout_rate=payout_rate,
            max_gale=3,
            apply_risk_limits=True,
        )
        optimizer = StrategyOptimizer(history_data, backtester_config=backtester_config)
        
        summary = optimizer.optimize(
            param_grid=param_grid_consecutive_candles,
            optimization_metric="composite_score",
            min_trades=5,
        )
        
        if summary.best_result:
            res = summary.best_result
            # Format results for frontend
            result_dict = {
                "strategy_type": "consecutive_candles",
                "timeframe": timeframe,
                "timeframe_label": f"M{timeframe // 60}",
                "pnl": res.total_pnl,
                "win_rate": res.win_rate,
                "composite_score": res.composite_score,
                "sharpe_ratio": res.sharpe_ratio,
                "profit_factor": res.profit_factor,
                "total_trades": res.total_trades,
                "max_drawdown_percent": res.max_drawdown_percent,
                "consecutive_candles": res.params.get("consecutive_candles"),
                "rsi_oversold": res.params.get("rsi_oversold"),
                "rsi_overbought": res.params.get("rsi_overbought"),
                "use_rsi_filter": res.params.get("use_rsi_filter"),
                "rsi_label": f"{res.params.get('rsi_oversold')}-{res.params.get('rsi_overbought')}",
                "gale": backtester_config.max_gale,
                "candles": res.params.get("consecutive_candles"),
            }
            all_optimized_results.append(result_dict)

    # Ordenar por composite_score
    all_optimized_results.sort(key=lambda x: x["composite_score"], reverse=True)
    
    print("\nTop 5 Configuracoes Otimizadas (Composite Score):")
    for idx, r in enumerate(all_optimized_results[:5]):
        print(f"{idx+1}. M{r['timeframe']//60}/{r['candles']}V/Gale {r['gale']}/RSI {r['rsi_label']} => PnL: ${r['pnl']:.2f} (WR: {r['win_rate']:.1f}%) / Score: {r['composite_score']:.2f}")
    
    return all_optimized_results


if __name__ == "__main__":
    asyncio.run(optimize())
