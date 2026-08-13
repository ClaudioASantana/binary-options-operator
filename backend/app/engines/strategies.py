"""
Estrategias Adicionais para Opcoes Binarias.

Este modulo implementa estrategias adicionais alem da estrategia principal de
reversao por velas consecutivas.

Estrategias incluidas:
1. RSI Puro (sobrevenda/sobrecompra)
2. Rompimento de Suporte/Resistencia (Breakout)
3. Cruzamento de Medias Moveis (MA Crossover)
4. Bollinger Bands (reversao a media)
"""
from typing import List, Tuple, Optional
from dataclasses import dataclass
from app.models.market import Candle, CandleDirection, Signal, SignalType
from app.engines.indicators import calculate_rsi


@dataclass
class StrategySignal:
    """Sinal gerado por uma estrategia."""
    signal_type: SignalType
    reason: str
    strength: float = 1.0  # Forca do sinal (0.0 a 1.0)


class RSIStrategy:
    """
    Estrategia de RSI - Sobrecompra e Sobrevenda.
    
    Gera sinais quando o RSI cruza os limites de sobrecompra (70) ou sobrevenda (30).
    
    Sinais:
    - CALL: Quando RSI sai da zona de sobrevenda (< 30) e cruza para cima
    - PUT: Quando RSI sai da zona de sobrecompra (> 70) e cruza para baixo
    """
    
    def __init__(
        self,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        confirmation_candles: int = 1,
    ):
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.confirmation_candles = confirmation_candles
    
    def evaluate(self, candles: List[Candle], seconds_in_cycle: int) -> StrategySignal:
        """
        Avalia se ha um sinal baseado no RSI.
        
        Args:
            candles: Lista de candles historicos (do mais antigo ao mais recente)
            seconds_in_cycle: Segundos no ciclo atual (para timing de execucao)
        
        Returns:
            StrategySignal com o tipo de sinal e justificativa
        """
        if seconds_in_cycle < 297 or seconds_in_cycle > 299:
            return StrategySignal(
                signal_type=SignalType.NONE,
                reason="Out of execution window (297-299s)",
            )
        
        if len(candles) < self.rsi_period + self.confirmation_candles:
            return StrategySignal(
                signal_type=SignalType.NONE,
                reason=f"Not enough candles: {len(candles)} < {self.rsi_period + self.confirmation_candles}",
            )
        
        # Calcular RSI atual e anterior
        current_rsi = calculate_rsi(candles, self.rsi_period)
        previous_rsi = calculate_rsi(candles[:-1], self.rsi_period) if len(candles) > self.rsi_period + 1 else 50.0
        
        # Verificar cruzamento de sobrevenda para cima (CALL)
        if previous_rsi < self.rsi_oversold and current_rsi >= self.rsi_oversold:
            return StrategySignal(
                signal_type=SignalType.CALL,
                reason=f"RSI cruzou para cima da sobrevenda: {previous_rsi:.2f} -> {current_rsi:.2f}",
                strength=min(1.0, (self.rsi_oversold - current_rsi) / 20 + 0.5),
            )
        
        # Verificar cruzamento de sobrecompra para baixo (PUT)
        if previous_rsi > self.rsi_overbought and current_rsi <= self.rsi_overbought:
            return StrategySignal(
                signal_type=SignalType.PUT,
                reason=f"RSI cruzou para baixo da sobrecompra: {previous_rsi:.2f} -> {current_rsi:.2f}",
                strength=min(1.0, (current_rsi - self.rsi_overbought) / 20 + 0.5),
            )
        
        # Verificar se esta em zona extrema (sinal mais fraco)
        if current_rsi < self.rsi_oversold:
            return StrategySignal(
                signal_type=SignalType.CALL,
                reason=f"RSI em sobrevenda extrema: {current_rsi:.2f}",
                strength=0.5,  # Sinal mais fraco sem confirmacao
            )
        
        if current_rsi > self.rsi_overbought:
            return StrategySignal(
                signal_type=SignalType.PUT,
                reason=f"RSI em sobrecompra extrema: {current_rsi:.2f}",
                strength=0.5,  # Sinal mais fraco sem confirmacao
            )
        
        return StrategySignal(
            signal_type=SignalType.NONE,
            reason=f"RSI neutro: {current_rsi:.2f}",
        )


