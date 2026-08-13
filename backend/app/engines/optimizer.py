"""
Strategy Optimizer - Otimizador de parametros para estrategias de trading.

Realiza busca em grade (grid search) para encontrar os melhores parametros
de uma estrategia com base em dados historicos.

Metricas de otimizacao:
- Win Rate (padrao)
- Profit Factor
- Sharpe Ratio
- Max Drawdown (minimizar)
- Composite Score (combina multiplas metricas)
"""
import logging
import json
import csv
import math
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
from app.models.market import Candle
from app.engines.backtester import Backtester, BacktesterConfig, BacktestResult, BacktestTrade
from app.engines.strategy import StrategyConfig

logger = logging.getLogger(__name__)


@dataclass
class OptimizationResult:
    """Resultado de uma unica execucao de otimizacao."""
    params: Dict[str, Any]
    win_rate: float
    total_pnl: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_percent: float
    total_trades: int
    final_balance: float
    sharpe_ratio: float = 0.0
    composite_score: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    expectancy: float = 0.0


@dataclass
class OptimizationSummary:
    """Resumo consolidado da otimizacao."""
    best_result: Optional[OptimizationResult]
    all_results: List[OptimizationResult]
    total_combinations: int
    valid_combinations: int
    optimization_metric: str
    

class StrategyOptimizer:
    """
    Otimizador de parametros para estrategias de trading.
    
    Uso:
        optimizer = StrategyOptimizer(history_candles)
        
        param_grid = {
            "consecutive_candles": [7, 8, 9, 10],
            "rsi_period": [12, 14, 16],
            "rsi_oversold": [25, 30, 35],
            "rsi_overbought": [65, 70, 75],
        }
        
        summary = optimizer.optimize(
            param_grid=param_grid,
            optimization_metric="win_rate",
            initial_balance=1000.0,
        )
        
        print(f"Melhor win rate: {summary.best_result.win_rate:.2f}%")
        print(f"Melhores params: {summary.best_result.params}")
    """
    
    def __init__(
        self,
        history: List[Candle],
        backtester_config: Optional[BacktesterConfig] = None,
        risk_free_rate: float = 0.0,
    ):
        self.history = history
        self.backtester_config = backtester_config or BacktesterConfig()
        self.backtester = Backtester(config=self.backtester_config)
        self.risk_free_rate = risk_free_rate
    
    def optimize(
        self,
        param_grid: Dict[str, List[Any]],
        optimization_metric: str = "win_rate",
        min_trades: int = 10,
        use_rsi_filter: bool = True,
    ) -> OptimizationSummary:
        """
        Executa grid search nos parametros especificados.
        
        Args:
            param_grid: Dicionario com listas de valores para cada parametro
            optimization_metric: Metrica para otimizar ("win_rate", "profit_factor", "sharpe", "pnl", "drawdown")
            min_trades: Numero minimo de trades para considerar um resultado valido
            use_rsi_filter: Se True, usa filtro RSI na estrategia
        
        Returns:
            OptimizationSummary com melhor resultado e todos os resultados
        """
        from itertools import product
        
        # Parametros que podem ser otimizados
        optimizable_params = [
            "consecutive_candles",
            "rsi_period",
            "rsi_oversold",
            "rsi_overbought",
        ]
        
        # Extrair valores do param_grid
        param_values = {}
        for param in optimizable_params:
            if param in param_grid:
                param_values[param] = param_grid[param]
            else:
                # Usar valor default se nao especificado
                defaults = {
                    "consecutive_candles": [9],
                    "rsi_period": [14],
                    "rsi_oversold": [30],
                    "rsi_overbought": [70],
                }
                param_values[param] = defaults[param]
        
        # Gerar todas as combinacoes
        all_combinations = list(product(
            param_values["consecutive_candles"],
            param_values["rsi_period"],
            param_values["rsi_oversold"],
            param_values["rsi_overbought"],
        ))
        
        logger.info(f"Iniciando otimizacao: {len(all_combinations)} combinacoes")
        
        all_results: List[OptimizationResult] = []
        valid_count = 0
        
        for i, (consecutive, rsi_period, rsi_oversold, rsi_overbought) in enumerate(all_combinations, 1):
            if i % 10 == 0:
                logger.info(f"Progresso: {i}/{len(all_combinations)}")
            
            # Executar backtest com esta combinacao
            strategy_params = {
                "consecutive_candles": consecutive,
                "rsi_period": rsi_period,
                "rsi_oversold": rsi_oversold,
                "rsi_overbought": rsi_overbought,
                "use_rsi_filter": use_rsi_filter,
                "timeframe": 300,  # M5
            }
            
            try:
                result = self.backtester.run(
                    history=self.history,
                    strategy_params=strategy_params,
                )
                
                # Calcular Sharpe Ratio
                sharpe_ratio = self._calculate_sharpe_ratio(result.trades, self.risk_free_rate, self.backtester_config.initial_balance)
                
                # Calcular Expectancy
                sum_wins = result.avg_win * result.wins if result.wins > 0 else 0
                sum_losses = result.avg_loss * result.losses if result.losses > 0 else 0
                expectancy = self._calculate_expectancy(result.wins, result.losses, sum_wins, sum_losses)
                
                # Criar OptimizationResult
                opt_result = OptimizationResult(
                    params=strategy_params,
                    win_rate=result.win_rate,
                    total_pnl=result.total_pnl,
                    profit_factor=result.profit_factor,
                    max_drawdown=result.max_drawdown,
                    max_drawdown_percent=result.max_drawdown_percent,
                    total_trades=result.total_trades,
                    final_balance=result.final_balance,
                    sharpe_ratio=sharpe_ratio,
                    avg_win=result.avg_win,
                    avg_loss=result.avg_loss,
                    largest_win=result.largest_win,
                    largest_loss=result.largest_loss,
                    consecutive_wins=result.max_consecutive_wins,
                    consecutive_losses=result.max_consecutive_losses,
                    expectancy=expectancy,
                )
                
                # Calcular Composite Score (50% Win Rate + 30% Profit Factor + 20% Sharpe Ratio)
                pf_normalized = min(result.profit_factor, 2.0) / 2.0 if result.profit_factor != float('inf') else 1.0
                sr_normalized = min(sharpe_ratio, 5.0) / 5.0 if sharpe_ratio > 0 else 0
                
                opt_result.composite_score = (
                    0.50 * (result.win_rate / 100) +
                    0.30 * pf_normalized +
                    0.20 * sr_normalized
                )
                
                # Filtrar por numero minimo de trades
                if result.total_trades >= min_trades:
                    valid_count += 1
                
                all_results.append(opt_result)
                
            except Exception as e:
                logger.warning(f"Erro na combinacao {strategy_params}: {e}")
                continue
        
        # Encontrar o melhor resultado baseado na metrica
        best_result = self._find_best(all_results, optimization_metric, min_trades)
        
        logger.info(
            f"Otimizacao concluida: {valid_count}/{len(all_results)} combinacoes validas. "
            f"Melhor {optimization_metric}: {getattr(best_result, optimization_metric, 0) if best_result else 'N/A'}"
        )
        
        return OptimizationSummary(
            best_result=best_result,
            all_results=all_results,
            total_combinations=len(all_combinations),
            valid_combinations=valid_count,
            optimization_metric=optimization_metric,
        )
    
    def _calculate_sharpe_ratio(self, trades: List[BacktestTrade], risk_free_rate: float, initial_balance: float) -> float:
        """
        Calcula o Sharpe Ratio baseado nos retornos dos trades.
        
        Sharpe Ratio = (Retorno Medio - Risk Free Rate) / Desvio Padrao dos Retornos
        """
        if not trades or len(trades) < 2:
            return 0.0
        
        # Calcular retornos percentuais de cada trade
        returns = []
        for trade in trades:
            if trade.stake > 0:
                return_pct = trade.pnl / trade.stake
                returns.append(return_pct)
        
        if len(returns) < 2:
            return 0.0
        
        # Calcular media e desvio padrao
        avg_return = sum(returns) / len(returns)
        variance = sum([(r - avg_return) ** 2 for r in returns]) / (len(returns) - 1)
        std_dev = math.sqrt(variance) if variance > 0 else 0.0
        
        if std_dev == 0:
            return 0.0
        
        # Sharpe Ratio (assumindo risk_free_rate anualizado, ajustar se necessario)
        sharpe = (avg_return - (risk_free_rate / 252)) / std_dev
        
        # Anualizar (opcional, dependendo da frequencia dos trades)
        # sharpe *= math.sqrt(252)  # Se forem retornos diarios
        
        return sharpe
    
    def _calculate_expectancy(self, wins: int, losses: int, sum_wins: float, sum_losses: float) -> float:
        """
        Calcula a expectativa de trading (expectancy).
        
        Expectancy = (Probabilidade Win * Valor Medio Win) - (Probabilidade Loss * Valor Medio Loss)
        """
        total_trades = wins + losses
        if total_trades == 0:
            return 0.0
        
        prob_win = wins / total_trades
        prob_loss = losses / total_trades
        
        avg_win_amount = (sum_wins / wins) if wins > 0 else 0.0
        avg_loss_amount = (sum_losses / losses) if losses > 0 else 0.0
        
        expectancy = (prob_win * avg_win_amount) - (prob_loss * avg_loss_amount)
        return expectancy
    
    def _find_best(
        self,
        results: List[OptimizationResult],
        metric: str,
        min_trades: int,
    ) -> Optional[OptimizationResult]:
        """Encontra o melhor resultado baseado na metrica especificada."""
        # Filtrar resultados validos (min_trades)
        valid_results = [r for r in results if r.total_trades >= min_trades]
        
        if not valid_results:
            return None
        
        # Mapear metricas para funcoes de comparacao
        # Para drawdown, queremos minimizar (menor e melhor)
        # Para outras metricas, queremos maximizar (maior e melhor)
        if metric == "drawdown" or metric == "max_drawdown" or metric == "max_drawdown_percent":
            return min(valid_results, key=lambda r: r.max_drawdown_percent)
        elif metric == "win_rate":
            return max(valid_results, key=lambda r: r.win_rate)
        elif metric == "profit_factor":
            return max(valid_results, key=lambda r: (r.profit_factor if r.profit_factor != float('inf') else 0))
        elif metric == "pnl" or metric == "total_pnl":
            return max(valid_results, key=lambda r: r.total_pnl)
        elif metric == "sharpe" or metric == "sharpe_ratio":
            return max(valid_results, key=lambda r: r.sharpe_ratio)
        elif metric == "trades" or metric == "total_trades":
            return max(valid_results, key=lambda r: r.total_trades)
        else:
            # Default: win_rate
            return max(valid_results, key=lambda r: r.win_rate)
    
    def get_top_results(
        self,
        summary: OptimizationSummary,
        top_n: int = 5,
        metric: Optional[str] = None,
    ) -> List[OptimizationResult]:
        """
        Retorna os top N resultados ordenados pela metrica especificada.
        
        Args:
            summary: Resumo da otimizacao
            top_n: Numero de resultados para retornar
            metric: Metrica para ordenacao (usa a da otimizacao se None)
        
        Returns:
            Lista dos top N OptimizationResult
        """
        metric = metric or summary.optimization_metric
        
        # Filtrar resultados validos (pelo menos 1 trade)
        valid_results = [r for r in summary.all_results if r.total_trades > 0]
        
        # Ordenar pela metrica
        if metric == "drawdown" or metric == "max_drawdown" or metric == "max_drawdown_percent":
            sorted_results = sorted(valid_results, key=lambda r: r.max_drawdown_percent)
        elif metric == "win_rate":
            sorted_results = sorted(valid_results, key=lambda r: r.win_rate, reverse=True)
        elif metric == "profit_factor":
            sorted_results = sorted(
                valid_results,
                key=lambda r: (r.profit_factor if r.profit_factor != float('inf') else 0),
                reverse=True,
            )
        elif metric == "pnl" or metric == "total_pnl":
            sorted_results = sorted(valid_results, key=lambda r: r.total_pnl, reverse=True)
        else:
            sorted_results = sorted(valid_results, key=lambda r: r.win_rate, reverse=True)
        
        return sorted_results[:top_n]
    
    def export_results(self, summary: OptimizationSummary, filename: str, format: str = "json"):
        """
        Exporta todos os resultados da otimizacao para um arquivo.
        
        Args:
            summary: Resumo da otimizacao
            filename: Nome do arquivo para salvar
            format: Formato do arquivo ("json" ou "csv")
        """
        export_data = [asdict(r) for r in summary.all_results]
        
        if format == "json":
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=4)
            logger.info(f"Resultados exportados para JSON: {filename}")
        elif format == "csv":
            if not export_data:
                logger.warning("Nenhum dado para exportar para CSV.")
                return
            
            keys = export_data[0].keys()
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(export_data)
            logger.info(f"Resultados exportados para CSV: {filename}")
        else:
            logger.warning(f"Formato de exportacao '{format}' nao suportado.")
    
    def analyze_param_sensitivity(
        self,
        summary: OptimizationSummary,
        param_name: str,
    ) -> Dict[str, Any]:
        """
        Analisa a sensibilidade de um parametro especifico.
        
        Args:
            summary: Resumo da otimizacao
            param_name: Nome do parametro para analisar
        
        Returns:
            Dicionario com estatisticas de sensibilidade
        """
        from collections import defaultdict
        
        # Agrupar resultados por valor do parametro
        param_groups: Dict[Any, List[OptimizationResult]] = defaultdict(list)
        
        for result in summary.all_results:
            if result.total_trades > 0:  # Apenas resultados validos
                param_value = result.params.get(param_name)
                if param_value is not None:
                    param_groups[param_value].append(result)
        
        # Calcular estatisticas por grupo
        sensitivity_analysis = {}
        for param_value, results in param_groups.items():
            win_rates = [r.win_rate for r in results]
            pnls = [r.total_pnl for r in results]
            
            sensitivity_analysis[param_value] = {
                "count": len(results),
                "avg_win_rate": sum(win_rates) / len(win_rates) if win_rates else 0,
                "max_win_rate": max(win_rates) if win_rates else 0,
                "min_win_rate": min(win_rates) if win_rates else 0,
                "avg_pnl": sum(pnls) / len(pnls) if pnls else 0,
                "max_pnl": max(pnls) if pnls else 0,
                "min_pnl": min(pnls) if pnls else 0,
            }
        
        return {
            "param_name": param_name,
            "analysis": sensitivity_analysis,
            "best_value": max(
                sensitivity_analysis.items(),
                key=lambda x: x[1]["avg_win_rate"],
            )[0] if sensitivity_analysis else None,
        }

    def walk_forward_optimization(
        self,
        param_grid: Dict[str, List[Any]],
        window_size: int,
        step_size: int,
        optimization_metric: str = "win_rate",
        min_trades: int = 10,
        use_rsi_filter: bool = True,
    ) -> Dict[str, Any]:
        """
        Realiza otimizacao walk-forward (validacao cruzada no tempo).
        
        Args:
            param_grid: Dicionario com listas de valores para cada parametro
            window_size: Tamanho da janela de treinamento (numero de candles)
            step_size: Tamanho do passo para avancar a janela (numero de candles)
            optimization_metric: Metrica para otimizar ("win_rate", "profit_factor", etc.)
            min_trades: Numero minimo de trades para considerar um resultado valido
            use_rsi_filter: Se True, usa filtro RSI na estrategia
        
        Returns:
            Dicionario com os melhores parametros para cada janela de teste
        """
        logger.info(f"Iniciando otimizacao Walk-Forward (janela: {window_size}, passo: {step_size})")
        
        all_walk_forward_results: List[Dict[str, Any]] = []
        
        # Iterar sobre as janelas de dados
        for i in range(0, len(self.history) - window_size, step_size):
            train_data = self.history[i : i + window_size]
            test_data = self.history[i + window_size : i + window_size + step_size]
            
            if not test_data:
                break
            
            logger.info(f"  > Janela {i // step_size + 1}: Treino de {len(train_data)} candles, Teste de {len(test_data)} candles")
            
            # Otimizar na janela de treinamento
            train_optimizer = StrategyOptimizer(train_data, self.backtester_config, self.risk_free_rate)
            train_summary = train_optimizer.optimize(
                param_grid=param_grid,
                optimization_metric=optimization_metric,
                min_trades=min_trades,
                use_rsi_filter=use_rsi_filter,
            )
            
            if not train_summary.best_result:
                logger.warning(f"  > Nao encontrado melhor resultado para a janela de treino {i // step_size + 1}. Pulando.")
                continue
            
            best_params_train = train_summary.best_result.params
            logger.info(f"  > Melhores parametros de treino: {best_params_train}")
            
            # Testar os melhores parametros na janela de teste
            test_backtester = Backtester(self.backtester_config)
            test_result = test_backtester.run(
                history=test_data,
                strategy_params=best_params_train,
            )
            
            # Registrar resultados walk-forward
            all_walk_forward_results.append({
                "train_start_epoch": train_data[0].epoch,
                "train_end_epoch": train_data[-1].epoch,
                "test_start_epoch": test_data[0].epoch,
                "test_end_epoch": test_data[-1].epoch,
                "best_params_train": best_params_train,
                "test_win_rate": test_result.win_rate,
                "test_total_pnl": test_result.total_pnl,
                "test_profit_factor": test_result.profit_factor,
                "test_total_trades": test_result.total_trades,
            })
            
            logger.info(
                f"  > Resultados Teste: Win Rate {test_result.win_rate:.2f}%, PnL {test_result.total_pnl:.2f}, "
                f"Trades {test_result.total_trades}"
            )
            
        logger.info("Otimizacao Walk-Forward concluida.")
        return {"walk_forward_results": all_walk_forward_results}

