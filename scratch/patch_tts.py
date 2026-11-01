import re

file_path = "legacy/tts.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target = """            if _active_sp_voice is not None:
                try:
                    # SVSFlagsAsync | SVSFPurgeBeforeSpeak (3) purges active hardware buffer
                    _active_sp_voice.Speak("", 3)
                except Exception:
                    pass
                _active_sp_voice = None"""

replacement = """            if _active_sp_voice is not None:
                try:
                    try:
                        import pythoncom
                        pythoncom.CoInitialize()
                    except Exception:
                        pass
                    # SVSFlagsAsync | SVSFPurgeBeforeSpeak (3) purges active hardware buffer
                    _active_sp_voice.Speak("", 3)
                except Exception:
                    pass
                _active_sp_voice = None"""

assert target in content, "Target not found in legacy/tts.py"
content = content.replace(target, replacement, 1)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("SUCCESS: legacy/tts.py patched with COM safety.")

