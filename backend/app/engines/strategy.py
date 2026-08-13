"""
Strategy Engine - Motor de estrategias de trading.

Este modulo fornece uma interface unificada para avaliar diferentes estrategias
de trading, incluindo a estrategia principal de reversao por velas consecutivas.

Estrategias disponiveis:
- consecutive_candles: Reversao por velas consecutivas (estrategia padrao)
- rsi: Sobrecompra/Sobrevenda de RSI
- breakout: Rompimento de suporte/resistencia
- ma_crossover: Cruzamento de medias moveis
- bollinger: Bandas de Bollinger
"""
from typing import List, Optional, Dict, Any
from app.models.market import Candle, CandleDirection, Signal, SignalType
from app.engines.indicators import calculate_rsi
from app.engines.strategies import (
    RSIStrategy,
    BreakoutStrategy,
    MACrossoverStrategy,
    BollingerBandsStrategy,
    get_strategy,
)


class StrategyConfig:
    """
    Configuracao generica para estrategias de trading.
    
    Atributos:
        strategy_type: Tipo de estrategia ("consecutive_candles", "rsi", "breakout", etc.)
        consecutive_candles: Numero de velas consecutivas (para consecutive_candles)
        rsi_period: Periodo do RSI
        rsi_overbought: Limite de sobrecompra do RSI
        rsi_oversold: Limite de sobrevenda do RSI
        use_rsi_filter: Se True, usa RSI como filtro confirmatorio
        execution_window_start: Inicio da janela de execucao (segundos no ciclo)
        execution_window_end: Fim da janela de execucao (segundos no ciclo)
        strategy_params: Parametros especificos para outras estrategias
    """
    
    def __init__(
        self,
        strategy_type: str = "consecutive_candles",
        consecutive_candles: int = 9,
        rsi_period: int = 14,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        use_rsi_filter: bool = True,
        execution_window_start: int = 297,
        execution_window_end: int = 299,
        strategy_params: Optional[Dict[str, Any]] = None,
    ):
        self.strategy_type = strategy_type
        self.consecutive_candles = consecutive_candles
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.use_rsi_filter = use_rsi_filter
        self.execution_window_start = execution_window_start
        self.execution_window_end = execution_window_end
        self.strategy_params = strategy_params or {}


class ConsecutiveCandlesStrategy:
    """
    Estrategia de Reversao por Velas Consecutivas.
    
    Gera sinais de reversao apos N velas da mesma cor consecutiva.
    Pode usar RSI como filtro confirmatorio.
    """
    
    def __init__(
        self,
        consecutive_candles: int = 9,
        rsi_period: int = 14,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        use_rsi_filter: bool = True,
    ):
        self.consecutive_candles = consecutive_candles
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.use_rsi_filter = use_rsi_filter
    
    def evaluate(self, candles: List[Candle], seconds_in_cycle: int) -> Signal:
        """
        Avalia se ha um sinal baseado em velas consecutivas.
        
        Args:
            candles: Lista de candles historicos (do mais antigo ao mais recente)
            seconds_in_cycle: Segundos no ciclo atual (para timing de execucao)
        
        Returns:
            Signal com tipo (CALL, PUT, NONE) e razao
        """
        if seconds_in_cycle < 297 or seconds_in_cycle > 299:
            return Signal(type=SignalType.NONE, reason="Out of execution window (297-299s)")
        
        if len(candles) < self.consecutive_candles:
            return Signal(type=SignalType.NONE, reason=f"Not enough candles: {len(candles)} < {self.consecutive_candles}")
        
        recent_n = candles[-self.consecutive_candles:]
        
        all_bullish = all(c.direction == CandleDirection.BULLISH for c in recent_n)
        if all_bullish:
            rsi_val = calculate_rsi(candles, self.rsi_period) if self.use_rsi_filter else 50.0
            
            if self.use_rsi_filter and rsi_val < self.rsi_overbought:
                return Signal(type=SignalType.NONE, reason=f"RSI {rsi_val:.2f} < {self.rsi_overbought} (sem sobrecompra)")
            
            return Signal(type=SignalType.PUT, reason=f"{self.consecutive_candles} bullish candles + RSI {rsi_val:.2f} (sobrecompra). Reversal PUT.")
            
        all_bearish = all(c.direction == CandleDirection.BEARISH for c in recent_n)
        if all_bearish:
            rsi_val = calculate_rsi(candles, self.rsi_period) if self.use_rsi_filter else 50.0
            
            if self.use_rsi_filter and rsi_val > self.rsi_oversold:
                return Signal(type=SignalType.NONE, reason=f"RSI {rsi_val:.2f} > {self.rsi_oversold} (sem sobrevenda)")
            
            return Signal(type=SignalType.CALL, reason=f"{self.consecutive_candles} bearish candles + RSI {rsi_val:.2f} (sobrevenda). Reversal CALL.")
            
        return Signal(type=SignalType.NONE, reason=f"No clear {self.consecutive_candles}-candle sequence")


