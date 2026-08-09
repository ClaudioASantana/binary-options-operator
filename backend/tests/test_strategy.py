import pytest
from app.models.market import Candle, SignalType
from app.engines.strategy import evaluate_strategy

def create_candle(close: float, open: float = 100.0) -> Candle:
    return Candle(epoch=0, open=open, high=max(open, close), low=min(open, close), close=close)

def test_strategy_generates_put_signal_when_conditions_met():
    # 9 bullish candles
    candles = [create_candle(101.0) for _ in range(9)]
    
    # Time is between 297 and 299 seconds in cycle
    signal = evaluate_strategy(candles, seconds_in_cycle=298)
    
    assert signal.type == SignalType.PUT
    assert "9" in signal.reason

def test_strategy_generates_call_signal_when_conditions_met():
    # 9 bearish candles
    candles = [create_candle(99.0) for _ in range(9)]
    
    signal = evaluate_strategy(candles, seconds_in_cycle=297)
    
    assert signal.type == SignalType.CALL

def test_strategy_ignores_when_too_early_in_candle():
    candles = [create_candle(101.0) for _ in range(9)]
    
    # 296 is before the 297-299 window
    signal = evaluate_strategy(candles, seconds_in_cycle=296)
    
    assert signal.type == SignalType.NONE

def test_strategy_ignores_when_not_enough_candles():
    # Only 8 bullish candles
    candles = [create_candle(101.0) for _ in range(8)]
    
    signal = evaluate_strategy(candles, seconds_in_cycle=298)
    
    assert signal.type == SignalType.NONE

def test_strategy_ignores_when_current_candle_reverses():
    # 8 bullish candles
    candles = [create_candle(101.0) for _ in range(8)]
    # 9th candle is bearish
    candles.append(create_candle(99.0))
    
    signal = evaluate_strategy(candles, seconds_in_cycle=298)
    
    assert signal.type == SignalType.NONE
