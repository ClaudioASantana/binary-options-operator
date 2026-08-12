"""
Proposal Validator - Valida propostas antes de enviar ordens a Deriv API.

Validacoes:
- payout minimo configuravel
- divergencia entre sinal e contrato (CALL/PUT)
- latencia no momento da compra (< 200ms)
- stake dentro dos limites
- ativo habilitado
- ambiente correto (demo/real)
"""
import time
from typing import List, Optional
from pydantic import BaseModel, Field
from enum import Enum


class ValidationErrorCode(str, Enum):
    """Codigos de erro de validacao."""
    PAYOUT_BELOW_MINIMUM = "payout_below_minimum"
    SIGNAL_CONTRACT_MISMATCH = "signal_contract_mismatch"
    HIGH_LATENCY = "high_latency"
    STAKE_ABOVE_LIMIT = "stake_above_limit"
    ASSET_DISABLED = "asset_disabled"
    ENVIRONMENT_MISMATCH = "environment_mismatch"
    INVALID_PROPOSAL = "invalid_proposal"
    PROPOSAL_EXPIRED = "proposal_expired"


class ProposalValidationResult(BaseModel):
    """Resultado da validacao de proposta."""
    is_valid: bool = Field(..., description="Se a proposta e valida")
    errors: List[ValidationErrorCode] = Field(default_factory=list, description="Lista de erros")
    error_messages: List[str] = Field(default_factory=list, description="Mensagens de erro detalhadas")
    warnings: List[str] = Field(default_factory=list, description="Avisos nao bloqueantes")
    
    def add_error(self, code: ValidationErrorCode, message: str):
        """Adiciona um erro de validacao."""
        self.errors.append(code)
        self.error_messages.append(message)
        self.is_valid = False
    
    def add_warning(self, message: str):
        """Adiciona um aviso nao bloqueante."""
        self.warnings.append(message)


class ProposalValidatorConfig(BaseModel):
    """Configuracao do validador de propostas."""
    min_payout_percent: float = Field(default=80.0, ge=0, le=100, description="Payout minimo em porcentagem")
    max_latency_ms: int = Field(default=200, ge=0, description="Latencia maxima em milissegundos")
    max_stake_usd: float = Field(default=100.0, ge=0, description="Stake maxima em USD")
    proposal_expiry_seconds: int = Field(default=30, ge=0, description="Expiracao da proposta em segundos")
    enabled_assets: List[str] = Field(default_factory=list, description="Lista de ativos habilitados")
    environment: str = Field(default="demo", description="Ambiente: demo ou real")


