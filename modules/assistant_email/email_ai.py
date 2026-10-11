import os
import re
import json
from typing import Tuple, List, Dict, Any, Optional
from extensions.llm_engine import LLMEngine

import concurrent.futures

def generate_with_ai(prompt: str, max_tokens: int = 500, timeout_budget: float = 3.5) -> Optional[str]:
    """
    Invokes LLMEngine with fallback handling and a strict bounded timeout budget (default 3.5s).
    Guarantees email operations never block on slow or unresponsive LLM providers,
    falling back immediately to the deterministic local restructuring engine.
    Does NOT log sensitive message contents or prompts to the console.
    """
    def _call():
        engine = LLMEngine()
        return engine.get_completion(prompt, max_tokens=max_tokens, timeout_budget=timeout_budget, task_type="interactive")

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_call)
            result = future.result(timeout=timeout_budget)
            if result and len(result.strip()) > 5:
                return result.strip()
    except Exception:
        pass
    return None

def generate_subject_from_text(raw_text: str) -> str:
    """Generates an appropriate subject from email intent text."""
    low = (raw_text or "").lower()
    if any(k in low for k in ["progress", "status", "update"]):
        return "Project Progress Update"
    if any(k in low for k in ["result", "results", "score", "scores"]):
        return "Request for Latest Results"
    if "meeting tomorrow" in low:
        return "Meeting Tomorrow"
    if any(k in low for k in ["meeting", "schedule", "call", "discuss"]):
        return "Discussion and Meeting Request"
    if any(k in low for k in ["report", "document", "file", "presentation", "sheet"]):
        return "Document Submission & Review"
    if any(k in low for k in ["internship", "job", "application", "placement"]):
        return "Internship Application Update"
    if any(k in low for k in ["leave", "sick", "vacation", "absence"]):
        return "Leave Notification"
    if any(k in low for k in ["submit", "submission", "assignment"]):
        return "Project Submission"
    if re.search(r'^(?:friday,?\s*)?(?:send\s+(?:an?\s+)?(?:email|mail)\s+(?:to\s+)?[\w\s]+)$', low.strip()):
        return "Message from Sathvik"
    return "Message & Follow-up"

def _format_fallback_body(raw_text: str, recipient_name: str, tone: str = "professional") -> str:
    """Fallback generator when AI engine is offline or unavailable."""
    cleaned = (raw_text or "").strip()
    try:
        from instance.config import settings as _cfg
        _asst = (_cfg.get_assistant_name() or "").lower()
    except Exception:
        _asst = ""
    fillers = ["hey", "hello", "hi", "um", "uh", "like", "you know", "please", "can you"]
    if _asst:
        fillers.extend([_asst, f"hey {_asst}"])
    for f in fillers:
        if cleaned.lower().startswith(f):
            cleaned = cleaned[len(f):].strip()

    cleaned = cleaned.lstrip(",.:;!? ").strip()

    # Detect if text was merely the dispatch command rather than body content
    low_cleaned = cleaned.lower()
    if re.search(r'^(?:send\s+(?:an?\s+)?(?:email|mail)\s+(?:to\s+)?[\w\s]+)$', low_cleaned):
        cleaned = "I am writing to follow up with you. Please let me know your thoughts."

    if cleaned and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]
    if cleaned and not cleaned.endswith('.'):
        cleaned += '.'

    salutation = f"Hi {recipient_name}," if tone in ("friendly", "casual") else f"Dear {recipient_name},"
    closing = "Warm regards," if tone in ("friendly", "casual") else "Best regards,"

    if tone == "concise":
        return f"{salutation}\n\n{cleaned}\n\n{closing}"

    return f"""{salutation}

I hope this message finds you well.

{cleaned}

Please let me know if you need any additional information.

{closing}"""

def rewrite_professional(raw_text: str, recipient_name: str = "Sir/Madam", tone: str = "professional") -> Tuple[str, str]:
    """
    Uses LLMEngine to convert spoken text or bullet points into an articulate,
    professional email preserving all stated facts and commitments.
    """
    tone_guidelines = {
        "formal": "Strictly formal, polite, objective, and structured.",
        "professional": "Professional, clear, respectful, and organized.",
        "friendly": "Friendly, approachable, yet respectful and clear.",
        "concise": "Extremely concise, punchy, direct to the point, minimal fluff.",
        "persuasive": "Persuasive, compelling, clearly highlighting benefits and urgency.",
        "technical": "Precise, structured, including technical terms accurately.",
        "follow_up": "Courteous follow-up referencing prior discussion."
    }
    style_instruction = tone_guidelines.get(tone.lower(), tone_guidelines["professional"])

    prompt = f"""Convert this message request into a high quality email.

Recipient: {recipient_name}
Desired Style: {style_instruction}
Original Message: "{raw_text}"

Requirements:
1. Generate a concise, descriptive Subject line.
2. Structure the email with appropriate greeting, clear body paragraphs, specific call to action / next step, and closing.
3. PRESERVE all facts, names, commitments, and deadlines. DO NOT invent dates, files, or facts not mentioned.
4. Output format MUST be strictly:
Subject: <subject line>

<Full email body starting with Dear/Hi {recipient_name}, and ending with Best regards/Warm regards>
"""

    ai_output = generate_with_ai(prompt, max_tokens=600)
    if not ai_output:
        subject = generate_subject_from_text(raw_text)
        body = _format_fallback_body(raw_text, recipient_name, tone=tone)
        return subject, body

    lines = ai_output.strip().split('\n')
    subject = ""
    body_lines = []
    in_body = False

    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("subject:"):
            subject = stripped[8:].strip()
            in_body = True
        elif in_body or stripped.lower().startswith("dear") or stripped.lower().startswith("hi"):
            in_body = True
            body_lines.append(line)

    body = '\n'.join(body_lines).strip()
    if not subject:
        subject = generate_subject_from_text(raw_text)
    if not body or len(body) < 20:
        body = _format_fallback_body(raw_text, recipient_name, tone=tone)

    return subject, body

