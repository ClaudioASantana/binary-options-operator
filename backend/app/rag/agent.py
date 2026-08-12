"""
RAG Agent - Agente supervisor com revisao de sinais e explicacao.

Fornece:
- Explicacao de sinais baseada em documentacao (RAG)
- Revisao de risco com recomendacao
- Citacao de fontes documentais
"""
import os
from typing import List, Optional
from pydantic import BaseModel
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser, PydanticOutputParser
from app.rag.vector import get_vector_store
from app.models.market import Signal, SignalType, RiskEvaluation, AgentReview

load_dotenv()

BASE_URL = os.getenv("MANIFEST_BASE_URL")
API_KEY = os.getenv("MANIFEST_API_KEY")
MODEL_NAME = os.getenv("MANIFEST_MODEL_NAME")

llm = ChatOpenAI(
    openai_api_base=BASE_URL,
    openai_api_key=API_KEY,
    model=MODEL_NAME,
    temperature=0.0
)

# Initialize vector store connection
vector_store = get_vector_store()
retriever = vector_store.as_retriever(search_kwargs={"k": 3})

# Parser para saida estruturada
review_parser = PydanticOutputParser(pydantic_object=AgentReview)

system_prompt_review = """Você é o Agente Supervisor de um sistema de trading de opções binárias.
Sua função é revisar sinais gerados pelo motor matemático e fornecer uma recomendação estruturada.

Você NÃO decide se o trade será executado - isso é feito pelo Risk Engine (determinístico) e pelo operador (confirmação manual).
Sua função é:
1. Analisar o sinal com base na documentação
2. Classificar o nível de risco (low, medium, high)
3. Recomendar uma ação (execute, block, manual_confirm)
4. Citar fontes relevantes da documentação

Contexto recuperado da documentação:
{context}

Sinal do Strategy Engine:
- Tipo: {signal_type}
- Razão: {signal_reason}
- Símbolo: {symbol}

Avaliação do Risk Engine:
- Decisão: {risk_decision}
- Stake: {risk_stake}
- Gale Level: {risk_gale}
- Razão: {risk_reason}

Critérios para classificação de risco:
- LOW: Sinal claro, dentro de todos os limites, ativo de baixo risco, sem notícias de alto impacto
- MEDIUM: Sinal válido mas com alguma ressalva (gale > 0, ativo volátil, notícias moderadas)
- HIGH: Sinal com múltiplas ressalvas (gale alto,接近 limites diários, notícias de alto impacto, ativo muito volátil)

Critérios para recomendação:
- execute: Risco baixo, todos os critérios atendidos, operador experiente
- manual_confirm: Risco médio, ou conta real, ou gale > 0, ou operador iniciante
- block: Risco alto extremo, violação de regras documentais, condições de mercado anormais

Responda com uma estrutura JSON contendo:
- risk_level: "low", "medium", ou "high"
- recommendation: "execute", "block", ou "manual_confirm"
- summary: Explicação curta (1-2 frases)
- sources: Lista de fontes citadas (nomes de arquivos)
"""

prompt_review = ChatPromptTemplate.from_messages([
    ("system", system_prompt_review),
    ("human", "Revise este sinal e forneça sua recomendação estruturada.")
])

# Chain para revisao estruturada
review_chain = prompt_review | llm | review_parser

# Prompt para explicacao em texto (compatibilidade)
system_prompt_explain = """Você é o Copiloto Explicativo de um robô de opções binárias.
Sua função não é decidir se o trade deve ser feito, pois o motor matemático (cockpit) já fez isso de forma determinística.
Sua função é explicar para o usuário POR QUE este trade faz sentido de acordo com as regras da estratégia.

Contexto recuperado da nossa documentação oficial:
{context}

Sinal gerado pelo motor matemático:
- Tipo: {signal_type}
- Razão matemática: {signal_reason}
- Avaliação de Risco prévia: {risk_evaluation}

Dê uma explicação amigável e curta (máximo 2 parágrafos) justificando este sinal com base na documentação. 
Fale como se você estivesse do lado do operador. Destaque alertas de risco se existirem."""

prompt_explain = ChatPromptTemplate.from_messages([
    ("system", system_prompt_explain),
    ("human", "Explique este sinal e os riscos.")
])

agent_explain_chain = prompt_explain | llm | StrOutputParser()


