import os
import sys

# Ensure project root is in path so 'app' and 'modules' can be imported if they exist
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from modules.writer.writer_engine import handle_write_command

commands = [
    "Write an essay on Artificial Intelligence",
    "Write a story about time travel",
    "Write notes on DBMS normalization",
    "Write a letter to principal for leave",
    "Write something about climate change"
]

for cmd in commands:
    print(f"\nRunning: {cmd}")
    handle_write_command(cmd)