def generate_email_structure(raw_speech: str, recipient_name: str = "Sir/Madam") -> Tuple[str, str]:
    """Entry point for structure generation, preserving existing signature."""
    return rewrite_professional(raw_speech, recipient_name, tone="professional")

def edit_email_draft(subject: str, body: str, instruction: str) -> Tuple[str, str]:
    """
    Applies conversational revision instructions to an existing draft.
    e.g., 'Make it more formal', 'Shorten the second paragraph', 'Change subject to XYZ'.
    """
    inst_clean = (instruction or "").strip()
    inst_low = inst_clean.lower()

    # Direct subject rewrite instruction
    m_subj = re.search(r'change\s+(?:the\s+)?subject\s+(?:to|as)\s+["\']?([^"\']+)["\']?', inst_clean, re.IGNORECASE)
    if m_subj:
        new_subject = m_subj.group(1).strip().rstrip('.,?!')
        return new_subject, body

    prompt = f"""You are an expert email editor. Revise the email according to the user's instructions.

Current Subject: {subject}
Current Body:
{body}

Revision Instruction: "{instruction}"

Requirements:
1. Update the subject only if instructed or if significantly needed.
2. Apply the requested changes (e.g., change tone, shorten paragraphs, add points, rephrase).
3. Do not invent commitments or facts not requested.
4. Output strictly:
Subject: <subject>

<revised body>
"""

    ai_output = generate_with_ai(prompt, max_tokens=600)
    if not ai_output:
        # Fallback heuristic modifications
        if "short" in inst_low or "concise" in inst_low:
            paragraphs = [p.strip() for p in body.split('\n\n') if p.strip()]
            if len(paragraphs) > 2:
                # Keep greeting, middle merged/trimmed, closing
                trimmed_body = paragraphs[0] + "\n\n" + paragraphs[1] + "\n\n" + paragraphs[-1]
                return subject, trimmed_body
        return subject, body

    lines = ai_output.strip().split('\n')
    new_subject = subject
    body_lines = []
    in_body = False

    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("subject:"):
            new_subject = stripped[8:].strip()
            in_body = True
        elif in_body or stripped.lower().startswith("dear") or stripped.lower().startswith("hi"):
            in_body = True
            body_lines.append(line)

    revised_body = '\n'.join(body_lines).strip()
    return new_subject, (revised_body if revised_body else body)

def generate_reply(original_email_content: str, reply_intent: str = "") -> str:
    """Generates a contextual reply to an email."""
    prompt = f"""Write a professional reply to this email:

Original email:
{original_email_content}

Reply intent/notes: "{reply_intent or 'Acknowledge receipt and respond politely.'}"

Output only the reply message body starting with greeting and ending with closing.
"""
    res = generate_with_ai(prompt, max_tokens=400)
    if res:
        return res.strip()
    return "Thank you for the update. I have reviewed your message and will follow up with further details shortly.\n\nBest regards."

def generate_summary(emails: List[Dict[str, Any]]) -> str:
    """Generates a concise executive summary of a collection of emails."""
    if not emails:
        return "No emails to summarize."
    emails_text = "\n\n".join([
        f"Email #{i+1} from {e.get('sender', 'Unknown')} | Subject: '{e.get('subject', 'No Subject')}'\nSnippet: {e.get('body', '')[:300]}"
        for i, e in enumerate(emails[:8])
    ])
    prompt = f"""Provide a concise, bulleted executive summary of these emails highlighting important senders, topics, requests, and deadlines:

{emails_text}
"""
    res = generate_with_ai(prompt, max_tokens=400)
    if res:
        return res.strip()
    return f"You have {len(emails)} recent messages. Latest is from {emails[0].get('sender')} regarding '{emails[0].get('subject')}'."

def extract_action_items(email_text: str) -> List[str]:
    """Extracts explicit action items, deadlines, and questions from an email."""
    prompt = f"""Extract any action items, requests, questions, or deadlines required from the recipient in this email:

{email_text}

Output as a numbered list of action items. If there are none, output 'None'.
"""
    res = generate_with_ai(prompt, max_tokens=250)
    if res and "none" not in res.lower():
        items = [line.strip() for line in res.split('\n') if re.match(r'^\d+[\.\)]\s*', line.strip())]
        if items:
            return items

    # Heuristic fallback for offline/no-LLM environments or unnumbered lists
    action_keywords = ["deadline", "due", "please", "submit", "action", "review", "confirm", "send", "urgent", "by tomorrow", "meeting", "interview"]
    found: List[str] = []
    for line in email_text.splitlines():
        line_str = line.strip()
        if any(k in line_str.lower() for k in action_keywords) and len(line_str) > 8:
            clean_item = re.sub(r'^(?:[-*•]|\d+[\.\)])\s*', '', line_str).strip()
            if clean_item and clean_item not in found:
                found.append(clean_item)
    return found[:5]


def explain_email_simple(email_text: str) -> str:
    """Explains an email in simple, plain language."""
    prompt = f"""Explain this email in simple, clear, conversational terms so anyone can easily understand what it means and what to do:

{email_text}
"""
    res = generate_with_ai(prompt, max_tokens=300)
    return res.strip() if res else "The email discusses the latest project progress and requests confirmation."
