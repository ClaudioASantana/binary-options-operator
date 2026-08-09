"use client";

import { useEffect, useState, useRef } from "react";

export default function Home() {
  const [liveData, setLiveData] = useState<any>({ quote: 0, candle: null });
  const [signal, setSignal] = useState<any>(null);
  const [agentMessage, setAgentMessage] = useState<string>("");
  const ws = useRef<WebSocket | null>(null);

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
      }
    };

    return () => {
      if (ws.current) ws.current.close();
    };
  }, []);

  const handleApprove = () => {
    if (ws.current) {
      ws.current.send(JSON.stringify({ command: "APPROVE_TRADE" }));
      alert("Trade Aprovado e enviado para o robô!");
      setSignal(null);
      setAgentMessage("");
    }
  };

  const handleIgnore = () => {
    if (ws.current) {
      ws.current.send(JSON.stringify({ command: "IGNORE_TRADE" }));
      setSignal(null);
      setAgentMessage("");
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

        <div className="glass" style={{ padding: "20px" }}>
          <h3 style={{ marginBottom: "16px" }}>Ação de Trade</h3>
          <div style={{ display: "flex", gap: "12px" }}>
            <button 
              className="btn btn-success" 
              style={{ flex: 1 }}
              disabled={!signal}
              onClick={handleApprove}
            >
              Aprovar Trade
            </button>
            <button 
              className="btn btn-danger" 
              style={{ flex: 1 }}
              disabled={!signal}
              onClick={handleIgnore}
            >
              Ignorar
            </button>
          </div>
        </div>
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

        <h4>Vela Atual (M5)</h4>
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
      </div>
    </div>
  );
}
