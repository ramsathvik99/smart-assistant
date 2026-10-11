# ======================================================
# legacy/actions.py  — Nova Action Layer
# Clean, audited, production-grade implementation.
# ======================================================

import os
import sys
import re
import time
import shutil
import webbrowser
import subprocess
import psutil
import ctypes


def speak(text: str, **kwargs) -> None:
    """Route speech through the TTS coordinator (COMMAND priority).

    This shim replaces the old module-level `from legacy.tts import speak`
    so that actions.py respects the coordinator's priority queue.
    Import is lazy to avoid initialization-order problems.
    """
    try:
        from extensions.system.tts_coordinator import speak as _coord_speak, TTSPriority
        _coord_speak(text, priority=TTSPriority.COMMAND)
    except Exception:
        try:
            from legacy.tts import speak as _direct_speak
            _direct_speak(text, **kwargs)
        except Exception:
            try:
                from instance.config import settings as _cfg
                _asst = _cfg.get_assistant_name() or "Assistant"
            except Exception:
                _asst = "Assistant"
            print(f"{_asst}: {text}")

try:
    import pyautogui
except (ImportError, Exception):
    pyautogui = None



# ======================================================
# KEYBOARD & TEXT ACTIONS
# ======================================================

def type_text(text):
    """Type text using simulated keyboard input."""
    if not pyautogui:
        speak("I cannot type because PyAutoGUI is missing.")
        return "PyAutoGUI not available."
    time.sleep(0.5)
    pyautogui.write(text, interval=0.01)
    return f"Typed: {text}"


def press_key(key_name):
    """Press a specific key (e.g. 'enter')."""
    if not pyautogui:
        return "PyAutoGUI not available."
    time.sleep(0.2)
    pyautogui.press(key_name)
    return f"Pressed {key_name}."


# ======================================================
# WEB ACTIONS
# ======================================================

def open_website(url, name=None, confirm=True):
    """Open a website cleanly in the default browser (no CMD flash)."""
    site_name = name or url

    try:
        speak(f"Opening {site_name}.")
        webbrowser.get().open_new_tab(url)

        # Set Global Context via Canonical ContextManager
        try:
            from extensions.context_manager import get_manager
            ctx = get_manager()
            ctx.set_active_context("browser", site_name.lower(), await_confirm=confirm)
            print(f"[COMMAND INTELLIGENCE] Set browser context: {site_name.lower()}")
        except Exception as e:
            print(f"[CONTEXT ERROR] Failed to set browser context: {e}")

        if confirm:
            time.sleep(0.5)
            speak(f"{site_name} is now open. Do you want to do something here?")

        return f"Opened {site_name}."

    except Exception as e:
        print("[Website Error]", e)
        msg = f"Sorry, I couldn't open {site_name}."
        speak(msg)
        return msg


def search_web(query):
    """Perform a Google search using the user's query."""
    import urllib.parse, webbrowser
    from legacy.tts import speak

    q = query.lower().strip()

    # ✅ ONLY trigger search if explicit phrase exists
    if "search for" in q:
        # extract ONLY after 'search for'
        search_part = q.split("search for", 1)[1].strip()

        # ❌ if nothing after → DO NOT SEARCH
        if not search_part:
            webbrowser.open("https://www.google.com")
            speak("Opening Google")
            return "No search query provided, opened Google."

        encoded = urllib.parse.quote(search_part)
        url = f"https://www.google.com/search?q={encoded}"
        
        speak("Searching on Google")
        webbrowser.open(url)
        return f"Searching for {search_part}."
    else:
        # ✅ SAFE DEFAULT
        webbrowser.open("https://www.google.com")
        speak("Opening Google")
        return "Opening Google"


# ======================================================

def _normalize_name(name):
    """Remove spaces and special characters for robust partial matching."""
    return re.sub(r'[^a-z0-9]', '', name.lower())

def open_app(name):
    """Open any installed Windows application truthfully using smart_opener."""
    from extensions.system.smart_opener import smart_opener

    raw_name = name.strip()
    name_clean = raw_name.lower()

    if name_clean in ["camera", "webcam"]:
        return open_camera()

    # Delegate application discovery and launching to authoritative smart_opener
    result = smart_opener.smart_open(name_clean)

    if isinstance(result, dict):
        success = result.get("success", False)
        display_name = result.get("display_name") or raw_name
        message = result.get("message")

        if success:
            # Set Command Intelligence Context for successful app opens via canonical ContextManager
            try:
                from extensions.context_manager import get_manager
                ctx = get_manager()
                ctx.set_active_context("app", display_name.lower(), await_confirm=False)
                print(f"[COMMAND INTELLIGENCE] Set app context: {display_name.lower()}")
            except Exception as e:
                print(f"[COMMAND INTELLIGENCE CONTEXT] Failed to set app context: {e}")

            return f"Opened {display_name}."
        else:
            return message or f"Could not find '{raw_name}' on your system."

    return str(result)


