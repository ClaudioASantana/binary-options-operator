from typing import List
from app.models.market import Candle

def calculate_win_rate(closed_candles: List[Candle], target_consecutive: int) -> dict:
    """
    Analisa o historico de velas e simula entradas apos `target_consecutive` velas da mesma cor.
    Se a vela N for igual as ultimas (ex: 5 velas vermelhas), simulamos entrada CALL (verde) na proxima.
    Retorna o total de sinais gerados e a % de vitoria (Win Rate).
    """
    if len(closed_candles) <= target_consecutive:
        return {"signals": 0, "wins": 0, "losses": 0, "win_rate": 0.0}

    signals_generated = 0
    wins = 0
    losses = 0

    consecutive_count = 1
    for i in range(1, len(closed_candles) - 1): # ate a penultima, pq simulamos a proxima
        prev_candle = closed_candles[i-1]
        curr_candle = closed_candles[i]
        next_candle = closed_candles[i+1]

        if curr_candle.direction.value == prev_candle.direction.value:
            consecutive_count += 1
        else:
            consecutive_count = 1

        if consecutive_count == target_consecutive:
            # Gatilho de sinal!
            signals_generated += 1
            
            # A aposta seria de reversão (contra a direcao da current_candle)
            # Win se next_candle tiver direcao oposta
            if next_candle.direction.value != curr_candle.direction.value:
                wins += 1
            else:
                losses += 1
                
            # Resetamos a contagem pq ja "operamos"
            consecutive_count = 0
            
    win_rate = 0.0
    if signals_generated > 0:
        win_rate = round((wins / signals_generated) * 100, 2)
        
    return {
        "signals": signals_generated,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate
    }
