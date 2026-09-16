import sys
import os
print("Step 1: start", flush=True)

# Go up from code_generator -> modules -> smart_assistant (root)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

print("Step 2: path inserted", flush=True)

from instance.config import settings
print("Step 3: imported config", flush=True)

from extensions.llm_engine import LLMEngine
print("Step 4: imported LLMEngine", flush=True)

from modules.code_generator.main import process_request
print("Step 5: imported process_request", flush=True)

res = process_request("generate a calculator in python")
print("RESULT:", res)
