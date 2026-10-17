import os
import re
import json
from typing import Tuple, List, Dict, Any, Optional
from extensions.llm_engine import LLMEngine

import concurrent.futures

def generate_with_ai(prompt: str, max_tokens: int = 500, timeout_budget: float = 12.0, user_id: Optional[Any] = None) -> Optional[str]:
    """
    Invokes LLMEngine with fallback handling and a bounded timeout budget (default 12.0s).
    Guarantees email operations never block indefinitely on slow or unresponsive LLM providers,
    falling back to remaining configured providers and finally to the deterministic local engine.
    Does NOT log sensitive message contents or prompts to the console.
    """
    def _call():
        engine = LLMEngine()
        return engine.get_completion(prompt, max_tokens=max_tokens, timeout_budget=timeout_budget, task_type="email_generation", user_id=user_id)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_call)
            result = future.result(timeout=timeout_budget)
            if result and len(result.strip()) > 5:
                return result.strip()
    except Exception:
        pass
    return None

def get_sender_display_name(user_id: Optional[Any] = None) -> Optional[str]:
    """Resolves the user's authentic display name for email sign-offs without hallucinations."""
    if user_id is not None:
        if isinstance(user_id, int) or (isinstance(user_id, str) and user_id.isdigit()):
            uid = int(user_id)
            try:
                from legacy.memory_manager import get_username_by_id
                uname = get_username_by_id(uid)
                if uname:
                    u_str = str(uname).strip()
                    if u_str.lower() == "ram":
                        return "Ram Sathvik"
                    return u_str.capitalize()
            except Exception:
                pass
        elif isinstance(user_id, str):
            u_clean = user_id.strip()
            if u_clean.lower() == "ram":
                return "Ram Sathvik"
            elif u_clean.lower() not in ("user", "default", "none", "", "default_user"):
                return u_clean.capitalize()

    try:
        from instance.config import settings
        cur_u = getattr(settings, "CURRENT_USERNAME", None)
        if cur_u and str(cur_u).strip().lower() not in ("user", "default", "none", ""):
            u_clean = str(cur_u).strip()
            if u_clean.lower() == "ram":
                return "Ram Sathvik"
            return u_clean.capitalize()
    except Exception:
        pass

    try:
        from instance.config import settings
        uid = getattr(settings, "CURRENT_USER_ID", None)
        if uid:
            from legacy.memory_manager import get_username_by_id
            uname = get_username_by_id(uid)
            if uname:
                u_str = str(uname).strip()
                if u_str.lower() == "ram":
                    return "Ram Sathvik"
                return u_str.capitalize()
    except Exception:
        pass

    return None

def clean_recipient_label(recip: str) -> str:
    """Normalizes natural spoken recipient labels to natural greetings."""
    r = (recip or "").strip()
    r_low = r.lower()
    if r_low in ("my professor", "professor", "the professor"):
        return "Professor"
    if r_low in ("hr", "human resources", "the hr", "my hr"):
        return "HR Team"
    if r_low in ("customer support", "support", "customer service", "the support team", "the customer support"):
        return "Customer Support Team"
    if r_low in ("my team", "team", "the team"):
        return "Team"
    if r_low in ("my friend", "friend", "a friend"):
        return "Friend"
    if r_low.startswith("my "):
        return r[3:].strip().capitalize()
    return r or "Sir/Madam"

def detect_email_category(topic: str, recipient: str = "") -> str:
    """Classifies email topic into semantic category for contextual expansion."""
    t = (topic or "").lower()
    r = (recipient or "").lower()
    combined = f"{r} {t}"

    if re.search(r'\b(?:short|one[- ]line|brief|quick\s+note|keep\s+it\s+(?:short|brief|to\s+one\s+line))\b', t):
        return "short_request"
    if re.search(r'\b(?:extension|more\s+time|extend\s+(?:the\s+)?deadline|postpone)\b', t):
        return "academic_extension"
    if re.search(r'\b(?:reexam|re-exam|re\s+exam)\b', t) or (re.search(r'\b(?:exam|examination|test)\b', t) and any(w in t for w in ["tomorrow", "warn", "last chance", "mandatory", "miss"])):
        return "academic_exam"
    if any(k in r for k in ["professor", "faculty", "dean", "instructor"]) or "professor" in t:
        return "academic_general"
    if any(k in combined for k in ["internship", "job application", "recruiter", "hiring", "interview", "candidacy", "intern application"]):
        return "job_internship"
    if any(k in combined for k in ["customer support", "customer service", "support team", "complain", "complaint", "technical issue", "bug report", "billing issue", "the issue"]):
        return "customer_support"
    if any(k in t for k in ["thank", "thanks", "gratitude", "grateful", "appreciate", "helping"]):
        return "thank_you"
    if any(k in t for k in ["lost the game", "game we lost", "match we lost", "we lost", "win next time"]):
        return "gaming_team_match"
    if any(k in t for k in ["tournament", "championship", "scrimmage", "bracket"]):
        return "gaming_tournament"
    if any(k in t for k in ["meeting", "schedule a call", "discuss project", "sync up", "conference"]):
        return "meeting_request"
    if any(k in t for k in ["apologize", "sorry", "regret"]):
        return "apology"
    return "general"

