"""
Decision Harness - Unifica sinal, risco, agente e politica de execucao.

Este componente:
1. Recebe sinal do Strategy Engine
2. Avalia risco com Risk Engine (incluindo limites absolutos e circuit breakers)
3. Solicita revisao do agente RAG (se disponivel)
4. Determina se requer confirmacao manual
5. Produz decisao estruturada para execucao
"""
import logging
from typing import Optional, Tuple
from app.models.market import (
    Signal, AccountState, RiskEvaluation, RiskDecision,
    DerivProposal, AgentReview, DecisionHarnessOutput
)
from app.engines.risk import evaluate_risk
from app.validators.proposal_validator import ProposalValidator, ProposalValidationResult
from app.validators.risk_limits import AbsoluteLimits

logger = logging.getLogger(__name__)


class DecisionHarnessConfig:
    """Configuracao do Decision Harness."""
    
    def __init__(
        self,
        require_manual_confirmation_real: bool = True,
        require_manual_confirmation_demo: bool = False,
        auto_confirm_low_risk: bool = False,
        agent_required_for_high_risk: bool = True,
    ):
        """
        Args:
            require_manual_confirmation_real: Exige confirmacao manual em conta real
            require_manual_confirmation_demo: Exige confirmacao manual em conta demo
            auto_confirm_low_risk: Auto-confirmar operacoes de risco baixo
            agent_required_for_high_risk: Exige revisao do agente para risco alto
        """
        self.require_manual_confirmation_real = require_manual_confirmation_real
        self.require_manual_confirmation_demo = require_manual_confirmation_demo
        self.auto_confirm_low_risk = auto_confirm_low_risk
        self.agent_required_for_high_risk = agent_required_for_high_risk


