def extract_context(user_input):
    text = user_input.lower()

    context = {
        "type": None,
        "language": "english",
        "tone": "neutral",
        "keywords": []
    }

    # TYPE DETECTION
    if "movie" in text:
        context["type"] = "movies"
    elif "song" in text or "music" in text:
        context["type"] = "songs"
    elif "life" in text or "advice" in text:
        context["type"] = "life"
    else:
        context["type"] = "general"

    # LANGUAGE DETECTION
    if "telugu" in text:
        context["language"] = "telugu"
    elif "hindi" in text:
        context["language"] = "hindi"

    # TONE DETECTION
    if any(word in text for word in ["sad", "depressed", "low", "tired"]):
        context["tone"] = "sad"
    elif any(word in text for word in ["bored", "nothing to do"]):
        context["tone"] = "bored"
    elif any(word in text for word in ["happy", "excited"]):
        context["tone"] = "excited"

    context["keywords"] = text.split()

    return context


def build_prompt(context, user_input):
    return f"""
You are a smart recommendation assistant.

User request: {user_input}

Context:
- Type: {context['type']}
- Language: {context['language']}
- Tone: {context['tone']}

Generate high-quality personalized recommendations.

Rules:
- Match the user's tone (if sad → comforting, if bored → engaging)
- Recommend based on language preference
- Give 5-7 suggestions
- Add short explanation for each
- Keep it natural and human-like
"""


def get_recommendations(user_input, ai_generate):
    context = extract_context(user_input)
    prompt = build_prompt(context, user_input)

    response = ai_generate(prompt)

    return response