def is_explicit_short_request(topic: str) -> bool:
    """Checks whether the user explicitly requested a short or one-line email."""
    t = (topic or "").lower()
    return bool(re.search(r'\b(?:short\s+(?:email|mail|message)|one[- ]line|brief\s+(?:email|mail|note)|quick\s+note|just\s+say|keep\s+it\s+(?:short|brief|to\s+one\s+line))\b', t))

def clean_topic_phrase(topic: str) -> str:
    """Strips leading command boilerplates to extract clean subject core."""
    t = re.sub(
        r'^(?:send\s+(?:an?\s+|another\s+)?(?:short\s+)?(?:email|mail|message)\s+(?:to\s+.+?\s+)?|'
        r'email\s+(?:to\s+.+?\s+)?|mail\s+(?:to\s+.+?\s+)?|write\s+(?:to\s+.+?\s+)?|'
        r'tell\s+(?:him|her|them)\s+(?:that)?\s*|saying\s+|say\s+|that\s+|about\s+|regarding\s+|'
        r'asking\s+for\s+|requesting\s+(?:a\s+meeting\s+to\s+discuss\s+)?)+',
        '', topic, flags=re.I
    ).strip()
    return re.sub(r'\b(?:short\s+(?:email|mail|message)|one[- ]line|brief\s+(?:email|mail|note)|quick\s+note|with\s+a\s+short\s+email)\b', '', t, flags=re.I).strip(' ,.:;!?')

def generate_subject_from_text(raw_text: str, recipient_name: str = "", category: str = "") -> str:
    """Generates an appropriate, specific subject line from email intent text."""
    low = (raw_text or "").lower()
    cat = category or detect_email_category(raw_text, recipient_name)

    if cat == "academic_extension":
        return "Request for Extension on Assignment Submission"
    if cat == "academic_exam":
        if "tomorrow" in low:
            return "Urgent Notice: Tomorrow's Re-Examination"
        return "Important Notice: Examination Schedule Update"
    if cat == "academic_general":
        return "Academic Inquiry & Coursework Update"
    if cat == "job_internship":
        return "Inquiry Regarding Internship Application Status"
    if cat == "customer_support":
        return "Support Inquiry: Assistance Needed Regarding Open Issue"
    if cat == "thank_you":
        return "Sincere Thanks for Your Help"
    if cat == "gaming_team_match":
        return "Reflecting on Our Match and Moving Forward Together"
    if cat == "gaming_tournament":
        return "Update on the Upcoming Tournament"
    if cat == "meeting_request":
        return "Meeting Request: Discussion on Project Priorities"
    if cat == "apology":
        return "Sincere Apologies Regarding Recent Event"
    if cat == "short_request":
        clean_top = clean_topic_phrase(raw_text)
        return f"Quick Note: {clean_top.capitalize() if clean_top else 'Important Update'}"

    # General domain rules
    if any(k in low for k in ["progress", "status", "update"]):
        return "Project Progress & Status Update"
    if any(k in low for k in ["result", "results", "score", "scores"]):
        return "Inquiry Regarding Latest Results"
    if any(k in low for k in ["report", "document", "file", "presentation", "sheet"]):
        return "Document Review & Submission"
    if any(k in low for k in ["leave", "sick", "vacation", "absence"]):
        return "Notification of Leave"

    clean_top = clean_topic_phrase(raw_text)
    if clean_top and len(clean_top) > 3:
        return f"Update Regarding {clean_top[0].upper() + clean_top[1:]}"
    return "Important Update & Notice"

