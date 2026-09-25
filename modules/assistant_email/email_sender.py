import smtplib
import os
import mimetypes
from email.message import EmailMessage
from typing import List, Optional

def send_email(to_email, subject, body, email_id=None, email_pass=None, attachments: Optional[List[str]] = None):
    """
    Sends an email using provided credentials, with optional attachments.
    """
    if not email_id or not email_pass:
        print("❌ Dynamic email credentials missing")
        return False
        
    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = email_id
    msg['To'] = to_email
    
    # Process attachments
    if attachments:
        for fpath in attachments:
            if os.path.isfile(fpath):
                ctype, encoding = mimetypes.guess_type(fpath)
                if ctype is None or encoding is not None:
                    ctype = 'application/octet-stream'
                maintype, subtype = ctype.split('/', 1)
                try:
                    with open(fpath, 'rb') as fp:
                        msg.add_attachment(
                            fp.read(),
                            maintype=maintype,
                            subtype=subtype,
                            filename=os.path.basename(fpath)
                        )
                except Exception as att_err:
                    print(f"⚠️ Warning: Could not attach '{fpath}': {att_err}")

    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(email_id, email_pass)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"❌ SMTP Error: {e}")
        return False
