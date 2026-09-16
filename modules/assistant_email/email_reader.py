import imaplib
import email
import re
import time
import os
from email.header import decode_header

# Cache structure: {"time": stamp, "data": []}
_email_cache = {"time": 0, "data": []}
CACHE_TTL = 60 # 60 seconds caching

def strip_html(text):
    if not text: return ""
    clean = re.sub(r'<[^>]+>', ' ', text)
    return " ".join(clean.split())

def fetch_latest_emails(limit=5, email_id=None, email_pass=None):
    global _email_cache
    if time.time() - _email_cache["time"] < CACHE_TTL and _email_cache["data"]:
        return _email_cache["data"][:limit]

    if not email_id or not email_pass:
        return []

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_id, email_pass)
        mail.select("inbox")
        _, messages = mail.search(None, "ALL")
        email_ids = messages[0].split()
        fetch_limit = max(limit, 10)
        latest_email_ids = email_ids[-fetch_limit:]
        
        email_list = []
        for e_id in reversed(latest_email_ids):
            _, msg_data = mail.fetch(e_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject_data = decode_header(msg.get("Subject", ""))[0]
                    subject, encoding = subject_data
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding if encoding else "utf-8", errors="ignore")
                    sender = msg.get("From")
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            if content_type == "text/plain":
                                try:
                                    body = part.get_payload(decode=True).decode(errors="ignore")
                                except: pass
                                break
                    else:
                        body_bytes = msg.get_payload(decode=True)
                        if body_bytes: body = body_bytes.decode(errors="ignore")
                    email_list.append({
                        "subject": str(subject),
                        "sender": str(sender),
                        "body": strip_html(body)
                    })
        mail.close()
        mail.logout()
        if email_list:
            _email_cache["time"] = time.time()
            _email_cache["data"] = email_list
        return email_list[:limit]
    except Exception as e:
        print(f"❌ Reader Error: {e}")
        return _email_cache["data"][:limit] if _email_cache["data"] else []

def get_latest_email(email_id=None, email_pass=None):
    emails = fetch_latest_emails(limit=1, email_id=email_id, email_pass=email_pass)
    return emails[0] if emails else None
