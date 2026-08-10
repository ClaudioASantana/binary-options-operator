"use client";
import React from 'react';

import { useEffect, useState, useRef } from "react";
import { createChart, ColorType, CandlestickSeries } from "lightweight-charts";

export default function Home() {
  const [liveData, setLiveData] = useState<any>({ quote: 0, candle: null });
  const [signal, setSignal] = useState<any>(null);
  const [agentMessage, setAgentMessage] = useState<string>("");
  const [catalog, setCatalog] = useState<any[]>([]);
  const [activeConfig, setActiveConfig] = useState<any>({ timeframe: 300, candles: 5 });
  const [autoOptimize, setAutoOptimize] = useState<boolean>(false);
  const [simulatorState, setSimulatorState] = useState<any>(null);
  const [newsStatus, setNewsStatus] = useState<any>(null);
  const [portfolio, setPortfolio] = useState<any>(null);
  const [activeSymbol, setActiveSymbol] = useState<string>("R_100");
  const ws = useRef<WebSocket | null>(null);
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartSeriesRef = useRef<any>(null);

  useEffect(() => {
    // Connect to WebSocket
    ws.current = new WebSocket("ws://127.0.0.1:8000/ws");
    
    ws.current.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.event === "tick") {
        setLiveData(msg.data);
      } else if (msg.event === "signal") {
        setSignal(msg.data);
      } else if (msg.event === "agent_message") {
        setAgentMessage(msg.data);
      } else if (msg.event === "catalog") {
        setCatalog(msg.data.catalog);
        setActiveConfig(msg.data.active_config);
        setAutoOptimize(msg.data.auto_optimize);
        if (msg.data.simulator) setSimulatorState(msg.data.simulator);
        if (msg.data.news_status) setNewsStatus(msg.data.news_status);
      } else if (msg.event === "simulator") {
        setSimulatorState(msg.data.simulator || msg.data);
        if (msg.data.news_status) setNewsStatus(msg.data.news_status);
      } else if (msg.event === "active_symbol") {
        setActiveSymbol(msg.data);
      }
    };

    return () => {
      if (ws.current) ws.current.close();
    };
  }, []);

  useEffect(() => {
    const fetchPortfolio = async () => {
      try {
        const res = await fetch("http://localhost:8000/portfolio");
        const data = await res.json();
        setPortfolio(data);
      } catch (e) {}
    };
    fetchPortfolio();
    const interval = setInterval(fetchPortfolio, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!chartContainerRef.current) return;
    
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#d1d4dc',
      },
      grid: {
        vertLines: { color: 'rgba(42, 46, 57, 0)' },
        horzLines: { color: 'rgba(42, 46, 57, 0.2)' },
      },
      width: chartContainerRef.current.clientWidth,
      height: 250,
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
      }
    });

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350',
    });
    chartSeriesRef.current = candlestickSeries;

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, []);

  useEffect(() => {
    if (chartSeriesRef.current) {
      chartSeriesRef.current.setData([]);
    }
  }, [activeSymbol]);

  useEffect(() => {
    if (chartSeriesRef.current && liveData.candle) {
        const data = {
            time: liveData.candle.epoch,
            open: liveData.candle.open,
            high: liveData.candle.high,
            low: liveData.candle.low,
            close: liveData.candle.close,
        };
        try {
            chartSeriesRef.current.update(data);
        } catch (e) {
            chartSeriesRef.current.setData([data]);
        }
    }
  }, [liveData.candle]);

  // Modo Autônomo: Os métodos handleApprove e handleIgnore foram removidos.
  // O backend agora executa ordens e salva logs automaticamente.

  const handleSetConfig = (timeframe: number, candles: number) => {
    if (ws.current) {
      ws.current.send(JSON.stringify({ command: "SET_CONFIG", timeframe, candles }));
      setActiveConfig({ timeframe, candles });
    }
  };

  const handleToggleAutoOptimize = () => {
    if (ws.current) {
      const newState = !autoOptimize;
      ws.current.send(JSON.stringify({ command: "TOGGLE_AUTO_OPTIMIZE", enabled: newState }));
      setAutoOptimize(newState);
    }
  };

  const handleChangeSymbol = (symbol: string) => {
    if (ws.current) {
      ws.current.send(JSON.stringify({ command: "WATCH_SYMBOL", symbol }));
      setActiveSymbol(symbol);
    }
  };

  return (
    <div className="layout-container">
      {/* Esquerda: Agente RAG e Controles */}
      <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
        
        <header>
          <h1>Cockpit de Decisão</h1>
          <p style={{ opacity: 0.6 }}>Análise Quantitativa + IA</p>
        </header>

        {/* Seletor de Ativo */}
        <div className="glass" style={{ padding: "16px", display: "flex", flexDirection: "column", gap: "10px" }}>
          <h3 style={{ margin: 0, fontSize: "1rem", color: "var(--accent)" }}>Ativo Operacional</h3>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            {["R_10", "R_25", "R_50", "R_75", "R_100", "1HZ10V", "1HZ25V", "1HZ50V", "1HZ75V", "1HZ100V", "RDBEAR", "RDBULL"].map(sym => {
              let label = sym;
              if (sym.startsWith("R_")) label = sym.replace("R_", "Vol ");
              if (sym.startsWith("1HZ")) {
                label = sym.replace("1HZ", "Vol ");
                label = label.slice(0, -1) + " (1s)";
              }
              if (sym === "RDBEAR") label = "Bear";
              if (sym === "RDBULL") label = "Bull";
              
              return (
                <button
                  key={sym}
                  onClick={() => handleChangeSymbol(sym)}
                  style={{
                    flex: "1 1 20%",
                    padding: "6px 8px",
                    background: activeSymbol === sym ? "var(--accent)" : "rgba(255,255,255,0.05)",
                    color: activeSymbol === sym ? "#000" : "#fff",
                    border: `1px solid ${activeSymbol === sym ? "var(--accent)" : "rgba(255,255,255,0.1)"}`,
                    borderRadius: "6px",
                    cursor: "pointer",
                    fontSize: "0.85rem",
                    fontWeight: activeSymbol === sym ? "bold" : "normal",
                    transition: "all 0.2s"
                  }}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="glass" style={{ flex: 1, padding: "20px", display: "flex", flexDirection: "column" }}>
          <h3 style={{ marginBottom: "16px", color: "var(--accent)" }}>🧠 Análise da IA</h3>
          <div style={{ 
            flex: 1, 
            background: "rgba(0,0,0,0.3)", 
            borderRadius: "8px", 
            padding: "16px", 
            overflowY: "auto",
            fontFamily: "var(--font-geist-mono), monospace",
            fontSize: "0.95rem",
            lineHeight: "1.6",
            whiteSpace: "pre-wrap"
          }}>
            {agentMessage ? (
              <p>{agentMessage}</p>
            ) : (
              <p style={{ opacity: 0.4 }}>Aguardando formação de sinais no mercado...</p>
            )}
          </div>
        </div>

        <div className="glass" style={{ padding: "20px", overflowX: "auto" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
            <h3 style={{ margin: 0 }}>📊 Catalogador de Sinais</h3>
            <button 
              onClick={handleToggleAutoOptimize}
              style={{ 
                padding: "8px 16px", 
                borderRadius: "20px", 
                border: "none",
                background: autoOptimize ? "var(--accent)" : "rgba(255,255,255,0.1)",
                color: "white",
                fontWeight: "bold",
                cursor: "pointer",
                transition: "0.2s",
                display: "flex",
                alignItems: "center",
                gap: "8px"
              }}
            >
              {autoOptimize ? "🧬 Mutante Ativo" : "🔧 Modo Manual"}
            </button>
          </div>
          <p style={{ fontSize: "0.85rem", opacity: 0.7, marginBottom: "16px" }}>
            {autoOptimize ? 
              "O robô está varrendo a tabela e se reconfigurando sozinho a cada vela fechada!"
              : "Clique no card para alterar a estratégia base do robô autônomo."
            }
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "8px", minWidth: "500px" }}>
            <div style={{ fontWeight: "bold", opacity: 0.5 }}>Timeframe</div>
            <div style={{ fontWeight: "bold", opacity: 0.5, textAlign: "center" }}>3 Velas</div>
            <div style={{ fontWeight: "bold", opacity: 0.5, textAlign: "center" }}>5 Velas</div>
            <div style={{ fontWeight: "bold", opacity: 0.5, textAlign: "center" }}>7 Velas</div>
            <div style={{ fontWeight: "bold", opacity: 0.5, textAlign: "center" }}>9 Velas</div>
            
            {[60, 300, 900].map(tf => (
              <React.Fragment key={tf}>
                <div style={{ display: "flex", alignItems: "center", fontWeight: "bold" }}>
                  M{tf / 60}
                </div>
                {[3, 5, 7, 9].map(c => {
                  const cat = (catalog || []).find(x => x.timeframe === tf && x.candles === c);
                  const winRate = cat ? cat.stats.win_rate : 0;
                  const isManualActive = activeConfig.timeframe === tf && activeConfig.candles === c;
                  const isActive = autoOptimize ? (winRate >= 80) : isManualActive;
                  return (
                    <div 
                      key={`${tf}-${c}`} 
                      onClick={() => !autoOptimize && handleSetConfig(tf, c)}
                      style={{ 
                        padding: "8px", 
                        borderRadius: "4px", 
                        textAlign: "center",
                        cursor: autoOptimize ? "not-allowed" : "pointer",
                        opacity: autoOptimize && !isActive ? 0.4 : 1,
                        background: winRate >= 80 ? "rgba(38, 166, 154, 0.2)" : (winRate >= 60 ? "rgba(255, 255, 255, 0.1)" : "rgba(239, 83, 80, 0.2)"),
                        border: isActive ? "2px solid var(--accent)" : "2px solid transparent",
                        transition: "all 0.2s"
                      }}
                    >
                      <div style={{ fontWeight: "bold", color: winRate >= 80 ? "var(--success)" : (winRate < 60 ? "var(--danger)" : "white") }}>
                        {winRate}%
                      </div>
                      <div style={{ fontSize: "0.75rem", opacity: 0.6 }}>
                        {cat ? `${cat.stats.wins}W / ${cat.stats.losses}L` : "--"}
                      </div>
                    </div>
                  );
                })}
              </React.Fragment>
            ))}
          </div>
        </div>
        
        {/* Status de Notícias (Calendário Econômico) */}
        {newsStatus && (
          <div style={{ marginBottom: "20px", padding: "12px 20px", background: newsStatus.safe ? "rgba(38, 166, 154, 0.15)" : "rgba(239, 83, 80, 0.2)", borderRadius: "8px", border: `1px solid ${newsStatus.safe ? "var(--success)" : "var(--danger)"}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <span style={{ fontSize: "1.5rem" }}>{newsStatus.safe ? "🟢" : "🔴"}</span>
              <div>
                <h4 style={{ margin: 0, color: newsStatus.safe ? "var(--success)" : "var(--danger)" }}>
                  {newsStatus.safe ? "Mercado Seguro para Operar" : "ZONA DE NOTÍCIA (Pausa Ativa)"}
                </h4>
                <p style={{ margin: 0, fontSize: "0.85rem", opacity: 0.8 }}>
                  {newsStatus.reason}
                </p>
              </div>
            </div>
            {newsStatus.next_event && (
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: "0.7rem", opacity: 0.6, textTransform: "uppercase" }}>Próxima Notícia (3 Touros)</div>
                <div style={{ fontWeight: "bold" }}>{newsStatus.next_event.name}</div>
                <div style={{ fontSize: "0.85rem", opacity: 0.8 }}>Impacto: {newsStatus.next_event.impact}</div>
              </div>
            )}
          </div>
        )}

        {/* Módulo Simulador Financeiro (Movido para dentro da coluna esquerda) */}
        {simulatorState && (
        <div style={{ display: "flex", gap: "20px" }}>
          <div className="glass" style={{ padding: "20px", flex: 1 }}>
            <h3 style={{ marginBottom: "16px", color: "var(--accent)" }}>💳 Conta (Deste Ativo)</h3>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: "8px" }}>
              <span style={{ fontSize: "0.9rem", opacity: 0.7 }}>Saldo Virtual</span>
              <span style={{ fontSize: "1.5rem", fontWeight: "bold" }}>${simulatorState.balance.toFixed(2)}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px", background: "rgba(0,0,0,0.2)", borderRadius: "8px" }}>
              <span style={{ fontSize: "0.85rem" }}>Lucro/Prejuízo (PnL)</span>
              <span style={{ fontWeight: "bold", color: simulatorState.pnl >= 0 ? "var(--success)" : "var(--danger)" }}>
                {simulatorState.pnl >= 0 ? "+" : ""}${simulatorState.pnl.toFixed(2)}
              </span>
            </div>
            {simulatorState.risk && (
              <div style={{ marginTop: "16px", padding: "12px", background: "rgba(0,0,0,0.3)", borderRadius: "8px", fontSize: "0.85rem" }}>
                <div style={{ marginBottom: "8px", fontWeight: "bold", color: "var(--accent)" }}>🛡️ Gestão de Risco</div>
                
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
                  <span style={{ opacity: 0.7 }}>Nível de Gale</span>
                  <span>{simulatorState.risk.consecutive_losses === 0 ? "Operação Base" : `Gale ${simulatorState.risk.consecutive_losses}`} / {simulatorState.risk.max_gale}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
                  <span style={{ opacity: 0.7 }}>Próxima Entrada</span>
                  <span style={{ fontWeight: "bold" }}>${simulatorState.risk.next_stake.toFixed(2)}</span>
                </div>
                
                {/* Stop Gain Progress */}
                <div style={{ marginTop: "12px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.7rem", opacity: 0.8, marginBottom: "4px" }}>
                    <span>Stop Gain (${simulatorState.risk.stop_gain})</span>
                    <span>{Math.min(100, Math.max(0, (simulatorState.pnl / simulatorState.risk.stop_gain) * 100)).toFixed(0)}%</span>
                  </div>
                  <div style={{ width: "100%", height: "6px", background: "rgba(255,255,255,0.1)", borderRadius: "3px", overflow: "hidden" }}>
                    <div style={{ width: `${Math.min(100, Math.max(0, (simulatorState.pnl / simulatorState.risk.stop_gain) * 100))}%`, height: "100%", background: "var(--success)" }}></div>
                  </div>
                </div>
                
                {/* Stop Loss Progress */}
                <div style={{ marginTop: "8px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.7rem", opacity: 0.8, marginBottom: "4px" }}>
                    <span>Stop Loss (-${simulatorState.risk.stop_loss})</span>
                    <span>{Math.min(100, Math.max(0, (simulatorState.pnl / -simulatorState.risk.stop_loss) * 100)).toFixed(0)}%</span>
                  </div>
                  <div style={{ width: "100%", height: "6px", background: "rgba(255,255,255,0.1)", borderRadius: "3px", overflow: "hidden" }}>
                    <div style={{ width: `${Math.min(100, Math.max(0, (simulatorState.pnl / -simulatorState.risk.stop_loss) * 100))}%`, height: "100%", background: "var(--danger)" }}></div>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="glass" style={{ padding: "20px", flex: 2, overflowY: "auto", maxHeight: "250px" }}>
            <h3 style={{ marginBottom: "16px" }}>📋 Últimas Operações</h3>
            {simulatorState.pending.length > 0 && (
              <div style={{ marginBottom: "16px" }}>
                <strong style={{ fontSize: "0.85rem", opacity: 0.7 }}>PENDENTES</strong>
                {simulatorState.pending.map((t: any) => (
                  <div key={t.id} style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid rgba(255,255,255,0.1)" }}>
                    <span>⏳ {t.direction} <span style={{fontSize:'0.7rem', opacity:0.5}}>[{t.strategy_info || "N/A"}]</span></span>
                    <span style={{ opacity: 0.7 }}>${t.stake.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            )}
            
            <div>
              <strong style={{ fontSize: "0.85rem", opacity: 0.7 }}>HISTÓRICO</strong>
              {simulatorState.history.length === 0 ? (
                <p style={{ opacity: 0.5, fontSize: "0.85rem" }}>Nenhuma operação finalizada ainda.</p>
              ) : (
                simulatorState.history.map((t: any) => (
                  <div key={t.id} style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid rgba(255,255,255,0.1)" }}>
                    <span style={{ color: t.status === "WIN" ? "var(--success)" : (t.status === "LOSS" ? "var(--danger)" : "white") }}>
                      {t.status === "WIN" ? "📈" : (t.status === "LOSS" ? "📉" : "⚖️")} {t.direction} <span style={{fontSize:'0.7rem', opacity:0.5}}>[{t.strategy_info || "N/A"}]</span>
                    </span>
                    <span style={{ fontWeight: "bold", color: t.status === "WIN" ? "var(--success)" : (t.status === "LOSS" ? "var(--danger)" : "white") }}>
                      {t.profit >= 0 ? "+" : ""}${t.profit.toFixed(2)}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
        )}
      </div>

      {/* Direita: Market Feed */}
      <div className="glass" style={{ padding: "20px", display: "flex", flexDirection: "column" }}>
        <h3 style={{ marginBottom: "16px", display: "flex", alignItems: "center" }}>
          <span className="live-indicator"></span> 
          Mercado Ao Vivo
        </h3>
        
        <div style={{ marginBottom: "24px" }}>
          <div style={{ fontSize: "0.8rem", opacity: 0.6, textTransform: "uppercase" }}>Volatility 100 (1s)</div>
          <div style={{ fontSize: "2.8rem", fontWeight: "bold" }}>
            {liveData.quote > 0 ? liveData.quote.toFixed(2) : "0.00"}
          </div>
        </div>

        <h4>Vela Atual (M{activeConfig.timeframe / 60})</h4>
        <div className="feed-section" style={{ marginTop: "12px" }}>
          {liveData.candle ? (
            <div className={`candle-card ${liveData.candle.close >= liveData.candle.open ? 'candle-bullish' : 'candle-bearish'}`}>
              <div>
                <div className="badge" style={{ 
                  background: liveData.candle.close >= liveData.candle.open ? 'var(--success-glow)' : 'var(--danger-glow)',
                  color: liveData.candle.close >= liveData.candle.open ? 'var(--bullish)' : 'var(--bearish)'
                }}>
                  {liveData.candle.close >= liveData.candle.open ? 'BULLISH' : 'BEARISH'}
                </div>
                <div style={{ marginTop: "8px", fontSize: "0.95rem" }}>O: {liveData.candle.open.toFixed(2)}</div>
                <div style={{ fontSize: "0.95rem" }}>C: {liveData.candle.close.toFixed(2)}</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: "0.95rem" }}>H: {liveData.candle.high.toFixed(2)}</div>
                <div style={{ fontSize: "0.95rem" }}>L: {liveData.candle.low.toFixed(2)}</div>
              </div>
            </div>
          ) : (
            <p style={{ opacity: 0.5, fontSize: "0.9rem" }}>Aguardando sincronização da Deriv...</p>
          )}
        </div>
        <div 
          ref={chartContainerRef} 
          style={{ width: "100%", height: "250px", marginTop: "24px" }} 
        />
      </div>
    </div>
  );
}
