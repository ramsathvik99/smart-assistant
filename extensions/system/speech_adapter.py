"""
Natural Speech Adapter (Conversational Response & TTS Upgrade)

Prepares text specifically for spoken synthesis:
- Strips non-spoken Markdown syntax (headings, asterisks, backticks, table borders)
- Normalizes numbered/bulleted lists into smooth spoken phrasing
- Replaces raw URLs with human-friendly site names
- Pronounces symbols and abbreviations naturally (%, &, @, e.g., etc., vs.)
- Handles code blocks gracefully without reading syntax verbatim
- Converts mathematical expressions into verbal forms
- Strips repetitive robotic AI filler ("As an AI...", "Sure! I would be happy to...")
- Injects natural punctuation cadence for TTS audio pausing
"""

import re
from typing import Dict, Any, Optional, Tuple, List


def sanitize_user_response(text: str, user_input: str = "") -> str:
    """
    Remove accidental internal-pipeline language, retrieval meta-commentary,
    and memory announcements without changing legitimate user content
    or user-requested source attribution.
    """
    if not text or not isinstance(text, str):
        return ""

    s = text.strip()

    # 1. Whole-sentence internal debug / pipeline disclosures
    debug_sentences = [
        r"(?:I(?:\'ve|\s+have)?\s+(?:queried|checked|searched|accessed|retrieved)\s+(?:the\s+|your\s+)?(?:database|memory|history|context|historical\s+records|records|previous\s+conversations?)[^.\n]*[.\?!]\s*)",
        r"(?:I(?:\'ve|\s+have)?\s+(?:used|executed|called)\s+(?:the\s+)?(?:tool|subsystem|function)[^.\n]*[.\?!]\s*)",
        r"(?:I(?:\'ve|\s+have)?\s+analyzed\s+your\s+request(?:\s+based\s+on\s+[^.\n]+)?[.\?!]\s*)",
    ]
    for ds in debug_sentences:
        m = re.match(ds, s, flags=re.IGNORECASE)
        if m and len(s) > m.end():
            s = s[m.end():].strip()

    # 2. Target forbidden phrases that refer to internal implementation details
    forbidden_sources = (
        r"(?:(?:our|your|my|the)\s+)?"
        r"(?:available|current|stored|internal|historical|previous|retrieved)?\s*"
        r"(?:"
        r"context|"
        r"memory|"
        r"memories|"
        r"information(?:\s+I\s+have)?|"
        r"knowledge(?:\s+base)?|"
        r"data|"
        r"references|"
        r"records|"
        r"sources|"
        r"evidence|"
        r"activity|"
        r"interactions|"
        r"conversations|"
        r"history|"
        r"search\s+results|"
        r"RAG(?:\s+results)?|"
        r"database(?:\s+records)?|"
        r"what\s+I\s+recall|"
        r"what\s+I\s+know\s+about\s+you"
        r")"
    )

    combined_source = rf"{forbidden_sources}(?:\s+(?:and|,)\s+{forbidden_sources})*"

    patterns = [
        rf"\b(?:based\s+on|according\s+to|using|from|considering)\s+{combined_source}[,\s:]*",
        r"\b(?:according\s+to|in)\s+my\s+(?:internal\s+)?(?:context|memory|reasoning|knowledge)[,\s:]*",
        r"\bfrom\s+(?:my\s+memory|the\s+RAG|our\s+previous\s+conversations?)[,\s:]*",
        r"\bI\s+(?:checked|retrieved)\s+(?:your\s+)?(?:memory|previous\s+conversations?)[,\s:]*",
        r"\bas\s+far\s+as\s+my\s+(?:context|memory)\s+goes[,\s:]*",
    ]

    for pat in patterns:
        s = re.sub(rf"^{pat}", "", s, flags=re.IGNORECASE).strip()
        s = re.sub(rf"((?:[\.\?!]\s+)){pat}", r"\1", s, flags=re.IGNORECASE).strip()

    def _capitalize_sentence(text_to_cap: str) -> str:
        if not text_to_cap:
            return ""
        text_to_cap = text_to_cap[0].upper() + text_to_cap[1:]
        def _cap(m):
            return m.group(1) + m.group(2).upper()
        return re.sub(r'([\.\?!]\s+)([a-z])', _cap, text_to_cap)

    return _capitalize_sentence(s)


