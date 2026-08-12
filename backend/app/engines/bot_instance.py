"""
Bot Instance - Instancia de bot por ativo com seguranca aprimorada.

Integra:
- Decision Harness para fluxo de decisao unificado
- Circuit Breakers para protecao do sistema
- Proposal Validator para validacao pre-compra
- Limites absolutos de risco (hard-coded)
- Fluxo de confirmacao manual para conta real
- RAG Agent para revisao e explicacao de sinais
"""
import asyncio
import logging
import time
from typing import Dict, Any, Optional

from app.services.deriv_client import DerivClient
from app.engines.candle_builder import CandleBuilder
from app.engines.simulator import PaperTrader
from app.engines.cataloger import calculate_win_rate
from app.models.market import (
    Tick, Signal, SignalType, AccountState, CandleDirection,
    RiskDecision, DerivProposal
)
from app.engines.news import NewsFilter
from app.engines.indicators import calculate_rsi
from app.engines.risk import evaluate_risk, get_effective_risk_limits
from app.engines.decision_harness import DecisionHarness, get_decision_harness, DecisionHarnessConfig
from app.engines.circuit_breaker import get_circuit_breaker_manager
from app.validators.risk_limits import AbsoluteLimits
from app.rag.agent import get_agent_service

logger = logging.getLogger(__name__)