class DecisionHarness:
    """
    Orquestra processo de decisao de trading.
    
    Fluxo:
        Signal -> Risk Evaluation -> Agent Review (opcional) -> Final Decision
    
    Uso:
        harness = DecisionHarness(config)
        output = harness.evaluate(signal, account, agent_service)
        
        if output.final_decision == RiskDecision.APPROVED:
            # Executar operacao
        elif output.manual_confirmation_required:
            # Aguardar confirmacao do usuario
        else:
            # Bloqueado
    """
    
    def __init__(self, config: Optional[DecisionHarnessConfig] = None):
        self.config = config or DecisionHarnessConfig()
        self.absolute_limits = AbsoluteLimits()
        self.proposal_validator = ProposalValidator()
    
    def evaluate(
        self,
        signal: Signal,
        account: AccountState,
        agent_service: Optional[object] = None,
        news_filter: Optional[object] = None,
        proposal: Optional[DerivProposal] = None,
    ) -> DecisionHarnessOutput:
        """
        Avalia sinal e produz decisao estruturada.
        
        Args:
            signal: Sinal do Strategy Engine
            account: Estado atual da conta
            agent_service: Servico RAG do agente (opcional)
            news_filter: Filtro de noticias (opcional)
            proposal: Proposta da Deriv API (para validacao final)
        
        Returns:
            DecisionHarnessOutput com decisao final e instrucoes
        """
        messages = []
        
        # 1. Avaliacao de risco
        risk_evaluation = evaluate_risk(
            signal=signal,
            account=account,
            news_filter=news_filter,
        )
        
        if risk_evaluation.decision == RiskDecision.BLOCKED:
            logger.info(f"Signal blocked by risk engine: {risk_evaluation.reason}")
            return DecisionHarnessOutput(
                signal=signal,
                risk_evaluation=risk_evaluation,
                final_decision=RiskDecision.BLOCKED,
                final_message=f"Blocked by risk: {risk_evaluation.reason}",
                stake_to_use=0.0,
                gale_level_to_use=0,
                manual_confirmation_required=False,
            )
        
        # 2. Revisao do agente (se disponivel)
        agent_review: Optional[AgentReview] = None
        if agent_service:
            try:
                agent_review = self._get_agent_review(agent_service, signal, risk_evaluation)
                messages.append(f"Agent review: {agent_review.summary}")
                
                # Se agente recomenda bloquear e e risco alto, respeitar
                if (agent_review.recommendation == "block" and 
                    agent_review.risk_level == "high"):
                    logger.info(f"Signal blocked by agent review: {agent_review.summary}")
                    return DecisionHarnessOutput(
                        signal=signal,
                        risk_evaluation=risk_evaluation,
                        agent_review=agent_review,
                        final_decision=RiskDecision.BLOCKED,
                        final_message=f"Blocked by agent: {agent_review.summary}",
                        stake_to_use=0.0,
                        gale_level_to_use=0,
                        manual_confirmation_required=False,
                    )
            except Exception as e:
                logger.warning(f"Agent review failed: {e}")
                # Continuar sem agente - nao bloquear por falha do agente
        
        # 3. Validar proposta (se fornecida)
        if proposal:
            validation_result = self.proposal_validator.validate(
                proposal=proposal.dict(),
                signal={"type": signal.type.value},
            )
            
            if not validation_result.is_valid:
                errors_str = ", ".join(validation_result.error_messages)
                logger.info(f"Proposal validation failed: {errors_str}")
                return DecisionHarnessOutput(
                    signal=signal,
                    risk_evaluation=risk_evaluation,
                    agent_review=agent_review,
                    final_decision=RiskDecision.BLOCKED,
                    final_message=f"Proposal validation failed: {errors_str}",
                    stake_to_use=0.0,
                    gale_level_to_use=0,
                    manual_confirmation_required=False,
                )
            
            messages.extend(validation_result.warnings)
        
        # 4. Determinar se requer confirmacao manual
        manual_confirmation_required = self._requires_manual_confirmation(
            account=account,
            risk_evaluation=risk_evaluation,
            agent_review=agent_review,
        )
        
        # 5. Determinar decisao final
        if manual_confirmation_required:
            final_decision = RiskDecision.PENDING_MANUAL
            final_message = "Awaiting manual confirmation"
        else:
            final_decision = RiskDecision.APPROVED
            final_message = "Auto-approved for execution"
        
        # Adicionar mensagens de contexto
        if agent_review:
            final_message += f" | Agent: {agent_review.summary}"
        if messages:
            final_message += " | " + ", ".join(messages)
        
        return DecisionHarnessOutput(
            signal=signal,
            risk_evaluation=risk_evaluation,
            agent_review=agent_review,
            final_decision=final_decision,
            final_message=final_message,
            stake_to_use=risk_evaluation.stake,
            gale_level_to_use=risk_evaluation.gale_level,
            manual_confirmation_required=manual_confirmation_required,
        )
    
    def _get_agent_review(
        self,
        agent_service: object,
        signal: Signal,
        risk_evaluation: RiskEvaluation,
    ) -> AgentReview:
        """
        Solicita revisao do agente RAG.
        
        Args:
            agent_service: Instancia do servico RAG (RagAgentService)
            signal: Sinal atual
            risk_evaluation: Avaliacao de risco
        
        Returns:
            AgentReview com recomendacao do agente
        """
        # Usar a funcao review_signal do rag.agent
        # Verificar se e o servico RagAgentService ou um modulo
        try:
            # Tentar chamar como metodo de instancia
            if hasattr(agent_service, "review_signal"):
                review = agent_service.review_signal(signal, risk_evaluation, symbol=signal.symbol or "")
                if isinstance(review, AgentReview):
                    return review
                if isinstance(review, dict):
                    return AgentReview(**review)
            
            # Fallback: tentar importar do modulo rag.agent
            from app.rag.agent import review_signal as rag_review_signal
            review = rag_review_signal(signal, risk_evaluation, symbol=signal.symbol or "")
            if isinstance(review, AgentReview):
                return review
            if isinstance(review, dict):
                return AgentReview(**review)
        except Exception as e:
            logger.warning(f"Agent review call failed: {e}")
        
        # Fallback final: criar review basico
        return AgentReview(
            risk_level="medium",
            recommendation="execute",
            summary="Agent review unavailable",
            sources=[],
        )
    
    def _requires_manual_confirmation(
        self,
        account: AccountState,
        risk_evaluation: RiskEvaluation,
        agent_review: Optional[AgentReview],
    ) -> bool:
        """
        Determina se operacao requer confirmacao manual.
        
        Regras:
        - Conta real: sempre requer confirmacao (configuravel)
        - Risco alto: requer confirmacao
        - Agente recomenda confirmacao: requer confirmacao
        - Gale > 0: requer confirmacao em conta real
        """
        # Conta real sempre requer confirmacao (padrao)
        if account.environment == "real":
            if self.config.require_manual_confirmation_real:
                return True
        
        # Conta demo pode requerer confirmacao (configuravel)
        if account.environment == "demo":
            if self.config.require_manual_confirmation_demo:
                return True
        
        # Agente recomenda confirmacao manual
        if agent_review and agent_review.recommendation == "manual_confirm":
            return True
        
        # Gale > 0 em conta real
        if account.environment == "real" and risk_evaluation.gale_level > 0:
            return True
        
        # Risco alto (se agente classificou)
        if agent_review and agent_review.risk_level == "high":
            return True
        
        return False
    
    def confirm_manual_decision(
        self,
        decision_id: str,
        confirmed: bool,
        user_id: str,
    ) -> Tuple[bool, str]:
        """
        Processa confirmacao manual do usuario.
        
        Args:
            decision_id: ID da decisao pendente
            confirmed: True para confirmar, False para bloquear
            user_id: ID do usuario que confirmou
        
        Returns:
            Tuple[bool, str]: (sucesso, mensagem)
        """
        # TODO: Implementar armazenamento de decisoes pendentes
        # Por enquanto, apenas logar
        action = "confirmed" if confirmed else "rejected"
        logger.info(f"Manual decision {decision_id} {action} by user {user_id}")
        
        if confirmed:
            return True, "Decision confirmed - proceeding with execution"
        else:
            return False, "Decision rejected - trade blocked"


# Singleton global
_global_harness: Optional[DecisionHarness] = None


def get_decision_harness(config: Optional[DecisionHarnessConfig] = None) -> DecisionHarness:
    """Obtem instancia singleton do DecisionHarness."""
    global _global_harness
    if _global_harness is None:
        _global_harness = DecisionHarness(config)
    return _global_harness


def reset_decision_harness():
    """Reseta singleton (para testes)."""
    global _global_harness
    _global_harness = None
