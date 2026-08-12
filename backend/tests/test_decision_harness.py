"""
Testes para o Decision Harness.
"""
import pytest
from unittest.mock import MagicMock
from app.models.market import Signal, SignalType, AccountState, RiskEvaluation, RiskDecision, AgentReview, DerivProposal
from app.engines.decision_harness import DecisionHarness, DecisionHarnessConfig
from app.engines.circuit_breaker import CircuitBreakerManager, get_circuit_breaker_manager, reset_circuit_breaker_manager
from app.engines.news import NewsFilter
from app.validators.proposal_validator import ProposalValidatorConfig
import time


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reseta singletons antes e depois de cada teste."""
    reset_circuit_breaker_manager()
    yield
    reset_circuit_breaker_manager()


@pytest.fixture
def base_signal():
    return Signal(type=SignalType.PUT, reason="9 velas de alta", symbol="R_100")

@pytest.fixture
def base_account():
    return AccountState(
        balance=1000.0,
        daily_pnl=0.0,
        current_gale_level=0,
        daily_stop_loss=20.0,
        daily_stop_gain=15.0,
        max_gale=3,
        stake_initial=0.35,
        environment="demo",
    )

@pytest.fixture
def mock_agent_service():
    mock = MagicMock()
    mock.review_signal.return_value = AgentReview(
        risk_level="low",
        recommendation="execute",
        summary="Sinal ABR ok, risco baixo",
        sources=["doc1.md"]
    )
    return mock

@pytest.fixture
def mock_news_filter():
    mock = MagicMock()
    mock.check_safety.return_value = {"safe": True, "reason": "No news"}
    return mock

@pytest.fixture
def harness(base_account, mock_news_filter):
    # Config default para o harness
    config = DecisionHarnessConfig(
        require_manual_confirmation_real=True,
        require_manual_confirmation_demo=False,
    )
    return DecisionHarness(config)


class TestDecisionHarness:
    def test_signal_blocked_by_risk_engine(self, harness, base_signal, base_account, mock_agent_service, mock_news_filter):
        # Simular circuit breaker aberto
        cb_manager = get_circuit_breaker_manager()
        cb_manager.record_latency(600)  # Abre o circuit breaker de latencia
        
        output = harness.evaluate(base_signal, base_account, mock_agent_service, mock_news_filter)
        
        assert output.final_decision == RiskDecision.BLOCKED
        assert "Circuit breaker" in output.final_message
        assert output.manual_confirmation_required is False
        
        cb_manager.reset_all() # Resetar para nao afetar outros testes
    
    def test_signal_approved_auto(self, harness, base_signal, base_account, mock_agent_service, mock_news_filter):
        output = harness.evaluate(base_signal, base_account, mock_agent_service, mock_news_filter)
        
        assert output.final_decision == RiskDecision.APPROVED
        assert output.manual_confirmation_required is False
        assert output.stake_to_use == pytest.approx(0.35)
        assert "Auto-approved" in output.final_message
        assert output.agent_review is not None
    
    def test_signal_pending_manual_confirmation_real_account(self, base_signal, mock_agent_service, mock_news_filter):
        real_account = AccountState(
            balance=1000.0, daily_pnl=0.0, current_gale_level=0,
            daily_stop_loss=20.0, daily_stop_gain=15.0, max_gale=3, stake_initial=0.35,
            environment="real" # Conta real
        )
        harness_real = DecisionHarness(DecisionHarnessConfig(require_manual_confirmation_real=True)) # Usar config padrao
        
        output = harness_real.evaluate(base_signal, real_account, mock_agent_service, mock_news_filter)
        
        assert output.final_decision == RiskDecision.PENDING_MANUAL
        assert output.manual_confirmation_required is True
        assert "Awaiting manual confirmation" in output.final_message
    
    def test_signal_pending_manual_confirmation_agent_recommendation(self, harness, base_signal, base_account, mock_news_filter):
        mock_agent_service = MagicMock()
        mock_agent_service.review_signal.return_value = AgentReview(
            risk_level="medium",
            recommendation="manual_confirm", # Agente recomenda confirmacao manual
            summary="Sinal com risco medio, requer confirmacao",
            sources=["doc2.md"]
        )
        
        output = harness.evaluate(base_signal, base_account, mock_agent_service, mock_news_filter)
        
        assert output.final_decision == RiskDecision.PENDING_MANUAL
        assert output.manual_confirmation_required is True
        assert "Awaiting manual confirmation" in output.final_message
        assert output.agent_review.recommendation == "manual_confirm"
    
    def test_signal_blocked_by_agent_high_risk(self, harness, base_signal, base_account, mock_news_filter):
        mock_agent_service = MagicMock()
        mock_agent_service.review_signal.return_value = AgentReview(
            risk_level="high",
            recommendation="block", # Agente recomenda bloquear em risco alto
            summary="Risco alto detectado pelo agente",
            sources=["doc3.md"]
        )
        
        output = harness.evaluate(base_signal, base_account, mock_agent_service, mock_news_filter)
        
        assert output.final_decision == RiskDecision.BLOCKED
        assert output.manual_confirmation_required is False
        assert "Blocked by agent" in output.final_message
    
    def test_proposal_validation_failure_blocks_trade(self, harness, base_signal, base_account, mock_agent_service, mock_news_filter):
        # Usar timestamp atual para evitar problema de latencia/expiracao
        current_time = int(time.time())
        invalid_proposal = DerivProposal(
            proposal_id="prop_123", symbol="R_100", contract_type="PUT",
            duration=5, duration_unit="m", amount=0.35, price=0.35,
            payout=0.6, longcode="", shortcode="", display_value="",
            spot=100.0, spot_time=current_time, payout_percent=70.0, # Payout muito baixo
            environment="demo", currency="USD" # Adicionar currency
        )
        
        output = harness.evaluate(base_signal, base_account, mock_agent_service, mock_news_filter, proposal=invalid_proposal)
        
        assert output.final_decision == RiskDecision.BLOCKED
        assert "Proposal validation failed" in output.final_message
        assert "Payout 70.0% abaixo do minimo 80.0%" in output.final_message # Agora deve passar aqui
    
    def test_manual_confirmation_gale_level_real_account(self, base_signal, mock_agent_service, mock_news_filter):
        account_with_gale = AccountState(
            balance=1000.0, daily_pnl=0.0, current_gale_level=1, # Gale 1
            daily_stop_loss=20.0, daily_stop_gain=15.0, max_gale=3, stake_initial=0.35,
            environment="real" # Conta real
        )
        harness_real = DecisionHarness(DecisionHarnessConfig(require_manual_confirmation_real=False)) # Desabilitar confirmacao base
        
        output = harness_real.evaluate(base_signal, account_with_gale, mock_agent_service, mock_news_filter)
        
        assert output.final_decision == RiskDecision.PENDING_MANUAL
        assert output.manual_confirmation_required is True
        assert "Awaiting manual confirmation" in output.final_message
        
    def test_agent_service_not_provided(self, harness, base_signal, base_account, mock_news_filter):
        output = harness.evaluate(base_signal, base_account, news_filter=mock_news_filter)
        
        assert output.final_decision == RiskDecision.APPROVED
        assert output.agent_review is None
        assert "Auto-approved" in output.final_message
        assert "Agent review unavailable" not in output.final_message