class BotInstance:
    """
    Instancia de bot para um ativo especifico.
    
    Agora inclui:
    - Decision Harness para decisoes unificadas
    - Circuit Breakers para protecao
    - Confirmacao manual para conta real
    - RAG Agent para revisao de sinais
    """
    
    def __init__(
        self,
        symbol: str,
        token: str,
        news_filter: NewsFilter,
        manager,
        environment: str = "demo",  # demo ou real
        require_manual_confirmation: bool = False,
    ):
        self.symbol = symbol
        self.token = token
        self.news_filter = news_filter
        self.manager = manager
        self.environment = environment
        self.require_manual_confirmation = require_manual_confirmation
        
        import os
        self.client = DerivClient(app_id=os.getenv("DERIV_APP_ID", "1089").strip())
        self.client.symbol = self.symbol
        self.client.add_tick_callback(self.on_tick)
        self.client.add_history_callback(self.on_history)
        
        self.builder_m1 = CandleBuilder(60)
        self.builder_m5 = CandleBuilder(300)
        self.builder_m15 = CandleBuilder(900)
        
        # Paper trader com limites conservadores
        self.paper_trader = PaperTrader(initial_balance=200.0, payout_rate=0.95)
        self.paper_trader.daily_stop_loss = 20.0  # Limite conservador
        self.paper_trader.daily_stop_gain = 15.0
        self.paper_trader.max_gale = 3  # Respeita limite absoluto
        
        self.active_config = {
            "timeframe": 300,
            "candles": 5,
            "gale": 3,
            "rsi_oversold": 30,
            "rsi_overbought": 70
        }
        self.auto_optimize = False
        self.global_catalog = []
        
        self.tick_count = 0
        self.last_signal_direction = None
        
        # Pending manual confirmations
        self.pending_confirmations: Dict[str, dict] = {}
        
        # Obter singleton do Decision Harness
        harness_config = DecisionHarnessConfig(
            require_manual_confirmation_real=(environment == "real"),
            require_manual_confirmation_demo=False,
        )
        self.harness = get_decision_harness(harness_config)
        
        # Obter singleton do Circuit Breaker Manager
        self.cb_manager = get_circuit_breaker_manager()
        
        # Obter singleton do Agent Service (RAG)
        self.agent_service = get_agent_service()
        
        # Limites absolutos
        self.absolute_limits = AbsoluteLimits()
    
    def get_active_builder(self):
        if self.active_config["timeframe"] == 60:
            return self.builder_m1
        elif self.active_config["timeframe"] == 300:
            return self.builder_m5
        return self.builder_m15
    
    async def on_history(self, granularity: int, candles: list):
        from app.models.market import Candle
        b = self.builder_m1 if granularity == 60 else (self.builder_m5 if granularity == 300 else self.builder_m15)
        b.closed_candles = []
        for c in candles:
            direction = CandleDirection.BULLISH if c["close"] >= c["open"] else CandleDirection.BEARISH
            b.closed_candles.append(Candle(
                epoch=c["epoch"],
                open=c["open"],
                high=c["high"],
                low=c["low"],
                close=c["close"],
                direction=direction
            ))
        logger.info(f"[{self.symbol}] Builder M{granularity//60} inicializado com {len(b.closed_candles)} velas historicas.")
    
    async def broadcast_catalog(self):
        catalog = []
        for timeframe, b in [(60, self.builder_m1), (300, self.builder_m5), (900, self.builder_m15)]:
            for candles_req in [3, 5, 7, 9]:
                stats = await asyncio.to_thread(calculate_win_rate, b.closed_candles, candles_req)
                catalog.append({
                    "timeframe": timeframe,
                    "candles": candles_req,
                    "stats": stats
                })
        results = catalog
        self.global_catalog = results
        await self.manager.broadcast({
            "event": "catalog",
            "symbol": self.symbol,
            "data": {
                "catalog": results,
                "active_config": self.active_config,
                "auto_optimize": self.auto_optimize
            }
        })
    
    async def on_tick(self, tick: Tick):
        self.tick_count += 1
        c1 = self.builder_m1.process_tick(tick)
        c5 = self.builder_m5.process_tick(tick)
        c15 = self.builder_m15.process_tick(tick)
        
        active_builder = self.get_active_builder()
        
        if active_builder.current_candle:
            await self.manager.broadcast({
                "event": "tick",
                "symbol": self.symbol,
                "data": {
                    "quote": tick.quote,
                    "epoch": tick.epoch,
                    "candle": active_builder.current_candle.model_dump()
                }
            })
        
        if c1 or c5 or c15:
            asyncio.create_task(self.broadcast_catalog())
        
        # Check expirations
        finished_trades = self.paper_trader.check_expirations(tick.epoch, tick.quote)
        if finished_trades:
            await self.manager.broadcast({
                "event": "simulator",
                "symbol": self.symbol,
                "data": self.paper_trader.get_state()
            })
        
        # Strategy Logic
        approved_configs = []
        if self.auto_optimize and len(self.global_catalog) > 0:
            approved_configs = [c for c in self.global_catalog if c["stats"]["win_rate"] >= 80]
            if not approved_configs:
                approved_configs = [max(self.global_catalog, key=lambda x: x["stats"]["win_rate"])]
        else:
            approved_configs = [self.active_config]
        
        for config in approved_configs:
            tf = config["timeframe"]
            req_candles = config["candles"]
            builder = self.builder_m1 if tf == 60 else (self.builder_m5 if tf == 300 else self.builder_m15)
            
            seconds_in_cycle = builder.get_seconds_in_cycle(tick)
            if seconds_in_cycle >= (tf - 2):
                if len(builder.closed_candles) >= req_candles:
                    last_n = builder.closed_candles[-req_candles:]
                    signal = Signal(type=SignalType.NONE, reason="")
                    
                    if all(c.direction.value == "BEARISH" for c in last_n):
                        signal = Signal(
                            type=SignalType.CALL,
                            reason=f"{req_candles} velas de baixa no M{tf//60}",
                            symbol=self.symbol
                        )
                    elif all(c.direction.value == "BULLISH" for c in last_n):
                        signal = Signal(
                            type=SignalType.PUT,
                            reason=f"{req_candles} velas de alta no M{tf//60}",
                            symbol=self.symbol
                        )
                    
                    # RSI filter
                    if signal.type.value != "NONE":
                        strategy_info = f"M{tf//60}/{req_candles}V"
                        rsi_val = calculate_rsi(builder.closed_candles)
                        rsi_os = config.get("rsi_oversold", 30)
                        rsi_ob = config.get("rsi_overbought", 70)
                        if signal.type.value == "CALL" and rsi_val >= rsi_os:
                            signal.type = SignalType.NONE
                        elif signal.type.value == "PUT" and rsi_val <= rsi_ob:
                            signal.type = SignalType.NONE
                    
                    # News filter check
                    if signal.type.value != "NONE":
                        news_status = self.news_filter.check_safety(tick.epoch)
                        if not news_status.get("safe", True):
                            logger.warning(f"⛔ [{self.symbol} - {strategy_info}] BLOQUEADO NOTICIA: {news_status.get('reason', 'High impact news')}")
                            signal.type = SignalType.NONE
                    
                    # Process signal through Decision Harness
                    if signal.type.value != "NONE":
                        await self._process_signal(signal, strategy_info, tick, config)
    
    async def _process_signal(
        self,
        signal: Signal,
        strategy_info: str,
        tick: Tick,
        config: dict
    ):
        """Processa sinal atraves do Decision Harness."""
        logger.info(f"🎯 [{self.symbol} - {strategy_info}] SINAL DETECTADO: {signal.type.value}")
        
        await self.manager.broadcast({
            "event": "signal",
            "symbol": self.symbol,
            "data": {
                "type": signal.type.value,
                "reason": signal.reason,
                "strategy": strategy_info
            }
        })
        
        # Criar AccountState atualizado
        account_state = AccountState(
            balance=self.paper_trader.balance,
            daily_pnl=self.paper_trader.get_pnl(),
            current_gale_level=self.paper_trader.consecutive_losses,
            daily_stop_loss=self.paper_trader.daily_stop_loss,
            daily_stop_gain=self.paper_trader.daily_stop_gain,
            max_gale=self.paper_trader.max_gale,
            stake_initial=self.paper_trader.stake_initial,
            consecutive_losses=self.paper_trader.consecutive_losses,
            trades_today=self.paper_trader.trades_today,
            max_trades_per_day=50,
            environment=self.environment,
        )
        
        # Usar Decision Harness para avaliar sinal (COM AGENTE)
        output = self.harness.evaluate(
            signal=signal,
            account=account_state,
            agent_service=self.agent_service,  # Passa o agent_service
            news_filter=self.news_filter,
        )
        
        # Broadcast agent message if available
        if output.agent_review:
            await self.manager.broadcast({
                "event": "agent_message",
                "symbol": self.symbol,
                "data": output.agent_review.summary
            })
        
        # Handle decision
        if output.final_decision == RiskDecision.BLOCKED:
            logger.warning(f"⛔ [{self.symbol} - {strategy_info}] BLOQUEADO: {output.final_message}")
            return
        
        if output.final_decision == RiskDecision.PENDING_MANUAL:
            # Requires manual confirmation
            logger.info(f"⏳ [{self.symbol} - {strategy_info}] Aguardando confirmacao manual")
            
            # Store pending confirmation
            decision_id = f"{self.symbol}_{tick.epoch}"
            self.pending_confirmations[decision_id] = {
                "signal": signal,
                "output": output,
                "tick": tick,
                "config": config,
                "strategy_info": strategy_info,
                "created_at": time.time(),
            }
            
            await self.manager.broadcast({
                "event": "manual_confirmation_required",
                "symbol": self.symbol,
                "data": {
                    "decision_id": decision_id,
                    "signal_type": signal.type.value,
                    "stake": output.stake_to_use,
                    "reason": output.final_message,
                    "timeout_seconds": 30,
                }
            })
            return
        
        # Auto-approved - execute
        if output.final_decision == RiskDecision.APPROVED:
            await self._execute_trade(signal, strategy_info, tick, config, output.stake_to_use)
    
    async def _execute_trade(
        self,
        signal: Signal,
        strategy_info: str,
        tick: Tick,
        config: dict,
        stake: float
    ):
        """Executa trade apos aprovacao."""
        logger.info(f"✅ [{self.symbol} - {strategy_info}] EXECUTANDO: {signal.type.value} stake={stake:.2f}")
        
        # Update paper trader gale max
        self.paper_trader.max_gale = config.get("gale", 3)
        self.last_signal_direction = signal.type.value
        
        # Open trade in simulator
        self.paper_trader.open_trade(signal.type.value, config["timeframe"], tick.epoch, tick.quote)
        
        await self.manager.broadcast({
            "event": "simulator",
            "symbol": self.symbol,
            "data": self.paper_trader.get_state()
        })
        
        await self.manager.broadcast({
            "event": "trade_opened",
            "symbol": self.symbol,
            "data": {
                "direction": signal.type.value,
                "price": tick.quote,
                "stake": stake,
                "strategy": strategy_info,
            }
        })
    
    async def confirm_manual_trade(
        self,
        decision_id: str,
        confirmed: bool
    ):
        """
        Processa confirmacao manual do usuario.
        
        Args:
            decision_id: ID da decisao pendente
            confirmed: True para confirmar, False para bloquear
        """
        if decision_id not in self.pending_confirmations:
            logger.warning(f"Decision {decision_id} not found or expired")
            return
        
        pending = self.pending_confirmations.pop(decision_id)
        
        if confirmed:
            # Execute the trade
            await self._execute_trade(
                signal=pending["signal"],
                strategy_info=pending["strategy_info"],
                tick=pending["tick"],
                config=pending["config"],
                stake=pending["output"].stake_to_use,
            )
        else:
            logger.info(f"⛔ [{self.symbol}] Trade rejeitado pelo usuario (decision_id={decision_id})")
            await self.manager.broadcast({
                "event": "manual_confirmation_result",
                "symbol": self.symbol,
                "data": {
                    "decision_id": decision_id,
                    "confirmed": False,
                    "message": "Trade rejeitado pelo usuario",
                }
            })
    
    async def start(self):
        await self.client.connect_and_listen(self.token)
    
    def stop(self):
        self.client.stop()
    
    def cleanup_pending_confirmations(self, current_time: float):
        """Remove pending confirmations that have timed out."""
        timeout_seconds = 30
        expired = []
        
        for decision_id, pending in self.pending_confirmations.items():
            if current_time - pending["created_at"] > timeout_seconds:
                expired.append(decision_id)
        
        for decision_id in expired:
            pending = self.pending_confirmations.pop(decision_id)
            logger.info(f"⏰ [{self.symbol}] Decision {decision_id} timed out")
            asyncio.create_task(self.manager.broadcast({
                "event": "manual_confirmation_result",
                "symbol": self.symbol,
                "data": {
                    "decision_id": decision_id,
                    "confirmed": False,
                    "message": "Confirmation timeout",
                }
            }))
