from app.models.market import Signal, AccountState, RiskEvaluation, RiskDecision, SignalType

def evaluate_risk(signal: Signal, account: AccountState) -> RiskEvaluation:
    if signal.type == SignalType.NONE:
        return RiskEvaluation(
            decision=RiskDecision.BLOCKED,
            reason="No signal to execute",
            stake=0.0,
            gale_level=0
        )
        
    if account.daily_pnl <= account.daily_stop_loss:
        return RiskEvaluation(
            decision=RiskDecision.BLOCKED,
            reason=f"Daily stop-loss reached: {account.daily_pnl}",
            stake=0.0,
            gale_level=0
        )
        
    if account.daily_pnl >= account.daily_stop_gain:
        return RiskEvaluation(
            decision=RiskDecision.BLOCKED,
            reason=f"Daily stop-gain reached: {account.daily_pnl}",
            stake=0.0,
            gale_level=0
        )
        
    if account.current_gale_level > account.max_gale:
        return RiskEvaluation(
            decision=RiskDecision.BLOCKED,
            reason=f"Max gale level exceeded: {account.current_gale_level} > {account.max_gale}",
            stake=0.0,
            gale_level=0
        )
        
    calculated_stake = account.stake_initial * (2 ** account.current_gale_level)
    
    return RiskEvaluation(
        decision=RiskDecision.APPROVED,
        reason="Risk constraints passed",
        stake=calculated_stake,
        gale_level=account.current_gale_level
    )
