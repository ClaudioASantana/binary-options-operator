---
description: Desenvolver um módulo de backtesting para validar estratégias em dados históricos
priority: high
status: pending
---

# Task 02: Backtesting de Estratégias

## Objetivo

Desenvolver um módulo de backtesting que permita testar estratégias de trading (incluindo as regras ABR e otimizadas) em dados históricos de forma automática, gerando métricas de desempenho detalhadas.

---

## Subtasks

### 1. Módulo de Backtesting (`backend/app/engines/backtester.py`)

- [ ] Criar uma classe `Backtester` que orquestre o processo de simulação.
- [ ] Definir a interface para carregar dados históricos (ticks ou candles).
- [ ] Implementar o loop de simulação temporal, processando dados tick a tick ou candle a candle.
- [ ] Reutilizar os componentes existentes:
    - `CandleBuilder`: Para reconstruir candles em diferentes timeframes.
    - `Strategy Engine`: Para gerar sinais.
    - `Risk Engine`: Para aplicar regras de risco (em modo de simulação).
    - `NewsFilter`: Para bloquear trades durante notícias.
    - `PaperTrader`: Adaptar para simular trades e calcular PnL no backtest.

### 2. Definição de Estratégias para Backtest

- [ ] Criar um formato configurável para definir estratégias a serem testadas (ex: YAML ou JSON).
- [ ] Permitir a configuração de parâmetros da estratégia (e.g., `timeframe`, `candles`, `gale`, `rsi`).

### 3. Geração de Métricas de Desempenho

- [ ] Calcular e registrar as seguintes métricas ao final de cada backtest:
    - PnL Total (Profit and Loss)
    - Win Rate (Taxa de Vitórias)
    - Drawdown Máximo
    - Número de Trades
    - Média de PnL por Trade
    - Fator de Lucro (Profit Factor)
    - Risco/Retorno
- [ ] Gerar um log detalhado de cada trade simulado (entrada, saída, PnL, motivo).

### 4. Interface API para Backtesting (`backend/app/main.py`)

- [ ] Criar um endpoint `/api/backtest/run` (POST) para iniciar um backtest.
    - Entrada: Nome da estratégia, período histórico (data de início/fim), parâmetros.
    - Saída: ID do backtest em execução ou resultados finais se for síncrono e rápido.
- [ ] Criar um endpoint `/api/backtest/results/{backtest_id}` (GET) para recuperar os resultados de um backtest.

### 5. Integração com o `optimizer.py` (Refatoração)

- [ ] O script `optimizer.py` deve ser refatorado para usar o novo módulo `backtester.py`.
- [ ] Garantir que o `optimizer.py` possa executar múltiplos backtests com diferentes parâmetros para encontrar as configurações ideais.

---

## Critérios de Aceite para a Task:

- [ ] Um backtest pode ser executado via API com um conjunto de parâmetros e dados históricos.
- [ ] O backtest gera um relatório de métricas de desempenho.
- [ ] O sistema de backtesting consegue simular trades usando as regras de risco e estratégia definidas.
- [ ] O `optimizer.py` foi atualizado para usar o novo módulo de backtesting.
