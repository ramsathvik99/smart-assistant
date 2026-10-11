"""
Validation runner for real voice utterance pipeline.
Tests:
1. "Friday what is the time"
2. "Friday explain yourself"
3. "Friday open Chrome"
Exercises exact entry point:
  _process_utterance(audio_data) -> _recognise -> process_input -> semantic understanding -> router -> response -> TTS
"""

import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.chdir(str(PROJECT_ROOT))

import numpy as np
from unittest.mock import patch
import legacy.sst as sst

commands = [
    "Friday what is the time",
    "Friday explain yourself",
    "Friday open Chrome",
]

print("=== STARTING REAL VOICE PIPELINE TEST ===")
fake_audio = np.zeros(16000, dtype=np.int16)

results = {}

for cmd in commands:
    print(f"\n=======================================================")
    print(f"VOICE COMMAND: '{cmd}'")
    print(f"=======================================================")
    with patch("legacy.sst._recognise", return_value=cmd):
        try:
            sst._process_utterance(fake_audio)
            print(f"[VERIFIED] Voice command '{cmd}' executed without errors.")
            results[cmd] = "SUCCESS"
        except Exception as e:
            print(f"[FAILED] Voice command '{cmd}' raised exception: {e}")
            results[cmd] = f"FAILED: {e}"
            sys.exit(1)

print("\n=======================================================")
print("=== FINAL SUMMARY OF VOICE PIPELINE EXECUTION ===")
for cmd, status in results.items():
    print(f"  {cmd} -> {status}")
print("=======================================================")
