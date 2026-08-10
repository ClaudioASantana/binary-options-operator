import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

class PaperTrader:
    def __init__(self, initial_balance: float = 1000.0, payout_rate: float = 0.95):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.payout_rate = payout_rate
        self.pending_trades = []
        self.history_trades = []
        # Gestão de Risco & Gales
        self.consecutive_losses = 0
        self.daily_stop_loss = 50.0
        self.daily_stop_gain = 50.0
        self.max_gale = 2
        self.stake_initial = 1.0
        
    def get_pnl(self) -> float:
        return round(self.balance - self.initial_balance, 2)
        
    def register_trade(self, direction: str, entry_price: float, stake: float, timeframe_seconds: int, current_epoch: int):
        expiration_epoch = current_epoch + timeframe_seconds
        trade = {
            "id": str(uuid.uuid4())[:8],
            "direction": direction.upper(),
            "entry_price": entry_price,
            "stake": stake,
            "entry_epoch": current_epoch,
            "expiration_epoch": expiration_epoch,
            "status": "PENDING"
        }
        self.pending_trades.append(trade)
        logger.info(f"📊 [PaperTrader] Trade Registrado: {direction} | Stake: ${stake} | Entry: {entry_price} | Expira em: {timeframe_seconds}s")
        
    def check_expirations(self, current_epoch: int, current_price: float) -> list:
        finished = []
        for trade in self.pending_trades[:]:
            if current_epoch >= trade["expiration_epoch"]:
                # Expirou! Vamos checar WIN ou LOSS
                is_win = False
                if trade["direction"] == "CALL" and current_price > trade["entry_price"]:
                    is_win = True
                elif trade["direction"] == "PUT" and current_price < trade["entry_price"]:
                    is_win = True
                # Empate (current_price == entry_price) geralmente é LOSS em OB, ou devolução.
                # Vamos considerar devolução (Empate) para simplificar:
                is_tie = (current_price == trade["entry_price"])
                
                trade["exit_price"] = current_price
                trade["exit_epoch"] = current_epoch
                
                if is_win:
                    profit = trade["stake"] * self.payout_rate
                    self.balance += profit
                    trade["status"] = "WIN"
                    trade["profit"] = profit
                    self.consecutive_losses = 0 # Zera o gale
                    logger.info(f"🎉 [PaperTrader] WIN! +${profit:.2f} (Entry: {trade['entry_price']} -> Exit: {current_price})")
                elif is_tie:
                    trade["status"] = "TIE"
                    trade["profit"] = 0.0
                    # Empate não zera nem incrementa o gale, costuma repetir a mão.
                    logger.info(f"⚖️ [PaperTrader] EMPATE! (Entry: {trade['entry_price']} -> Exit: {current_price})")
                else:
                    self.balance -= trade["stake"]
                    trade["status"] = "LOSS"
                    trade["profit"] = -trade["stake"]
                    self.consecutive_losses += 1 # Incrementa o gale
                    logger.info(f"💀 [PaperTrader] LOSS! -${trade['stake']:.2f} (Entry: {trade['entry_price']} -> Exit: {current_price})")
                
                self.pending_trades.remove(trade)
                self.history_trades.insert(0, trade) # Inserir no inicio para o front mostrar os mais recentes primeiro
                finished.append(trade)
                
        return finished
        
    def get_next_stake(self):
        if self.consecutive_losses > self.max_gale:
            return self.stake_initial # Voltou pro início por atingir limite
        # Multiplicador 2x a cada loss (para simplificar)
        return self.stake_initial * (2 ** self.consecutive_losses)

    def get_state(self):
        return {
            "balance": round(self.balance, 2),
            "pnl": self.get_pnl(),
            "pending": self.pending_trades,
            "history": self.history_trades[:10], # Envia os 10 ultimos pro painel
            "risk": {
                "consecutive_losses": self.consecutive_losses,
                "max_gale": self.max_gale,
                "next_stake": self.get_next_stake(),
                "stop_loss": self.daily_stop_loss,
                "stop_gain": self.daily_stop_gain
            }
        }