def open_camera():
    """Open the Windows Camera app truthfully via smart_opener."""
    from extensions.system.smart_opener import smart_opener
    speak("Opening camera.")
    result = smart_opener.smart_open("camera")
    if isinstance(result, dict) and result.get("success", False):
        try:
            from extensions.context_manager import get_manager
            get_manager().set_active_context("app", "camera", await_confirm=False)
        except Exception as e:
            print(f"[CONTEXT ERROR] Could not set camera context: {e}")
        return "Opened Camera."
    else:
        msg = "Could not open camera."
        speak(msg)
        return msg


# ======================================================
# BROWSER TAB CONTROLS
# ======================================================

def close_tab(count=1):
    """Close browser tabs using Ctrl+W."""
    if not pyautogui:
        speak("Tab control not available.")
        return "PyAutoGUI not available."

    speak(f"Closing {count} tab{'s' if count > 1 else ''}.")
    for _ in range(count):
        pyautogui.hotkey('ctrl', 'w')
        time.sleep(0.3)
    return f"Closed {count} tab{'s' if count > 1 else ''}."


def new_tab():
    """Open a new browser tab using Ctrl+T."""
    if not pyautogui:
        speak("Tab control not available.")
        return "PyAutoGUI not available."

    speak("Opening new tab.")
    pyautogui.hotkey('ctrl', 't')
    return "Opened new tab."


def switch_tab():
    """Switch to the next browser tab using Ctrl+Tab."""
    if not pyautogui:
        speak("Tab control not available.")
        return "PyAutoGUI not available."

    pyautogui.hotkey('ctrl', 'tab')
    return "Switched tab."


# ======================================================
# SYSTEM ACTIONS
# ======================================================

def system_action(action):
    """Perform basic system control actions via safe OS gateway."""
    action = action.lower()
    from legacy.skills_utilities import shutdown_system, restart_system, lock_system, sleep_system

    if action == "shutdown":
        return shutdown_system() or "Shutting down system."
    elif action == "restart":
        return restart_system() or "Restarting system."
    elif action == "lock":
        return lock_system() or "System locked."
    elif action in ["sleep", "suspend", "standby"]:
        return sleep_system() or "Putting system to sleep."
    else:
        speak("I'm not sure which system action you meant.")
        return "Unknown system action."


# ======================================================
# CLOSE APP
# ======================================================