class StrategyManager:
    """
    Gerenciador de estrategias de trading.
    
    Permite carregar e avaliar diferentes estrategias de forma unificada.
    
    Uso:
        manager = StrategyManager()
        
        # Carregar estrategia de velas consecutivas
        manager.load_strategy("consecutive_candles", consecutive_candles=9)
        
        # Ou carregar estrategia de RSI
        manager.load_strategy("rsi", rsi_period=14)
        
        # Avaliar sinal
        signal = manager.evaluate(candles, seconds_in_cycle)
    """
    
    def __init__(self):
        self._strategy: Optional[object] = None
        self._strategy_type: str = "consecutive_candles"
    
    def load_strategy(self, strategy_type: str, **kwargs) -> None:
        """
        Carrega uma estrategia especifica.
        
        Args:
            strategy_type: Tipo de estrategia ("consecutive_candles", "rsi", "breakout", etc.)
            **kwargs: Parametros especificos da estrategia
        """
        self._strategy_type = strategy_type
        
        if strategy_type == "consecutive_candles":
            self._strategy = ConsecutiveCandlesStrategy(
                consecutive_candles=kwargs.get("consecutive_candles", 9),
                rsi_period=kwargs.get("rsi_period", 14),
                rsi_overbought=kwargs.get("rsi_overbought", 70.0),
                rsi_oversold=kwargs.get("rsi_oversold", 30.0),
                use_rsi_filter=kwargs.get("use_rsi_filter", True),
            )
        else:
            # Usar factory para outras estrategias
            self._strategy = get_strategy(strategy_type, **kwargs)
    
    def evaluate(self, candles: List[Candle], seconds_in_cycle: int) -> Signal:
        """
        Avalia se ha um sinal usando a estrategia carregada.
        
        Args:
            candles: Lista de candles historicos
            seconds_in_cycle: Segundos no ciclo atual
        
        Returns:
            Signal com tipo (CALL, PUT, NONE) e razao
        """
        if self._strategy is None:
            # Carregar estrategia padrao se nenhuma estiver carregada
            self.load_strategy("consecutive_candles")
        
        # Chamar metodo evaluate da estrategia
        result = self._strategy.evaluate(candles, seconds_in_cycle)
        
        # Converter StrategySignal para Signal (se necessario)
        if hasattr(result, 'signal_type'):
            # E um StrategySignal
            return Signal(
                type=result.signal_type,
                reason=result.reason,
            )
        else:
            # Ja e um Signal
            return result
    
    def evaluate_with_config(self, candles: List[Candle], seconds_in_cycle: int, config: StrategyConfig) -> Signal:
        """
        Avalia sinal usando uma configuracao especifica.
        
        Args:
            candles: Lista de candles historicos
            seconds_in_cycle: Segundos no ciclo atual
            config: Objeto StrategyConfig
        
        Returns:
            Signal com tipo (CALL, PUT, NONE) e razao
        """
        # Carregar estrategia da config
        self.load_strategy(
            config.strategy_type,
            consecutive_candles=config.consecutive_candles,
            rsi_period=config.rsi_period,
            rsi_overbought=config.rsi_overbought,
            rsi_oversold=config.rsi_oversold,
            use_rsi_filter=config.use_rsi_filter,
            **config.strategy_params,
        )
        
        return self.evaluate(candles, seconds_in_cycle)


# Funcoes de compatibilidade com codigo existente
def evaluate_strategy(
    candles: List[Candle],
    seconds_in_cycle: int,
    consecutive_candles: int = 9,
    rsi_period: int = 14,
    rsi_overbought: float = 70.0,
    rsi_oversold: float = 30.0,
    use_rsi_filter: bool = True,
) -> Signal:
    """
    Funcao de compatibilidade para avaliacao rapida da estrategia de velas consecutivas.
    
    Args:
        candles: Lista de candles historicos
        seconds_in_cycle: Segundos no ciclo atual
        consecutive_candles: Numero de velas consecutivas
        rsi_period: Periodo do RSI
        rsi_overbought: Limite de sobrecompra
        rsi_oversold: Limite de sobrevenda
        use_rsi_filter: Se True, usa RSI como filtro
    
    Returns:
        Signal com tipo (CALL, PUT, NONE) e razao
    """
    strategy = ConsecutiveCandlesStrategy(
        consecutive_candles=consecutive_candles,
        rsi_period=rsi_period,
        rsi_overbought=rsi_overbought,
        rsi_oversold=rsi_oversold,
        use_rsi_filter=use_rsi_filter,
    )
    return strategy.evaluate(candles, seconds_in_cycle)


def evaluate_strategy_with_config(candles: List[Candle], seconds_in_cycle: int, config: StrategyConfig) -> Signal:
    """
    Funcao de compatibilidade para avaliacao com objeto de configuracao.
    
    Args:
        candles: Lista de candles historicos
        seconds_in_cycle: Segundos no ciclo atual
        config: Objeto StrategyConfig
    
    Returns:
        Signal com tipo (CALL, PUT, NONE) e razao
    """
    manager = StrategyManager()
    return manager.evaluate_with_config(candles, seconds_in_cycle, config)


# Singleton global
_global_manager: Optional[StrategyManager] = None


def get_strategy_manager() -> StrategyManager:
    """Obtem instancia singleton do StrategyManager."""
    global _global_manager
    if _global_manager is None:
        _global_manager = StrategyManager()
    return _global_manager


def reset_strategy_manager():
    """Reseta singleton (para testes)."""
    global _global_manager
    _global_manager = None
