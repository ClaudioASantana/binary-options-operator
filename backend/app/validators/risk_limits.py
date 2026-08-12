"""
Risk Limits - Limites absolutos de risco que nao podem ser sobrescritos.

Implementa os guardrails de seguranca para Martingale e exposicao.
"""
from pydantic import BaseModel, Field
from typing import Optional


class AbsoluteLimits(BaseModel):
    """
    Limites absolutos de risco - NUNCA podem ser excedidos.
    
    Estes limites sao hard-coded e nao devem ser modificados por configuracao.
    Qualquer tentativa de operacao que exceda estes limites deve ser bloqueada.
    """
    # Martingale
    MAX_GALE_ABSOLUTE: int = Field(default=3, description="Numero maximo absoluto de gale")
    
    # Stake por operacao
    MAX_STAKE_ABSOLUTE_USD: float = Field(default=100.0, description="Stake maxima por operacao em USD")
    
    # Exposicao total (soma de todas as stakes em aberto)
    MAX_EXPOSURE_ABSOLUTE_USD: float = Field(default=500.0, description="Exposicao maxima total em USD")
    
    # Loss diario absoluto
    MAX_DAILY_LOSS_ABSOLUTE_USD: float = Field(default=50.0, description="Loss diario maximo absoluto em USD")
    
    # Gain diario absoluto (para proteger ganhos)
    MAX_DAILY_GAIN_ABSOLUTE_USD: float = Field(default=30.0, description="Gain diario maximo absoluto em USD")
    
    # Loss consecutivo
    MAX_CONSECUTIVE_LOSSES_ABSOLUTE: int = Field(default=5, description="Numero maximo de losses consecutivos")
    
    # Operacoes por dia
    MAX_TRADES_PER_DAY: int = Field(default=50, description="Numero maximo de operacoes por dia")
    
    def validate_gale_level(self, gale_level: int) -> tuple[bool, str]:
        """
        Valida nivel de gale.
        
        Returns:
            tuple[bool, str]: (is_valid, error_message)
        """
        if gale_level > self.MAX_GALE_ABSOLUTE:
            return False, f"Gale level {gale_level} excede limite absoluto de {self.MAX_GALE_ABSOLUTE}"
        return True, ""
    
    def validate_stake(self, stake: float) -> tuple[bool, str]:
        """
        Valida stake da operacao.
        
        Returns:
            tuple[bool, str]: (is_valid, error_message)
        """
        if stake > self.MAX_STAKE_ABSOLUTE_USD:
            return False, f"Stake {stake:.2f} USD excede limite absoluto de {self.MAX_STAKE_ABSOLUTE_USD} USD"
        return True, ""
    
    def validate_exposure(self, current_exposure: float, new_stake: float) -> tuple[bool, str]:
        """
        Valida exposicao total.
        
        Returns:
            tuple[bool, str]: (is_valid, error_message)
        """
        total_exposure = current_exposure + new_stake
        if total_exposure > self.MAX_EXPOSURE_ABSOLUTE_USD:
            return False, f"Exposicao total {total_exposure:.2f} USD excede limite de {self.MAX_EXPOSURE_ABSOLUTE_USD} USD"
        return True, ""
    
    def validate_daily_pnl(self, daily_pnl: float) -> tuple[bool, str]:
        """
        Valida PnL diario.
        
        Returns:
            tuple[bool, str]: (is_valid, error_message)
        """
        if daily_pnl <= -self.MAX_DAILY_LOSS_ABSOLUTE_USD:
            return False, f"Loss diario {daily_pnl:.2f} USD atingiu limite absoluto de {-self.MAX_DAILY_LOSS_ABSOLUTE_USD} USD"
        
        if daily_pnl >= self.MAX_DAILY_GAIN_ABSOLUTE_USD:
            return False, f"Gain diario {daily_pnl:.2f} USD atingiu limite absoluto de {self.MAX_DAILY_GAIN_ABSOLUTE_USD} USD"
        
        return True, ""
    
    def calculate_martingale_sequence(self, initial_stake: float, gale_level: int) -> list[float]:
        """
        Calcula sequencia de Martingale respeitando limites absolutos.
        
        Args:
            initial_stake: Stake inicial
            gale_level: Numero de niveles de gale
        
        Returns:
            list[float]: Sequencia de stakes validadas
        """
        sequence = [initial_stake]
        
        for i in range(1, min(gale_level, self.MAX_GALE_ABSOLUTE) + 1):
            next_stake = initial_stake * (2 ** i)
            
            # Aplicar limite absoluto de stake
            if next_stake > self.MAX_STAKE_ABSOLUTE_USD:
                next_stake = self.MAX_STAKE_ABSOLUTE_USD
            
            sequence.append(next_stake)
        
        return sequence
    
    def get_safe_gale_level(
        self,
        initial_stake: float,
        current_gale: int,
        config_gale: int
    ) -> int:
        """
        Determina nivel de gale seguro respeitando todos os limites.
        
        Args:
            initial_stake: Stake inicial
            current_gale: Nivel atual de gale
            config_gale: Gale configurado pelo usuario
        
        Returns:
            int: Nivel de gale seguro
        """
        # Nunca exceder limite absoluto
        max_allowed = min(config_gale, self.MAX_GALE_ABSOLUTE)
        
        # Verificar se stakes futuras estao dentro do limite
        for level in range(current_gale + 1, max_allowed + 1):
            future_stake = initial_stake * (2 ** level)
            if future_stake > self.MAX_STAKE_ABSOLUTE_USD:
                return level - 1
        
        return max_allowed


