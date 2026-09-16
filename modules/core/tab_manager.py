import re
import time
import pyautogui
import psutil

def close_tabs(count=1):
    import pyautogui
    import time

    count = max(1, min(count, 20))  # safety limit

    for _ in range(count):
        pyautogui.hotkey('ctrl', 'w')
        time.sleep(0.2)

def open_tabs(count=1):
    import pyautogui
    import time

    count = max(1, min(count, 20))  # safety limit

    for _ in range(count):
        pyautogui.hotkey('ctrl', 't')
        time.sleep(0.2)

def close_by_name(name):
    import psutil
    import pyautogui

    name = name.lower()

    # Handle browser tabs (YouTube, etc.)
    if name in ["youtube", "google", "browser"]:
        pyautogui.hotkey('ctrl', 'w')
        return f"Closed {name} tab."

    # Handle applications
    terminated = False
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            proc_name = proc.info['name'].lower()

            if name in proc_name:
                proc.terminate()
                terminated = True

        except Exception:
            continue
    
    if terminated:
        return f"Closed {name}."
    return f"Could not find or close {name}."

def close_last_action():
    """Closes the last opened item from context."""
    try:
        from legacy.assistant import context
        if context:
            ctx = context.get_context()
            if ctx:
                val = ctx.get("value")
                typ = ctx.get("type")
                if typ == "browser":
                    pyautogui.hotkey('ctrl', 'w')
                    return f"Closed last browser item: {val}"
                elif typ == "system":
                    close_by_name(val)
                    return f"Closed last application: {val}"
        return "No recent action to close."
    except Exception as e:
        print(f"[SYSTEM ERROR] close_last_action: {e}")
        # Fallback: generic Alt+F4
        pyautogui.hotkey('alt', 'f4')
        return "Closed last window (fallback)."

def handle_tab_command(user_input: str) -> str:
    """
    Handles browser tab and application operations.
    Priority: 1. Count-based tabs, 2. Generic tabs, 3. Named close, 4. Last action.
    """
    user_input = user_input.lower().strip()
    
    # 1. & 2. TABS LOGIC
    match_tabs_count = re.search(r"close (\d+) tabs?", user_input)
    if match_tabs_count:
        count = int(match_tabs_count.group(1))
        close_tabs(count)
        return f"Closed {count} tab(s)."
    
    if "close tab" in user_input or "close tabs" in user_input:
        close_tabs(1)
        return "Closed 1 tab."
        
    match_open_tabs = re.search(r"open (\d+) tabs?", user_input)
    if match_open_tabs:
        count = int(match_open_tabs.group(1))
        open_tabs(count)
        return f"Opened {count} tab(s)."
        
    if "open tab" in user_input or "new tab" in user_input:
        open_tabs(1)
        return "Opened 1 tab."

    # 3. & 4. CLOSE BY NAME OR LAST ACTION
    match_close = re.search(r"close (.+)", user_input)
    if match_close:
        target = match_close.group(1).strip()

        # Ignore generic words
        if target not in ["tab", "tabs", "it", "that", "action"]:
            return close_by_name(target)

        elif target in ["tab", "tabs"]:
            close_tabs(1)
            return "Closed 1 tab."

        else:
            return close_last_action()

    return None
