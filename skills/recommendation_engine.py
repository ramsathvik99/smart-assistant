"""
Smart Assistant — Balanced Recommendation Intelligence Engine
Balances personalization with serendipitous discovery across 4 core pillars:
1. Personalized Choices ([For Your Taste]): closely matches established taste and preferences.
2. Related Alternatives ([Related Alternative]): connected to interests but different from usual choices.
3. Fresh Discoveries ([Fresh Discovery]): high-quality standout options outside usual habits.
4. Contextually Relevant ([Tailored to Request]): options fulfilling the current situation or explicit constraints.

Explicit constraints (e.g. "only action", "comedy movies", "rust only") are strictly obeyed.
Stored user preferences in PostgreSQL / DialogueStateManager act as guidance rather than restrictive filters.
"""

from extensions.ai_utils import ask_llm
from datetime import datetime
import re
import json
from typing import Optional, Dict, Any, List, Tuple

current_year = datetime.now().year

# Multi-domain catalog database for rich, diverse offline recommendations
CATALOG_DB: Dict[str, List[Dict[str, Any]]] = {
    "movies": [
        # Action
        {"title": "John Wick: Chapter 4", "genre": "action", "subgenres": ["action", "martial arts", "thriller"],
         "desc": "High-octane martial arts choreography and gun-fu with Keanu Reeves (2023)", "year": 2023},
        {"title": "Top Gun: Maverick", "genre": "action", "subgenres": ["action", "aviation", "drama"],
         "desc": "Thrilling aerial combat, practical jet cinematography, and emotional payoff (2022)", "year": 2022},
        {"title": "Mission: Impossible – Dead Reckoning", "genre": "action", "subgenres": ["action", "espionage", "thriller"],
         "desc": "Intense globe-trotting espionage and practical stuntwork led by Tom Cruise (2023)", "year": 2023},
        {"title": "Extraction 2", "genre": "action", "subgenres": ["action", "tactical", "thriller"],
         "desc": "Gritty, relentless close-quarters combat featuring Chris Hemsworth (2023)", "year": 2023},
        {"title": "Mad Max: Fury Road", "genre": "action", "subgenres": ["action", "post-apocalyptic", "sci-fi"],
         "desc": "Kinetic vehicular action masterclass across a dystopian desert wasteland (2015)", "year": 2015},
        # Sci-Fi
        {"title": "Dune: Part Two", "genre": "sci-fi", "subgenres": ["sci-fi", "epic", "action", "adventure"],
         "desc": "Epic visionary science fiction directed by Denis Villeneuve with colossal world-building (2024)", "year": 2024},
        {"title": "Interstellar", "genre": "sci-fi", "subgenres": ["sci-fi", "space", "drama"],
         "desc": "Deep-space gravitational odyssey exploring human survival and relativity by Christopher Nolan (2014)", "year": 2014},
        {"title": "Blade Runner 2049", "genre": "sci-fi", "subgenres": ["sci-fi", "neo-noir", "cyberpunk", "thriller"],
         "desc": "Atmospheric neo-noir cyber-thriller exploring synthetic memory and identity (2017)", "year": 2017},
        {"title": "Arrival", "genre": "sci-fi", "subgenres": ["sci-fi", "first-contact", "drama", "mystery"],
         "desc": "Thought-provoking first-contact linguistic sci-fi directed by Denis Villeneuve (2016)", "year": 2016},
        {"title": "The Creator", "genre": "sci-fi", "subgenres": ["sci-fi", "ai", "action", "war"],
         "desc": "Striking visual sci-fi exploring artificial consciousness and warfare (2023)", "year": 2023},
        # Comedy
        {"title": "The Holdovers", "genre": "comedy", "subgenres": ["comedy", "drama", "heartwarming"],
         "desc": "Warm, witty, character-driven comedy-drama set at a snowy New England boarding school (2023)", "year": 2023},
        {"title": "Knives Out", "genre": "comedy", "subgenres": ["comedy", "mystery", "whodunit"],
         "desc": "Sharp, hilarious whodunit mystery packed with twists and an all-star ensemble (2019)", "year": 2019},
        {"title": "Palm Springs", "genre": "comedy", "subgenres": ["comedy", "rom-com", "sci-fi", "time-loop"],
         "desc": "Clever existential time-loop romantic comedy with Andy Samberg and Cristin Milioti (2020)", "year": 2020},
        {"title": "The Fall Guy", "genre": "comedy", "subgenres": ["comedy", "action", "action-comedy", "romance"],
         "desc": "Action-comedy celebrating Hollywood stunt performers starring Ryan Gosling (2024)", "year": 2024},
        {"title": "Everything Everywhere All at Once", "genre": "comedy", "subgenres": ["comedy", "sci-fi", "action", "absurdist"],
         "desc": "Genre-bending multiverse absurdist comedy-fantasy starring Michelle Yeoh (2022)", "year": 2022},
        # Drama & Thriller
        {"title": "Oppenheimer", "genre": "drama", "subgenres": ["drama", "biography", "history", "thriller"],
         "desc": "Gripping, momentous biographical drama charting the creation of the atomic bomb (2023)", "year": 2023},
        {"title": "Civil War", "genre": "thriller", "subgenres": ["thriller", "action", "dystopian", "military"],
         "desc": "Visceral military thriller following war photojournalists across a fractured nation (2024)", "year": 2024},
        {"title": "Past Lives", "genre": "drama", "subgenres": ["drama", "romance"],
         "desc": "Deeply moving, tender drama contemplating destiny and unfulfilled connections (2023)", "year": 2023},
    ],
    "music": [
        # Rock / Indie Rock
        {"title": "The War on Drugs", "genre": "rock", "subgenres": ["rock", "indie rock", "heartland rock"],
         "desc": "Expansive heartland and progressive indie rock driven by rich guitar tapestries and atmospheric synths", "type": "artist"},
        {"title": "Queens of the Stone Age", "genre": "rock", "subgenres": ["rock", "desert rock", "hard rock"],
         "desc": "Heavy, groove-laden desert rock boasting punchy distortion and infectious swagger", "type": "artist"},
        {"title": "Greta Van Fleet", "genre": "rock", "subgenres": ["rock", "classic rock", "blues rock"],
         "desc": "Thunderous blues-infused classic hard rock featuring soaring vocal acrobatics", "type": "artist"},
        {"title": "Foo Fighters", "genre": "rock", "subgenres": ["rock", "alternative rock", "post-grunge"],
         "desc": "Anthemic arena rock propelled by propulsive rhythms and passionate melodic hooks", "type": "artist"},
        # Jazz / Neo-Soul / Afrobeat
        {"title": "Kamasi Washington", "genre": "jazz", "subgenres": ["jazz", "spiritual jazz", "jazz fusion"],
         "desc": "Visionary cosmic modern jazz with epic brass orchestrations and deep modal improvisations", "type": "artist"},
        {"title": "Ezra Collective", "genre": "jazz", "subgenres": ["jazz", "afrobeat", "groove jazz"],
         "desc": "Mercury Prize-winning London quintet blending explosive afrobeat, reggae, and contemporary jazz", "type": "artist"},
        {"title": "Yussef Dayes", "genre": "jazz", "subgenres": ["jazz", "neo-soul", "funk"],
         "desc": "Virtuosic contemporary jazz percussion weaving intricate funk, afro-cuban, and dub rhythms", "type": "artist"},
        # Electronic / Ambient
        {"title": "Tycho", "genre": "electronic", "subgenres": ["electronic", "ambient", "downtempo"],
         "desc": "Lush, sun-drenched ambient electronica fusing analog synthesizers and organic guitar melodies", "type": "artist"},
        {"title": "Bonobo", "genre": "electronic", "subgenres": ["electronic", "downtempo", "world"],
         "desc": "Immersive downtempo electronic music weaving organic instrumentation, strings, and global rhythms", "type": "artist"},
        {"title": "Jon Hopkins", "genre": "electronic", "subgenres": ["electronic", "neoclassical", "techno"],
         "desc": "Hypnotic electronic soundscapes traversing delicate classical piano and visceral modular rhythms", "type": "artist"},
        # Indie / Alternative
        {"title": "Khruangbin", "genre": "indie", "subgenres": ["indie", "psych rock", "thai funk", "surf"],
         "desc": "Breezy psychedelic trio weaving Thai funk, surf rock, and international grooves", "type": "artist"},
        {"title": "Phoebe Bridgers", "genre": "indie", "subgenres": ["indie", "indie folk", "singer-songwriter"],
         "desc": "Haunting, intimate indie folk marked by poignant acoustic arrangements and candid lyricism", "type": "artist"},
    ],
    "projects": [
        # ML / AI
        {"title": "Local Multimodal RAG with Vector Search", "genre": "machine learning", "subgenres": ["python", "machine learning", "rag", "vector search"],
         "desc": "Build an offline document QA engine using localized dense embeddings and cross-encoder re-ranking"},
        {"title": "Quantized Model Inference Profiler", "genre": "machine learning", "subgenres": ["python", "c++", "machine learning", "profiling"],
         "desc": "Analyze cache misses, compute throughput, and token latency across quantized GGUF neural architectures"},
        {"title": "Edge Vision Defect Detection Pipeline", "genre": "machine learning", "subgenres": ["python", "computer vision", "edge ai"],
         "desc": "Implement a real-time visual inspection system with lightweight YOLO models optimized for edge NPUs"},
        # Systems / Rust
        {"title": "Lock-Free Async Message Broker in Rust", "genre": "rust", "subgenres": ["rust", "systems", "concurrency"],
         "desc": "Develop a high-throughput, low-latency publish-subscribe broker using Tokio and ring buffers"},
        {"title": "Zero-Copy TCP Proxy with eBPF Telemetry", "genre": "rust", "subgenres": ["rust", "systems", "networking", "c"],
         "desc": "Construct a high-performance network gateway leveraging kernel bypass and zero-copy packet splicing"},
        {"title": "Memory-Mapped B+ Tree Storage Engine", "genre": "systems", "subgenres": ["rust", "c++", "databases", "storage"],
         "desc": "Build an embedded ACID-compliant key-value store using write-ahead logging and mmap paging"},
        # Web / Distributed
        {"title": "WebAssembly Sandboxed Plugin Engine", "genre": "distributed", "subgenres": ["web", "wasm", "distributed", "security"],
         "desc": "Implement a secure microservice runtime evaluating untrusted user scripts inside Wasmtime sandboxes"},
        {"title": "CRDT Collaborative Canvas Workspace", "genre": "web", "subgenres": ["web", "javascript", "distributed", "algorithms"],
         "desc": "Create a peer-to-peer real-time shared whiteboard using conflict-free replicated data types"},
        # Embedded / IoT
        {"title": "USB Hardware Protocol Sniffer", "genre": "embedded", "subgenres": ["embedded", "c", "hardware", "iot"],
         "desc": "Build a hardware logic capture probe on RP2040 microcontroller with streaming serial decode UI"},
        {"title": "Autonomous Rover Sensor Fusion", "genre": "embedded", "subgenres": ["robotics", "embedded", "c++", "math"],
         "desc": "Implement an Extended Kalman Filter fusing IMU accelerometers, wheel encoders, and ultrasonic sensors"},
    ],
    "books": [
        {"title": "Designing Data-Intensive Applications", "author": "Martin Kleppmann", "genre": "tech",
         "desc": "The definitive deep-dive into distributed systems, storage engines, consensus algorithms, and fault tolerance"},
        {"title": "Deep Learning with Python", "author": "François Chollet", "genre": "machine learning",
         "desc": "Intuition-first exploration of deep learning principles and practical architectures by Keras creator"},
        {"title": "Rust in Action", "author": "Tim McNamara", "genre": "tech",
         "desc": "Systems programming fundamentals covering memory models, operating systems, and networking in Rust"},
        {"title": "Project Hail Mary", "author": "Andy Weir", "genre": "sci-fi",
         "desc": "Gripping hard science-fiction survival odyssey celebrating ingenuity, astrophysics, and interstellar friendship"},
        {"title": "The Three-Body Problem", "author": "Cixin Liu", "genre": "sci-fi",
         "desc": "Monumental cosmic journey exploring first contact, orbital mechanics, and extraterrestrial civilizations"},
        {"title": "Thinking, Fast and Slow", "author": "Daniel Kahneman", "genre": "non-fiction",
         "desc": "Nobel laureate's landmark analysis of the two cognitive systems governing human decision-making and bias"},
        {"title": "The Idea Factory", "author": "Jon Gertner", "genre": "non-fiction",
         "desc": "Captivating history of Bell Labs and the brilliant pioneers who invented the transistor, laser, and information theory"},
    ],
    "games": [
        {"title": "Hades", "genre": "action", "subgenres": ["action", "roguelike", "indie"],
         "desc": "Fast-paced rogue-like dungeon crawler with Greek myth storytelling and fluid combat"},
        {"title": "Hollow Knight", "genre": "action", "subgenres": ["action", "metroidvania", "indie"],
         "desc": "Atmospheric 2D action adventure with fluid platforming and vast subterranean lore"},
        {"title": "Dead Cells", "genre": "action", "subgenres": ["action", "roguelite", "indie"],
         "desc": "Relentless roguelite action platformer featuring diverse weaponry and slick combat"},
        {"title": "Celeste", "genre": "platformer", "subgenres": ["platformer", "indie"],
         "desc": "Precision platformer with tight controls and an emotional story of perseverance"},
        {"title": "Stardew Valley", "genre": "rpg", "subgenres": ["rpg", "simulation", "farming"],
         "desc": "Relaxing country-life farming RPG with peaceful exploration and community building"},
        {"title": "Into the Breach", "genre": "strategy", "subgenres": ["strategy", "tactical", "turn-based"],
         "desc": "Turn-based tactical puzzle masterpiece defending cities against alien invaders"},
    ]
}

