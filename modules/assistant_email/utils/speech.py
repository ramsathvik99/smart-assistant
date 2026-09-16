import pyttsx3
import speech_recognition as sr
import random

# Initialize TTS
engine = pyttsx3.init()
engine.setProperty('rate', 160)

# Initialize Recognizer
recognizer = sr.Recognizer()

def speak(text):
    print(f"Assistant: {text}")
    engine.say(text)
    engine.runAndWait()

def speak_dynamic(category="confirm"):
    responses = {
        "confirm": ["Got it.", "Alright.", "Done.", "Understood.", "Okay."],
        "listening": ["Go ahead, I'm listening.", "I'm ready, what's your message?", "I'm listening.", "Please dictate your email."]
    }
    choices = responses.get(category, responses["confirm"])
    speak(random.choice(choices))

def clean_speech(text):
    if not text:
        return ""
    text = text.lower().strip()
    
    # Remove filler words
    fillers_exact = ["uh", "um", "like", "you know"]
    text_words = text.split()
    
    cleaned_words = []
    for w in text_words:
        if w not in fillers_exact:
            cleaned_words.append(w)
            
    text = " ".join(cleaned_words)
    
    # Handle misrecognitions
    replacements = {
        "send male": "send mail",
        "read male": "read mail",
        "compose male": "compose mail",
        "male someone": "mail someone"
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
        
    return text.strip()

def listen():
    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=1)
        while True:
            try:
                audio = recognizer.listen(source, timeout=None)
                raw_text = recognizer.recognize_google(audio)
                text = clean_speech(raw_text)
                
                if text:
                    # Only react when valid speech detected
                    print("Captured:", text)
                    return text
                
            except Exception:
                # Do NOT spam logs during silence.
                continue

def listen_continuous():
    full_text = ""
    while True:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.3)
            try:
                print("Listening for message...")
                audio = recognizer.listen(
                    source,
                    timeout=5,
                    phrase_time_limit=8
                )
                chunk = recognizer.recognize_google(audio)
                chunk = chunk.lower().strip()
                print("Captured:", chunk)
                # STOP CONDITION
                if any(x in chunk for x in ["stop message", "stop", "end", "finish"]):
                    break
                # CRITICAL: accumulate correctly
                full_text = full_text + " " + chunk
                print("CURRENT FULL TEXT:", full_text)
            except sr.WaitTimeoutError:
                continue
            except Exception as e:
                print("Speech error:", e)
                continue
                
    full_text = full_text.strip()
    print("FINAL MESSAGE:", full_text)
    return full_text
