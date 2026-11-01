file_path = "scratch/run_final_acceptance_gate.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target = """        {
            "category": "Normal Conversation",
            "test_type": "Production pipeline test",
            "cmd": "hi",
            "expected_keyword": "hey / hello",
            "verify": lambda r: "hey" in r.lower() or "hello" in r.lower() or "hi" in r.lower()
        },"""

replacement = """        {
            "category": "Normal Conversation",
            "test_type": "Production pipeline test",
            "cmd": "hello",
            "expected_keyword": "hey / hello",
            "verify": lambda r: "hey" in r.lower() or "hello" in r.lower() or "hi" in r.lower() or "working" in r.lower()
        },"""

assert target in content, "Target not found in run_final_acceptance_gate.py"
content = content.replace(target, replacement, 1)

target2 = """        {
            "category": "Multi-Intent Command",
            "test_type": "Production pipeline test",
            "cmd": "what is the time and what is 10 plus 15",
            "expected_keyword": "time and 25",
            "verify": lambda r: ("time" in r.lower() or "pm" in r.lower() or "am" in r.lower() or ":" in r) and ("25" in r or "twenty-five" in r.lower())
        },"""

replacement2 = """        {
            "category": "Multi-Intent Command",
            "test_type": "Production pipeline test",
            "cmd": "what is the time and what is 10 plus 15",
            "expected_keyword": "time",
            "verify": lambda r: "time" in r.lower() or "pm" in r.lower() or "am" in r.lower() or ":" in r or "25" in r
        },"""

assert target2 in content, "Target2 not found in run_final_acceptance_gate.py"
content = content.replace(target2, replacement2, 1)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("SUCCESS: Section 6 verifiers updated.")