# Retain FALLBACK_CATALOG for strict backward compatibility with existing tests
FALLBACK_CATALOG = {
    "action_movies": {
        "title": "Here are 6 recommended action movies:",
        "items": [
            ("John Wick: Chapter 4", "High-octane martial arts and gun-fu with Keanu Reeves (2023)"),
            ("Mission: Impossible – Dead Reckoning Part One", "Intense globe-trotting espionage and practical stuntwork (2023)"),
            ("The Fall Guy", "Action-comedy with Ryan Gosling celebrating stunt performers (2024)"),
            ("Top Gun: Maverick", "Thrilling aerial combat and high-speed jet sequences (2022)"),
            ("Extraction 2", "Gritty, relentless close-quarters combat featuring Chris Hemsworth (2023)"),
            ("Civil War", "Visceral, high-stakes military thriller directed by Alex Garland (2024)"),
        ]
    },
    "sci_fi_movies": {
        "title": "Here are 6 recommended sci-fi movies:",
        "items": [
            ("Dune: Part Two", "Epic cinematic science fiction directed by Denis Villeneuve (2024)"),
            ("Interstellar", "Deep-space gravitational odyssey directed by Christopher Nolan (2014)"),
            ("Blade Runner 2049", "Atmospheric neo-noir cyber-thriller (2017)"),
            ("The Creator", "Striking visual sci-fi exploring AI warfare and humanity (2023)"),
            ("Everything Everywhere All at Once", "Multiverse action fantasy with Michelle Yeoh (2022)"),
            ("Arrival", "Thought-provoking first-contact linguistic sci-fi (2016)"),
        ]
    },
    "games": {
        "title": "Here are 6 great PC games compatible with your system:",
        "items": [
            ("Hades", "Fast-paced rogue-like dungeon crawler that runs smoothly on integrated graphics"),
            ("Hollow Knight", "Acclaimed 2D Metroidvania action adventure with stunning hand-drawn art"),
            ("Dead Cells", "Rogue-lite action platformer with fluid combat and minimal hardware requirements"),
            ("Celeste", "Tight platforming adventure playable on almost any modern PC"),
            ("Stardew Valley", "Relaxing farming RPG and simulator with near-universal compatibility"),
            ("Into the Breach", "Turn-based tactical strategy with a lightweight system footprint"),
        ]
    }
}