class BreakoutStrategy:
    """
    Estrategia de Rompimento (Breakout).
    
    Identifica suportes e resistencias baseados em maximos e minimos recentes,
    e gera sinais quando o preco rompe esses niveles.
    
    Sinais:
    - CALL: Quando o preco rompe uma resistencia para cima
    - PUT: Quando o preco rompe um suporte para baixo
    """
    
    def __init__(
        self,
        lookback_period: int = 20,
        confirmation_candles: int = 1,
        min_breakout_strength: float = 0.3,
    ):
        self.lookback_period = lookback_period
        self.confirmation_candles = confirmation_candles
        self.min_breakout_strength = min_breakout_strength
    
    def _find_support_resistance(self, candles: List[Candle]) -> Tuple[Optional[float], Optional[float]]:
        """
        Encontra niveles de suporte e resistencia nos ultimos candles.
        
        Returns:
            Tuple[suporte, resistencia] ou (None, None) se nao encontrar
        """
        if len(candles) < self.lookback_period:
            return None, None
        
        recent = candles[-self.lookback_period:]
        
        # Suporte: minimo dos ultimos N candles (excluindo o ultimo)
        support = min(c.low for c in recent[:-1]) if len(recent) > 1 else None
        
        # Resistencia: maximo dos ultimos N candles (excluindo o ultimo)
        resistance = max(c.high for c in recent[:-1]) if len(recent) > 1 else None
        
        return support, resistance
    
    def evaluate(self, candles: List[Candle], seconds_in_cycle: int) -> StrategySignal:
        """
        Avalia se ha um sinal baseado em rompimento.
        
        Args:
            candles: Lista de candles historicos
            seconds_in_cycle: Segundos no ciclo atual
        
        Returns:
            StrategySignal com o tipo de sinal e justificativa
        """
        if seconds_in_cycle < 297 or seconds_in_cycle > 299:
            return StrategySignal(
                signal_type=SignalType.NONE,
                reason="Out of execution window (297-299s)",
            )
        
        if len(candles) < self.lookback_period + 1:
            return StrategySignal(
                signal_type=SignalType.NONE,
                reason=f"Not enough candles: {len(candles)} < {self.lookback_period + 1}",
            )
        
        support, resistance = self._find_support_resistance(candles)
        
        if support is None or resistance is None:
            return StrategySignal(
                signal_type=SignalType.NONE,
                reason="Unable to determine support/resistance levels",
            )
        
        current_candle = candles[-1]
        
        # Calcular forca do rompimento
        breakout_strength = 0.0
        
        # Rompimento de resistencia para cima (CALL)
        if current_candle.close > resistance:
            breakout_strength = (current_candle.close - resistance) / (resistance * 0.01)  # % acima da resistencia
            
            if breakout_strength >= self.min_breakout_strength:
                return StrategySignal(
                    signal_type=SignalType.CALL,
                    reason=f"Rompimento de resistencia em {resistance:.5f} (forca: {breakout_strength:.2f})",
                    strength=min(1.0, breakout_strength),
                )
        
        # Rompimento de suporte para baixo (PUT)
        if current_candle.close < support:
            breakout_strength = (support - current_candle.close) / (support * 0.01)  # % abaixo do suporte
            
            if breakout_strength >= self.min_breakout_strength:
                return StrategySignal(
                    signal_type=SignalType.PUT,
                    reason=f"Rompimento de suporte em {support:.5f} (forca: {breakout_strength:.2f})",
                    strength=min(1.0, breakout_strength),
                )
        
        return StrategySignal(
            signal_type=SignalType.NONE,
            reason=f"Sem rompimento. Suporte: {support:.5f}, Resistencia: {resistance:.5f}",
        )


