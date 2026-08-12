"""
Testes para os validadores: ProposalValidator e RiskLimits.
"""
import pytest
import time
from app.validators.proposal_validator import (
    ProposalValidator, ProposalValidatorConfig, ProposalValidationResult,
    ValidationErrorCode
)
from app.validators.risk_limits import AbsoluteLimits, RiskLimits


class TestProposalValidator:
    
    @pytest.fixture
    def validator(self):
        config = ProposalValidatorConfig(
            min_payout_percent=80.0,
            max_latency_ms=200,
            max_stake_usd=100.0,
            enabled_assets=["R_100", "R_50"],
            environment="demo",
        )
        return ProposalValidator(config)
    
    @pytest.fixture
    def valid_proposal(self):
        # Usar timestamp atual para evitar problemas de latencia/expiracao
        current_time = time.time()
        return {
            "proposal_id": "test_123",
            "contract_type": "CALL",
            "currency": "USD",
            "payout": 1.95,
            "payout_percent": 95.0,
            "price": 0.35,
            "symbol": "R_100",
            "environment": "demo",
            "current_spot_time": current_time,
        }
    
    @pytest.fixture
    def valid_signal(self):
        return {"type": "CALL"}
    
    def test_valid_proposal_passes(self, validator, valid_proposal, valid_signal):
        result = validator.validate(valid_proposal, valid_signal)
        assert result.is_valid is True
        assert len(result.errors) == 0
    
    def test_blocks_low_payout(self, validator, valid_proposal, valid_signal):
        valid_proposal["payout_percent"] = 70.0
        result = validator.validate(valid_proposal, valid_signal)
        assert result.is_valid is False
        assert ValidationErrorCode.PAYOUT_BELOW_MINIMUM in result.errors
    
    def test_blocks_signal_contract_mismatch(self, validator, valid_proposal, valid_signal):
        valid_signal["type"] = "PUT"
        result = validator.validate(valid_proposal, valid_signal)
        assert result.is_valid is False
        assert ValidationErrorCode.SIGNAL_CONTRACT_MISMATCH in result.errors
    
    def test_blocks_high_stake(self, validator, valid_proposal, valid_signal):
        valid_proposal["price"] = 150.0
        result = validator.validate(valid_proposal, valid_signal)
        assert result.is_valid is False
        assert ValidationErrorCode.STAKE_ABOVE_LIMIT in result.errors
    
    def test_blocks_disabled_asset(self, validator, valid_proposal, valid_signal):
        valid_proposal["symbol"] = "DISABLED_ASSET"
        result = validator.validate(valid_proposal, valid_signal)
        assert result.is_valid is False
        assert ValidationErrorCode.ASSET_DISABLED in result.errors
    
    def test_blocks_environment_mismatch(self, validator, valid_proposal, valid_signal):
        valid_proposal["environment"] = "real"
        result = validator.validate(valid_proposal, valid_signal)
        assert result.is_valid is False
        assert ValidationErrorCode.ENVIRONMENT_MISMATCH in result.errors


class TestAbsoluteLimits:
    
    @pytest.fixture
    def limits(self):
        return AbsoluteLimits()
    
    def test_gale_limit(self, limits):
        # Deve permitir gale <= 3
        is_valid, _ = limits.validate_gale_level(3)
        assert is_valid is True
        
        # Deve bloquear gale > 3
        is_valid, error = limits.validate_gale_level(4)
        assert is_valid is False
        assert "excede" in error.lower()
    
    def test_stake_limit(self, limits):
        # Deve permitir stake <= 100
        is_valid, _ = limits.validate_stake(100.0)
        assert is_valid is True
        
        # Deve bloquear stake > 100
        is_valid, error = limits.validate_stake(100.01)
        assert is_valid is False
    
    def test_daily_loss_limit(self, limits):
        # Deve permitir loss dentro do limite
        is_valid, _ = limits.validate_daily_pnl(-49.0)
        assert is_valid is True
        
        # Deve bloquear loss acima do limite
        is_valid, error = limits.validate_daily_pnl(-50.01)
        assert is_valid is False
    
    def test_daily_gain_limit(self, limits):
        # Deve permitir gain dentro do limite
        is_valid, _ = limits.validate_daily_pnl(29.0)
        assert is_valid is True
        
        # Deve bloquear gain acima do limite
        is_valid, error = limits.validate_daily_pnl(30.01)
        assert is_valid is False
    
    def test_martingale_sequence(self, limits):
        sequence = limits.calculate_martingale_sequence(0.35, 5)
        # Deve limitar a sequencia ao maximo absoluto
        assert len(sequence) <= limits.MAX_GALE_ABSOLUTE + 1
        # Nenhuma stake deve exceder o limite absoluto
        for stake in sequence:
            assert stake <= limits.MAX_STAKE_ABSOLUTE_USD


class TestRiskLimits:
    
    @pytest.fixture
    def risk_limits(self):
        return RiskLimits(
            max_gale_config=2,  # Configurado pelo usuario
            max_stake_config=50.0,
            max_daily_loss_config=20.0,
            max_daily_gain_config=15.0,
        )
    
    def test_effective_limits_respect_absolute(self, risk_limits):
        effective = risk_limits.get_effective_limits()
        
        # Gale efetivo deve ser o minimo entre configurado e absoluto
        assert effective["max_gale"] == min(2, risk_limits.absolute.MAX_GALE_ABSOLUTE)
        # Stake efetiva deve ser o minimo entre configurado e absoluta
        assert effective["max_stake_usd"] == min(50.0, risk_limits.absolute.MAX_STAKE_ABSOLUTE_USD)
    
    def test_config_more_restrictive_than_absolute(self, risk_limits):
        # Configuracao do usuario e mais restritiva que o absoluto
        assert risk_limits.max_gale_config < risk_limits.absolute.MAX_GALE_ABSOLUTE
        assert risk_limits.max_stake_config < risk_limits.absolute.MAX_STAKE_ABSOLUTE_USD
        
        # Validacao deve usar limites mais restritivos
        is_valid, _ = risk_limits.validate_gale(2)
        assert is_valid is True
        
        is_valid, error = risk_limits.validate_gale(3)
        assert is_valid is False  # Bloqueado pelo limite configurado (2)
    
    def test_safe_stake_calculation(self, risk_limits):
        stake, is_valid, msg = risk_limits.calculate_safe_stake(
            initial_stake=0.35,
            gale_level=2,
            current_exposure=0.0,
        )
        
        # 0.35 * 2^2 = 1.40, dentro dos limites
        assert stake == 1.40
        assert is_valid is True
