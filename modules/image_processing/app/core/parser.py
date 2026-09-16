import re

class AssistantParser:
    """
    Smart natural language parser for the Assistant.
    Extracts input methods, file names, and sequential actions from flexible user text.
    """

    # ── Keywords & Mapping ──────────────────────────────────────────────
    
    # Input Methods
    INPUT_METHODS = {
        "camera": ["camera", "photo", "take a picture", "take a photo", "live", "capture cam"],
        "screenshot": ["screenshot", "screen", "capture screen", "read screen"],
        "upload": ["upload", "open", "file", "load", "from disk", "pick"]
    }

    # Action Mapping (Keywords → Dispatcher Operation)
    ACTION_PATTERNS = {
        "grayscale": ["grayscale", "black and white", "bw", "gray"],
        "blur": ["blur", "soften"],
        "brightness": ["brightness", "brighten", "lighten"],
        "contrast": ["contrast"],
        "edges": ["edge", "boundary", "outline", "contour"],
        "sharpen": ["sharpen", "clarify", "focus"],
        "sepia": ["sepia", "vintage", "old photo"],
        "invert": ["invert", "negative"],
        "threshold": ["threshold", "binary"],
        "denoise": ["denoise", "clean", "remove noise", "smooth"],
        "enhance": ["enhance", "improve", "fix quality", "auto-enhance"],
        "detect_objects": ["detect objects", "identify", "what is in", "recognize", "find objects"],
        "describe": ["describe", "scene", "explain", "what do you see"],
        "extract_text": ["text", "read", "ocr", "scan words", "what does it say"],
        "detect_faces": ["face", "people", "who is", "person"],
        "count_objects": ["count", "how many"]
    }

    # Regex for filenames (Excluding spaces to avoid greedy matches with keywords)
    FILE_REGEX = r'\b[\w\-.]+\.(?:jpg|jpeg|png)\b'

    def parse(self, text):
        """
        Parse a natural language command into a structured intent dictionary.
        """
        text = text.lower().strip()
        intent = {
            "method": None,
            "filename": None,
            "actions": []
        }

        # 1. Extract Filename
        file_matches = re.findall(self.FILE_REGEX, text)
        if file_matches:
            intent["filename"] = file_matches[0]  # Take first match
            intent["method"] = "upload" # Implicitly an upload if a filename is present

        # 2. Extract Input Method (if not already set by filename)
        if not intent["method"]:
            for method, keywords in self.INPUT_METHODS.items():
                if any(kw in text for kw in keywords):
                    intent["method"] = method
                    break

        # 3. Extract Actions (Maintain user's intended sequence)
        # We find all positions of action keywords and sort them
        found_actions = []
        for action, keywords in self.ACTION_PATTERNS.items():
            for kw in keywords:
                # Find all occurrences of the keyword
                for match in re.finditer(re.escape(kw), text):
                    found_actions.append((match.start(), action))
        
        # Sort by occurrence in the sentence
        found_actions.sort()
        
        # Deduplicate sequential actions (e.g., "detect objects" matching "detect" and "objects")
        if found_actions:
            intent["actions"] = []
            last_pos = -10
            for pos, act in found_actions:
                if pos > last_pos + 5: # Threshold to avoid double-matching overlapping keywords
                    intent["actions"].append(act)
                    last_pos = pos

        return intent
