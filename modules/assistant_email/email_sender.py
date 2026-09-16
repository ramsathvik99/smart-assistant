import smtplib
import os
from email.message import EmailMessage

def send_email(to_email, subject, body, email_id=None, email_pass=None):
    """
    Sends an email using provided credentials.
    """
    if not email_id or not email_pass:
        print("❌ Dynamic email credentials missing")
        return False
        
    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = email_id
    msg['To'] = to_email
    
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(email_id, email_pass)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"❌ SMTP Error: {e}")
        return False
