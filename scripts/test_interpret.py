import os
import sys
sys.path.insert(0, r'C:\Users\Michael Okelola\Downloads\NigeriaCompliance')
from workflow.genai_agents import interpretation_agent

raw_doc = {
    'raw_text': 'Revenue: 100000\nTotal payroll: 25000\nVAT: 7000\n',
    'raw_tables': [],
    'source_path': 'repository/finance/Finance_Report_Q1.pdf',
    'file_type': 'pdf',
}

os.environ['OLLAMA_BASE_URL'] = 'http://localhost:11434'
os.environ['OLLAMA_MODEL'] = 'gemma3:4b'

print('Calling interpretation_agent()...')
res = interpretation_agent(raw_doc)
print('--- RESULT ---')
print(res)
