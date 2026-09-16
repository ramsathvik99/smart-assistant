# music_recommendation.py
import time
from datetime import datetime
from typing import List, Dict, Optional
from extensions.personality_engine.response_formatter import format_response

# Import preference engine for personalization
try:
    from extensions.user_preference_engine import (
        get_preference_engine, 
        detect_user_language, 
        detect_user_genre,
        update_user_preference,
        get_adaptive_context
    )
    PREFERENCE_ENGINE_AVAILABLE = True
except ImportError as e:
    print(f"[MUSIC RECOMMENDATION] Preference engine import failed: {e}")
    PREFERENCE_ENGINE_AVAILABLE = False
    
    # Fallback functions
    def get_preference_engine(): return None
    def detect_user_language(cmd): return 'english'
    def detect_user_genre(cmd, cat): return None
    def update_user_preference(cat, cmd): pass
    def get_adaptive_context(cat, ctx): return {'preferences': {}}

class MusicRecommender:
    """Intelligent music recommendation system with context awareness and memory integration"""
    
    def __init__(self):
        # Enhanced genre database with contextual tags
        self.genres = {
            'pop': {
                'artists': ['Taylor Swift', 'Ed Sheeran', 'Ariana Grande', 'Justin Bieber', 'Billie Eilish'],
                'energy': 'medium',
                'mood': ['happy', 'energetic'],
                'time_preference': ['afternoon', 'evening']
            },
            'rock': {
                'artists': ['Queen', 'The Beatles', 'Led Zeppelin', 'Pink Floyd', 'The Rolling Stones'],
                'energy': 'high',
                'mood': ['energetic', 'focused'],
                'time_preference': ['morning', 'afternoon']
            },
            'hip-hop': {
                'artists': ['Drake', 'Kendrick Lamar', 'J. Cole', 'Travis Scott', 'Eminem'],
                'energy': 'high',
                'mood': ['energetic', 'confident'],
                'time_preference': ['afternoon', 'evening']
            },
            'electronic': {
                'artists': ['Daft Punk', 'Deadmau5', 'Skrillex', 'Calvin Harris', 'Avicii'],
                'energy': 'high',
                'mood': ['energetic', 'focused'],
                'time_preference': ['evening', 'night']
            },
            'classical': {
                'artists': ['Mozart', 'Beethoven', 'Bach', 'Chopin', 'Vivaldi'],
                'energy': 'low',
                'mood': ['focused', 'relaxed'],
                'time_preference': ['morning', 'night']
            },
            'jazz': {
                'artists': ['Miles Davis', 'John Coltrane', 'Bill Evans', 'Herbie Hancock', 'Wayne Shorter'],
                'energy': 'medium',
                'mood': ['relaxed', 'focused'],
                'time_preference': ['evening', 'night']
            },
            'lofi': {
                'artists': ['Lofi Hip Hop Radio', 'Study Lofi', 'Chill Lofi', 'Peaceful Lofi', 'Focus Lofi'],
                'energy': 'low',
                'mood': ['relaxed', 'focused'],
                'time_preference': ['morning', 'afternoon', 'night']
            }
        }
        
        # Initialize command memory for pattern detection
        self.command_memory = CommandMemory()
        
    def get_time_context(self) -> str:
        """Get current time context"""
        hour = datetime.now().hour
        if 6 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 22:
            return "evening"
        else:
            return "night"
    
    def analyze_user_patterns(self) -> Dict[str, any]:
        """Analyze user listening patterns from command memory"""
        patterns = {
            'frequent_genres': [],
            'recent_activity': False,
            'work_hours': False,
            'relaxation_time': False
        }
        
        # Check for frequent music-related commands
        music_commands = [cmd for cmd in self.command_memory._commands if any(keyword in cmd.lower() for keyword in ['music', 'play', 'song', 'lofi'])]
        
        if music_commands:
            # Analyze frequency patterns
            genre_count = {}
            for cmd in music_commands:
                for genre in self.genres.keys():
                    if genre in cmd.lower():
                        genre_count[genre] = genre_count.get(genre, 0) + 1
            
            patterns['frequent_genres'] = sorted(genre_count.keys(), key=genre_count.get, reverse=True)[:3]
            patterns['recent_activity'] = len(music_commands) > 0
            
            # Check if user typically listens during work hours
            work_hour_commands = [cmd for cmd in music_commands if 9 <= datetime.fromtimestamp(self.command_memory._timestamps[music_commands.index(cmd)]).hour <= 17]
            patterns['work_hours'] = len(work_hour_commands) > len(music_commands) * 0.6
            
            # Check for relaxation patterns
            night_commands = [cmd for cmd in music_commands if 20 <= datetime.fromtimestamp(self.command_memory._timestamps[music_commands.index(cmd)]).hour <= 23]
            patterns['relaxation_time'] = len(night_commands) > len(music_commands) * 0.4
        
        return patterns
    
    def recommend_by_context(self, context: Dict[str, any]) -> str:
        """Generate recommendation based on context and user patterns"""
        time_context = self.get_time_context()
        user_patterns = self.analyze_user_patterns()
        
        # Priority 1: Time-based recommendations
        if time_context == "morning":
            if user_patterns.get('work_hours', False):
                return "Starting your day with some focused music might help. I recommend classical or lofi beats for productivity."
            else:
                return "Good morning! Try something energetic to start your day. Rock or electronic music could give you that boost."
        
        elif time_context == "night":
            if user_patterns.get('relaxation_time', False):
                return "Based on your evening patterns, I suggest some calming lofi or jazz to help you unwind."
            else:
                return "It's getting late. How about something calm and relaxing to end your day?"
        
        # Priority 2: User pattern-based recommendations
        if user_patterns.get('frequent_genres'):
            frequent_genre = user_patterns['frequent_genres'][0]
            if frequent_genre == 'lofi':
                return "I notice you often enjoy lofi music. Playing your usual study mix would be perfect right now."
            elif frequent_genre in self.genres:
                genre_info = self.genres[frequent_genre]
                return f"Since you often listen to {frequent_genre}, I suggest some {genre_info['artists'][0]} or similar artists."
        
        # Priority 3: Activity-based recommendations
        current_activity = context.get('current_app', '').lower()
        if 'code' in current_activity or 'work' in current_activity:
            return "For focused work, I recommend classical music or lofi beats to maintain concentration."
        
        # Priority 4: Mood-based fallback
        user_mood = context.get('mood', '').lower()
        if user_mood:
            if 'energetic' in user_mood:
                return "For an energetic mood, try some rock or electronic music to keep the energy high."
            elif 'relaxed' in user_mood:
                return "For a relaxed vibe, jazz or classical music would be perfect."
            elif 'focused' in user_mood:
                return "To maintain focus, I recommend lofi or classical music without lyrics."
        
        # Default intelligent recommendation
        return "I can suggest something based on your current mood and activity. What are you in the mood for right now?"
    
    def recommend_by_genre(self, genre: str) -> List[str]:
        """Get recommendations by genre"""
        genre_lower = genre.lower()
        if genre_lower in self.genres:
            return self.genres[genre_lower]['artists'][:3]
        return []
    
    def recommend_by_mood(self, mood: str) -> List[str]:
        """Get recommendations by mood"""
        mood_lower = mood.lower()
        matching_genres = []
        
        for genre, info in self.genres.items():
            if mood_lower in info['mood']:
                matching_genres.extend(info['artists'][:2])
        
        return matching_genres[:3]

