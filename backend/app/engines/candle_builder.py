from typing import List, Optional
from app.models.market import Tick, Candle

class CandleBuilder:
    def __init__(self, timeframe: int = 300):
        self.timeframe = timeframe
        self.current_candle: Optional[Candle] = None
        self.closed_candles: List[Candle] = []
        self.max_history = 100

    def process_tick(self, tick: Tick) -> Optional[Candle]:
        """Processes a tick and returns a finalized candle if one just closed, otherwise None."""
        candle_epoch = tick.epoch - (tick.epoch % self.timeframe)
        
        if self.current_candle is None:
            self._start_new_candle(candle_epoch, tick.quote)
            return None
            
        if candle_epoch > self.current_candle.epoch:
            # We crossed into a new candle timeframe
            finalized = self.current_candle
            self.closed_candles.append(finalized)
            if len(self.closed_candles) > self.max_history:
                self.closed_candles.pop(0)
                
            self._start_new_candle(candle_epoch, tick.quote)
            return finalized
            
        if candle_epoch == self.current_candle.epoch:
            # Update current candle
            self.current_candle.high = max(self.current_candle.high, tick.quote)
            self.current_candle.low = min(self.current_candle.low, tick.quote)
            self.current_candle.close = tick.quote
            
        return None

    def _start_new_candle(self, epoch: int, quote: float):
        self.current_candle = Candle(
            epoch=epoch,
            open=quote,
            high=quote,
            low=quote,
            close=quote
        )
        
    def get_seconds_in_cycle(self, tick: Tick) -> int:
        return tick.epoch % self.timeframe
