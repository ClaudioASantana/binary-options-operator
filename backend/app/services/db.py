import sqlite3
import os
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# O banco será salvo na pasta /backend/data/
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "data")
DB_PATH = os.path.join(DB_DIR, "trading_history.db")

def init_db():
    """Inicializa o banco de dados e cria as tabelas se não existirem."""
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR, exist_ok=True)
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Tabela de operações (Trades)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS trades (
        id TEXT PRIMARY KEY,
        timestamp REAL,
        symbol TEXT,
        strategy TEXT,
        direction TEXT,
        stake REAL,
        payout_percent REAL,
        environment TEXT,
        agent_review TEXT,
        decision_reason TEXT,
        result TEXT DEFAULT 'PENDING',
        profit_loss REAL DEFAULT 0.0
    )
    ''')
    
    conn.commit()
    conn.close()
    logger.info(f"Banco de dados inicializado em {DB_PATH}")

def save_trade(trade_data: Dict[str, Any]):
    """Salva um novo trade no banco de dados."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO trades (
            id, timestamp, symbol, strategy, direction, stake, 
            payout_percent, environment, agent_review, decision_reason, result
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            trade_data.get('id', ''),
            trade_data.get('timestamp', 0.0),
            trade_data.get('symbol', ''),
            trade_data.get('strategy', ''),
            trade_data.get('direction', ''),
            trade_data.get('stake', 0.0),
            trade_data.get('payout_percent', 0.0),
            trade_data.get('environment', 'demo'),
            trade_data.get('agent_review', ''),
            trade_data.get('decision_reason', ''),
            trade_data.get('result', 'PENDING')
        ))
        
        conn.commit()
        conn.close()
        logger.info(f"💾 Trade salvo no BD: {trade_data.get('id')}")
    except Exception as e:
        logger.error(f"Erro ao salvar trade no BD: {e}")

def update_trade_result(trade_id: str, result: str, profit_loss: float):
    """Atualiza o resultado (WIN/LOSS) de um trade existente."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
        UPDATE trades 
        SET result = ?, profit_loss = ?
        WHERE id = ?
        ''', (result, profit_loss, trade_id))
        
        conn.commit()
        conn.close()
        logger.info(f"💾 Trade atualizado no BD: {trade_id} -> {result} ({profit_loss})")
    except Exception as e:
        logger.error(f"Erro ao atualizar trade no BD: {e}")

def get_recent_trades(limit: int = 50) -> List[Dict[str, Any]]:
    """Busca as ultimas operacoes para analise."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT * FROM trades 
        ORDER BY timestamp DESC 
        LIMIT ?
        ''', (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Erro ao buscar trades no BD: {e}")
        return []

# Inicializa o banco de dados na importacao do modulo
init_db()
