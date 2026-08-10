import time
from typing import Dict, Optional
from datetime import datetime

class NewsFilter:
    def __init__(self, block_minutes_before=5, block_minutes_after=5):
        # Para a demo, vamos usar apenas 5 minutos de bloqueio pra podermos testar mais rápido
        self.block_before = block_minutes_before * 60
        self.block_after = block_minutes_after * 60
        self.simulated_events = []
        self._generate_schedule()
        
    def _generate_schedule(self):
        """Gera eventos simulados (3 Touros) no futuro para demonstração."""
        now = int(time.time())
        # Cria uma notícia que vai acontecer daqui a 3 minutos para testarmos o bloqueio
        self.simulated_events.append({
            "name": "NFP (Payroll) [Simulado]",
            "epoch": now + 300, # 5 min a frente
            "impact": "Alta Volatilidade (3 Touros)"
        })
        # Uma daqui a 1 hora
        self.simulated_events.append({
            "name": "Discurso do FED [Simulado]",
            "epoch": now + 3600,
            "impact": "Alta Volatilidade (3 Touros)"
        })
        
    def check_safety(self, current_epoch: int) -> Dict:
        """Verifica se o mercado está na zona proibida de alguma notícia"""
        
        next_event = None
        # Encontra o próximo evento futuro
        for event in sorted(self.simulated_events, key=lambda x: x["epoch"]):
            if event["epoch"] + self.block_after > current_epoch:
                next_event = event
                break
                
        if not next_event:
            return {"safe": True, "reason": "Livre de notícias", "next_event": None}
            
        time_to_event = next_event["epoch"] - current_epoch
        
        # Passou da notícia mas ainda tá na zona de choque (depois)
        if current_epoch >= next_event["epoch"] and current_epoch < next_event["epoch"] + self.block_after:
            return {
                "safe": False, 
                "reason": f"Pós-Notícia: {next_event['name']}. Aguardando o mercado normalizar.",
                "next_event": next_event
            }
            
        # Antes da notícia, dentro da zona de bloqueio
        if time_to_event <= self.block_before and time_to_event > 0:
            return {
                "safe": False,
                "reason": f"Pré-Notícia: {next_event['name']} em {int(time_to_event/60)} min. Alto Risco.",
                "next_event": next_event
            }
            
        return {
            "safe": True,
            "reason": "Mercado livre de choques",
            "next_event": next_event
        }