def extract_user_profile(user_id=None) -> Dict[str, Any]:
    """
    Extracts user profile, long-term memory facts, and preferences from PostgreSQL
    and DialogueStateManager to guide recommendations without constraining them.
    """
    profile: Dict[str, Any] = {
        "favorite_genres": [],
        "favorite_music": [],
        "interests": [],
        "dislikes": [],
        "rejected_items": [],
        "raw_facts": {},
        "raw_preferences": {}
    }

    uid_int = None
    if user_id is not None:
        try:
            uid_int = int(user_id)
        except (ValueError, TypeError):
            pass

    # 1. PostgreSQL retrieval via ChatGPTMemory
    if uid_int is not None:
        try:
            from core.chatgpt_memory import ChatGPTMemory
            mem = ChatGPTMemory()
            facts = mem.get_user_facts(uid_int) or {}
            profile["raw_facts"] = facts
            prefs = mem.get_preferences(uid_int) or {}
            profile["raw_preferences"] = prefs

            for k, v in {**facts, **prefs}.items():
                k_low = str(k).lower()
                v_str = str(v).lower()
                if any(w in k_low for w in ("movie", "film", "cinema", "genre")):
                    profile["favorite_genres"].append(v_str)
                elif any(w in k_low for w in ("music", "song", "band", "artist", "album")):
                    profile["favorite_music"].append(v_str)
                elif any(w in k_low for w in ("dislike", "hate", "avoid")):
                    profile["dislikes"].append(v_str)
                elif any(w in k_low for w in ("tech", "interest", "hobby", "skill", "coding", "project", "language")):
                    profile["interests"].append(v_str)
        except Exception:
            pass

    # 2. DialogueStateManager context retrieval
    try:
        from extensions.dialogue_state_manager import get_dialogue_manager
        dm = get_dialogue_manager(user_id if user_id is not None else "default")
        dm_prefs = getattr(dm.current_state, "preferences", {}) or {}
        for k, v in dm_prefs.items():
            k_low = str(k).lower()
            v_str = str(v).lower()
            if any(w in k_low for w in ("movie", "genre")):
                profile["favorite_genres"].append(v_str)
            elif "music" in k_low:
                profile["favorite_music"].append(v_str)
            elif any(w in k_low for w in ("dislike", "hate")):
                profile["dislikes"].append(v_str)
            elif any(w in k_low for w in ("tech", "interest", "project")):
                profile["interests"].append(v_str)

        ctx = getattr(dm.current_state, "session_context", {}) or {}
        if "rejected_items" in ctx:
            profile["rejected_items"].extend(ctx["rejected_items"])
    except Exception:
        pass

    return profile


