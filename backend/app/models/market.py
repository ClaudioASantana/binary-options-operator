from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional

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
    symbol: Optional[str] = None # Adicionado para melhor rastreamento

class RiskDecision(str, Enum):
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    PENDING_MANUAL = "PENDING_MANUAL" # Adicionado para o fluxo de confirmacao manual

class RiskEvaluation(BaseModel):
    decision: RiskDecision
    reason: str
    stake: float
    gale_level: int
    reason_codes: List[str] = Field(default_factory=list) # Codigos para log e auditoria
    messages: List[str] = Field(default_factory=list) # Mensagens para display no frontend
    
class AccountState(BaseModel):
    balance: float
    daily_pnl: float
    current_gale_level: int
    daily_stop_loss: float
    daily_stop_gain: float
    max_gale: int
    stake_initial: float
    consecutive_losses: int = 0 # Adicionado para validacao de losses consecutivos
    trades_today: int = 0 # Adicionado para validacao de trades por dia
    max_trades_per_day: int = 50 # Default, pode ser configuravel
    environment: str = "demo" # Adicionado para identificar ambiente
    
# Adicionar modelo para a proposta da Deriv API
class DerivProposal(BaseModel):
    """Representa uma proposta de contrato da Deriv API."""
    proposal_id: str
    symbol: str # underlying
    contract_type: str # CALL/PUT
    duration: int
    duration_unit: str # s, m, h, d
    amount: float # stake
    price: float # price to buy (same as amount for buy_contract)
    payout: float
    longcode: str
    shortcode: str
    display_value: str
    spot: float
    spot_time: int
    # Campos adicionais para validacao
    payout_percent: float = 0.0 # Calculado se nao fornecido
    environment: str = "demo" # Para verificar ambiente
    currency: str = "USD" # Para validacao de proposta

# Adicionar modelo para a revisao do agente
class AgentReview(BaseModel):
    risk_level: str = "low" # low, medium, high
    recommendation: str = "execute" # execute, block, manual_confirm
    summary: str = ""
    sources: List[str] = Field(default_factory=list)

# Adicionar modelo para a decisao final do harness
class DecisionHarnessOutput(BaseModel):
    signal: Signal
    risk_evaluation: RiskEvaluation
    agent_review: Optional[AgentReview] = None
    final_decision: RiskDecision
    final_message: str
    stake_to_use: float
    gale_level_to_use: int
    manual_confirmation_required: bool = False
    