class SpeechAdapter:
    """Deterministic, high-performance adapter converting written responses to natural speech."""

    # Abbreviations map (word-boundary matched)
    ABBREVIATIONS = [
        (r'(?:\be\.g\.|\beg\b),?', 'for example,'),
        (r'(?:\bi\.e\.|\bie\b),?', 'that is,'),
        (r'\betc\b\.?', 'etcetera'),
        (r'\bvs\b\.?', 'versus'),
        (r'\bapprox\b\.?', 'approximately'),
        (r'\bmins?\b\.?', 'minutes'),
        (r'\bsecs?\b\.?', 'seconds'),
        (r'\bhrs?\b\.?', 'hours'),
        (r'\bdept\b\.?', 'department'),
        (r'\bgovt\b\.?', 'government'),
        (r'\bno\b\.?\s*(?=\d)', 'number '),
        (r'\bprof\b\.?', 'professor'),
        (r'\bdr\b\.?', 'doctor'),
    ]

    # Robotic / Artificial filler phrases to remove or simplify
    ROBOTIC_AI_PREFIXES = [
        r"^as an ai (?:language )?model,?\s*",
        r"^according to (?:the )?(?:information|data|details) (?:provided|available),?\s*",
        r"^based on (?:my )?(?:the )?(?:information|data|search results),?\s*",
        r"^sure(?: thing)?! (?:i would be (?:happy|glad) to help(?: you)? with that\.?\s*)?",
        r"^certainly! (?:i can (?:help|assist) with that\.?\s*)?",
        r"^absolutely! (?:let's do that\.?\s*)?",
        r"^of course! (?:i can do that\.?\s*)?",
        r"^i(?: would)? be (?:happy|glad) to help(?: you)? with that\.?\s*",
        r"^here is the answer to your question:?\s*",
        r"^the requested application has been successfully launched\.?\s*",
        r"^your request has been completed successfully\.?\s*",
    ]

    def compress_for_speech(
        self,
        text: str,
        response_type: str = "direct_answer",
        intent: str = "",
        user_input: str = "",
        action_result: Optional[Dict[str, Any]] = None,
        max_sentences: int = 2,
        max_words: int = 40,
        query: str = "",
        **kwargs,
    ) -> str:
        """
        Dedicated speech-response compression/summarization policy:
        Strict separation between FULL RESPONSE (UI/chat) and SPOKEN RESPONSE (TTS).

        Rules:
        - Action confirmations: concise voice summary (~1-3 seconds of speech, ~4-12 words).
          e.g. "Done. I created the Deep Learning document."
          Never read file paths, hashes, slide counts, verification details aloud.
        - Knowledge / Research / RAG / Explanations: summarize into 1-3 concise sentences while keeping
          the complete answer available in UI.
        - Simple queries: prefer 1 short sentence.
        """
        if not text or not str(text).strip():
            return ""

        effective_input = user_input or query or kwargs.get("user_query", "")
        s = str(text).strip()
        act_res = action_result or {}
        intent_up = (intent or act_res.get("intent") or "").upper()
        inp_low = effective_input.lower().strip()

        # ── 0. Pure Local Time & Date Queries ────────────────────────────────
        if intent_up in ("TIME_QUERY", "LOCAL_TIME") or any(t in inp_low for t in ("what time", "what is the time", "tell me the time", "current time")):
            m_time = re.search(r'\b(\d{1,2}:\d{2})(?::\d{2})?\s*(AM|PM|am|pm)?\b', s)
            if m_time:
                t_val = m_time.group(1)
                ampm = f" {m_time.group(2).upper()}" if m_time.group(2) else ""
                return f"The time is {t_val}{ampm}."
            elif "is " in s:
                return s.split("\n")[0].strip()

        if intent_up in ("DATE_QUERY", "LOCAL_DATE") or any(t in inp_low for t in ("what date", "what is the date", "what's today's date", "today's date")):
            m_date = re.search(r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)[,\s]+[A-Za-z]+\s+\d{1,2}(?:,\s+\d{4})?\b', s)
            if m_date:
                return f"Today is {m_date.group(0)}."

        # ── 1. Action Confirmations ──────────────────────────────────────────
        # ── 1. Action Confirmations ──────────────────────────────────────────
        is_doc_cmd = (
            intent_up in ("DOCUMENT_GENERATION", "CREATE_DOCUMENT")
            or any(w in inp_low for w in ("create a document", "create document", "generate a document", "generate document", "create a presentation", "create presentation", "create a spreadsheet", "create spreadsheet", "create a report", "create report"))
        )
        if is_doc_cmd or response_type == "action_confirmation" or intent_up in (
            "DOCUMENT_GENERATION", "CREATE_DOCUMENT", "OPEN_APPLICATION", "FILE_OPERATIONS",
            "POWER_ACTION", "WINDOW_CONTEXT", "AUDIO_DEVICES", "DEVICE_CONTROL",
            "TASK_MANAGEMENT", "REMINDERS", "NOTES"
        ) or any(phrase in s.lower() for phrase in ("created and saved", "successfully created", "has been created")):
            # Document Generation
            if is_doc_cmd or intent_up in ("DOCUMENT_GENERATION", "CREATE_DOCUMENT") or any(w in s.lower() for w in ("document", "presentation", "spreadsheet", "pdf document", "report")):
                topic = act_res.get("topic") or act_res.get("subject") or ""
                if not topic:
                    m_top = re.search(r'\b(?:about|on|for)\s+([A-Za-z0-9\s_-]+?)(?:\s+(?:document|presentation|report|slides|spreadsheet|file)|\.|$)', effective_input, re.I)
                    if m_top:
                        topic = m_top.group(1).strip()
                if not topic:
                    m_file_top = re.search(r"['\"]?([A-Za-z0-9_-]+?)_?\d{8}[_\d]*\.", s)
                    if m_file_top:
                        topic = m_file_top.group(1).replace("_", " ").strip()

                doc_type = "presentation" if any(w in (effective_input + s).lower() for w in ("presentation", "ppt", "slides")) else (
                    "spreadsheet" if any(w in (effective_input + s).lower() for w in ("excel", "sheet", "spreadsheet")) else (
                        "PDF" if "pdf" in (effective_input + s).lower() else "document"
                    )
                )

                if topic:
                    clean_top = topic.strip().title()
                    clean_top = re.sub(r'\.(?:docx?|pptx?|xlsx?|pdf)$', '', clean_top, flags=re.I).strip()
                    return f"Done. I created the {clean_top} {doc_type}."
                else:
                    return f"Done. I created the {doc_type}."

            # Application Launch
            if intent_up == "OPEN_APPLICATION" or any(w in inp_low for w in ("open ", "launch ", "start ")):
                m_app = re.match(r'^(?:open|launch|start|bring up)\s+(?:the\s+)?(.+?)(?:\s+app|\s+application)?[\.!\?]?$', effective_input.strip(), re.I)
                target = m_app.group(1).title() if m_app else "the application"
                return f"Done. Opening {target}."

            # File Operations / Generic Action
            clean_act = re.sub(r'[A-Za-z]:\\[^\s,]+', '', s)
            clean_act = re.sub(r'/[^\s,]+/[^\s,]+', '', clean_act)
            clean_act = re.sub(r'\b[A-Za-z0-9_\-]+\.(?:docx|pptx|xlsx|pdf|txt|py|csv)\b', '', clean_act)
            clean_act = re.sub(r'\s+', ' ', clean_act).strip()
            sents = re.split(r'(?<=[.!?])\s+', clean_act)
            first_s = sents[0] if sents else "Done."
            first_words = first_s.split()
            if len(first_words) > 10:
                first_s = " ".join(first_words[:8]).rstrip(",:;") + "."
            return first_s if first_s else "Done."

        # ── 1.5 Recommendation Queries (Concise 1–3s Spoken Summary) ──────────
        is_rec = (
            response_type == "recommendation"
            or intent_up in ("RECOMMENDATION", "RECOMMENDATIONS", "GAME_DISCOVERY", "SYSTEM_COMPATIBILITY")
            or any(kw in inp_low for kw in ("suggest", "recommend", "recommendation", "recommendations"))
        )
        if is_rec:
            # Parse recommended item titles from bulleted or numbered lines
            items: List[str] = []
            for line in s.split("\n"):
                l_strip = line.strip()
                if not l_strip:
                    continue
                # Match bullet points (*, -, •) or numbered items (1., 2.)
                m_item = re.match(r'^(?:[\*\-•]|\d+[\.\)])\s*(.+)', l_strip)
                if m_item:
                    raw_title = m_item.group(1).strip()
                    # Strip bold/italic markdown
                    raw_title = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', raw_title)
                    # Extract title portion before delimiter (colon, hyphen, dash, parens)
                    title_part = re.split(r'[:–—\-\(]', raw_title)[0].strip()
                    # Keep reasonably concise (under 6 words)
                    t_words = title_part.split()
                    if len(t_words) > 5:
                        title_part = " ".join(t_words[:4])
                    if title_part and len(title_part) >= 2:
                        items.append(title_part)

            if len(items) >= 2:
                return f"I'd suggest {items[0]} or {items[1]}."
            elif len(items) == 1:
                return f"I'd suggest {items[0]}."

        # ── 2. Knowledge, Research, RAG, and Conversational Responses ────────
        # Strip fenced code blocks, markdown tables, headers, and URLs
        s = re.sub(r'```[\s\S]*?```', '', s)
        s = re.sub(r'\|[^\n]+\|', '', s)
        s = re.sub(r'#{1,6}\s+[^\n]+', '', s)
        s = re.sub(r'https?://\S+', '', s)
        # Strip citation brackets like [1], [Source: ...], Sources: ...
        s = re.sub(r'\[\d+\]', '', s)
        s = re.sub(r'\[Source:[^\]]+\]', '', s, flags=re.I)
        s = re.split(r'\n+\s*(?:Sources|References):', s, flags=re.I)[0]

        # Strip markdown bullets and numbered lists
        s = re.sub(r'^\s*[-*•]\s+', '', s, flags=re.MULTILINE)
        s = re.sub(r'^\s*\d+[\.\)]\s+', '', s, flags=re.MULTILINE)

        # Normalize whitespace
        s = re.sub(r'\s+', ' ', s).strip()

        # Split into clean sentences
        raw_sents = re.split(r'(?<=[.!?])\s+', s)
        filtered_sents = []
        for sent in raw_sents:
            sent_str = sent.strip()
            if not sent_str or len(sent_str) < 6:
                continue
            # Filter meta or filler statements
            if any(sent_str.lower().startswith(p) for p in (
                "here is", "here are", "based on", "according to", "in summary",
                "to summarize", "sure!", "certainly!", "as requested"
            )):
                continue
            filtered_sents.append(sent_str)

        if not filtered_sents:
            filtered_sents = [s] if s else ["I have found the relevant information."]

        # For spoken responsiveness, target 1 concise sentence (~1-3 seconds, ~6-16 words)
        first_sent = filtered_sents[0].strip()
        first_words = first_sent.split()
        if len(first_words) > 16:
            # Trim at natural clause boundary if available
            clause_parts = re.split(r'[,;]\s+', first_sent)
            if clause_parts and len(clause_parts[0].split()) >= 4:
                first_sent = clause_parts[0].rstrip(",;:") + "."
            else:
                first_sent = " ".join(first_words[:14]).rstrip(",;:") + "."

        spoken_summary = first_sent
        if not spoken_summary.endswith((".", "!", "?")):
            spoken_summary += "."

        return spoken_summary

    def adapt_for_speech(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        response_type: str = "direct_answer",
        intent: str = "",
        user_input: str = "",
        action_result: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Transforms written response text into natural, spoken-ready audio text.
        Applies dedicated speech compression policy so TTS is concise and responsive.
        
        Returns:
            Tuple of (adapted_speech_text, metadata_dict)
        """
        if not text or not str(text).strip():
            return "", metadata or {}

        s = str(text).strip()
        meta = dict(metadata or {})

        # Apply dedicated speech compression / summarization policy
        # If metadata already provides an explicit response_type or intent, prioritize it
        eff_resp_type = meta.get("response_type") or response_type
        eff_intent = meta.get("intent") or intent

        s = self.compress_for_speech(
            s,
            response_type=eff_resp_type,
            intent=eff_intent,
            user_input=user_input,
            action_result=action_result
        )

        # 0. Sanitize internal pipeline language and retrieval disclosures
        s = sanitize_user_response(s)

        # 1. Clean robotic AI prefixes and formal boilerplate
        s = self._clean_robotic_prefixes(s)

        # 2. Handle fenced code blocks before markdown removal
        s = self._handle_code_blocks(s)

        # 3. Handle raw URLs before symbol processing
        s = self._normalize_urls(s)

        # 4. Handle mathematical expressions and units
        s = self._normalize_math_and_units(s)

        # 5. Handle markdown tables and structure
        s = self._normalize_markdown_tables(s)

        # 6. Normalize numbered and bulleted lists into spoken phrasing
        s = self._normalize_lists(s)

        # 7. Strip general markdown formatting (headers, bold, italics, backticks)
        s = self._strip_markdown_syntax(s)

        # 8. Expand spoken abbreviations
        s = self._expand_abbreviations(s)

        # 9. Clean symbols (% -> percent, & -> and, @ -> at, etc.)
        s = self._normalize_symbols(s)

        # 10. Fix sentence flow, punctuation, and natural pauses
        s = self._polish_speech_cadence(s)

        # Metrics measurement: spoken char count, spoken word count, playback duration
        words = s.split()
        spoken_chars = len(s)
        spoken_words = len(words)
        expected_dur = round(max(0.5, spoken_words / 2.5), 2)  # ~150 words/min = 2.5 words/sec

        meta["spoken_char_count"] = spoken_chars
        meta["spoken_word_count"] = spoken_words
        meta["word_count"] = spoken_words
        meta["playback_duration"] = expected_dur
        meta["expected_duration"] = expected_dur
        meta.setdefault("first_audio_ms", 120)

        return s, meta

    # -------------------------------------------------------------------------
    # Internal Transformations
    # -------------------------------------------------------------------------

    def _clean_robotic_prefixes(self, text: str) -> str:
        s = text
        for pat in self.ROBOTIC_AI_PREFIXES:
            s = re.sub(pat, '', s, flags=re.IGNORECASE).strip()
        return s

    def _handle_code_blocks(self, text: str) -> str:
        # Replace fenced code blocks with a natural spoken indicator
        def _replace_code(match):
            lang = match.group(1) or "code"
            code_body = match.group(2)
            lines = [l for l in code_body.strip().splitlines() if l.strip()]
            if len(lines) <= 2 and not any(kw in code_body for kw in ("def ", "class ", "import ", "for ", "while ")):
                # Short snippet like a single command or expression
                return f" {code_body.strip()} "
            return " I've prepared the code for you. "

        s = re.sub(r'```([a-zA-Z0-9_\-]+)?\s*\n?(.*?)```', _replace_code, text, flags=re.DOTALL)
        # Inline code backticks: `variable` -> variable
        s = re.sub(r'`([^`]+)`', r'\1', s)
        return s

    def _normalize_urls(self, text: str) -> str:
        def _replace_url(match):
            url = match.group(0)
            url_low = url.lower()
            if "youtube.com" in url_low or "youtu.be" in url_low:
                return "YouTube"
            if "google.com" in url_low:
                return "Google"
            if "github.com" in url_low:
                return "GitHub"
            if "wikipedia.org" in url_low:
                return "Wikipedia"
            # Extract domain name without protocol
            m_domain = re.search(r'https?://(?:www\.)?([^/]+)', url, re.IGNORECASE)
            if m_domain:
                return m_domain.group(1)
            return "the website"

        return re.sub(r'https?://\S+', _replace_url, text)

    def _normalize_math_and_units(self, text: str) -> str:
        s = text
        # Temperature: 28°C / 28 °C / 28° / 28 degrees Celsius
        s = re.sub(r'(\d+)\s*°\s*C\b', r'\1 degrees Celsius', s)
        s = re.sub(r'(\d+)\s*°\s*F\b', r'\1 degrees Fahrenheit', s)
        s = re.sub(r'(\d+)\s*°\b', r'\1 degrees', s)

        # Multiplications: 25 * 18 -> 25 times 18
        s = re.sub(r'(\b\d+)\s*\*\s*(\d+\b)', r'\1 times \2', s)
        # Divisions: 100 / 4 -> 100 divided by 4
        s = re.sub(r'(\b\d+)\s*/\s*(\d+\b)', r'\1 divided by \2', s)
        # Additions: 10 + 5 -> 10 plus 5
        s = re.sub(r'(\b\d+)\s*\+\s*(\d+\b)', r'\1 plus \2', s)
        # Subtractions: 20 - 5 -> 20 minus 5
        s = re.sub(r'(\b\d+)\s*-\s*(\d+\b)', r'\1 minus \2', s)
        # Equals: = 450 -> equals 450
        s = re.sub(r'\s*=\s*(\d+)', r' equals \1', s)

        # Approximation: ~28 -> around 28
        s = re.sub(r'~(\d+)', r'around \1', s)

        return s

    def _normalize_markdown_tables(self, text: str) -> str:
        # Detect markdown tables (lines starting and ending with |)
        lines = text.splitlines()
        filtered = []
        is_table = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("|") and stripped.endswith("|"):
                if re.match(r'^\|[\s\-:|]+\|$', stripped):
                    # Table separator line
                    continue
                cells = [c.strip() for c in stripped.split("|")[1:-1] if c.strip()]
                if cells:
                    filtered.append(". ".join(cells) + ".")
                is_table = True
            else:
                filtered.append(line)
        return "\n".join(filtered)

    def _normalize_lists(self, text: str) -> str:
        lines = text.splitlines()
        normalized_lines = []
        items_buffer = []

        def flush_items():
            nonlocal items_buffer, normalized_lines
            if not items_buffer:
                return
            n = len(items_buffer)
            if n == 1:
                normalized_lines.append(items_buffer[0])
            elif n == 2:
                normalized_lines.append(f"{items_buffer[0]}, and {items_buffer[1]}")
            elif n == 3:
                # E.g. prompt example: "I found the file, opened it, and finished the analysis."
                # Check if items are concise clauses
                if all(len(item.split()) < 8 for item in items_buffer):
                    clean_items = [re.sub(r'^(the|a)\s+', '', item, flags=re.I).rstrip('.') for item in items_buffer]
                    normalized_lines.append(f"{items_buffer[0]}, {items_buffer[1]}, and {items_buffer[2]}")
                else:
                    normalized_lines.append(f"First, {items_buffer[0]}. Second, {items_buffer[1]}. And third, {items_buffer[2]}.")
            else:
                # 4+ items: speak sequentially with natural transitions
                ordinal = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth"]
                out = []
                for idx, itm in enumerate(items_buffer):
                    prefix = ordinal[idx] if idx < len(ordinal) else f"Step {idx + 1}"
                    out.append(f"{prefix}, {itm.rstrip('.')}.")
                normalized_lines.append(" ".join(out))
            items_buffer = []

        for line in lines:
            stripped = line.strip()
            # Match numbered item: "1. item text" or "1) item text"
            m_num = re.match(r'^(?:\d+[\.\)]|\*|-|\+)\s+(.+)$', stripped)
            if m_num:
                item_text = m_num.group(1).strip()
                items_buffer.append(item_text)
            else:
                if items_buffer:
                    flush_items()
                normalized_lines.append(line)

        if items_buffer:
            flush_items()

        return "\n".join(normalized_lines)

    def _strip_markdown_syntax(self, text: str) -> str:
        s = text
        # Remove headers like "## Result" -> "Result." or if it's "Result" / "Output", drop it
        def _header_sub(m):
            header_text = m.group(1).strip()
            if header_text.lower() in ("result", "results", "output", "summary", "overview", "answer"):
                return ""
            return f"{header_text}. "

        s = re.sub(r'^\s*#{1,6}\s*(.+)$', _header_sub, s, flags=re.MULTILINE)

        # Bold & Italic: **text** / *text* / __text__ / _text_
        s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
        s = re.sub(r'\*(.+?)\*', r'\1', s)
        s = re.sub(r'__(.+?)__', r'\1', s)
        s = re.sub(r'_(.+?)_', r'\1', s)

        # Blockquotes: "> text"
        s = re.sub(r'^\s*>\s*(.+)$', r'\1', s, flags=re.MULTILINE)

        # Horizontal rules: "---", "***"
        s = re.sub(r'^\s*[-*_]{3,}\s*$', '', s, flags=re.MULTILINE)

        return s

    def _expand_abbreviations(self, text: str) -> str:
        s = text
        for pat, repl in self.ABBREVIATIONS:
            s = re.sub(pat, repl, s, flags=re.IGNORECASE)
        return s

    def _normalize_symbols(self, text: str) -> str:
        s = text
        # % symbol: 50% -> 50 percent
        s = re.sub(r'(\d+)\s*%', r'\1 percent', s)
        s = re.sub(r'\s+%\s+', ' percent ', s)

        # & symbol: Rock & Roll -> Rock and Roll
        s = re.sub(r'\s*&\s*', ' and ', s)

        # @ symbol: user@domain -> user at domain
        s = re.sub(r'(\w+)@(\w+)', r'\1 at \2', s)

        # >= and <=
        s = re.sub(r'\s*>=\s*', ' greater than or equal to ', s)
        s = re.sub(r'\s*<=\s*', ' less than or equal to ', s)
        s = re.sub(r'\s*>\s*', ' greater than ', s)
        s = re.sub(r'\s*<\s*', ' less than ', s)

        return s

    def _polish_speech_cadence(self, text: str) -> str:
        # Collapse multiple newlines and whitespace into natural punctuation flow
        s = re.sub(r'\s*\n+\s*', ' ', text).strip()
        # Clean double punctuation
        s = re.sub(r'\.{2,}', '...', s)
        s = re.sub(r',\s*,', ',', s)
        s = re.sub(r'\?\s*\?', '?', s)
        s = re.sub(r'!\s*!', '!', s)
        s = re.sub(r'\s+([,\.!\?:;])', r'\1', s)
        # Ensure clean single spaces
        s = re.sub(r'\s+', ' ', s).strip()

        # Split run-on sentences over 30 words at logical conjunctions (and, but, because, so)
        sentences = re.split(r'([\.!\?]+\s+)', s)
        reconstructed = []
        for i in range(0, len(sentences), 2):
            sent = sentences[i]
            punct = sentences[i + 1] if i + 1 < len(sentences) else ""
            words = sent.split()
            if len(words) > 30:
                # Find logical mid-point conjunction
                mid = len(words) // 2
                split_done = False
                for offset in range(len(words) // 3):
                    for idx in (mid + offset, mid - offset):
                        if 0 <= idx < len(words) and words[idx].lower() in ("and", "but", "however", "although", "because", "so"):
                            part1 = " ".join(words[:idx])
                            part2 = " ".join(words[idx:])
                            sent = f"{part1}. {part2.capitalize()}"
                            split_done = True
                            break
                    if split_done:
                        break
            reconstructed.append(sent + punct)

        return "".join(reconstructed).strip()


# Singleton instance
_speech_adapter = SpeechAdapter()
speech_adapter = _speech_adapter

def get_speech_adapter() -> SpeechAdapter:
    """Return the global SpeechAdapter instance."""
    return _speech_adapter

def adapt_for_speech(
    text: str,
    metadata: Optional[Dict[str, Any]] = None,
    response_type: str = "direct_answer",
    intent: str = "",
    user_input: str = "",
    action_result: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Convenience helper to adapt text for speech."""
    return _speech_adapter.adapt_for_speech(
        text,
        metadata=metadata,
        response_type=response_type,
        intent=intent,
        user_input=user_input,
        action_result=action_result
    )

def compress_for_speech(
    text: str,
    response_type: str = "direct_answer",
    intent: str = "",
    user_input: str = "",
    action_result: Optional[Dict[str, Any]] = None,
    max_sentences: int = 2,
    max_words: int = 40,
    query: str = "",
    **kwargs,
) -> str:
    """Convenience helper for speech-response compression policy."""
    return _speech_adapter.compress_for_speech(
        text,
        response_type=response_type,
        intent=intent,
        user_input=user_input,
        action_result=action_result,
        max_sentences=max_sentences,
        max_words=max_words,
        query=query,
        **kwargs,
    )

def estimate_speech_duration(text: str) -> float:
    """Convenience helper to estimate speech duration."""
    return _speech_adapter.estimate_speech_duration(text)