def run_optimization_example(history: List[Candle]) -> OptimizationSummary:
    """
    Exemplo de uso do otimizador com parametros comuns.
    
    Args:
        history: Lista de candles historicos
    
    Returns:
        OptimizationSummary com resultados
    """
    optimizer = StrategyOptimizer(history)
    
    param_grid = {
        "consecutive_candles": [7, 8, 9, 10, 11],
        "rsi_period": [12, 14, 16],
        "rsi_oversold": [25, 30, 35],
        "rsi_overbought": [65, 70, 75],
    }
    
    summary = optimizer.optimize(
        param_grid=param_grid,
        optimization_metric="composite_score",
        min_trades=5,
    )
    
    if summary.best_result:
        logger.info(f"Melhor resultado (Composite Score {summary.best_result.composite_score:.2f}):")
        logger.info(f"Parametros: {summary.best_result.params}")
        logger.info(f"Win Rate: {summary.best_result.win_rate:.2f}% | PnL: {summary.best_result.total_pnl:.2f}")
        logger.info(f"Sharpe Ratio: {summary.best_result.sharpe_ratio:.2f} | Profit Factor: {summary.best_result.profit_factor:.2f}")
    
    # Exemplo de Walk-Forward Optimization
    # wf_results = optimizer.walk_forward_optimization(
    #    param_grid=param_grid,
    #    window_size=1000, # Ex: 1000 candles para treino
    #    step_size=200,    # Ex: avancar 200 candles no teste
    #    optimization_metric="win_rate",
    #    min_trades=2,
    # )
    # logger.info(f"Resultados Walk-Forward: {wf_results}")

    return summary