class RiskLimits:
    """
    Validador de limites de risco com limites absolutos e configuraveis.
    
    Uso:
        limits = RiskLimits(config_gale=5, config_stake=50.0)
        
        # Validar gale
        is_valid, error = limits.validate_gale(3)
        
        # Obter gale seguro
        safe_gale = limits.get_safe_gale_level(initial_stake=0.35, current_gale=0)
    """
    
    def __init__(
        self,
        max_gale_config: int = 5,
        max_stake_config: float = 50.0,
        max_daily_loss_config: float = 20.0,
        max_daily_gain_config: float = 15.0,
        max_consecutive_losses_config: int = 3,
        max_trades_per_day_config: int = 30,
    ):
        self.absolute = AbsoluteLimits()
        
        # Limites configuraveis (usuario pode ajustar, mas nunca excede absolutos)
        self.max_gale_config = min(max_gale_config, self.absolute.MAX_GALE_ABSOLUTE)
        self.max_stake_config = min(max_stake_config, self.absolute.MAX_STAKE_ABSOLUTE_USD)
        self.max_daily_loss_config = min(max_daily_loss_config, self.absolute.MAX_DAILY_LOSS_ABSOLUTE_USD)
        self.max_daily_gain_config = min(max_daily_gain_config, self.absolute.MAX_DAILY_GAIN_ABSOLUTE_USD)
        self.max_consecutive_losses_config = min(
            max_consecutive_losses_config,
            self.absolute.MAX_CONSECUTIVE_LOSSES_ABSOLUTE
        )
        self.max_trades_per_day_config = min(
            max_trades_per_day_config,
            self.absolute.MAX_TRADES_PER_DAY
        )
    
    def validate_gale(self, gale_level: int) -> tuple[bool, str]:
        """Valida nivel de gale contra limites configuraveis e absolutos."""
        # Primeiro valida contra limite absoluto
        is_valid, error = self.absolute.validate_gale_level(gale_level)
        if not is_valid:
            return is_valid, error
        
        # Depois valida contra limite configuravel
        if gale_level > self.max_gale_config:
            return False, f"Gale level {gale_level} excede limite configurado de {self.max_gale_config}"
        
        return True, ""
    
    def validate_stake(self, stake: float) -> tuple[bool, str]:
        """Valida stake contra limites configuraveis e absolutos."""
        # Primeiro valida contra limite absoluto
        is_valid, error = self.absolute.validate_stake(stake)
        if not is_valid:
            return is_valid, error
        
        # Depois valida contra limite configuravel
        if stake > self.max_stake_config:
            return False, f"Stake {stake:.2f} USD excede limite configurado de {self.max_stake_config} USD"
        
        return True, ""
    
    def validate_daily_pnl(self, daily_pnl: float) -> tuple[bool, str]:
        """Valida PnL diario."""
        # Validar contra limites absolutos primeiro
        is_valid, error = self.absolute.validate_daily_pnl(daily_pnl)
        if not is_valid:
            return is_valid, error
        
        # Validar contra limites configuraveis
        if daily_pnl <= -self.max_daily_loss_config:
            return False, f"Loss diario {daily_pnl:.2f} USD atingiu limite configurado de {-self.max_daily_loss_config} USD"
        
        if daily_pnl >= self.max_daily_gain_config:
            return False, f"Gain diario {daily_pnl:.2f} USD atingiu limite configurado de {self.max_daily_gain_config} USD"
        
        return True, ""
    
    def validate_consecutive_losses(self, consecutive_losses: int) -> tuple[bool, str]:
        """Valida losses consecutivos."""
        if consecutive_losses >= self.max_consecutive_losses_config:
            return False, f"Losses consecutivos {consecutive_losses} atingiram limite de {self.max_consecutive_losses_config}"
        return True, ""
    
    def get_effective_limits(self) -> dict:
        """Retorna limites efetivos (o menor entre configurado e absoluto)."""
        return {
            "max_gale": min(self.max_gale_config, self.absolute.MAX_GALE_ABSOLUTE),
            "max_stake_usd": min(self.max_stake_config, self.absolute.MAX_STAKE_ABSOLUTE_USD),
            "max_daily_loss_usd": min(self.max_daily_loss_config, self.absolute.MAX_DAILY_LOSS_ABSOLUTE_USD),
            "max_daily_gain_usd": min(self.max_daily_gain_config, self.absolute.MAX_DAILY_GAIN_ABSOLUTE_USD),
            "max_consecutive_losses": min(
                self.max_consecutive_losses_config,
                self.absolute.MAX_CONSECUTIVE_LOSSES_ABSOLUTE
            ),
            "max_trades_per_day": min(
                self.max_trades_per_day_config,
                self.absolute.MAX_TRADES_PER_DAY
            ),
            # Limites absolutos (hard-coded)
            "absolute_max_gale": self.absolute.MAX_GALE_ABSOLUTE,
            "absolute_max_stake_usd": self.absolute.MAX_STAKE_ABSOLUTE_USD,
            "absolute_max_exposure_usd": self.absolute.MAX_EXPOSURE_ABSOLUTE_USD,
        }
    
    def calculate_safe_stake(
        self,
        initial_stake: float,
        gale_level: int,
        current_exposure: float = 0.0
    ) -> tuple[float, bool, str]:
        """
        Calcula stake segura respeitando todos os limites.
        
        Returns:
            tuple[float, bool, str]: (stake_calculada, is_valid, error_message)
        """
        # Calcular stake do Martingale
        calculated_stake = initial_stake * (2 ** gale_level)
        
        # Validar contra limite absoluto de stake
        if calculated_stake > self.absolute.MAX_STAKE_ABSOLUTE_USD:
            return self.absolute.MAX_STAKE_ABSOLUTE_USD, False, \
                f"Stake reduzida para limite absoluto de {self.absolute.MAX_STAKE_ABSOLUTE_USD} USD"
        
        # Validar contra limite configuravel
        if calculated_stake > self.max_stake_config:
            return self.max_stake_config, False, \
                f"Stake reduzida para limite configurado de {self.max_stake_config} USD"
        
        # Validar exposicao total
        total_exposure = current_exposure + calculated_stake
        if total_exposure > self.absolute.MAX_EXPOSURE_ABSOLUTE_USD:
            max_allowed = self.absolute.MAX_EXPOSURE_ABSOLUTE_USD - current_exposure
            if max_allowed <= 0:
                return 0.0, False, "Exposicao maxima atingida - nenhuma operacao permitida"
            return max_allowed, False, f"Stake reduzida para limite de exposicao"
        
        return calculated_stake, True, ""
