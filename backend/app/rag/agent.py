import os
from pydantic import BaseModel
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from app.rag.vector import get_vector_store
from app.models.market import Signal, SignalType

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

system_prompt = """Você é o Copiloto Explicativo de um robô de opções binárias.
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

prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    ("human", "Explique este sinal e os riscos.")
])

agent_chain = prompt | llm | StrOutputParser()

def explain_signal(signal: Signal, risk_evaluation: str) -> str:
    if signal.type == SignalType.NONE:
        return "Nenhum sinal."
        
    query = f"Regras para sinal {signal.type.value} e limites de risco"
    docs = retriever.invoke(query)
    context = "\n\n".join([doc.page_content for doc in docs])
    
    response = agent_chain.invoke({
        "context": context,
        "signal_type": signal.type.value,
        "signal_reason": signal.reason,
        "risk_evaluation": risk_evaluation
    })
    
    return response

if __name__ == "__main__":
    test_signal = Signal(type=SignalType.CALL, reason="9 velas de baixa seguidas")
    print("Testando o Agente...")
    print(explain_signal(test_signal, "Risco OK. Gale permitido até nível 1."))
