import requests
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langchain.agents import create_react_agent
from langchain import hub

ENDPOINT_URL = "https://ais-dev-dcea2b4uscqtl7gysisksn-340346620147.europe-west2.run.app/api/agent/context"

@tool
def get_agent_context() -> str:
    """Pobiera aktualne dane, wiedzę oraz strukturę bazy z zewnętrznego API context.
    Użyj tej funkcji, gdy potrzebujesz dostępu do bazy wiedzy agenta.
    """
    try:
        response = requests.get(ENDPOINT_URL, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        return f"Błąd pobierania danych z API: {e}"

llm = ChatOllama(
    model="llama3.1",  # Upewnij się, że ten model jest pobrany (ollama pull llama3.1)
    base_url="http://localhost:11434",
    temperature=0
)

tools = [get_agent_context]

# Poprawny import i inicjalizacja wg standardu LangChain
prompt = hub.pull("hwchase17/react")
agent = create_react_agent(llm, tools, prompt)

if __name__ == "__main__":
    print("Agent gotowy do użycia.")