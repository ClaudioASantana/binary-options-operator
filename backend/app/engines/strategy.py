from typing import List
from app.models.market import Candle, CandleDirection, Signal, SignalType

def evaluate_strategy(candles: List[Candle], seconds_in_cycle: int, consecutive_candles: int = 9) -> Signal:
    """
    Avalia se ha um sinal de trading baseado em candles consecutivas.
    
    Args:
        candles: Lista de candles historicos (do mais antigo ao mais recente)
        seconds_in_cycle: Segundos no ciclo atual (para timing de execucao)
        consecutive_candles: Numero de candles consecutivas da mesma cor para gerar sinal (default: 9)
    
    Returns:
        Signal com tipo (CALL, PUT, NONE) e razao
    """
    if seconds_in_cycle < 297 or seconds_in_cycle > 299:
        return Signal(type=SignalType.NONE, reason="Out of execution window (297-299s)")
    
    if len(candles) < consecutive_candles:
        return Signal(type=SignalType.NONE, reason=f"Not enough candles: {len(candles)} < {consecutive_candles}")
    
    recent_n = candles[-consecutive_candles:]
    
    all_bullish = all(c.direction == CandleDirection.BULLISH for c in recent_n)
    if all_bullish:
        return Signal(type=SignalType.PUT, reason=f"{consecutive_candles} consecutive bullish candles. Reversal PUT.")
        
    all_bearish = all(c.direction == CandleDirection.BEARISH for c in recent_n)
    if all_bearish:
        return Signal(type=SignalType.CALL, reason=f"{consecutive_candles} consecutive bearish candles. Reversal CALL.")
        
    return Signal(type=SignalType.NONE, reason="No clear {consecutive_candles}-candle sequence")