class MACrossoverStrategy:
    """
    Estrategia de Cruzamento de Medias Moveis (MA Crossover).
    
    Usa duas medias moveis (rapida e lenta) e gera sinais quando elas se cruzam.
    
    Sinais:
    - CALL: Quando a media rapida cruza para cima da lenta (golden cross)
    - PUT: Quando a media rapida cruza para baixo da lenta (death cross)
    """
    
    def __init__(
        self,
        fast_period: int = 9,
        slow_period: int = 21,
        ma_type: str = "EMA",  # "SMA" ou "EMA"
    ):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.ma_type = ma_type
    
    def _calculate_ma(self, candles: List[Candle], period: int) -> float:
        """Calcula media movel (SMA ou EMA) dos candles."""
        if len(candles) < period:
            return 0.0
        
        closes = [c.close for c in candles[-period:]]
        
        if self.ma_type == "SMA":
            return sum(closes) / period
        
        # EMA (Exponential Moving Average)
        multiplier = 2 / (period + 1)
        ema = sum(closes[:period]) / period  # Comeca com SMA
        
        for close in closes[period:]:
            ema = (close * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def evaluate(self, candles: List[Candle], seconds_in_cycle: int) -> StrategySignal:
        """
        Avalia se ha um sinal baseado em cruzamento de medias.
        
        Args:
            candles: Lista de candles historicos
            seconds_in_cycle: Segundos no ciclo atual
        
        Returns:
            StrategySignal com o tipo de sinal e justificativa
        """
        if seconds_in_cycle < 297 or seconds_in_cycle > 299:
            return StrategySignal(
                signal_type=SignalType.NONE,
                reason="Out of execution window (297-299s)",
            )
        
        if len(candles) < self.slow_period + 1:
            return StrategySignal(
                signal_type=SignalType.NONE,
                reason=f"Not enough candles: {len(candles)} < {self.slow_period + 1}",
            )
        
        # Calcular medias atuais e anteriores
        fast_ma_current = self._calculate_ma(candles, self.fast_period)
        slow_ma_current = self._calculate_ma(candles, self.slow_period)
        
        fast_ma_previous = self._calculate_ma(candles[:-1], self.fast_period)
        slow_ma_previous = self._calculate_ma(candles[:-1], self.slow_period)
        
        # Golden Cross (rapida cruza para cima da lenta) -> CALL
        if fast_ma_previous <= slow_ma_previous and fast_ma_current > slow_ma_current:
            return StrategySignal(
                signal_type=SignalType.CALL,
                reason=f"Golden Cross: MA{self.fast_period} ({fast_ma_current:.5f}) cruzou MA{self.slow_period} ({slow_ma_current:.5f})",
                strength=min(1.0, (fast_ma_current - slow_ma_current) / (slow_ma_current * 0.01) + 0.5),
            )
        
        # Death Cross (rapida cruza para baixo da lenta) -> PUT
        if fast_ma_previous >= slow_ma_previous and fast_ma_current < slow_ma_current:
            return StrategySignal(
                signal_type=SignalType.PUT,
                reason=f"Death Cross: MA{self.fast_period} ({fast_ma_current:.5f}) cruzou MA{self.slow_period} ({slow_ma_current:.5f})",
                strength=min(1.0, (slow_ma_current - fast_ma_current) / (slow_ma_current * 0.01) + 0.5),
            )
        
        # Verificar se medias estao alinhadas (tendencia estabelecida)
        if fast_ma_current > slow_ma_current:
            return StrategySignal(
                signal_type=SignalType.NONE,
                reason=f"Tendencia de alta: MA{self.fast_period} ({fast_ma_current:.5f}) > MA{self.slow_period} ({slow_ma_current:.5f})",
            )
        else:
            return StrategySignal(
                signal_type=SignalType.NONE,
                reason=f"Tendencia de baixa: MA{self.fast_period} ({fast_ma_current:.5f}) < MA{self.slow_period} ({slow_ma_current:.5f})",
            )


class BollingerBandsStrategy:
    """
    Estrategia de Bandas de Bollinger.
    
    Usa bandas de Bollinger para identificar quando o preco esta desviado
    da media e pode retornar (reversao a media).
    
    Sinais:
    - CALL: Quando o preco toca/ultrapassa a banda inferior e volta para dentro
    - PUT: Quando o preco toca/ultrapassa a banda superior e volta para dentro
    """
    
    def __init__(
        self,
        period: int = 20,
        std_dev: float = 2.0,
        confirmation_candles: int = 1,
    ):
        self.period = period
        self.std_dev = std_dev
        self.confirmation_candles = confirmation_candles
    
    def _calculate_bollinger_bands(self, candles: List[Candle]) -> Tuple[float, float, float]:
        """
        Calcula Bandas de Bollinger.
        
        Returns:
            Tuple[upper_band, middle_band (SMA), lower_band]
        """
        if len(candles) < self.period:
            return 0.0, 0.0, 0.0
        
        closes = [c.close for c in candles[-self.period:]]
        
        # Banda do meio (SMA)
        middle = sum(closes) / self.period
        
        # Desvio padrao
        variance = sum((close - middle) ** 2 for close in closes) / self.period
        std = variance ** 0.5
        
        # Bandas superior e inferior
        upper = middle + (self.std_dev * std)
        lower = middle - (self.std_dev * std)
        
        return upper, middle, lower
    
    def evaluate(self, candles: List[Candle], seconds_in_cycle: int) -> StrategySignal:
        """
        Avalia se ha um sinal baseado nas Bandas de Bollinger.
        
        Args:
            candles: Lista de candles historicos
            seconds_in_cycle: Segundos no ciclo atual
        
        Returns:
            StrategySignal com o tipo de sinal e justificativa
        """
        if seconds_in_cycle < 297 or seconds_in_cycle > 299:
            return StrategySignal(
                signal_type=SignalType.NONE,
                reason="Out of execution window (297-299s)",
            )
        
        if len(candles) < self.period + self.confirmation_candles:
            return StrategySignal(
                signal_type=SignalType.NONE,
                reason=f"Not enough candles: {len(candles)} < {self.period + self.confirmation_candles}",
            )
        
        upper, middle, lower = self._calculate_bollinger_bands(candles)
        
        if upper == 0.0 or lower == 0.0:
            return StrategySignal(
                signal_type=SignalType.NONE,
                reason="Unable to calculate Bollinger Bands",
            )
        
        current_candle = candles[-1]
        current_price = current_candle.close
        
        # Calcular posicao relativa do preco (% entre as bandas)
        price_position = (current_price - lower) / (upper - lower)
        
        # Preco tocou banda inferior e fechou acima (CALL - reversao para cima)
        if current_candle.low <= lower and current_price > lower:
            # Confirmar com candle anterior tambem tendo tocado a banda
            if self.confirmation_candles > 1 and len(candles) > 1:
                prev_candle = candles[-2]
                if prev_candle.low <= lower:
                    return StrategySignal(
                        signal_type=SignalType.CALL,
                        reason=f"Preco tocou banda inferior ({lower:.5f}) e reverteu. Posicao: {price_position:.2%}",
                        strength=min(1.0, 1.0 - price_position),
                    )
            else:
                return StrategySignal(
                    signal_type=SignalType.CALL,
                    reason=f"Preco tocou banda inferior ({lower:.5f}) e reverteu. Posicao: {price_position:.2%}",
                    strength=min(1.0, 1.0 - price_position),
                )
        
        # Preco tocou banda superior e fechou abaixo (PUT - reversao para baixo)
        if current_candle.high >= upper and current_price < upper:
            # Confirmar com candle anterior tambem tendo tocado a banda
            if self.confirmation_candles > 1 and len(candles) > 1:
                prev_candle = candles[-2]
                if prev_candle.high >= upper:
                    return StrategySignal(
                        signal_type=SignalType.PUT,
                        reason=f"Preco tocou banda superior ({upper:.5f}) e reverteu. Posicao: {price_position:.2%}",
                        strength=min(1.0, price_position),
                    )
            else:
                return StrategySignal(
                    signal_type=SignalType.PUT,
                    reason=f"Preco tocou banda superior ({upper:.5f}) e reverteu. Posicao: {price_position:.2%}",
                    strength=min(1.0, price_position),
                )
        
        return StrategySignal(
            signal_type=SignalType.NONE,
            reason=f"Preco dentro das bandas. Upper: {upper:.5f}, Middle: {middle:.5f}, Lower: {lower:.5f}",
        )


# Factory para criar estrategias
def get_strategy(strategy_name: str, **kwargs) -> object:
    """
    Factory para criar instancias de estrategias.
    
    Args:
        strategy_name: Nome da estrategia ("rsi", "breakout", "ma_crossover", "bollinger")
        **kwargs: Parametros especificos da estrategia
    
    Returns:
        Instancia da estrategia
    """
    strategies = {
        "rsi": RSIStrategy,
        "breakout": BreakoutStrategy,
        "ma_crossover": MACrossoverStrategy,
        "bollinger": BollingerBandsStrategy,
    }
    
    if strategy_name not in strategies:
        raise ValueError(f"Estrategia '{strategy_name}' nao encontrada. Disponiveis: {list(strategies.keys())}")
    
    return strategies[strategy_name](**kwargs)
