"""
Circuit Breaker - Implementa padrao Circuit Breaker para protecao do sistema.

Circuit breakers implementados:
- Latencia alta (> 500ms) → bloquear por 5 minutos
- Reconexao recente → bloquear por 2 minutos apos reconnect
- Erro Deriv API consecutivo (3 erros) → bloquear por 10 minutos
- Payout abaixo do minimo (< 80%) → bloquear entrada
- Proposal divergente → bloquear e alertar
"""
import time
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class CircuitState(str, Enum):
    """Estados do circuit breaker."""
    CLOSED = "closed"  # Normal, operacoes permitidas
    OPEN = "open"  # Bloqueado, operacoes rejeitadas
    HALF_OPEN = "half_open"  # Testando, uma operacao permitida


class BreakerType(str, Enum):
    """Tipos de circuit breaker."""
    LATENCY = "latency"
    RECONNECTION = "reconnection"
    API_ERROR = "api_error"
    PAYOUT = "payout"
    PROPOSAL = "proposal"


class CircuitBreakerConfig(BaseModel):
    """Configuracao dos circuit breakers."""
    # Latencia
    latency_threshold_ms: int = Field(default=500, description="Limite de latencia em ms")
    latency_cooldown_seconds: int = Field(default=300, description="Cooldown apos latencia alta (5 min)")
    
    # Reconexão
    reconnection_cooldown_seconds: int = Field(default=120, description="Cooldown apos reconexão (2 min)")
    
    # Erros API
    api_error_threshold: int = Field(default=3, description="Erros consecutivos para abrir circuit")
    api_error_cooldown_seconds: int = Field(default=600, description="Cooldown apos erros API (10 min)")
    
    # Payout
    min_payout_percent: float = Field(default=80.0, description="Payout minimo em porcentagem")
    
    # Proposal divergente
    proposal_divergence_cooldown_seconds: int = Field(default=60, description="Cooldown apos proposal divergente")


class CircuitBreakerStatus(BaseModel):
    """Status de um circuit breaker."""
    breaker_type: BreakerType
    state: CircuitState
    opened_at: Optional[float] = None
    cooldown_remaining_seconds: float = 0.0
    failure_count: int = 0
    last_failure_time: Optional[float] = None
    message: str = ""