class ProposalValidator:
    """
    Validador de propostas para operacoes na Deriv API.
    
    Uso:
        validator = ProposalValidator(config)
        result = validator.validate(proposal, signal, config)
        if result.is_valid:
            # Prosseguir com a operacao
        else:
            # Bloquear e logar erros
    """
    
    def __init__(self, config: Optional[ProposalValidatorConfig] = None):
        self.config = config or ProposalValidatorConfig()
        self._validation_timestamp: Optional[float] = None
    
    def validate(
        self,
        proposal: dict,
        signal: dict,
        runtime_config: Optional[dict] = None
    ) -> ProposalValidationResult:
        """
        Valida uma proposta antes de enviar ordem.
        
        Args:
            proposal: Dados da proposta da Deriv API
            signal: Sinal gerado pelo Strategy Engine
            runtime_config: Configuracao runtime (pode sobrescrever alguns valores)
        
        Returns:
            ProposalValidationResult com status da validacao
        """
        self._validation_timestamp = time.time()
        result = ProposalValidationResult(is_valid=True)
        
        # Aplicar configuracao runtime se fornecida
        config = self._merge_config(runtime_config)
        
        # Executar todas as validacoes
        self._validate_proposal_structure(proposal, result)
        if not result.is_valid:
            return result
            
        self._validate_payout(proposal, config, result)
        self._validate_signal_contract_match(proposal, signal, result)
        self._validate_latency(proposal, config, result)
        self._validate_stake(proposal, config, result)
        self._validate_asset(proposal, config, result)
        self._validate_environment(proposal, config, result)
        self._validate_proposal_expiry(proposal, config, result)
        
        return result
    
    def _merge_config(self, runtime_config: Optional[dict]) -> ProposalValidatorConfig:
        """Funde configuracao padrao com runtime config."""
        if not runtime_config:
            return self.config
        
        return ProposalValidatorConfig(
            min_payout_percent=runtime_config.get("min_payout_percent", self.config.min_payout_percent),
            max_latency_ms=runtime_config.get("max_latency_ms", self.config.max_latency_ms),
            max_stake_usd=runtime_config.get("max_stake_usd", self.config.max_stake_usd),
            proposal_expiry_seconds=runtime_config.get("proposal_expiry_seconds", self.config.proposal_expiry_seconds),
            enabled_assets=runtime_config.get("enabled_assets", self.config.enabled_assets),
            environment=runtime_config.get("environment", self.config.environment),
        )
    
    def _validate_proposal_structure(self, proposal: dict, result: ProposalValidationResult):
        """Valida estrutura basica da proposta."""
        required_fields = ["proposal_id", "contract_type", "currency", "payout"]
        
        for field in required_fields:
            if field not in proposal:
                result.add_error(
                    ValidationErrorCode.INVALID_PROPOSAL,
                    f"Campo obrigatorio ausente: {field}"
                )
    
    def _validate_payout(self, proposal: dict, config: ProposalValidatorConfig, result: ProposalValidationResult):
        """Valida se o payout esta acima do minimo configurado."""
        payout = proposal.get("payout", 0)
        payout_percent = proposal.get("payout_percent", 0)
        
        # Se payout_percent nao estiver disponivel, calcular
        if payout_percent == 0 and payout > 0:
            stake = proposal.get("price", 0)
            if stake > 0:
                payout_percent = ((payout - stake) / stake) * 100
        
        if payout_percent < config.min_payout_percent:
            result.add_error(
                ValidationErrorCode.PAYOUT_BELOW_MINIMUM,
                f"Payout {payout_percent:.1f}% abaixo do minimo {config.min_payout_percent}%"
            )
    
    def _validate_signal_contract_match(self, proposal: dict, signal: dict, result: ProposalValidationResult):
        """Valida se o tipo de contrato corresponde ao sinal."""
        signal_type = signal.get("type", "").upper()
        contract_type = proposal.get("contract_type", "").upper()
        
        # Mapeamento de sinal para tipo de contrato
        signal_to_contract = {
            "CALL": "CALL",
            "PUT": "PUT",
            "RISE": "CALL",
            "FALL": "PUT",
        }
        
        expected_contract = signal_to_contract.get(signal_type)
        
        if expected_contract and contract_type != expected_contract:
            result.add_error(
                ValidationErrorCode.SIGNAL_CONTRACT_MISMATCH,
                f"Sinal {signal_type} nao corresponde ao contrato {contract_type}"
            )
    
    def _validate_latency(self, proposal: dict, config: ProposalValidatorConfig, result: ProposalValidationResult):
        """Valida latencia entre recebimento da proposta e validacao."""
        if self._validation_timestamp is None:
            return
        
        proposal_time = proposal.get("current_spot_time", proposal.get("timestamp", 0))
        if proposal_time > 0:
            latency_ms = (self._validation_timestamp - proposal_time) * 1000
            
            if latency_ms > config.max_latency_ms:
                result.add_error(
                    ValidationErrorCode.HIGH_LATENCY,
                    f"Latencia {latency_ms:.0f}ms excede limite de {config.max_latency_ms}ms"
                )
            elif latency_ms > config.max_latency_ms * 0.8:
                result.add_warning(f"Latencia {latency_ms:.0f}ms proxima do limite")
    
    def _validate_stake(self, proposal: dict, config: ProposalValidatorConfig, result: ProposalValidationResult):
        """Valida se a stake esta dentro dos limites."""
        stake = proposal.get("price", proposal.get("stake", 0))
        
        if stake > config.max_stake_usd:
            result.add_error(
                ValidationErrorCode.STAKE_ABOVE_LIMIT,
                f"Stake {stake:.2f} USD excede limite de {config.max_stake_usd} USD"
            )
    
    def _validate_asset(self, proposal: dict, config: ProposalValidatorConfig, result: ProposalValidationResult):
        """Valida se o ativo esta habilitado."""
        if not config.enabled_assets:
            return  # Lista vazia significa todos habilitados
        
        symbol = proposal.get("symbol", proposal.get("underlying", ""))
        
        if symbol and symbol not in config.enabled_assets:
            result.add_error(
                ValidationErrorCode.ASSET_DISABLED,
                f"Ativo {symbol} nao esta habilitado para operacao"
            )
    
    def _validate_environment(self, proposal: dict, config: ProposalValidatorConfig, result: ProposalValidationResult):
        """Valida se o ambiente corresponde ao configurado."""
        proposal_env = proposal.get("environment", "demo")
        
        if proposal_env != config.environment:
            result.add_error(
                ValidationErrorCode.ENVIRONMENT_MISMATCH,
                f"Ambiente da proposta ({proposal_env}) difere do configurado ({config.environment})"
            )
    
    def _validate_proposal_expiry(self, proposal: dict, config: ProposalValidatorConfig, result: ProposalValidationResult):
        """Valida se a proposta nao expirou."""
        if self._validation_timestamp is None:
            return
        
        proposal_time = proposal.get("current_spot_time", proposal.get("timestamp", 0))
        if proposal_time > 0:
            age_seconds = self._validation_timestamp - proposal_time
            
            if age_seconds > config.proposal_expiry_seconds:
                result.add_error(
                    ValidationErrorCode.PROPOSAL_EXPIRED,
                    f"Proposta expirada: {age_seconds:.1f}s > {config.proposal_expiry_seconds}s"
                )