# Global recommender instance
recommender = MusicRecommender()

def recommend_music(context: Dict[str, any] = None, genre_or_mood: str = None) -> str:
    """Main recommendation function with context awareness and personalization"""
    if context is None:
        context = {}
    
    # Auto-detect language and genre from command if available
    if 'command' in context:
        detected_language = detect_user_language(context['command'])
        detected_genre = detect_user_genre(context['command'], 'music')
        if detected_genre:
            update_user_preference('music', context['command'])
    
    # Get adaptive context with preferences
    if PREFERENCE_ENGINE_AVAILABLE:
        adaptive_context = get_adaptive_context('music', context)
        preferences = adaptive_context.get('preferences', {})
        preferred_language = adaptive_context.get('preferred_language', 'english')
        preferred_genre = adaptive_context.get('preferred_genre')
    else:
        adaptive_context = {}
        preferences = {}
        preferred_language = 'english'
        preferred_genre = None
    
    # Priority 1: Personalized recommendation based on user history
    if preferred_genre and not genre_or_mood:
        if preferred_language == 'telugu':
            telugu_genres = {
                'classical': "Try some traditional Carnatic music",
                'devotional': "How about some devotional Telugu songs?", 
                'folk': "Some Telugu folk music might be nice",
                'modern': "Latest Telugu hits could be good"
            }
            if preferred_genre in telugu_genres:
                recommendation = telugu_genres[preferred_genre]
                return format_response(f"Based on your preferences, {recommendation}", intent="SUGGESTION")
        
        # Priority 2: Language and genre specific recommendation
    if genre_or_mood:
        genre_lower = genre_or_mood.lower()
        if genre_lower in get_genre_list():
            recommendations = recommender.recommend_by_genre(genre_lower)
            
            # Add language-specific enhancement
            if preferred_language == 'telugu':
                if genre_lower == 'classical':
                    response = f"Here are some {genre_or_mood} recommendations: {', '.join(recommendations)}. Would you like some Telugu classical music?"
                elif genre_lower == 'devotional':
                    response = f"Here are some {genre_or_mood} recommendations: {', '.join(recommendations)}. I can also suggest some Telugu devotional songs."
                else:
                    response = f"Here are some {genre_or_mood} recommendations: {', '.join(recommendations)}"
            else:
                response = f"Here are some {genre_or_mood} recommendations: {', '.join(recommendations)}"
            
            return format_response(response, intent="SUGGESTION")
    
    # Priority 3: Context-based intelligent recommendation with personalization
    if not genre_or_mood:
        time_context = recommender.get_time_context()
        user_patterns = recommender.analyze_user_patterns()
        
        # Personalized recommendations based on language and time
        if preferred_language == 'telugu':
            if time_context == "morning":
                recommendation = "Good morning! Starting your day with some pleasant Telugu melodies would be wonderful."
            elif time_context == "night":
                recommendation = "For a peaceful evening, how about some calming Telugu devotional music?"
            elif user_patterns.get('recent_activity'):
                recommendation = "Since you enjoy Telugu music, I suggest some latest Telugu hits that match your taste."
            else:
                recommendation = "Based on your preferences, I can recommend some Telugu music. What mood are you in?"
        else:
            # Original context-based logic for English
            recommendation = recommender.recommend_by_context(context)
        
        return format_response(recommendation, intent="SUGGESTION")
    
    # Priority 4: Mood-based recommendation with personalization
    recommendations = recommender.recommend_by_mood(genre_lower)
    if recommendations:
        if preferred_language == 'telugu':
            response = f"For a {genre_or_mood} mood, I recommend: {', '.join(recommendations)}. Would you prefer Telugu songs in this mood?"
        else:
            response = f"For a {genre_or_mood} mood, I recommend: {', '.join(recommendations)}"
        return format_response(response, intent="SUGGESTION")
    
    # Fallback to intelligent recommendation
    recommendation = recommender.recommend_by_context(context)
    return format_response(recommendation, intent="SUGGESTION")

def get_genre_list() -> List[str]:
    """Get list of available genres"""
    return list(recommender.genres.keys())

def get_mood_list() -> List[str]:
    """Get list of available moods"""
    moods = set()
    for genre_info in recommender.genres.values():
        moods.update(genre_info['mood'])
    return list(moods)

def get_recommender_instance():
    """Get the global recommender instance"""
    return recommender
