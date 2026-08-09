from enum import Enum
# pyrefly: ignore [missing-import]
from pydantic import BaseModel
from typing import List

class CandleDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"

class Tick(BaseModel):
    epoch: int
    quote: float
    symbol: str

class Candle(BaseModel):
    epoch: int
    open: float
    high: float
    low: float
    close: float
    
    @property
    def direction(self) -> CandleDirection:
        if self.close > self.open:
            return CandleDirection.BULLISH
        elif self.close < self.open:
            return CandleDirection.BEARISH
        return CandleDirection.NEUTRAL

class SignalType(str, Enum):
    PUT = "PUT"
    CALL = "CALL"
    NONE = "NONE"

class Signal(BaseModel):
    type: SignalType
    reason: str

class RiskDecision(str, Enum):
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"

class RiskEvaluation(BaseModel):
    decision: RiskDecision
    reason: str
    stake: float
    gale_level: int

class AccountState(BaseModel):
    balance: float
    daily_pnl: float
    current_gale_level: int
    daily_stop_loss: float
    daily_stop_gain: float
    max_gale: int
    stake_initial: float
