"""
Testes para Circuit Breaker.
"""
import pytest
import time
from app.engines.circuit_breaker import (
    CircuitBreaker, CircuitBreakerManager, CircuitBreakerConfig,
    BreakerType, CircuitState,
    get_circuit_breaker_manager, reset_circuit_breaker_manager
)


class TestCircuitBreaker:
    
    @pytest.fixture
    def config(self):
        return CircuitBreakerConfig(
            latency_threshold_ms=500,
            latency_cooldown_seconds=5,  # 5 segundos para testes
            api_error_threshold=3,
            api_error_cooldown_seconds=10,
        )
    
    @pytest.fixture
    def breaker(self, config):
        return CircuitBreaker(BreakerType.LATENCY, config)
    
    def test_initial_state_closed(self, breaker):
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_open() is False
    
    def test_opens_after_threshold(self, breaker, config):
        # Threshold para latencia e 1
        breaker.record_failure("Latencia alta")
        assert breaker.state == CircuitState.OPEN
        assert breaker.is_open() is True
    
    def test_closes_after_success(self, breaker):
        breaker.record_failure("Erro")
        assert breaker.is_open() is True
        
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_open() is False
    
    def test_half_open_after_cooldown(self, config):
        # Usar cooldown muito curto para teste
        config.latency_cooldown_seconds = 0.1
        breaker = CircuitBreaker(BreakerType.LATENCY, config)
        
        breaker.record_failure("Erro")
        assert breaker.is_open() is True
        
        # Aguardar cooldown
        time.sleep(0.15)
        
        # Chamar is_open() para forcar transicao para HALF_OPEN
        is_open = breaker.is_open()
        assert is_open is False  # HALF_OPEN nao bloqueia
        assert breaker.state == CircuitState.HALF_OPEN


class TestCircuitBreakerManager:
    
    @pytest.fixture(autouse=True)
    def reset_manager(self):
        """Reseta manager antes e depois de cada teste."""
        reset_circuit_breaker_manager()
        yield
        reset_circuit_breaker_manager()
    
    @pytest.fixture
    def manager(self):
        config = CircuitBreakerConfig(
            latency_threshold_ms=500,
            latency_cooldown_seconds=5,
            api_error_threshold=3,
        )
        return get_circuit_breaker_manager(config)
    
    def test_initial_state_all_closed(self, manager):
        assert manager.is_all_closed() is True
        assert manager.is_any_open() is False
        can_trade, reason = manager.can_trade()
        assert can_trade is True
    
    def test_records_latency(self, manager):
        # Latencia normal
        manager.record_latency(100)
        assert manager.get_last_latency() == 100
        
        # Latencia alta
        manager.record_latency(600)
        # Deve abrir circuit breaker de latencia
        can_trade, reason = manager.can_trade()
        assert can_trade is False
        assert "latency" in reason.lower()
    
    def test_records_api_errors(self, manager):
        # 3 erros devem abrir o circuit
        manager.record_api_error("Erro 1")
        manager.record_api_error("Erro 2")
        manager.record_api_error("Erro 3")
        
        can_trade, reason = manager.can_trade()
        assert can_trade is False
        assert "api_error" in reason.lower()
    
    def test_success_resets_api_errors(self, manager):
        manager.record_api_error("Erro 1")
        manager.record_api_error("Erro 2")
        manager.record_api_success()  # Reset
        
        # Mais 2 erros nao devem abrir (contador foi resetado)
        manager.record_api_error("Erro 3")
        manager.record_api_error("Erro 4")
        
        # Circuit ainda deve estar fechado
        assert manager.is_all_closed() is True
    
    def test_low_payout_opens_circuit(self, manager):
        manager.record_low_payout(70.0)  # Abaixo de 80%
        
        can_trade, reason = manager.can_trade()
        assert can_trade is False
        assert "payout" in reason.lower()
    
    def test_proposal_divergence(self, manager):
        manager.record_proposal_divergence("Sinal CALL, proposta PUT")
        
        can_trade, reason = manager.can_trade()
        assert can_trade is False
        assert "proposal" in reason.lower()
    
    def test_reconnection_blocks_temporarily(self, manager):
        manager.record_reconnection()
        
        can_trade, reason = manager.can_trade()
        assert can_trade is False
        assert "reconnection" in reason.lower()
    
    def test_reset_all(self, manager):
        manager.record_latency(600)
        manager.record_api_error("Erro")
        
        assert manager.is_any_open() is True
        
        manager.reset_all()
        
        assert manager.is_all_closed() is True
        can_trade, reason = manager.can_trade()
        assert can_trade is True