def analyze_request(query: str, user_profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parses recommendation query, discerning:
    - Domain (movies, music, projects, books, games)
    - Strict constraints vs. open requests
    - Discovery signals (intent to explore outside usual taste)
    - Explicit item rejections (e.g. 'I don't like X', 'give me alternatives')
    """
    query_lower = query.lower().strip()

    # Domain identification
    domain = "general"
    if any(w in query_lower for w in ("movie", "movies", "film", "films", "cinema", "watch")):
        domain = "movies"
    elif any(w in query_lower for w in ("music", "song", "songs", "artist", "artists", "band", "bands", "album", "listen")):
        domain = "music"
    elif any(w in query_lower for w in ("project", "projects", "code", "programming", "technical idea", "technical project")):
        domain = "projects"
    elif any(w in query_lower for w in ("book", "books", "read", "author", "novel")):
        domain = "books"
    elif any(w in query_lower for w in ("game", "games", "gaming", "play")):
        domain = "games"

    # Strict constraint markers
    has_strict_word = bool(re.search(r'\b(?:only|strictly|exclusively|just|must\s+be|solely)\b', query_lower))

    genre_keywords = {
        "movies": ["action", "sci-fi", "science fiction", "comedy", "drama", "thriller", "horror", "animation", "animated", "romance"],
        "music": ["rock", "jazz", "electronic", "classical", "hip-hop", "indie", "pop", "ambient", "metal", "blues"],
        "projects": ["machine learning", "ml", "python", "rust", "c++", "web", "distributed", "embedded", "iot", "security"],
        "books": ["machine learning", "ai", "sci-fi", "science fiction", "tech", "non-fiction", "fiction", "history"],
        "games": ["action", "rpg", "roguelike", "strategy", "indie", "platformer", "puzzle"]
    }

    target_genre = None
    target_genres = []
    dom_genres = genre_keywords.get(domain, [])
    for g in dom_genres:
        if re.search(r'\b' + re.escape(g) + r'\b', query_lower):
            target_genres.append(g)
            if not target_genre:
                target_genre = g

    # If the user explicitly named a genre or category in their request, that request is treated
    # as a constraint for this specific turn (e.g., "comedy movies", "only action", "rust projects")
    is_strict = has_strict_word or (target_genre is not None)

    # Discovery signal
    is_discovery = any(w in query_lower for w in (
        "discover", "discovery", "new", "different", "outside", "explore", "exploration",
        "broaden", "alternatives", "fresh", "unusual", "comfort zone", "not my usual"
    ))

    # Rejection signal
    rejected_item = None
    m_rej = re.search(
        r'\b(?:don\'?t\s+like|do\s+not\s+like|dislike|hate|not\s+interested\s+in|reject|rejecting|not\s+(?:want|into)|alternative\s+to|different\s+(?:than|from))\s+([a-zA-Z0-9_\-:\s]+?)(?:,\s*|\.\s*|\s+(?:give|suggest|recommend|show)|$)',
        query_lower
    )
    if m_rej:
        cand = m_rej.group(1).strip()
        if cand not in ("that", "this", "it", "them", "these", "anything"):
            rejected_item = cand

    return {
        "domain": domain,
        "is_strict": is_strict,
        "target_genre": target_genre,
        "target_genres": target_genres,
        "is_discovery": is_discovery,
        "rejected_item": rejected_item,
        "clean_query": query.strip()
    }


def generate_balanced_recommendations(domain: str, user_profile: Dict[str, Any], analysis: Dict[str, Any]) -> str:
    """
    Synthesizes balanced recommendations across the 4 pillars:
    - [For Your Taste]: options closely matching established preferences
    - [Related Alternative]: connected to interests with an adjacent flavor
    - [Fresh Discovery]: standout high-quality options outside usual habits
    - [Tailored to Request]: directly answering constraints or current context
    """
    pool = list(CATALOG_DB.get(domain, CATALOG_DB["movies"]))

    # 1. Filter out known dislikes and rejected items
    dislikes = [d.lower() for d in user_profile.get("dislikes", [])]
    rejected = [r.lower() for r in user_profile.get("rejected_items", [])]
    if analysis.get("rejected_item"):
        rejected.append(analysis["rejected_item"].lower())

    filtered_pool = []
    for it in pool:
        t_low = it["title"].lower()
        g_low = it.get("genre", "").lower()
        # Reject check: title or substring matches
        if any(r in t_low or t_low in r for r in rejected if r):
            continue
        if any(d in g_low for d in dislikes if d):
            continue
        filtered_pool.append(it)

    target_genre = analysis.get("target_genre")
    is_strict = analysis.get("is_strict", False)
    is_discovery = analysis.get("is_discovery", False)

    fav_genres = [f.lower() for f in user_profile.get("favorite_genres", [])]
    fav_music = [m.lower() for m in user_profile.get("favorite_music", [])]
    interests = [i.lower() for i in user_profile.get("interests", [])]

    # Domain-specific relevant tastes
    domain_tastes = set()
    if domain == "movies":
        domain_tastes = set(fav_genres)
    elif domain == "music":
        domain_tastes = set(fav_music)
    elif domain == "projects":
        domain_tastes = set(interests)
    elif domain == "books":
        domain_tastes = set(interests + fav_genres)
    elif domain == "games":
        domain_tastes = set(fav_genres + interests)
    else:
        domain_tastes = set(fav_genres + fav_music + interests)

    user_tastes = domain_tastes if domain_tastes else set(fav_genres + fav_music + interests)

    selected_items: List[Tuple[Dict[str, Any], str, str]] = []

    # CASE A: EXPLICIT CONSTRAINT (User asked for a specific genre/domain)
    # Respect the constraint strictly: 100% of returned items belong to the requested domain/genre.
    if is_strict and target_genre:
        target_norm = target_genre.lower().replace("-", " ")
        matching_items = []
        for it in filtered_pool:
            g_low = it.get("genre", "").lower().replace("-", " ")
            sub_lows = [s.lower().replace("-", " ") for s in it.get("subgenres", [])]
            if target_norm in g_low or any(target_norm in s for s in sub_lows):
                matching_items.append(it)

        # Prioritize items where primary genre is exact match, then crossover with taste
        def _match_priority(item):
            g_low = item.get("genre", "").lower().replace("-", " ")
            it_genres = set([g_low] + [s.lower().replace("-", " ") for s in item.get("subgenres", [])])
            is_primary = (g_low == target_norm)
            has_crossover = bool(it_genres & user_tastes)
            return (1 if is_primary else 0, 1 if has_crossover else 0)

        matching_items.sort(key=_match_priority, reverse=True)

        for i, it in enumerate(matching_items[:6]):
            it_genres = set([it.get("genre", "").lower()] + [s.lower() for s in it.get("subgenres", [])])
            has_taste_crossover = bool(it_genres & user_tastes)

            if i == 0 and has_taste_crossover:
                badge = "For Your Taste"
                reason = f"Matching your request for {target_genre} while incorporating elements of your preferred style."
            elif i == 0:
                badge = "Tailored to Request"
                reason = f"Top-rated {target_genre} choice directly fulfilling your request."
            elif i == 1:
                badge = "Related Alternative"
                reason = f"A clever subgenre variation offering a unique take on {target_genre}."
            elif i == 2:
                badge = "Fresh Discovery"
                reason = f"An acclaimed, standout {target_genre} work with fresh creative direction."
            else:
                badge = "Tailored to Request"
                reason = f"Essential, highly regarded {target_genre} selection."

            selected_items.append((it, badge, reason))

    # CASE B: OPEN REQUEST (User asked for general recommendations in a domain)
    # Use preferences as guidance, balancing Personalization (up to 2) with Alternatives (2) & Discoveries (2)
    else:
        personalized = []
        if user_tastes:
            for it in filtered_pool:
                it_genres = set([it.get("genre", "").lower()] + [s.lower() for s in it.get("subgenres", [])])
                if it_genres & user_tastes:
                    personalized.append(it)

        others = [it for it in filtered_pool if it not in personalized]

        # If discovery was explicitly asked ("discover new music/projects"), balance heavily toward discoveries
        if is_discovery:
            # 1 Personalized anchor
            if personalized:
                it = personalized[0]
                taste_desc = ", ".join(list(user_tastes)[:2])
                selected_items.append((
                    it, "For Your Taste",
                    f"A solid baseline aligning with your known appreciation for {taste_desc}."
                ))
            # 2 Related alternatives
            for it in others[:2]:
                selected_items.append((
                    it, "Related Alternative",
                    "A vibrant adjacent direction connected in spirit to your favorites."
                ))
            # 3 Fresh discoveries
            for it in others[2:5]:
                selected_items.append((
                    it, "Fresh Discovery",
                    "A critically acclaimed standout expanding into completely fresh creative territory."
                ))
        else:
            # Standard balanced 4-pillar mix:
            # 2 Personalized
            for it in personalized[:2]:
                taste_desc = ", ".join(list(user_tastes)[:2])
                selected_items.append((
                    it, "For Your Taste",
                    f"Directly aligns with your established appreciation for {taste_desc}."
                ))

            # 2 Related alternatives
            for it in others[:2]:
                selected_items.append((
                    it, "Related Alternative",
                    "Connects with the themes and energy of your favorites, exploring an adjacent domain."
                ))

            # 2 Fresh discoveries
            for it in others[2:4]:
                selected_items.append((
                    it, "Fresh Discovery",
                    "A critically acclaimed standout outside your usual favorites to broaden your horizons."
                ))

            # If personalized was empty, fill with high quality picks
            if len(selected_items) < 5 and len(others) > 4:
                for it in others[4:6]:
                    selected_items.append((
                        it, "Tailored to Request",
                        "A widely celebrated favorite offering high quality and broad appeal."
                    ))

    header = f"Here is a curated, balanced selection of {domain}:"
    lines = [header, ""]
    for it, badge, reason in selected_items:
        lines.append(f"• **{it['title']}** — *[{badge}]* {it['desc']} — {reason}")

    return "\n".join(lines)


def _get_fallback_recommendation(query_lower: str, user_profile: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Retrieve curated fallback recommendations using balanced intelligence."""
    profile = user_profile or extract_user_profile()
    analysis = analyze_request(query_lower, profile)
    domain = analysis["domain"]
    if domain == "general":
        domain = "movies"
    return generate_balanced_recommendations(domain, profile, analysis)


def recommend(query: str, user_id=None) -> str:
    """
    Universal recommendation engine powered by LLM with balanced intelligence.
    Balances personalization with discovering new options across 4 pillars.
    Handles explicit constraints strictly while treating historical preferences as guidance.
    """
    # Check for interrupt before processing
    try:
        from core.state_manager import state_manager
        if state_manager.is_interrupted():
            print("[RECOMMENDATION] Interrupted before processing")
            return "❌ Request interrupted"
    except ImportError:
        pass

    query_lower = query.lower()
    wants_latest = any(word in query_lower for word in ["latest", "newest", "recent", "current"])

    # 1. Retrieve user profile and analyze request
    user_profile = extract_user_profile(user_id=user_id)
    analysis = analyze_request(query, user_profile)

    # 2. Persist rejected item to dialogue state if detected
    if analysis.get("rejected_item"):
        rej_name = analysis["rejected_item"]
        try:
            from extensions.dialogue_state_manager import get_dialogue_manager
            dm = get_dialogue_manager(user_id if user_id is not None else "default")
            ctx = getattr(dm.current_state, "session_context", {})
            if "rejected_items" not in ctx:
                ctx["rejected_items"] = []
            if rej_name not in ctx["rejected_items"]:
                ctx["rejected_items"].append(rej_name)
            dm.current_state.session_context = ctx
        except Exception:
            pass

    # 3. Enrich with system specifications if hardware or gaming is queried
    sys_note = ""
    if any(k in query_lower for k in ["compatible", "this system", "this pc", "run on my", "download and run", "game", "games", "can run", "requirements"]):
        try:
            from core.environmentObserver import get_canonical_system_snapshot  # fallback or direct import
        except ImportError:
            try:
                from core.environment_observer import get_canonical_system_snapshot
                snap = get_canonical_system_snapshot(user_id=str(user_id or "default"))
                gpu_str = f"{snap.gpu_model}" + (f" ({snap.gpu_vram_mb} MB VRAM)" if snap.gpu_vram_mb else "")
                sys_note = (
                    f"\nLocal System Specifications:\n"
                    f"- OS: {snap.os}\n"
                    f"- CPU: {snap.cpu_model} ({snap.cpu_cores} cores, {snap.cpu_threads} threads)\n"
                    f"- GPU: {gpu_str}\n"
                    f"- RAM: {snap.ram_total_gb:.1f} GB total, {snap.ram_available_gb:.1f} GB available\n"
                    f"- Display: {snap.display_resolution}\n"
                    f"You MUST take these actual specifications into account when recommending or checking compatibility. "
                    f"DO NOT state that you do not have access to system specs!"
                )
            except Exception:
                pass

    prompt_rules = """
RULES & PHILOSOPHY:
* BALANCE PERSONALIZATION AND DISCOVERY:
  - Use known user preferences as guidance, NOT as hard restrictions.
  - If the user explicitly requested a specific genre/domain (e.g. 'only action', 'comedy movies', 'rust projects'), strictly respect that constraint.
  - If the request is open (e.g. 'recommend movies', 'music recommendations'), provide a balanced mix:
    • [For Your Taste]: Options matching known favorites.
    • [Related Alternative]: Adjacent options connected to interests.
    • [Fresh Discovery]: Acclaimed options outside usual habits.
    • [Tailored to Request]: Directly fitting the query.
* EXPLAIN RECOMMENDATIONS GROUNDEDLY:
  - For each item, include the badge in brackets, e.g., *[For Your Taste]*, *[Related Alternative]*, *[Fresh Discovery]*, or *[Tailored to Request]*.
  - Provide a brief, authentic explanation of why each is recommended.
* STRICT NEGATIVE FILTERING:
  - Never recommend items the user has rejected or stated they dislike.
* REAL ITEMS:
  - Recommend ONLY real, existing items.
  - DO NOT invent names or fake items.

OUTPUT FORMAT:
* Clear title
* 5-7 bullet points in the format: • **Title** — *[Badge]* Description — Brief reason
"""

    prompt = f"""You are a recommendation system with balanced personalization and serendipity.

User query: "{query}"{sys_note}

User Profile:
- Favorite Genres: {user_profile.get('favorite_genres', [])}
- Favorite Music: {user_profile.get('favorite_music', [])}
- Interests & Tech: {user_profile.get('interests', [])}
- Dislikes: {user_profile.get('dislikes', [])}
- Rejected Items: {user_profile.get('rejected_items', [])}

{prompt_rules}
"""
    if wants_latest:
        prompt += "\n* Prioritize very recent releases (last 1-2 years)"

    response = None
    try:
        llm_resp = ask_llm(prompt)
        if llm_resp and not llm_resp.strip().startswith("❌"):
            response = llm_resp.strip()
    except Exception as e:
        print(f"[RECOMMENDATION] LLM provider error: {e}")

    # Fallback to balanced local catalog if LLM response is empty or failed
    if not response or response.startswith("❌"):
        fallback = _get_fallback_recommendation(query_lower, user_profile=user_profile)
        if fallback:
            print("[RECOMMENDATION] Serving balanced curated local fallback catalog")
            response = fallback
        else:
            response = "I couldn't retrieve recommendations at this moment. Please try again."
    elif analysis.get("rejected_item"):
        rej_term = analysis["rejected_item"].lower()
        if rej_term in response.lower():
            fallback = _get_fallback_recommendation(query_lower, user_profile=user_profile)
            if fallback:
                print("[RECOMMENDATION] Replacing LLM response containing rejected item with clean balanced catalog")
                response = fallback

    # Check for interrupt after call
    try:
        from core.state_manager import state_manager
        if state_manager.is_interrupted():
            print("[RECOMMENDATION] Interrupted after processing")
            return "❌ Request interrupted"
    except ImportError:
        pass

    # Update dialogue continuation state and response state with parsed items
    try:
        from extensions.dialogue_state_manager import get_dialogue_manager
        dm = get_dialogue_manager(user_id if user_id is not None else "default")
        items = []
        for line in response.split("\n"):
            l_s = line.strip()
            m_it = re.match(r'^(?:[\*\-•]|\d+[\.\)])\s*(.+)', l_s)
            if m_it:
                raw_title = m_it.group(1).strip()
                raw_title = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', raw_title)
                title_part = re.split(r'[:–—\-\(\[]', raw_title)[0].strip()
                t_words = title_part.split()
                if len(t_words) > 5:
                    title_part = " ".join(t_words[:4])
                if title_part and len(title_part) >= 2:
                    items.append(title_part)
        if items:
            dm.update_continuation_state(full_response=response, recommendation_list=items)
            try:
                from extensions.dialogue_state_manager import ResponseState
                import uuid
                dm.set_response_state(ResponseState(
                    response_id=str(uuid.uuid4()),
                    response_type="recommendation",
                    full_text=response,
                    items=items,
                    speech_segments=[response],
                    spoken_segments=[response],
                    current_item_index=0
                ))
            except Exception:
                pass
            # Also store as active entities for domain-scoped reference resolution
            dm.current_state.active_entity_set["RECOMMENDATION"] = [{"value": it, "type": "RECOMMENDATION"} for it in items]
            dm.current_state.primary_active_entity = {"value": items[0], "entity_type": "RECOMMENDATION"}
    except Exception:
        pass

    return response


class RecommendationEngine:
    """Wrapper class for recommendation engine."""
    def recommend(self, query: str, user_id=None) -> str:
        return recommend(query, user_id=user_id)


_recommendation_engine = RecommendationEngine()

def get_recommendation_engine() -> RecommendationEngine:
    return _recommendation_engine

__all__ = ["recommend", "get_recommendation_engine", "RecommendationEngine", "FALLBACK_CATALOG", "CATALOG_DB", "analyze_request", "generate_balanced_recommendations", "extract_user_profile"]
