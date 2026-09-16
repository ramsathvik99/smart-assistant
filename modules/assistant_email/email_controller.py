import os
from .email_memory import resolve_contact, save_contact
from .email_sender import send_email
from .email_ai import generate_email_structure, generate_summary, generate_reply
from .email_reader import fetch_latest_emails, get_latest_email
from .email_ui import get_email_credentials_popup, show_email_editor
from .user_storage import get_user_email, save_user_email
from dotenv import load_dotenv

# ── GLOBAL CONFIG ────────────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
ENV_PATH = os.path.join(PROJECT_ROOT, "legacy", ".env")
load_dotenv(ENV_PATH)

# Nova current user context (as specified by user)
CURRENT_USER = "ram"

try:
    from legacy.tts import speak
    from legacy.sst import listen, listen_continuous
except ImportError:
    def speak(t): print(f"ASSISTANT: {t}")
    def listen(): return input("USER: ")
    def listen_continuous(t): return input(f"USER (until stop message): ")

def _audio_available() -> bool:
    """Return True only when PyAudio / microphone hardware is usable."""
    try:
        import speech_recognition as _sr
        _sr.Microphone()
        return True
    except Exception:
        return False

def get_credentials():
    """Fetches user credentials from JSON or pops up if missing."""
    email, password = get_user_email(CURRENT_USER)
    if not email or not password:
        speak("I don't have your email credentials saved. Please enter them in the popup.")
        email, password = get_email_credentials_popup()
        if email and password:
            save_user_email(CURRENT_USER, email, password)
            speak("Credentials saved successfully.")
        else:
            speak("I couldn't get your credentials. I won't be able to send or read emails.")
            return None, None
    return email, password

def listen_for_recipient():
    """
    Patiently listens for a valid recipient name with retries and reminders.
    """
    max_attempts = 3
    timeout_seconds = 6

    for attempt in range(max_attempts):
        if attempt == 0:
            speak("Who do you want to send the email to?")
        
        response = listen(timeout=timeout_seconds)

        if response and len(response.strip()) > 1:
            return response.strip()

        # If no response or invalid input
        if attempt < max_attempts - 1:
            speak("I didn't catch that. Please tell me the recipient name.")
        else:
            speak("No response received. Cancelling email.")
            return None

def handle_email_command(command):
    # Step 1: Ensure credentials exist
    email_id, email_pass = get_credentials()
    if not email_id: return

    # Try to extract recipient from command like "send email to [Name]"
    initial_recipient = None
    if " to " in command.lower():
        parts = command.lower().split(" to ", 1)
        if len(parts) > 1:
            initial_recipient = parts[1].strip()
    
    if "send" in command or "compose" in command or "write" in command:
        handle_send_email(initial_recipient, email_id, email_pass)
    elif "check" in command or "inbox" in command or "list" in command:
        handle_check_inbox(email_id, email_pass)
    elif "read" in command or "open" in command:
        handle_read_email(email_id, email_pass)
    elif "summarize" in command or "summary" in command:
        handle_summarize_inbox(email_id, email_pass)
    elif "reply" in command:
        handle_reply_to_latest(email_id, email_pass)
    elif "add" in command and "contact" in command:
        handle_add_contact()
    else:
        speak("I'm not sure what you want to do with email. You can say send email, check inbox, or summarize mail.")