def sanitize_generated_body(body: str, sender_name: Optional[str] = None, recipient_name: str = "") -> str:
    """Cleans up hallucinated bracketed placeholders and ensures truthful sign-off."""
    if not body:
        return ""
    b = body

    # Replace bracketed placeholder tokens with natural phrases or sender name
    if sender_name:
        b = re.sub(r'\[(?:Your\s+Name|Your\s+Full\s+Name|Sender\s+Name|Name)\]', sender_name, b, flags=re.I)
    else:
        b = re.sub(r'\[(?:Your\s+Name|Your\s+Full\s+Name|Sender\s+Name|Name)\]', '', b, flags=re.I)

    b = re.sub(r'\[(?:Assignment\s+Name|Course/Assignment\s+Name)\]', 'the assignment', b, flags=re.I)
    b = re.sub(r'\[Course\s+Name\]', 'our course', b, flags=re.I)
    b = re.sub(r'\[Due\s+Date\]', 'the scheduled due date', b, flags=re.I)
    b = re.sub(r'\[Date\]', 'the scheduled date', b, flags=re.I)
    b = re.sub(r'\[(?:brief,?\s*objective\s+reason|brief\s+reason|insert\s+reason|reason)\]', 'unforeseen circumstances', b, flags=re.I)
    b = re.sub(r'\[(?:Number|number|\d+)\]\s*days?', 'a few days', b, flags=re.I)
    b = re.sub(r'\[(?:Company\s+Name|Organization\s+Name)\]', 'your organization', b, flags=re.I)
    b = re.sub(r'\[([a-zA-Z0-9_\s]{2,30})\]', r'\1', b)

    # Ensure truthful sender name in closing
    if sender_name:
        lines = b.rstrip().split('\n')
        signoff_markers = ['best regards', 'warm regards', 'sincerely', 'thank you', 'thanks', 'cheers', 'regards']
        found_signoff = False
        for i in range(len(lines) - 1, -1, -1):
            line_low = lines[i].strip().lower().rstrip(',.')
            if any(line_low == m or line_low.startswith(m) for m in signoff_markers):
                found_signoff = True
                remainder = lines[i+1:] if i + 1 < len(lines) else []
                remainder_text = ' '.join(r.strip() for r in remainder if r.strip())
                if remainder_text and remainder_text != sender_name:
                    lines = lines[:i+1] + [sender_name]
                    b = '\n'.join(lines)
                elif not remainder_text:
                    lines = lines[:i+1] + [sender_name]
                    b = '\n'.join(lines)
                break
        if not found_signoff:
            b = f"{b.rstrip()}\n\nBest regards,\n{sender_name}"

    return b.strip()

