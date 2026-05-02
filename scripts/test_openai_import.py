import sys
import traceback

try:
    from openai import OpenAI
    print("IMPORT_OK")
    print(OpenAI)
except Exception:
    print("IMPORT_ERR")
    traceback.print_exc()
    sys.exit(2)
