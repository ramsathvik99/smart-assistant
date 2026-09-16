import random

RESPONSES = [
    "Yes?",
    "I'm listening.",
    "Go ahead.",
    "Yes Boss."
]

def get_wake_response():
    """Returns a random professional wake response."""
    return random.choice(RESPONSES)