def close_app(app_name):
    """Close a running application by name. Always returns a string."""
    app_name = app_name.lower().strip()
    app_name = re.sub(r'\s+', ' ', app_name)

    speak(f"Closing {app_name}.")

    # ---- Special handling for WhatsApp (Store/Desktop) ----
    if "whatsapp" in app_name:
        terminated = False
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if 'whatsapp' in proc.info['name'].lower():
                        proc.terminate()
                        terminated = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass

        if not terminated:
            subprocess.run(
                ['taskkill', '/F', '/IM', 'WhatsApp.exe'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
            )
            subprocess.run(
                ['taskkill', '/F', '/FI', 'WINDOWTITLE eq WhatsApp*'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
            )

        speak("WhatsApp closed.")
        return "WhatsApp closed."

    # ---- Generic Browser handling ----
    if app_name in ["browser", "the browser", "web browser", "internet", "default browser"]:
        browser_exes = ["chrome.exe", "msedge.exe", "brave.exe", "firefox.exe", "opera.exe"]
        closed_any = False
        for exe in browser_exes:
            try:
                subprocess.run(["taskkill", "/F", "/IM", exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                closed_any = True
            except Exception:
                pass
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                pn = (proc.info['name'] or "").lower()
                if any(b in pn for b in ["chrome", "msedge", "brave", "firefox", "opera"]):
                    proc.kill()
                    closed_any = True
            except Exception:
                pass
        if closed_any:
            speak("Browser closed.")
            return "Browser closed."
        else:
            return "No running browser was found."

    # ---- Process name map ----
    process_map = {
        "chrome":              ["chrome.exe"],
        "google chrome":       ["chrome.exe"],
        "brave":               ["brave.exe"],
        "brave browser":       ["brave.exe"],
        "notepad":             ["notepad.exe", "Notepad.exe"],
        "calculator":          ["calc.exe", "CalculatorApp.exe", "Calculator.exe"],
        "calc":                ["calc.exe", "CalculatorApp.exe", "Calculator.exe"],
        "paint":               ["mspaint.exe", "Paint.exe"],
        "mspaint":             ["mspaint.exe", "Paint.exe"],
        "vscode":              ["Code.exe", "code.exe"],
        "vs code":             ["Code.exe", "code.exe"],
        "visual studio code":  ["Code.exe", "code.exe"],
        "code":                ["Code.exe", "code.exe"],
        "vlc":                 ["vlc.exe"],
        "vlc media player":    ["vlc.exe"],
        "camera":              ["WindowsCamera.exe", "ApplicationFrameHost.exe"],
        "spotify":             ["Spotify.exe"],
        "discord":             ["Discord.exe"],
        "telegram":            ["Telegram.exe"],
        "telegram desktop":    ["Telegram.exe"],
        "edge":                ["msedge.exe"],
        "microsoft edge":      ["msedge.exe"],
        "ms edge":             ["msedge.exe"],
        "firefox":             ["firefox.exe"],
        "mozilla firefox":     ["firefox.exe"],
        "opera":               ["opera.exe"],
        "opera browser":       ["opera.exe"],
        "settings":            ["SystemSettings.exe"],
        "task manager":        ["taskmgr.exe", "Taskmgr.exe"],
        "taskmgr":             ["taskmgr.exe", "Taskmgr.exe"],
        "cmd":                 ["cmd.exe"],
        "terminal":            ["WindowsTerminal.exe", "wt.exe"],
        "explorer":            ["explorer.exe"],
        "file explorer":       ["explorer.exe"],
        "postman":             ["Postman.exe"],
        "steam":               ["steam.exe"],
        "anydesk":             ["AnyDesk.exe"],
        "zoom":                ["Zoom.exe"],
        "cursor":              ["Cursor.exe"],
    }

    candidate_exes = list(process_map.get(app_name, []))
    if not candidate_exes:
        try:
            from extensions.system.smart_opener import smart_opener
            resolved = smart_opener.resolve_detailed(app_name)
            if resolved:
                target_path = resolved[1]
                if target_path.lower().endswith(".exe"):
                    candidate_exes.append(os.path.basename(target_path))
                elif target_path.lower().endswith(".lnk"):
                    base = os.path.splitext(os.path.basename(target_path))[0]
                    candidate_exes.append(f"{base}.exe")
        except Exception:
            pass
    if not candidate_exes:
        candidate_exes.append(app_name + ".exe")
        candidate_exes.append(app_name.replace(" ", "") + ".exe")

    closed_any = False

    for exe in candidate_exes:
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", exe],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True
            )
            closed_any = True
        except subprocess.CalledProcessError:
            pass

    # Fallback to psutil process search if not yet closed
    if not closed_any:
        try:
            clean_target = re.sub(r'[^a-z0-9]', '', app_name)
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    pname = (proc.info['name'] or "").lower()
                    pclean = re.sub(r'[^a-z0-9]', '', pname)
                    if any(ce.lower() == pname for ce in candidate_exes):
                        proc.kill()
                        closed_any = True
                    elif clean_target and (clean_target in pclean or pclean.startswith(clean_target)):
                        proc.kill()
                        closed_any = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass

    if closed_any:
        display_name = app_name.capitalize()
        speak(f"{display_name} closed.")
        
        # Clear context via canonical ContextManager
        try:
            from extensions.context_manager import get_manager
            ctx = get_manager()
            if ctx.get_active_context().get("name") == app_name.lower():
                ctx.clear_context()
                print(f"[COMMAND INTELLIGENCE] Cleared context for {app_name}")
        except Exception as e:
            print(f"[CONTEXT ERROR] Failed to clear context for {app_name}: {e}")
        return f"{display_name} closed."
    else:
        display_name = app_name.capitalize()
        msg = f"I could not find or close {display_name}."
        speak(msg)
        return msg


# ======================================================
# SYSTEM VOLUME CONTROL (Windows Native)
# ======================================================

def increase_volume():
    """Increase system volume by approximately 10%."""
    try:
        from legacy.tts import speak
        for _ in range(5):  # 5 key presses ≈ 10%
            ctypes.windll.user32.keybd_event(0xAF, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0xAF, 0, 2, 0)
        speak("Volume increased by 10 percent.")
        return "Volume increased by 10 percent."
    except Exception as e:
        print("[Volume Error]", e)
        return "Volume increase failed."


def decrease_volume():
    """Decrease system volume by approximately 10%."""
    try:
        from legacy.tts import speak
        for _ in range(5):  # 5 key presses ≈ 10%
            ctypes.windll.user32.keybd_event(0xAE, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0xAE, 0, 2, 0)
        speak("Volume decreased by 10 percent.")
        return "Volume decreased by 10 percent."
    except Exception as e:
        print("[Volume Error]", e)
        return "Volume decrease failed."

def toggle_mute():
    """Toggle system mute using VK_VOLUME_MUTE (0xAD)."""
    try:
        from legacy.tts import speak
        ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xAD, 0, 2, 0)
        speak("Volume toggled.")
        return "Volume toggled."
    except Exception as e:
        print("[Volume Error]", e)
        return "Mute failed."


# ======================================================
# NOVA SHUTDOWN
# ======================================================

def shutdown_assistant():
    """Terminate all Assistant process components."""
    targets = [
        "assistant.py",
        "main.py",
    ]

    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = " ".join(p.info['cmdline']) if p.info['cmdline'] else ""
            for t in targets:
                if t in cmd and p.info['pid'] != os.getpid():
                    print(f"Terminating {t} (PID {p.info['pid']})")
                    p.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Expected for some processes
            pass
        except Exception as e:
            print(f"[SHUTDOWN] Error terminating process: {e}")