def _format_fallback_body(raw_text: str, recipient_name: str, tone: str = "professional", user_id: Optional[Any] = None) -> str:
    """
    Context-aware deterministic local fallback generator when AI engine is offline or unavailable.
    Constructs a complete, multi-paragraph, professional email expanding the user's intent naturally.
    """
    cleaned = (raw_text or "").strip()
    clean_name = clean_recipient_label(recipient_name)
    category = detect_email_category(cleaned, recipient_name)
    sender_name = get_sender_display_name(user_id)
    topic_core = clean_topic_phrase(cleaned)

    salutation = f"Hi {clean_name}," if (tone in ("friendly", "casual") or category in ("gaming_tournament", "gaming_team_match", "thank_you")) else f"Dear {clean_name},"
    closing_word = "Warm regards," if (tone in ("friendly", "casual") or category == "thank_you") else ("Sincerely," if category == "academic_extension" else "Best regards,")
    signoff = f"{closing_word}\n{sender_name}" if sender_name else closing_word

    if category == "short_request" or tone in ("short", "concise") or is_explicit_short_request(cleaned):
        short_topic = topic_core or cleaned or "our discussion"
        if any(w in short_topic.lower() for w in ["luck", "match", "game"]):
            msg = "Just wanted to drop a quick note to say good luck in the match! You've got this."
        else:
            msg = f"Just a quick note regarding {short_topic}. Please let me know if you need anything else from my side."
        return f"{salutation}\n\n{msg}\n\n{signoff}"

    if category == "academic_extension":
        return f"""{salutation}

I hope this email finds you well. I am writing to respectfully request a brief extension on the upcoming assignment submission.

I am committed to submitting thorough and high-quality work, and having a short extension would allow me to review and finalize my material to the required standard. I am currently making steady progress and would be glad to share my current draft with you.

Thank you very much for your time, guidance, and consideration. Please let me know if this request is feasible.

{signoff}"""

    if category == "academic_exam":
        warning = ""
        if "no other chance" in cleaned.lower():
            warning = " Please be advised that if you miss this, there is no other chance."
        elif "last chance" in cleaned.lower():
            warning = " Please be advised that this is your last chance to take this examination."
        return f"""{salutation}

I am writing to send you an important reminder regarding the re-examination scheduled for tomorrow.

Please make sure you are thoroughly prepared and arrive well ahead of time. This is a critical opportunity, so it is vital that you do not miss it under any circumstances.{warning}

Please double-check that you have all necessary materials ready and confirm that you have noted the schedule.

{signoff}"""

    if category == "job_internship":
        return f"""{salutation}

I hope you are having a productive week. I am writing to politely follow up on the status of my recent internship application.

I remain very enthusiastic about the opportunity to contribute to your team and organization. I would greatly appreciate any update you might have regarding the review timeline or upcoming stages in the selection process.

If you require any additional information, portfolio samples, or references from my side, please feel free to let me know. Thank you for your time and consideration.

{signoff}"""

    if category == "customer_support":
        return f"""{salutation}

I am writing to report an issue that I have encountered and would appreciate your assistance in looking into it.

I would be grateful if you could investigate this matter or provide guidance on the appropriate troubleshooting steps to help resolve it. If you need any further details, screenshots, or account verification from my end, I am happy to provide them.

Thank you for your prompt attention to this matter. I look forward to your guidance and resolution.

{signoff}"""

    if category == "thank_you":
        return f"""{salutation}

I just wanted to take a moment to send a note of sincere thanks for your help.

Your support made a real difference, and I truly appreciate the time, patience, and effort you shared to assist me. It is wonderful having someone like you to count on.

Let's connect again soon. Thanks once again for everything!

{signoff}"""

    if category == "gaming_team_match":
        return f"""{salutation}

I wanted to reach out to everyone following our recent match. While the outcome was not what we hoped for, everyone gave a tremendous effort out there.

Every tough game is a valuable learning opportunity for us to review what happened, refine our strategy, and build even stronger teamwork. I have complete confidence in our abilities, and if we stay focused and keep supporting each other, we can definitely secure the win next time.

Let's keep our spirits high and regroup for our next practice session. Looking forward to our next match together!

{signoff}"""

    if category == "gaming_tournament":
        return f"""{salutation}

I wanted to reach out regarding the tournament that was recently announced.

It looks like a great opportunity for us to compete. Let's connect soon so we can go over the format, plan our practice schedule, and make sure our team is fully prepared to jump in.

Let me know when you're free to catch up and talk through our strategy.

{signoff}"""

    if category == "meeting_request":
        topic_phrase = f"our discussion on {topic_core}" if topic_core else "our upcoming priorities"
        return f"""{salutation}

I hope you are having a great week. I would like to request a brief meeting to discuss {topic_phrase}.

I believe a direct discussion will help us align on priorities, address key questions, and coordinate our next steps effectively. I have gathered the relevant details and would welcome your perspective and guidance.

Please let me know what day and time might work best for your schedule, and I will be happy to coordinate our calendars accordingly.

{signoff}"""

    # General / Informational
    topic_phrase = topic_core[0].lower() + topic_core[1:] if topic_core else "our upcoming activities"
    return f"""{salutation}

I hope this message finds you well. I am writing to provide you with an update regarding {topic_phrase}.

I wanted to ensure you have the latest details and context regarding this matter so that we remain aligned. Please feel free to review this and let me know if you have any questions or require any further clarification.

I will keep you updated as things progress. Looking forward to hearing your thoughts.

{signoff}"""

