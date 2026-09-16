"""
User Preference Engine
Manages user preferences across languages and genres for personalized recommendations.
"""

import json
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from pathlib import Path

class UserPreferenceEngine:
    """Manages user preferences with adaptive learning and language support"""
    
    def __init__(self):
        self.preferences_file = Path(__file__).parent.parent / "data" / "user_preferences.json"
        self.preferences_file.parent.mkdir(exist_ok=True)
        
        self.lock = threading.Lock()
        self._load_preferences()
        
        # Initialize with default preferences if empty
        self._ensure_default_preferences()
        
        print("[PREFERENCE ENGINE] User preference system initialized")
    
    def _load_preferences(self):
        """Load preferences from file"""
        try:
            if self.preferences_file.exists():
                with open(self.preferences_file, 'r', encoding='utf-8') as f:
                    self.preferences = json.load(f)
            else:
                self.preferences = {}
        except Exception as e:
            print(f"[PREFERENCE ENGINE] Failed to load preferences: {e}")
            self.preferences = {}
    
    def _save_preferences(self):
        """Save preferences to file"""
        try:
            with open(self.preferences_file, 'w', encoding='utf-8') as f:
                json.dump(self.preferences, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[PREFERENCE ENGINE] Failed to save preferences: {e}")
    
    def _ensure_default_preferences(self):
        """Ensure default preferences exist"""
        if 'user_id' not in self.preferences:
            self.preferences['user_id'] = 'default_user'
        
        if 'music' not in self.preferences:
            self.preferences['music'] = {}
        
        if 'movies' not in self.preferences:
            self.preferences['movies'] = {}
        
        if 'life' not in self.preferences:
            self.preferences['life'] = {}
        
        if 'usage_history' not in self.preferences:
            self.preferences['usage_history'] = {
                'music': {},
                'movies': {},
                'life': {}
            }
        
        if 'language_detection' not in self.preferences:
            self.preferences['language_detection'] = {
                'telugu_keywords': ['telugu', 'andhra', 'tamil', 'malayalam', 'kannada', 'hindi'],
                'music_keywords': ['song', 'music', 'gaana', 'pata', 'melody', 'beat'],
                'movie_keywords': ['movie', 'cinema', 'film', 'picture', 'flick'],
                'life_keywords': ['advice', 'suggest', 'help', 'tip', 'recommend']
            }
        
        self._save_preferences()
    
    def detect_language_from_command(self, command: str) -> Optional[str]:
        """Detect language from user command"""
        command_lower = command.lower()
        lang_detection = self.preferences.get('language_detection', {})
        
        # Check for Indian language keywords
        for keyword in lang_detection.get('telugu_keywords', []):
            if keyword in command_lower:
                return 'telugu'
        
        # Check for language-specific patterns
        if any(word in command_lower for word in ['telugu song', 'andhra melody', 'tamil music']):
            return 'telugu'
        
        # Default to English for now
        return 'english'
    
    def detect_genre_from_command(self, command: str, category: str) -> Optional[str]:
        """Detect genre from user command"""
        command_lower = command.lower()
        
        # Genre mappings for different categories
        genre_mappings = {
            'music': {
                'telugu': {
                    'classical': ['classical', 'carnatic', 'traditional', 'old'],
                    'devotional': ['devotional', 'bhakti', 'spiritual', 'temple'],
                    'folk': ['folk', 'traditional', 'village', 'rural'],
                    'modern': ['modern', 'latest', 'new', 'trending'],
                    'romantic': ['romantic', 'love', 'melody', 'heart']
                },
                'english': {
                    'rock': ['rock', 'metal', 'alternative', 'band'],
                    'pop': ['pop', 'hip', 'top', 'chart'],
                    'electronic': ['electronic', 'edm', 'techno', 'dj'],
                    'jazz': ['jazz', 'blues', 'smooth', 'soul'],
                    'classical': ['classical', 'piano', 'orchestra', 'symphony']
                }
            },
            'movies': {
                'telugu': {
                    'action': ['action', 'fight', 'mass', 'commercial'],
                    'drama': ['drama', 'family', 'emotional', 'sentiment'],
                    'comedy': ['comedy', 'funny', 'laughter', 'entertainment'],
                    'thriller': ['thriller', 'suspense', 'crime', 'mystery'],
                    'romance': ['romance', 'love', 'heart', 'relationship']
                },
                'english': {
                    'action': ['action', 'adventure', 'superhero', 'marvel'],
                    'sci-fi': ['sci-fi', 'science fiction', 'space', 'future'],
                    'comedy': ['comedy', 'funny', 'humor', 'satire'],
                    'drama': ['drama', 'serious', 'emotional', 'inspiring'],
                    'thriller': ['thriller', 'horror', 'suspense', 'mystery']
                }
            }
        }
        
        # Detect language first
        language = self.detect_language_from_command(command)
        
        # Search for genre keywords
        if category in genre_mappings and language in genre_mappings[category]:
            for genre, keywords in genre_mappings[category][language].items():
                if any(keyword in command_lower for keyword in keywords):
                    return genre
        
        return None
    
    def update_preference(self, category: str, language: str, genre: str):
        """Update user preference for category and language"""
        with self.lock:
            if category not in self.preferences:
                self.preferences[category] = {}
            
            if language not in self.preferences[category]:
                self.preferences[category][language] = {}
            
            # Update genre frequency
            if genre not in self.preferences[category][language]:
                self.preferences[category][language][genre] = {'count': 0, 'last_used': None}
            
            self.preferences[category][language][genre]['count'] += 1
            self.preferences[category][language][genre]['last_used'] = datetime.now().isoformat()
            
            # Update usage history
            if category not in self.preferences['usage_history']:
                self.preferences['usage_history'][category] = {}
            
            if language not in self.preferences['usage_history'][category]:
                self.preferences['usage_history'][category][language] = {'genres': {}, 'total_usage': 0}
            
            if genre not in self.preferences['usage_history'][category][language]['genres']:
                self.preferences['usage_history'][category][language]['genres'][genre] = 0
            
            self.preferences['usage_history'][category][language]['genres'][genre] += 1
            self.preferences['usage_history'][category][language]['total_usage'] += 1
            
            self._save_preferences()
            
            print(f"[PREFERENCE ENGINE] Updated {category} preference: {language} -> {genre}")
    
    def get_most_used_language(self, category: str) -> Optional[str]:
        """Get most used language for a category"""
        if category not in self.preferences.get('usage_history', {}):
            return None
        
        category_history = self.preferences['usage_history'][category]
        max_usage = 0
        most_used_lang = None
        
        for language, data in category_history.items():
            if data.get('total_usage', 0) > max_usage:
                max_usage = data['total_usage']
                most_used_lang = language
        
        return most_used_lang
    
    def get_most_used_genre(self, category: str, language: str) -> Optional[str]:
        """Get most used genre for category and language"""
        if category not in self.preferences.get('usage_history', {}):
            return None
        
        if language not in self.preferences['usage_history'][category]:
            return None
        
        language_data = self.preferences['usage_history'][category][language]
        max_genre_usage = 0
        most_used_genre = None
        
        for genre, count in language_data.get('genres', {}).items():
            if count > max_genre_usage:
                max_genre_usage = count
                most_used_genre = genre
        
        return most_used_genre
    
    def get_preference_summary(self, category: str) -> Dict[str, Any]:
        """Get preference summary for a category"""
        with self.lock:
            category_prefs = self.preferences.get(category, {})
            category_history = self.preferences.get('usage_history', {}).get(category, {})
            
            most_used_lang = self.get_most_used_language(category)
            
            summary = {
                'preferences': category_prefs,
                'most_used_language': most_used_lang,
                'usage_history': category_history,
                'total_interactions': sum(
                    data.get('total_usage', 0) for data in category_history.values()
                )
            }
            
            if most_used_lang:
                summary['most_used_genre'] = self.get_most_used_genre(category, most_used_lang)
            
            return summary
    
    def get_adaptive_recommendation(self, category: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Get adaptive recommendation based on preferences and context"""
        with self.lock:
            summary = self.get_preference_summary(category)
            most_used_lang = summary.get('most_used_language', 'english')
            most_used_genre = summary.get('most_used_genre')
            
            # Build recommendation context
            recommendation_context = {
                'detected_language': self.detect_language_from_command(context.get('command', '')),
                'preferred_language': most_used_lang,
                'preferred_genre': most_used_genre,
                'time_context': context.get('time', datetime.now().hour),
                'mood': context.get('mood', ''),
                'activity': context.get('activity', ''),
                'preferences': summary
            }
            
            return recommendation_context
    
    def auto_learn_from_command(self, category: str, command: str, response: str):
        """Automatically learn from user interactions"""
        language = self.detect_language_from_command(command)
        genre = self.detect_genre_from_command(command, category)
        
        if genre:
            self.update_preference(category, language, genre)
            print(f"[PREFERENCE ENGINE] Auto-learned: {category} -> {language} -> {genre}")

# Global instance
preference_engine = None

def get_preference_engine() -> UserPreferenceEngine:
    """Get or create preference engine instance"""
    global preference_engine
    if preference_engine is None:
        preference_engine = UserPreferenceEngine()
    return preference_engine

def detect_user_language(command: str) -> Optional[str]:
    """Detect language from user command"""
    engine = get_preference_engine()
    if engine:
        return engine.detect_language_from_command(command)
    return 'english'

def detect_user_genre(command: str, category: str) -> Optional[str]:
    """Detect genre from user command"""
    engine = get_preference_engine()
    if engine:
        return engine.detect_genre_from_command(command, category)
    return None

def update_user_preference(category: str, command: str):
    """Update user preference from command"""
    engine = get_preference_engine()
    if engine:
        language = engine.detect_language_from_command(command)
        genre = engine.detect_genre_from_command(command, category)
        if genre:
            engine.update_preference(category, language, genre)

def get_adaptive_context(category: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Get adaptive recommendation context"""
    engine = get_preference_engine()
    if engine:
        return engine.get_adaptive_recommendation(category, context)
    return {'preferences': {}, 'preferred_language': 'english'}
