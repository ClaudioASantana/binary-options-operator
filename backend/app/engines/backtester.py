"""
Backtester - Motor de backtesting para validacao de estrategias em dados historicos.

Reutiliza componentes existentes:
- Strategy Engine (evaluate_strategy)
- Risk Engine (evaluate_risk)
- AbsoluteLimits
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass, field
from app.models.market import Candle, CandleDirection, Signal, SignalType, AccountState, RiskDecision
from app.engines.strategy import evaluate_strategy
from app.engines.risk import evaluate_risk
from app.validators.risk_limits import AbsoluteLimits, RiskLimits # Importar RiskLimits
from app.engines.indicators import calculate_rsi

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """Registro de um trade simulado no backtest."""
    entry_epoch: int
    entry_price: float
    direction: str  # CALL ou PUT
    stake: float
    gale_level: int
    exit_epoch: Optional[int] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    status: str = "OPEN"  # OPEN, WIN, LOSS, TIE
    strategy_info: str = ""


@dataclass
class BacktestResult:
    """Resultado consolidado de um backtest."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    initial_balance: float = 0.0
    final_balance: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_percent: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    trades: List[BacktestTrade] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte resultado para dicionario (JSON serializavel)."""
        return {
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
            "win_rate": round(self.win_rate, 2),
            "total_pnl": round(self.total_pnl, 2),
            "initial_balance": round(self.initial_balance, 2),
            "final_balance": round(self.final_balance, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_drawdown_percent": round(self.max_drawdown_percent, 2),
            "profit_factor": round(self.profit_factor, 2),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "largest_win": round(self.largest_win, 2),
            "largest_loss": round(self.largest_loss, 2),
            "consecutive_wins": self.consecutive_wins,
            "consecutive_losses": self.consecutive_losses,
            "max_consecutive_wins": self.max_consecutive_wins,
            "max_consecutive_losses": self.max_consecutive_losses,
            "config": self.config,
            "trades": [
                {
                    "entry_epoch": t.entry_epoch,
                    "entry_price": t.entry_price,
                    "direction": t.direction,
                    "stake": round(t.stake, 2),
                    "gale_level": t.gale_level,
                    "exit_epoch": t.exit_epoch,
                    "exit_price": t.exit_price,
                    "pnl": round(t.pnl, 2),
                    "status": t.status,
                    "strategy_info": t.strategy_info,
                }
                for t in self.trades
            ]
        }


class BacktesterConfig:
    """Configuracao do Backtester."""
    
    def __init__(
        self,
        initial_balance: float = 1000.0,
        stake_initial: float = 10.0,
        payout_rate: float = 0.95,
        max_gale: int = 2,
        daily_stop_loss: float = 50.0,
        daily_stop_gain: float = 30.0,
        apply_risk_limits: bool = True,
    ):
        self.initial_balance = initial_balance
        self.stake_initial = stake_initial
        self.payout_rate = payout_rate
        self.max_gale = max_gale
        self.daily_stop_loss = daily_stop_loss
        self.daily_stop_gain = daily_stop_gain
        self.apply_risk_limits = apply_risk_limits


class Backtester:
    """
    Motor de backtesting para estrategias de trading.
    """
    
    def __init__(self, config: Optional[BacktesterConfig] = None):
        self.config = config or BacktesterConfig()
        self.absolute_limits = AbsoluteLimits()
        self.risk_limits = RiskLimits( # Reintroduzir inicializacao
            max_gale_config=self.config.max_gale,
            max_stake_config=self.absolute_limits.MAX_STAKE_ABSOLUTE_USD,
            max_daily_loss_config=self.config.daily_stop_loss,
            max_daily_gain_config=self.config.daily_stop_gain,
        )
    
    def run(
        self,
        history: List[Candle],
        strategy_params: Dict[str, Any],
        rsi_period: int = 14,
    ) -> BacktestResult:
        """
        Executa backtest em uma serie historica de candles.
        """
        # Estado da simulacao
        balance = self.config.initial_balance
        peak_balance = balance
        max_drawdown = 0.0
        
        current_stake = self.config.stake_initial
        current_gale = 0
        consecutive_wins = 0
        consecutive_losses = 0
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        
        in_trade = False
        trade_direction = None
        trade_stake = 0.0
        trade_gale = 0
        trade_entry_price = 0.0
        trade_entry_epoch = 0
        
        trades: List[BacktestTrade] = []
        current_trade: Optional[BacktestTrade] = None
        
        wins = 0
        losses = 0
        ties = 0
        total_pnl = 0.0
        sum_wins = 0.0
        sum_losses = 0.0
        largest_win = 0.0
        largest_loss = 0.0
        
        # Extrair parametros da estrategia
        consecutive_candles = strategy_params.get("consecutive_candles", 9)
        rsi_oversold = strategy_params.get("rsi_oversold", 30)
        rsi_overbought = strategy_params.get("rsi_overbought", 70)
        
        logger.info(f"Iniciando backtest: {len(history)} candles, consecutive_candles={consecutive_candles}")
        
        for i in range(len(history)):
            current_candle = history[i]
            
            # 1. Se estamos em um trade aberto, verificar resultado com o candle ATUAL
            if in_trade and current_trade:
                won = False
                if trade_direction == "CALL" and current_candle.close > trade_entry_price:
                    won = True
                elif trade_direction == "PUT" and current_candle.close < trade_entry_price:
                    won = True
                
                is_tie = (current_candle.close == trade_entry_price)
                
                if won:
                    pnl = trade_stake * self.config.payout_rate
                    balance += pnl
                    total_pnl += pnl
                    sum_wins += pnl
                    wins += 1
                    consecutive_wins += 1
                    consecutive_losses = 0
                    max_consecutive_wins = max(max_consecutive_wins, consecutive_wins)
                    
                    if pnl > largest_win:
                        largest_win = pnl
                    
                    current_trade.status = "WIN"
                    current_trade.pnl = pnl
                    current_trade.exit_price = current_candle.close
                    current_trade.exit_epoch = current_candle.epoch
                    trades.append(current_trade)
                    
                    current_stake = self.config.stake_initial
                    current_gale = 0
                    in_trade = False
                    current_trade = None
                    
                elif is_tie:
                    pnl = 0.0
                    ties += 1
                    current_trade.status = "TIE"
                    current_trade.pnl = pnl
                    current_trade.exit_price = current_candle.close
                    current_trade.exit_epoch = current_candle.epoch
                    trades.append(current_trade)
                    in_trade = False
                    current_trade = None
                    
                else:
                    pnl = -trade_stake
                    balance += pnl
                    total_pnl += pnl
                    sum_losses += abs(pnl)
                    losses += 1
                    consecutive_losses += 1
                    consecutive_wins = 0
                    max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
                    
                    if abs(pnl) > abs(largest_loss):
                        largest_loss = pnl
                    
                    current_trade.status = "LOSS"
                    current_trade.pnl = pnl
                    current_trade.exit_price = current_candle.close
                    current_trade.exit_epoch = current_candle.epoch
                    trades.append(current_trade)
                    
                    if current_gale < self.config.max_gale:
                        current_gale += 1
                        next_stake = self.config.stake_initial * (2 ** current_gale)
                        is_valid, _ = self.absolute_limits.validate_stake(next_stake)
                        current_stake = next_stake if is_valid else self.absolute_limits.MAX_STAKE_ABSOLUTE_USD
                    else:
                        current_stake = self.config.stake_initial
                        current_gale = 0
                    
                    in_trade = False
                    current_trade = None
                
                if balance < peak_balance:
                    drawdown = peak_balance - balance
                    if drawdown > max_drawdown:
                        max_drawdown = drawdown
                else:
                    peak_balance = balance
                
                continue
            
            # 2. Gerar sinal (somente se nao estiver em trade)
            min_index = rsi_period + consecutive_candles
            if i < min_index:
                continue
            
            # Strategy Engine usa seconds_in_cycle para timing
            # Passar history[:i+1] significa "todos os candles ate o atual"
            # O Strategy Engine vai usar os `consecutive_candles` mais recentes desta lista.
            strategy_signal = evaluate_strategy(
                history[:i+1],
                seconds_in_cycle=298, # Fixo para backtest de M5
                consecutive_candles=consecutive_candles # Passar o parametro aqui
            )
            
            if strategy_signal.type == SignalType.NONE:
                continue
            
            signal = strategy_signal.type.value
            
            # Aplicar filtro RSI manualmente
            slice_history = history[:i+1]
            rsi_val = calculate_rsi(slice_history, rsi_period)
            
            skip_signal = False
            if signal == "CALL" and rsi_val >= rsi_oversold:
                skip_signal = True
            elif signal == "PUT" and rsi_val <= rsi_overbought:
                skip_signal = True
            
            if skip_signal:
                continue
            
            # Validar risco antes de entrar
            if self.config.apply_risk_limits:
                current_pnl = balance - self.config.initial_balance
                if current_pnl <= -self.config.daily_stop_loss:
                    logger.info(f"Backtest parado: Daily stop loss atingido ({current_pnl:.2f})")
                    break
                if current_pnl >= self.config.daily_stop_gain:
                    logger.info(f"Backtest parado: Daily stop gain atingido ({current_pnl:.2f})")
                    break
                
                account_state = AccountState(
                    balance=balance,
                    daily_pnl=current_pnl,
                    current_gale_level=current_gale,
                    daily_stop_loss=self.config.daily_stop_loss,
                    daily_stop_gain=self.config.daily_stop_gain,
                    max_gale=self.config.max_gale,
                    stake_initial=self.config.stake_initial,
                )
                risk_eval = evaluate_risk(
                    signal=strategy_signal,
                    account=account_state,
                    config_gale=self.config.max_gale,
                )
                
                if risk_eval.decision == RiskDecision.BLOCKED:
                    logger.debug(f"Sinal {signal} bloqueado pelo risco: {risk_eval.reason}")
                    continue
                
                trade_stake = risk_eval.stake
                trade_gale = risk_eval.gale_level
            else:
                # Se nao aplica limites de risco, usa stake e gale diretamente da config
                trade_stake = current_stake
                trade_gale = current_gale
            
            # Entrar no trade
            in_trade = True
            trade_direction = signal
            trade_entry_price = current_candle.close
            trade_entry_epoch = current_candle.epoch
            
            strategy_info = f"M{strategy_params.get('timeframe', 300)//60}/{consecutive_candles}V"
            
            current_trade = BacktestTrade(
                entry_epoch=trade_entry_epoch,
                entry_price=trade_entry_price,
                direction=signal,
                stake=trade_stake,
                gale_level=trade_gale,
                strategy_info=strategy_info,
            )
            
            logger.debug(f"Sinal {signal} em {datetime.fromtimestamp(trade_entry_epoch)} - Stake: {trade_stake:.2f}")
        
        # Calcular metricas finais
        total_trades = wins + losses + ties
        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0.0
        profit_factor = (sum_wins / sum_losses) if sum_losses > 0 else float('inf') if sum_wins > 0 else 0.0
        max_drawdown_percent = (max_drawdown / peak_balance * 100) if peak_balance > 0 else 0.0
        avg_win = (sum_wins / wins) if wins > 0 else 0.0
        avg_loss = (sum_losses / losses) if losses > 0 else 0.0
        
        result = BacktestResult(
            total_trades=total_trades,
            wins=wins,
            losses=losses,
            ties=ties,
            win_rate=win_rate,
            total_pnl=total_pnl,
            initial_balance=self.config.initial_balance,
            final_balance=balance,
            max_drawdown=max_drawdown,
            max_drawdown_percent=max_drawdown_percent,
            profit_factor=profit_factor,
            avg_win=avg_win,
            avg_loss=avg_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
            consecutive_wins=consecutive_wins,
            consecutive_losses=consecutive_losses,
            max_consecutive_wins=max_consecutive_wins,
            max_consecutive_losses=max_consecutive_losses,
            trades=trades,
            config={
                "consecutive_candles": consecutive_candles,
                "rsi_oversold": rsi_oversold,
                "rsi_overbought": rsi_overbought,
                "rsi_period": rsi_period,
                "initial_balance": self.config.initial_balance,
                "stake_initial": self.config.stake_initial,
                "payout_rate": self.config.payout_rate,
                "max_gale": self.config.max_gale,
            }
        )
        
        logger.info(f"Backtest concluido: {total_trades} trades, Win Rate: {win_rate:.2f}%, PnL: {total_pnl:.2f}")
        
        return result
