"""
Risk Engine - Motor de avaliacao de risco com limites absolutos e circuit breakers.

Integra:
- Limites absolutos hard-coded (nao podem ser sobrescritos)
- Circuit breakers para protecao do sistema
- News filter para bloqueio durante eventos de alto impacto
"""
from typing import Optional, Tuple
from app.models.market import Signal, AccountState, RiskEvaluation, RiskDecision, SignalType
from app.validators.risk_limits import AbsoluteLimits, RiskLimits
from app.engines.circuit_breaker import CircuitBreakerManager, get_circuit_breaker_manager


def evaluate_risk(
    signal: Signal,
    account: AccountState,
    news_filter: Optional[object] = None,
    circuit_breaker_manager: Optional[CircuitBreakerManager] = None,
    absolute_limits: Optional[AbsoluteLimits] = None,
    config_gale: int = 5,
    config_stake: float = 50.0,
    config_daily_loss: float = 20.0,
    config_daily_gain: float = 15.0,
) -> RiskEvaluation:
    """
    Avalia risco de um sinal considerando todos os guardrails de seguranca.
    
    Args:
        signal: Sinal gerado pelo Strategy Engine
        account: Estado atual da conta
        news_filter: Filtro de noticias (opcional)
        circuit_breaker_manager: Gerenciador de circuit breakers (opcional)
        absolute_limits: Limites absolutos (usa default se None)
        config_gale: Gale configurado pelo usuario (limitado pelo absoluto)
        config_stake: Stake configurada pelo usuario (limitada pelo absoluto)
        config_daily_loss: Loss diario configurado (limitado pelo absoluto)
        config_daily_gain: Gain diario configurado (limitado pelo absoluto)
    
    Returns:
        RiskEvaluation com decisao e justificativa
    """
    absolute = absolute_limits or AbsoluteLimits()
    cb_manager = circuit_breaker_manager or get_circuit_breaker_manager()
    
    # Criar RiskLimits com configuracoes do usuario (respeitando limites absolutos)
    risk_limits = RiskLimits(
        max_gale_config=config_gale,
        max_stake_config=config_stake,
        max_daily_loss_config=config_daily_loss,
        max_daily_gain_config=config_daily_gain,
    )
    
    # 1. Validar sinal basico
    if signal.type == SignalType.NONE:
        return RiskEvaluation(
            decision=RiskDecision.BLOCKED,
            reason="No signal to execute",
            stake=0.0,
            gale_level=0
        )
    
    # 2. Verificar circuit breakers PRIMEIRO (bloqueio global)
    can_trade, block_reason = cb_manager.can_trade()
    if not can_trade:
        return RiskEvaluation(
            decision=RiskDecision.BLOCKED,
            reason=f"Circuit breaker: {block_reason}",
            stake=0.0,
            gale_level=0
        )
    
    # 3. Verificar news filter (bloqueio durante eventos de alto impacto)
    if news_filter:
        try:
            news_safety = news_filter.check_safety()
            if not news_safety.get("is_safe", True):
                return RiskEvaluation(
                    decision=RiskDecision.BLOCKED,
                    reason=f"News filter: {news_safety.get('reason', 'High impact news detected')}",
                    stake=0.0,
                    gale_level=0
                )
        except Exception:
            pass  # Se news filter falhar, continuar sem bloquear
    
    # 4. Validar limites absolutos de PnL diario
    is_valid, error = absolute.validate_daily_pnl(account.daily_pnl)
    if not is_valid:
        return RiskEvaluation(
            decision=RiskDecision.BLOCKED,
            reason=f"Absolute limit: {error}",
            stake=0.0,
            gale_level=0
        )
    
    # 5. Validar limites configuraveis de PnL diario
    is_valid, error = risk_limits.validate_daily_pnl(account.daily_pnl)
    if not is_valid:
        return RiskEvaluation(
            decision=RiskDecision.BLOCKED,
            reason=f"Config limit: {error}",
            stake=0.0,
            gale_level=0
        )
    
    # 6. Validar gale level contra limites absolutos
    is_valid, error = absolute.validate_gale_level(account.current_gale_level)
    if not is_valid:
        return RiskEvaluation(
            decision=RiskDecision.BLOCKED,
            reason=f"Absolute gale limit: {error}",
            stake=0.0,
            gale_level=0
        )
    
    # 7. Validar gale level contra limites configuraveis
    is_valid, error = risk_limits.validate_gale(account.current_gale_level)
    if not is_valid:
        return RiskEvaluation(
            decision=RiskDecision.BLOCKED,
            reason=f"Config gale limit: {error}",
            stake=0.0,
            gale_level=0
        )
    
    # 8. Calcular stake segura respeitando todos os limites
    safe_stake, is_within_limits, stake_message = risk_limits.calculate_safe_stake(
        initial_stake=account.stake_initial,
        gale_level=account.current_gale_level,
        current_exposure=0.0  # TODO: Implementar tracking de exposicao
    )
    
    if safe_stake <= 0:
        return RiskEvaluation(
            decision=RiskDecision.BLOCKED,
            reason=f"Stake calculation: {stake_message}",
            stake=0.0,
            gale_level=0
        )
    
    # 9. Validar stake individual
    is_valid, error = risk_limits.validate_stake(safe_stake)
    if not is_valid and not is_within_limits:
        # Stake foi reduzida mas ainda e valida - usar reduzida
        if safe_stake > 0:
            pass  # Usar stake reduzida
        else:
            return RiskEvaluation(
                decision=RiskDecision.BLOCKED,
                reason=f"Stake limit: {error}",
                stake=0.0,
                gale_level=0
            )
    
    # 10. Verificar losses consecutivos (se disponivel no account)
    if hasattr(account, 'consecutive_losses'):
        is_valid, error = risk_limits.validate_consecutive_losses(account.consecutive_losses)
        if not is_valid:
            return RiskEvaluation(
                decision=RiskDecision.BLOCKED,
                reason=f"Consecutive losses: {error}",
                stake=0.0,
                gale_level=0
            )
    
    # 11. Verificar limite de trades por dia (se disponivel no account)
    if hasattr(account, 'trades_today') and hasattr(account, 'max_trades_per_day'):
        if account.trades_today >= account.max_trades_per_day:
            return RiskEvaluation(
                decision=RiskDecision.BLOCKED,
                reason=f"Daily trade limit reached: {account.trades_today}/{account.max_trades_per_day}",
                stake=0.0,
                gale_level=0
            )
    
    # Todos os checks passaram - APROVAR
    return RiskEvaluation(
        decision=RiskDecision.APPROVED,
        reason="Risk constraints passed" if is_within_limits else f"Risk approved with adjustments: {stake_message}",
        stake=safe_stake,
        gale_level=account.current_gale_level
    )


def get_effective_risk_limits(
    config_gale: int = 5,
    config_stake: float = 50.0,
    config_daily_loss: float = 20.0,
    config_daily_gain: float = 15.0,
) -> dict:
    """
    Retorna limites efetivos de risco (menor entre configurado e absoluto).
    
    Returns:
        dict com todos os limites efetivos
    """
    absolute = AbsoluteLimits()
    risk_limits = RiskLimits(
        max_gale_config=config_gale,
        max_stake_config=config_stake,
        max_daily_loss_config=config_daily_loss,
        max_daily_gain_config=config_daily_gain,
    )
    
    return risk_limits.get_effective_limits()