def handle_send_email(initial_recipient, sender_email, sender_pass):
    # STEP 2: RESOLVE RECIPIENT
    if initial_recipient:
        recipient_name = initial_recipient
    else:
        # If no audio hardware available, we cannot ask for recipient interactively
        if not _audio_available():
            speak("Email send requires voice input, but audio hardware is unavailable.")
            return
        recipient_name = listen_for_recipient()
    
    if not recipient_name: return
    
    recipient_email = resolve_contact(recipient_name)
    if not recipient_email:
        speak(f"I don't have an email for {recipient_name}. Please type it in the popup.")
        from .email_utils import get_text_input
        recipient_email = get_text_input("Contact Email", f"Enter email for {recipient_name}:")
        if recipient_email:
            save_contact(recipient_name, recipient_email)
    
    if not recipient_email:
        speak("I couldn't get a valid recipient email.")
        return

    # STEP 3: CAPTURE MESSAGE (VOICE ONLY)
    if not _audio_available():
        speak("Audio hardware unavailable. Cannot capture message voice input.")
        return

    speak("Start speaking your message. Say 'stop message' when done.")
    raw_text = listen_continuous("stop message")
    
    if not raw_text:
        speak("I didn't capture any message.")
        return
    
    # STEP 4: REWRITE MESSAGE PROFESSIONALLY (STRICT)
    speak("Processing and rewriting your message...")
    subject, body = generate_email_structure(raw_text, recipient_name)
    
    # STEP 5: VOICE CONFIRMATION AFTER PROCESSING
    speak("Your email is ready. Do you want to send it, edit it, or cancel?")
    
    while True:
        response = listen().lower()
        print(f"[DEBUG] USER DECISION: {response}")
        
        if "send" in response:
            # Send email directly
            speak("Sending email...")
            if send_email(recipient_email, subject, body, sender_email, sender_pass):
                speak("Email sent successfully.")
            else:
                speak("Failed to send email. Check your connection or credentials.")
            return
            
        elif "edit" in response:
            # Open popup for editing
            speak("Please review and edit the draft in the popup window.")
            edited = show_email_editor(subject, body, recipient_email, sender_email, sender_pass)
            
            if not edited["confirmed"]:
                speak("Email cancelled.")
                return
            
            if edited["sent"]:
                # Email was sent from popup
                return
                
            # Update with edited content and send
            subject = edited["subject"]
            body = edited["body"]
            speak("Sending edited email...")
            if send_email(recipient_email, subject, body, sender_email, sender_pass):
                speak("Email sent successfully.")
            else:
                speak("Failed to send email. Check your connection or credentials.")
            return
            
        elif "cancel" in response or "stop" in response or "abort" in response:
            speak("Email cancelled.")
            return
            
        else:
            speak("Please say send, edit, or cancel.")

def handle_check_inbox(email_id, email_pass):
    speak("Fetching your latest emails...")
    emails = fetch_latest_emails(limit=5, email_id=email_id, email_pass=email_pass)
    if not emails:
        speak("Your inbox is empty or I couldn't access it.")
        return
    
    speak(f"You have {len(emails)} recent emails.")
    for i, e in enumerate(emails):
        speak(f"Email {i+1} is from {e['sender']} regarding {e['subject']}")
    

def handle_summarize_inbox(email_id, email_pass):
    speak("Working on a summary of your latest emails...")
    emails = fetch_latest_emails(limit=10, email_id=email_id, email_pass=email_pass)
    summary = generate_summary(emails)
    speak(summary)

def handle_read_email(email_id, email_pass):
    speak("Which email number should I read?")
    num_text = listen()
    try:
        idx = int(''.join(filter(str.isdigit, num_text))) - 1
        emails = fetch_latest_emails(limit=10, email_id=email_id, email_pass=email_pass)
        if 0 <= idx < len(emails):
            e = emails[idx]
            speak(f"From: {e['sender']}")
            speak(f"Subject: {e['subject']}")
            # Not speaking body as per request to keep it professional/silent review if possible
            # But for reading mail, we must speak it.
            speak("Content:")
            speak(e['body'])
        else:
            speak("I couldn't find that email.")
    except:
        speak("I didn't catch the email number.")

def handle_reply_to_latest(email_id, email_pass):
    speak("Fetching the latest email to reply to...")
    latest = get_latest_email(email_id, email_pass)
    if not latest:
        speak("No emails found to reply to.")
        return
        
    speak(f"Replying to {latest['sender']} regarding {latest['subject']}")
    speak("Generating professional reply...")
    reply_body = generate_reply(f"From: {latest['sender']}\nSubject: {latest['subject']}\nBody: {latest['body']}")
    
    speak("Please review the reply in the popup.")
    edited = show_email_editor(f"Re: {latest['subject']}", reply_body, latest['sender'], email_id, email_pass)
    
    if not edited["confirmed"]:
        speak("Reply cancelled.")
        return
    
    if edited["sent"]:
        # Reply was sent from popup, no need for confirmation
        return
        
    subject = edited["subject"]
    body = edited["body"]

    while True:
        speak("Should I send this reply? Please say yes or no.")
        confirm = listen().lower()
        if "yes" in confirm or "send" in confirm:
            recipient_email = latest['sender']
            if "<" in recipient_email: 
                recipient_email = recipient_email.split("<")[-1].split(">")[0]
            if send_email(recipient_email, subject, body, email_id, email_pass):
                speak("Reply sent successfully.")
            else:
                speak("Failed to send reply.")
            return
        elif "no" in confirm or "cancel" in confirm:
            speak("Reply cancelled.")
            return
        else:
            speak("Please say yes or no.")

def handle_add_contact():
    name = listen_for_recipient()
    if not name: return
    speak(f"Please type the email address for {name} in the popup.")
    from .email_utils import get_text_input
    email_addr = get_text_input("New Contact", f"Email for {name}")
    if email_addr and save_contact(name, email_addr):
        speak(f"Contact {name} added.")
    else:
        speak("Could not save contact.")
