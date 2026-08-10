import asyncio
import logging
from typing import Dict, Any

from app.services.deriv_client import DerivClient
from app.engines.candle_builder import CandleBuilder
from app.engines.simulator import PaperTrader
from app.engines.cataloger import calculate_win_rate
from app.models.market import Tick, Signal, SignalType, AccountState, CandleDirection
from app.engines.news import NewsFilter
from app.engines.indicators import calculate_rsi
from app.engines.risk import evaluate_risk
from app.rag.agent import explain_signal

logger = logging.getLogger(__name__)

class BotInstance:
    def __init__(self, symbol: str, token: str, news_filter: NewsFilter, manager):
        self.symbol = symbol
        self.token = token
        self.news_filter = news_filter
        self.manager = manager  # WebSocket manager for broadcasting
        
        import os
        self.client = DerivClient(app_id=os.getenv("DERIV_APP_ID", "1089").strip())
        self.client.symbol = self.symbol
        self.client.add_tick_callback(self.on_tick)
        self.client.add_history_callback(self.on_history)
        
        self.builder_m1 = CandleBuilder(60)
        self.builder_m5 = CandleBuilder(300)
        self.builder_m15 = CandleBuilder(900)
        
        self.paper_trader = PaperTrader(initial_balance=1000.0, payout_rate=0.95)
        
        self.active_config = {"timeframe": 300, "candles": 5, "gale": 3, "rsi_oversold": 30, "rsi_overbought": 70}
        self.auto_optimize = False
        self.global_catalog = []
        
        self.tick_count = 0
        self.last_signal_direction = None

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
        logger.info(f"[{self.symbol}] Builder M{granularity//60} inicializado com {len(b.closed_candles)} velas históricas.")

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
        # We only broadcast if this bot is currently being watched by the UI
        # This logic will be handled by the manager in main.py, so we just send the message 
        # with our symbol attached.
        await self.manager.broadcast({"event": "catalog", "symbol": self.symbol, "data": {"catalog": results, "active_config": self.active_config, "auto_optimize": self.auto_optimize}})

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
            
        finished_trades = self.paper_trader.check_expirations(tick.epoch, tick.quote)
        if finished_trades:
            await self.manager.broadcast({"event": "simulator", "symbol": self.symbol, "data": self.paper_trader.get_state()})

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
                        signal = Signal(type=SignalType.CALL, reason=f"{req_candles} velas de baixa no M{tf//60}")
                    elif all(c.direction.value == "BULLISH" for c in last_n):
                        signal = Signal(type=SignalType.PUT, reason=f"{req_candles} velas de alta no M{tf//60}")
                        
                    if signal.type.value != "NONE":
                        strategy_info = f"M{tf//60}/{req_candles}V"
                        rsi_val = calculate_rsi(builder.closed_candles)
                        rsi_os = config.get("rsi_oversold", 30)
                        rsi_ob = config.get("rsi_overbought", 70)
                        if signal.type.value == "CALL" and rsi_val >= rsi_os:
                            # logger.warning(f"🚫 [{self.symbol} - {strategy_info}] CALL bloqueado. RSI={rsi_val}")
                            signal.type = SignalType.NONE
                        elif signal.type.value == "PUT" and rsi_val <= rsi_ob:
                            # logger.warning(f"🚫 [{self.symbol} - {strategy_info}] PUT bloqueado. RSI={rsi_val}")
                            signal.type = SignalType.NONE
                            
                    if signal.type.value != "NONE":
                        # Update paper trader gale max before opening trade
                        self.paper_trader.max_gale = config.get("gale", 3)
                        self.last_signal_direction = "CALL" if signal.type.value == "BUY" else "PUT"
                        news_status = self.news_filter.check_safety(tick.epoch)
                        if not news_status["safe"]:
                            logger.warning(f"⛔ [{self.symbol} - {strategy_info}] BLOQUEADO NOTÍCIA: {news_status['reason']}")
                            signal.type = SignalType.NONE
                            
                    if signal.type.value != "NONE":
                        logger.info(f"🎯 [{self.symbol} - {strategy_info}] SINAL DETECTADO: {signal.type.value}")
                        await self.manager.broadcast({"event": "signal", "symbol": self.symbol, "data": {"type": signal.type.value, "reason": signal.reason, "strategy": strategy_info}})
                        
                        account_state = AccountState(
                            balance=self.paper_trader.balance, 
                            current_consecutive_losses=self.paper_trader.consecutive_losses, 
                            daily_pnl=self.paper_trader.get_pnl(),
                            current_gale_level=self.paper_trader.consecutive_losses, 
                            daily_stop_loss=self.paper_trader.daily_stop_loss, 
                            daily_stop_gain=self.paper_trader.daily_stop_gain,
                            max_gale=self.paper_trader.max_gale, 
                            stake_initial=self.paper_trader.stake_initial
                        )
                        risk_eval = evaluate_risk(signal, account_state)
                        
                        try:
                            explanation = await asyncio.to_thread(explain_signal, signal, risk_eval.reason)
                            await self.manager.broadcast({"event": "agent_message", "symbol": self.symbol, "data": explanation})
                            
                            if risk_eval.decision.value == "BLOCKED":
                                logger.warning(f"⛔ [{self.symbol} - {strategy_info}] BLOQUEADO GESTOR: {risk_eval.reason}")
                            else:
                                self.paper_trader.open_trade(signal.type.value, tf, tick.epoch, tick.quote)
                                await self.manager.broadcast({"event": "simulator", "symbol": self.symbol, "data": self.paper_trader.get_state()})
                                await self.manager.broadcast({"event": "trade_opened", "symbol": self.symbol, "data": {"direction": signal.type.value, "price": tick.quote}})
                        except Exception as e:
                            logger.error(f"Erro IA [{self.symbol}]: {e}")

    async def start(self):
        await self.client.connect_and_listen(self.token)
        
    def stop(self):
        self.client.stop()
