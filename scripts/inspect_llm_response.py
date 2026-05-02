import json
from workflow.genai_agents import call_llm

raw_doc = {
    'raw_text': 'Revenue: 100000\nTotal payroll: 25000\nVAT: 7000\n',
    'raw_tables': [],
    'source_path': 'repository/finance/Finance_Report_Q1.pdf',
    'file_type': 'pdf',
}

system = (
    'You are a senior financial analyst and document classifier. '
    'Respond ONLY with valid JSON with keys: department, period, metrics, notes, missing_fields, confidence.'
)
user = json.dumps(raw_doc)

print('SYSTEM:', system)
print('USER:', user)
print('--- OUTPUT ---')
print(call_llm(system, user))
