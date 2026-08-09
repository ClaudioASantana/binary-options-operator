from typing import List
from app.models.market import Candle, CandleDirection, Signal, SignalType

def evaluate_strategy(candles: List[Candle], seconds_in_cycle: int) -> Signal:
    if seconds_in_cycle < 297 or seconds_in_cycle > 299:
        return Signal(type=SignalType.NONE, reason="Out of execution window (297-299s)")
    
    if len(candles) < 9:
        return Signal(type=SignalType.NONE, reason=f"Not enough candles: {len(candles)}")
    
    recent_9 = candles[-9:]
    
    all_bullish = all(c.direction == CandleDirection.BULLISH for c in recent_9)
    if all_bullish:
        return Signal(type=SignalType.PUT, reason="9 consecutive bullish candles. Reversal PUT.")
        
    all_bearish = all(c.direction == CandleDirection.BEARISH for c in recent_9)
    if all_bearish:
        return Signal(type=SignalType.CALL, reason="9 consecutive bearish candles. Reversal CALL.")
        
    return Signal(type=SignalType.NONE, reason="No clear 9-candle sequence")
