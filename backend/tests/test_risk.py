import pytest
from app.models.market import SignalType, Signal, AccountState, RiskDecision
from app.engines.risk import evaluate_risk

@pytest.fixture
def base_account():
    return AccountState(
        balance=1000.0,
        daily_pnl=0.0,
        current_gale_level=0,
        daily_stop_loss=-50.0,
        daily_stop_gain=20.0,
        max_gale=3,
        stake_initial=0.35
    )

def test_risk_approves_valid_signal(base_account):
    signal = Signal(type=SignalType.PUT, reason="Test")
    eval = evaluate_risk(signal, base_account)
    
    assert eval.decision == RiskDecision.APPROVED
    assert eval.stake == 0.35
    assert eval.gale_level == 0

def test_risk_blocks_empty_signal(base_account):
    signal = Signal(type=SignalType.NONE, reason="Test")
    eval = evaluate_risk(signal, base_account)
    
    assert eval.decision == RiskDecision.BLOCKED

def test_risk_blocks_stop_loss(base_account):
    base_account.daily_pnl = -51.0
    signal = Signal(type=SignalType.PUT, reason="Test")
    eval = evaluate_risk(signal, base_account)
    
    assert eval.decision == RiskDecision.BLOCKED
    # A mensagem agora inclui "absolute limit" ou "loss"
    assert "loss" in eval.reason.lower() or "limit" in eval.reason.lower()

def test_risk_blocks_stop_gain(base_account):
    base_account.daily_pnl = 21.0
    signal = Signal(type=SignalType.PUT, reason="Test")
    eval = evaluate_risk(signal, base_account)
    
    assert eval.decision == RiskDecision.BLOCKED
    # A mensagem agora inclui "gain" ou "limit"
    assert "gain" in eval.reason.lower() or "limit" in eval.reason.lower()

def test_risk_blocks_max_gale(base_account):
    base_account.current_gale_level = 4
    signal = Signal(type=SignalType.PUT, reason="Test")
    eval = evaluate_risk(signal, base_account)
    
    assert eval.decision == RiskDecision.BLOCKED
    assert "gale" in eval.reason.lower()

def test_risk_calculates_gale_stake(base_account):
    base_account.current_gale_level = 2
    signal = Signal(type=SignalType.PUT, reason="Test")
    eval = evaluate_risk(signal, base_account)
    
    assert eval.decision == RiskDecision.APPROVED
    assert eval.stake == 1.40
