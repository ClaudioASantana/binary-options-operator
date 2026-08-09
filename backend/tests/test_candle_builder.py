import pytest
from app.models.market import Tick, CandleDirection
from app.engines.candle_builder import CandleBuilder

def test_builder_creates_and_updates_candle():
    builder = CandleBuilder(timeframe=300)
    
    # Tick at epoch 300
    res1 = builder.process_tick(Tick(epoch=300, quote=100.0, symbol="R_100"))
    assert res1 is None
    assert builder.current_candle.open == 100.0
    assert builder.current_candle.epoch == 300
    
    # Tick at epoch 310
    res2 = builder.process_tick(Tick(epoch=310, quote=105.0, symbol="R_100"))
    assert res2 is None
    assert builder.current_candle.high == 105.0
    assert builder.current_candle.close == 105.0
    
    # Tick at epoch 320
    res3 = builder.process_tick(Tick(epoch=320, quote=95.0, symbol="R_100"))
    assert res3 is None
    assert builder.current_candle.low == 95.0
    assert builder.current_candle.close == 95.0
    
    # Tick at epoch 600 (next candle)
    finalized = builder.process_tick(Tick(epoch=600, quote=98.0, symbol="R_100"))
    assert finalized is not None
    assert finalized.epoch == 300
    assert finalized.open == 100.0
    assert finalized.high == 105.0
    assert finalized.low == 95.0
    assert finalized.close == 95.0
    assert finalized.direction == CandleDirection.BEARISH
    
    assert builder.current_candle.epoch == 600
    assert builder.current_candle.open == 98.0

def test_get_seconds_in_cycle():
    builder = CandleBuilder(timeframe=300)
    assert builder.get_seconds_in_cycle(Tick(epoch=300, quote=1.0, symbol="R_100")) == 0
    assert builder.get_seconds_in_cycle(Tick(epoch=599, quote=1.0, symbol="R_100")) == 299
    assert builder.get_seconds_in_cycle(Tick(epoch=600, quote=1.0, symbol="R_100")) == 0