class RagAgentService:
    """
    Servico de agente RAG para revisao de sinais.
    
    Uso:
        agent = RagAgentService()
        review = agent.review_signal(signal, risk_evaluation)
    """
    
    def __init__(self):
        self.vector_store = vector_store
        self.retriever = retriever
    
    def _retrieve_context(self, query: str) -> tuple[str, List[str]]:
        """
        Recupera contexto relevante e retorna fontes.
        
        Returns:
            tuple[str, List[str]]: (context_text, source_filenames)
        """
        docs = self.retriever.invoke(query)
        context_parts = []
        sources = []
        
        for doc in docs:
            context_parts.append(doc.page_content)
            # Extrair nome do arquivo dos metadados se disponivel
            if "source" in doc.metadata:
                sources.append(os.path.basename(doc.metadata["source"]))
            elif "filename" in doc.metadata:
                sources.append(os.path.basename(doc.metadata["filename"]))
        
        return "\n\n".join(context_parts), sources
    
    def review_signal(
        self,
        signal: Signal,
        risk_evaluation: RiskEvaluation,
        symbol: str = "",
    ) -> AgentReview:
        """
        Revisa um sinal e retorna recomendacao estruturada.
        
        Args:
            signal: Sinal do Strategy Engine
            risk_evaluation: Avaliacao do Risk Engine
            symbol: Simbolo do ativo (opcional)
        
        Returns:
            AgentReview com classificacao de risco e recomendacao
        """
        if signal.type == SignalType.NONE:
            return AgentReview(
                risk_level="low",
                recommendation="block",
                summary="Nenhum sinal para analisar",
                sources=[],
            )
        
        # Recuperar contexto relevante
        query = f"Regras para sinal {signal.type.value} {symbol} e limites de risco"
        context, sources = self._retrieve_context(query)
        
        try:
            response = review_chain.invoke({
                "context": context,
                "signal_type": signal.type.value,
                "signal_reason": signal.reason,
                "symbol": symbol,
                "risk_decision": risk_evaluation.decision.value,
                "risk_stake": risk_evaluation.stake,
                "risk_gale": risk_evaluation.gale_level,
                "risk_reason": risk_evaluation.reason,
            })
            
            # Garantir que sources nao esteja vazio se tivermos fontes recuperadas
            if not response.sources and sources:
                response.sources = sources[:3]  # Limitar a 3 fontes
            
            return response
            
        except Exception as e:
            # Fallback em caso de erro
            return AgentReview(
                risk_level="medium",
                recommendation="manual_confirm",
                summary=f"Revisão indisponível: {str(e)}",
                sources=sources[:3] if sources else [],
            )
    
    def explain_signal(self, signal: Signal, risk_evaluation: str) -> str:
        """
        Gera explicacao em texto para um sinal (compatibilidade).
        
        Args:
            signal: Sinal do Strategy Engine
            risk_evaluation: Texto com avaliacao de risco
        
        Returns:
            str: Explicacao em linguagem natural
        """
        if signal.type == SignalType.NONE:
            return "Nenhum sinal."
        
        query = f"Regras para sinal {signal.type.value} e limites de risco"
        context, _ = self._retrieve_context(query)
        
        try:
            response = agent_explain_chain.invoke({
                "context": context,
                "signal_type": signal.type.value,
                "signal_reason": signal.reason,
                "risk_evaluation": risk_evaluation,
            })
            return response
        except Exception as e:
            return f"Explicação indisponível: {str(e)}"


# Singleton global para compatibilidade
_agent_service: Optional[RagAgentService] = None


def get_agent_service() -> RagAgentService:
    """Obtem instancia singleton do RagAgentService."""
    global _agent_service
    if _agent_service is None:
        _agent_service = RagAgentService()
    return _agent_service


# Funcoes legacy para compatibilidade com codigo existente
def explain_signal(signal: Signal, risk_evaluation: str) -> str:
    """Funcao legacy para compatibilidade."""
    return get_agent_service().explain_signal(signal, risk_evaluation)


def review_signal(signal: Signal, risk_evaluation: RiskEvaluation, symbol: str = "") -> AgentReview:
    """Funcao wrapper para revisao de sinais."""
    return get_agent_service().review_signal(signal, risk_evaluation, symbol)


if __name__ == "__main__":
    # Teste do agente
    test_signal = Signal(type=SignalType.CALL, reason="9 velas de baixa seguidas", symbol="R_100")
    test_risk = RiskEvaluation(
        decision="APPROVED",
        reason="Risk constraints passed",
        stake=0.35,
        gale_level=0,
    )
    
    print("=" * 60)
    print("Testando RagAgentService...")
    print("=" * 60)
    
    agent = get_agent_service()
    
    print("\n1. Testando review_signal (estruturado):")
    print("-" * 40)
    review = agent.review_signal(test_signal, test_risk, "R_100")
    print(f"Risk Level: {review.risk_level}")
    print(f"Recommendation: {review.recommendation}")
    print(f"Summary: {review.summary}")
    print(f"Sources: {review.sources}")
    
    print("\n2. Testando explain_signal (texto):")
    print("-" * 40)
    explanation = agent.explain_signal(test_signal, "Risco OK. Gale permitido até nível 1.")
    print(explanation)
