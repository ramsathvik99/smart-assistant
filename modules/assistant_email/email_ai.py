import os
import re
import json
from extensions.llm_engine import LLMEngine

# Shared LLMEngine — provider and fallback handled centrally
_engine = LLMEngine()

# ── PROFESSIONAL REWRITING (TRUE INTENT-BASED) ───────────────────

def generate_subject_from_text(raw_text):
    raw_text = raw_text.lower()
    if "report" in raw_text or "file" in raw_text or "doc" in raw_text:
        return "Request for Project Report"
    if "meeting" in raw_text or "schedule" in raw_text or "call" in raw_text:
        return "Meeting Update"
    return "Project Update"

def rewrite_professional(raw_text, recipient_name="Sir/Madam"):
    """
    Uses LLMEngine to convert raw speech into professional email content.
    Preserves actual intent and content while formalizing the tone.

    BEFORE: call_openrouter() → call_gemini() → call_huggingface() (3 direct provider calls)
    AFTER:  LLMEngine.get_completion() → configured provider → fallback chain
    """
    print(f"[DEBUG] RAW INPUT: {raw_text}")

    prompt = f"""Convert this spoken message into a professional email:

Original message: "{raw_text}"

Requirements:
1. Summarize and formalize the content
2. Preserve ALL key information and intent
3. Remove conversational fillers but keep the core message
4. Use professional email format
5. Include specific details mentioned (movie, MCU, testing, etc.)
6. Generate appropriate subject based on content

Output format:
Subject: [appropriate subject line]

Dear {recipient_name},

[Professional version of the message with all key details]

Best regards,
"""

    processed_content = generate_with_ai(prompt)
    print(f"[DEBUG] PROCESSED OUTPUT: {processed_content}")

    # Fallback if AI fails
    if not processed_content:
        print("[DEBUG] AI processing failed, using improved fallback")

        subject = generate_subject_from_text(raw_text)

        cleaned_text = raw_text.strip()
        try:
            from instance.config import settings as _cfg
            _asst = (_cfg.get_assistant_name() or "").lower()
        except Exception:
            _asst = ""
        fillers = ["hey", "hello", "hi", "um", "uh", "like", "you know"]
        if _asst:
            fillers.extend([_asst, f"hey {_asst}"])
        for filler in fillers:
            cleaned_text = cleaned_text.replace(filler, "")

        if cleaned_text and cleaned_text[0].islower():
            cleaned_text = cleaned_text[0].upper() + cleaned_text[1:]
        if cleaned_text and not cleaned_text.endswith('.'):
            cleaned_text += '.'

        body = f"""Dear {recipient_name},

I hope this email finds you well.

I am writing to {cleaned_text}

Thank you for your attention to this matter.

Best regards,"""

        return subject, body

    # Parse AI response to extract subject and body
    lines = processed_content.strip().split('\n')
    subject = "Professional Communication"
    body_lines = []

    current_section = "subject"
    for line in lines:
        line = line.strip()
        if line.startswith("Subject:"):
            subject = line.replace("Subject:", "").strip()
            current_section = "body"
        elif line.startswith("Dear") or current_section == "body":
            body_lines.append(line)

    body = '\n'.join(body_lines).strip()

    if not body or len(body) < 20:
        body = f"""Dear {recipient_name},

I hope this email finds you well.

{raw_text}

Thank you for your attention to this matter.

Best regards,"""

    return subject, body

def generate_email_structure(raw_speech, recipient_name="Sir/Madam"):
    """
    Main entry for structure generation.
    Uses LLMEngine to process voice input into a professional email.
    """
    print(f"[DEBUG] generate_email_structure called with: '{raw_speech}'")

    subject, body = rewrite_professional(raw_speech, recipient_name)

    print(f"[DEBUG] FINAL MESSAGE PASSED TO POPUP: {body}")
    print(f"[DEBUG] Final subject: '{subject}'")
    print(f"[DEBUG] Final body length: {len(body)}")

    return subject, body

# ── CENTRAL AI GENERATION ─────────────────────────────────────────

def generate_with_ai(prompt):
    """
    BEFORE: call_openrouter() → call_gemini() → call_huggingface() (each a separate direct provider call)
    AFTER:  LLMEngine.get_completion() — single call, provider/fallback handled centrally
    """
    print("[DEBUG] AI generation started via LLMEngine...")
    result = _engine.get_completion(prompt, max_tokens=500)
    if result and len(result.strip()) > 10:
        return result
    print("[DEBUG] LLMEngine returned no result - using fallback")
    return None

def generate_reply(original_email_content):
    prompt = f"Write a professional reply to this email:\n\n{original_email_content}"
    res = generate_with_ai(prompt)
    return res.strip() if res else "Thank you for the update. I will get back to you soon."

def generate_summary(emails):
    if not emails:
        return "No emails to summarize."
    emails_text = "\n\n".join([f"From: {e['sender']}\nSubject: {e['subject']}\nBody: {e['body']}" for e in emails])
    prompt = f"Summarize these emails concisely:\n\n{emails_text}"
    res = generate_with_ai(prompt)
    return res.strip() if res else f"You have {len(emails)} new messages."
