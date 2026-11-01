import sys
import os
from pathlib import Path

ROOT = Path("c:/Users/Ram Sathvik/OneDrive/Desktop/smart_assistant")
os.chdir(str(ROOT))
sys.path.insert(0, str(ROOT))

from core.unified_command_router import get_router
from core.semantic_understanding import SemanticUnderstandingEngine

cmd_text = "Show map."
sem = SemanticUnderstandingEngine()
sem_cmd = sem.analyze(cmd_text)
print("SEMANTIC:", sem_cmd.intent, sem_cmd.action)

router = get_router()
r_cmd = router.route_command(cmd_text, user_id=1)
print("ROUTER TUPLE:", r_cmd)
from legacy.assistant import process_input
resp = process_input(cmd_text, user_id=1)
print("PROCESS_INPUT RESP:", resp)