class CircuitBreaker:
    """
    Circuit Breaker individual para um tipo especifico de falha.
    
    Uso:
        breaker = CircuitBreaker(BreakerType.LATENCY, config)
        breaker.record_latency(600)  # > 500ms
        if breaker.is_open():
            # Bloquear operacao
    """
    
    def __init__(self, breaker_type: BreakerType, config: CircuitBreakerConfig):
        self.breaker_type = breaker_type
        self.config = config
        self.state = CircuitState.CLOSED
        self.opened_at: Optional[float] = None
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self._threshold = self._get_threshold()
        self._cooldown = self._get_cooldown()
    
    def _get_threshold(self) -> int:
        """Obtem threshold baseado no tipo de breaker."""
        if self.breaker_type == BreakerType.API_ERROR:
            return self.config.api_error_threshold
        return 1  # Para outros tipos, uma falha ja abre
    
    def _get_cooldown(self) -> int:
        """Obtem cooldown baseado no tipo de breaker."""
        cooldowns = {
            BreakerType.LATENCY: self.config.latency_cooldown_seconds,
            BreakerType.RECONNECTION: self.config.reconnection_cooldown_seconds,
            BreakerType.API_ERROR: self.config.api_error_cooldown_seconds,
            BreakerType.PAYOUT: 60,  # 1 minuto
            BreakerType.PROPOSAL: self.config.proposal_divergence_cooldown_seconds,
        }
        return cooldowns.get(self.breaker_type, 60)
    
    def record_failure(self, reason: str = ""):
        """Registra uma falha e abre o circuit se threshold atingido."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self._threshold:
            self.open(reason)
    
    def record_success(self):
        """Registra sucesso e reseta o circuit."""
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.opened_at = None
    
    def open(self, reason: str = ""):
        """Abre o circuit breaker."""
        self.state = CircuitState.OPEN
        self.opened_at = time.time()
    
    def close(self):
        """Fecha o circuit breaker manualmente."""
        self.state = CircuitState.CLOSED
        self.opened_at = None
        self.failure_count = 0
    
    def is_open(self) -> bool:
        """
        Verifica se o circuit breaker esta aberto.
        
        Automaticamente transita para HALF_OPEN se cooldown expirou.
        
        Returns:
            bool: True se OPEN (bloqueando), False se CLOSED ou HALF_OPEN
        """
        if self.state == CircuitState.CLOSED:
            return False
        
        if self.state == CircuitState.OPEN and self.opened_at:
            elapsed = time.time() - self.opened_at
            if elapsed >= self._cooldown:
                # Transitar para HALF_OPEN
                self.state = CircuitState.HALF_OPEN
                self.opened_at = None  # Reset opened_at ao transitar
                return False  # HALF_OPEN nao bloqueia totalmente
        
        return self.state == CircuitState.OPEN
    
    def get_status(self) -> CircuitBreakerStatus:
        """Retorna status detalhado do circuit breaker."""
        cooldown_remaining = 0.0
        
        if self.state == CircuitState.OPEN and self.opened_at:
            elapsed = time.time() - self.opened_at
            cooldown_remaining = max(0, self._cooldown - elapsed)
        
        return CircuitBreakerStatus(
            breaker_type=self.breaker_type,
            state=self.state,
            opened_at=self.opened_at,
            cooldown_remaining_seconds=cooldown_remaining,
            failure_count=self.failure_count,
            last_failure_time=self.last_failure_time,
        )
    
    def cooldown_remaining(self) -> float:
        """Retorna tempo restante de cooldown em segundos."""
        if self.state != CircuitState.OPEN or not self.opened_at:
            return 0.0
        
        elapsed = time.time() - self.opened_at
        return max(0, self._cooldown - elapsed)


class CircuitBreakerManager:
    """
    Gerenciador de todos os circuit breakers do sistema.
    
    Uso:
        manager = CircuitBreakerManager()
        manager.record_latency(600)
        if manager.is_any_open():
            # Bloquear todas as operacoes
    """
    
    def __init__(self, config: Optional[CircuitBreakerConfig] = None):
        self.config = config or CircuitBreakerConfig()
        self.breakers = {
            BreakerType.LATENCY: CircuitBreaker(BreakerType.LATENCY, self.config),
            BreakerType.RECONNECTION: CircuitBreaker(BreakerType.RECONNECTION, self.config),
            BreakerType.API_ERROR: CircuitBreaker(BreakerType.API_ERROR, self.config),
            BreakerType.PAYOUT: CircuitBreaker(BreakerType.PAYOUT, self.config),
            BreakerType.PROPOSAL: CircuitBreaker(BreakerType.PROPOSAL, self.config),
        }
        self._last_latency: Optional[float] = None
    
    def record_latency(self, latency_ms: float):
        """Registra latencia e abre circuit se acima do threshold."""
        self._last_latency = latency_ms
        
        if latency_ms > self.config.latency_threshold_ms:
            self.breakers[BreakerType.LATENCY].record_failure(
                f"Latencia {latency_ms:.0f}ms > {self.config.latency_threshold_ms}ms"
            )
        else:
            self.breakers[BreakerType.LATENCY].record_success()
    
    def record_reconnection(self):
        """Registra reconexão e abre circuit temporariamente."""
        self.breakers[BreakerType.RECONNECTION].open("Reconexão realizada")
    
    def record_api_error(self, error: str = ""):
        """Registra erro da API Deriv."""
        self.breakers[BreakerType.API_ERROR].record_failure(error)
    
    def record_api_success(self):
        """Registra sucesso na API Deriv."""
        self.breakers[BreakerType.API_ERROR].record_success()
    
    def record_low_payout(self, payout_percent: float):
        """Registra payout abaixo do minimo."""
        if payout_percent < self.config.min_payout_percent:
            self.breakers[BreakerType.PAYOUT].record_failure(
                f"Payout {payout_percent:.1f}% < {self.config.min_payout_percent}%"
            )
    
    def record_proposal_divergence(self, reason: str = ""):
        """Registra proposal divergente."""
        self.breakers[BreakerType.PROPOSAL].record_failure(reason)
    
    def is_any_open(self) -> bool:
        """Verifica se algum circuit breaker esta aberto."""
        return any(breaker.is_open() for breaker in self.breakers.values())
    
    def is_all_closed(self) -> bool:
        """Verifica se todos os circuit breakers estao fechados ou half-open."""
        return all(not breaker.is_open() for breaker in self.breakers.values())
    
    def get_status(self) -> dict:
        """Retorna status de todos os circuit breakers."""
        return {
            breaker_type.value: breaker.get_status()
            for breaker_type, breaker in self.breakers.items()
        }
    
    def get_blocking_reason(self) -> Optional[str]:
        """Retorna motivo do bloqueio se algum circuit estiver aberto."""
        for breaker_type, breaker in self.breakers.items():
            if breaker.is_open():
                cooldown = breaker.cooldown_remaining()
                return f"Circuit {breaker_type.value} aberto - aguardar {cooldown:.0f}s"
        return None
    
    def can_trade(self) -> tuple[bool, Optional[str]]:
        """
        Verifica se operacoes podem ser realizadas.
        
        Returns:
            tuple[bool, Optional[str]]: (pode_operar, motivo_bloqueio)
        """
        if self.is_any_open():
            return False, self.get_blocking_reason()
        return True, None
    
    def reset_all(self):
        """Reseta todos os circuit breakers (apenas para debug/testes)."""
        for breaker in self.breakers.values():
            breaker.close()
    
    def get_last_latency(self) -> Optional[float]:
        """Retorna ultima latencia registrada."""
        return self._last_latency


# Singleton global para uso em todo o sistema
_global_manager: Optional[CircuitBreakerManager] = None


def get_circuit_breaker_manager(config: Optional[CircuitBreakerConfig] = None) -> CircuitBreakerManager:
    """Obtem instancia singleton do CircuitBreakerManager."""
    global _global_manager
    if _global_manager is None:
        _global_manager = CircuitBreakerManager(config)
    return _global_manager


def reset_circuit_breaker_manager():
    """Reseta singleton (para testes)."""
    global _global_manager
    _global_manager = None
