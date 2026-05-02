import os
import sys
sys.path.insert(0, r'C:\Users\Michael Okelola\Downloads\NigeriaCompliance\workflow')

from genai_agents import call_llm

# Set env
os.environ['OLLAMA_BASE_URL'] = 'http://localhost:11434'
os.environ['OLLAMA_MODEL'] = 'mistral:latest'

# Simple test
system = "You are a helpful assistant."
user = "Say 'Hello World' and explain what it means."

result = call_llm(system, user)
print("Result:", repr(result))