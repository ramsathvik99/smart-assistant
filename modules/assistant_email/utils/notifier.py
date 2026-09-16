import time
import threading
from email_reader import fetch_latest_emails
from utils.speech import speak

class EmailNotifier(threading.Thread):
    def __init__(self, interval=30):
        super().__init__()
        self.interval = interval
        self.daemon = True
        self.last_seen_subject = None
        self.running = True

    def run(self):
        while self.running:
            try:
                emails = fetch_latest_emails(limit=1)
                if emails:
                    latest = emails[0]
                    if latest['subject'] != self.last_seen_subject:
                        if self.last_seen_subject is not None:
                            speak(f"You received a new email from {latest['sender']}. Subject: {latest['subject']}")
                        self.last_seen_subject = latest['subject']
            except Exception as e:
                print(f"Notifier error: {e}")
            
            time.sleep(self.interval)

    def stop(self):
        self.running = False