def rewrite_professional(raw_text: str, recipient_name: str = "Sir/Madam", tone: str = "professional", user_id: Optional[Any] = None) -> Tuple[str, str]:
    """
    Converts spoken instructions or topics into a complete, articulate, contextually appropriate email.
    Uses LLMEngine with rich prompts and strict factual integrity rules, falling back gracefully
    to the context-aware deterministic local engine if all LLM providers fail or timeout.
    """
    clean_name = clean_recipient_label(recipient_name)
    category = detect_email_category(raw_text, recipient_name)
    sender_name = get_sender_display_name(user_id)
    topic_core = clean_topic_phrase(raw_text)
    is_short = is_explicit_short_request(raw_text) or tone.lower() in ("short", "concise") or category == "short_request"

    tone_guidelines = {
        "formal": "Strictly formal, polite, respectful, and structured.",
        "professional": "Professional, articulate, respectful, and well-organized.",
        "friendly": "Warm, approachable, conversational, supportive, and clear.",
        "casual": "Casual, natural, warm, and clear.",
        "concise": "Concise, punchy, direct to the point, minimal fluff.",
        "short": "Brief, concise, punchy, direct to the point, approximately 1-2 short sentences or one concise paragraph.",
        "persuasive": "Persuasive, compelling, clearly highlighting benefits and urgency.",
        "technical": "Precise, structured, and technically accurate.",
        "follow_up": "Courteous follow-up referencing prior discussion."
    }
    style_instruction = tone_guidelines.get(tone.lower(), tone_guidelines["professional"])

    if is_short:
        length_guideline = "LENGTH: Keep the email concise and brief (1 short paragraph) as explicitly requested by the user."
    elif tone in ("friendly", "casual"):
        length_guideline = "LENGTH: Produce approximately 2-3 natural, meaningful paragraphs with appropriate breathing room."
    elif category in ("academic_extension", "academic_exam", "job_internship", "customer_support"):
        length_guideline = "LENGTH: Produce approximately 3-4 structured, informative paragraphs (opening, context/rationale, next steps/call to action, closing)."
    else:
        length_guideline = "LENGTH: Produce approximately 2-4 well-structured paragraphs providing complete, helpful context."

    prompt = f"""You are an expert executive email assistant. Convert the user's message request into a complete, well-crafted, and contextually appropriate email.

Recipient: {clean_name} (desired style: {style_instruction})
Sender: {sender_name or "The User"}
User's Message Request: "{raw_text}"

Requirements:
1. SUBJECT LINE: Generate a concise, specific, and clear subject line (do NOT use generic titles like "Email" or "Update").
2. GREETING: Start with an appropriate greeting (e.g., "Hi {clean_name}," for friendly/team, "Dear {clean_name}," or "Dear Professor," for formal/academic/support).
3. OPENING PARAGRAPH: Clearly and naturally explain why you are writing.
4. BODY PARAGRAPHS: Meaningfully expand the user's request. Elaborate on the situation, purpose, background, encouragement, or rationale naturally with helpful detail. Do NOT merely repeat or copy the user's sentence.
5. NEXT STEPS / CALL TO ACTION: Include relevant implications, next steps, or a polite question/call to action.
6. CLOSING & SIGN-OFF: End with a natural closing sentence and a sign-off (e.g., "Best regards," or "Warm regards," followed by "{sender_name or ''}").
7. {length_guideline}
8. FACTUAL INTEGRITY CONSTRAINTS:
   - PRESERVE all facts stated by the user.
   - DO NOT invent fake specific facts, fake deadlines, fake venues, fake scores, or fake names.
   - NEVER use bracketed placeholder tokens such as [Your Name], [Assignment Name], [Due Date], [Insert Reason]. Write around missing specifics naturally.
   - Do NOT invent or sign with any name other than "{sender_name or ''}".

Format your output strictly as:
Subject: <subject line>

<full email body>
"""

    ai_output = generate_with_ai(prompt, max_tokens=650, timeout_budget=12.0, user_id=user_id)
    if not ai_output:
        subject = generate_subject_from_text(raw_text, recipient_name=clean_name, category=category)
        body = _format_fallback_body(raw_text, recipient_name=clean_name, tone=tone, user_id=user_id)
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
        elif in_body or stripped.lower().startswith("dear") or stripped.lower().startswith("hi") or stripped.lower().startswith("hello"):
            in_body = True
            body_lines.append(line)

    body = '\n'.join(body_lines).strip()
    if not subject:
        subject = generate_subject_from_text(raw_text, recipient_name=clean_name, category=category)

    # Sanitize placeholders and verify body quality
    body = sanitize_generated_body(body, sender_name=sender_name, recipient_name=clean_name)

    # Quality and depth validation:
    # If LLM failed to produce a body or returned a 1-sentence fragment when a full email was expected:
    words = body.split()
    min_words = 5 if is_short else 25
    if not body or len(words) < min_words:
        body = _format_fallback_body(raw_text, recipient_name=clean_name, tone=tone, user_id=user_id)

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
