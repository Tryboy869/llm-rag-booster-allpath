"""
Quickstart: use ragbooster as a plain Python library (no server, no Docker).

Requires an LLM endpoint. This example targets a local Ollama install
(https://ollama.com) so it runs with zero API keys and zero cost:
    ollama pull llama3
    ollama serve

Swap api_url/api_key/model for OpenAI, Groq, or Anthropic — see README.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ragbooster import RAGBooster

booster = RAGBooster(
    api_url="http://localhost:11434/api/chat",
    model="llama3",
)

booster.load_document("""
Guido van Rossum created Python and first released it in 1991.
It emphasizes readable, significantly-indented code.
Python is widely used for web backends, data science, and automation.
""", chunk_size=30, overlap=10)

result = booster.ask("Who created Python and when?")
print("Answer:", result["answer"])
print("Chunks used:", result["chunks_used"])
print("Sources:", result["sources"])

# Follow-up question re-uses conversation history automatically.
result2 = booster.ask("What is it commonly used for?")
print("\nFollow-up answer:", result2["answer"])
