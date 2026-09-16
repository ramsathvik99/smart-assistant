# life_recommendation.py
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
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
    print(f"[LIFE RECOMMENDATION] Preference engine import failed: {e}")
    PREFERENCE_ENGINE_AVAILABLE = False
    
    # Fallback functions
    def get_preference_engine(): return None
    def detect_user_language(cmd): return 'english'
    def detect_user_genre(cmd, cat): return None
    def update_user_preference(cat, cmd): pass
    def get_adaptive_context(cat, ctx): return {'preferences': {}}

# Import holistic guidance engine
try:
    from extensions.holistic_guidance_engine import (
        generate_holistic_guidance,
        format_holistic_response,
        detect_guidance_domain,
        get_follow_up_questions
    )
    HOLISTIC_ENGINE_AVAILABLE = True
except ImportError as e:
    print(f"[LIFE RECOMMENDATION] Holistic engine import failed: {e}")
    HOLISTIC_ENGINE_AVAILABLE = False
    
    # Fallback functions
    def generate_holistic_guidance(query, context): return {}
    def format_holistic_response(data): return str(data)
    def detect_guidance_domain(query): return 'life', 'general'
    def get_follow_up_questions(domain, intent): return []

class LifeRecommender:
    """Intelligent life recommendation system with context awareness and behavioral analysis"""
    
    def __init__(self):
        # Initialize command memory for pattern detection
        self.command_memory = CommandMemory()
        self.last_activity_time = time.time()
        self.session_start_time = time.time()
        self.work_start_time = None
        
        # Behavioral patterns tracking
        self.productivity_patterns = {
            'work_sessions': [],
            'break_times': [],
            'idle_periods': [],
            'repeated_tasks': [],
            'stress_indicators': []
        }
        
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
    
    def get_idle_time(self) -> float:
        """Calculate idle time since last activity"""
        return time.time() - self.last_activity_time
    
    def get_session_duration(self) -> float:
        """Get current session duration"""
        return time.time() - self.session_start_time
    
    def analyze_work_patterns(self) -> Dict[str, any]:
        """Analyze user work and productivity patterns"""
        patterns = {
            'working_long_hours': False,
            'frequent_breaks': False,
            'high_stress_level': False,
            'productive_morning': False,
            'evening_relaxation': False,
            'repetitive_tasks': False
        }
        
        # Analyze recent commands for work patterns
        recent_commands = self.command_memory._commands[-20:] if len(self.command_memory._commands) >= 20 else self.command_memory._commands
        
        if recent_commands:
            # Check for work-related commands
            work_commands = [cmd for cmd in recent_commands if any(keyword in cmd.lower() for keyword in ['work', 'code', 'project', 'task', 'meeting'])]
            
            # Check for stress indicators
            stress_commands = [cmd for cmd in recent_commands if any(keyword in cmd.lower() for keyword in ['stress', 'tired', 'frustrated', 'stuck', 'help'])]
            
            # Check for repetitive tasks
            task_frequency = {}
            for cmd in work_commands:
                base_task = cmd.lower().split()[0] if cmd.lower().split() else cmd.lower()
                task_frequency[base_task] = task_frequency.get(base_task, 0) + 1
            
            patterns['working_long_hours'] = len(work_commands) > 10  # Many work commands
            patterns['high_stress_level'] = len(stress_commands) > 2
            patterns['repetitive_tasks'] = any(count > 3 for count in task_frequency.values())
            
            # Analyze time-based patterns
            current_hour = datetime.now().hour
            patterns['productive_morning'] = 6 <= current_hour <= 10 and len(work_commands) > 5
            patterns['evening_relaxation'] = 18 <= current_hour <= 22 and len(work_commands) < 3
        
        return patterns
    
    def analyze_behavioral_patterns(self) -> Dict[str, any]:
        """Analyze user behavioral patterns for recommendations"""
        patterns = {
            'procrastination_detected': False,
            'sedentary_behavior': False,
            'screen_time_high': False,
            'break_needed': False,
            'motivation_low': False
        }
        
        # Check idle time
        idle_time = self.get_idle_time()
        if idle_time > 1800:  # 30 minutes
            patterns['sedentary_behavior'] = True
            patterns['break_needed'] = True
        
        # Check session duration
        session_duration = self.get_session_duration()
        if session_duration > 14400:  # 4 hours
            patterns['screen_time_high'] = True
            patterns['break_needed'] = True
        
        # Check for procrastination indicators
        recent_commands = self.command_memory._commands[-10:] if len(self.command_memory._commands) >= 10 else self.command_memory._commands
        distraction_commands = [cmd for cmd in recent_commands if any(keyword in cmd.lower() for keyword in ['youtube', 'social', 'reddit', 'browse', 'entertainment'])]
        
        if len(distraction_commands) > 5:
            patterns['procrastination_detected'] = True
            patterns['motivation_low'] = True
        
        return patterns
    
    def recommend_by_context(self, context: Dict[str, any]) -> str:
        """Generate intelligent life recommendation based on context and patterns"""
        time_context = self.get_time_context()
        work_patterns = self.analyze_work_patterns()
        behavioral_patterns = self.analyze_behavioral_patterns()
        idle_time = self.get_idle_time()
        
        # Priority 1: Health and wellness recommendations
        if idle_time > 1800:  # 30 minutes idle
            return "You've been inactive for a while. Maybe take a short walk or do some stretches to stay healthy."
        
        if behavioral_patterns.get('screen_time_high', False):
            return "You've been using the computer for a long time. Consider taking a 15-minute break to rest your eyes and mind."
        
        # Priority 2: Work and productivity recommendations
        if work_patterns.get('working_long_hours', False):
            return "You've been working a lot. Consider taking a meaningful break to recharge and maintain productivity."
        
        if work_patterns.get('high_stress_level', False):
            return "I notice some stress indicators. Maybe take a few deep breaths or step away for a moment to clear your mind."
        
        if behavioral_patterns.get('procrastination_detected', False):
            return "It seems like you might be procrastinating. How about we tackle one small task together to get started?"
        
        # Priority 3: Time-based recommendations
        if time_context == "morning":
            if work_patterns.get('productive_morning', False):
                return "Starting your day with a clear plan and priorities might help maintain this productive momentum."
            else:
                return "Good morning! Consider setting 3 main goals for today to give your day direction and purpose."
        
        elif time_context == "afternoon":
            if work_patterns.get('working_long_hours', False):
                return "Afternoon energy dip is normal. Maybe take a short break or switch to a different type of task."
            else:
                return "Afternoon is a great time to review progress and adjust your day's plan if needed."
        
        elif time_context == "evening":
            if work_patterns.get('evening_relaxation', False):
                return "Evening relaxation time is important. Consider winding down with something enjoyable and screen-free."
            else:
                return "Evening is perfect for reflection. Maybe review what you accomplished today and plan tomorrow."
        
        elif time_context == "night":
            return "Late hours are best for rest. Consider preparing for tomorrow and getting quality sleep to recharge."
        
        # Priority 4: Behavioral recommendations
        if behavioral_patterns.get('repetitive_tasks', False):
            return "I notice you're doing repetitive tasks. Maybe we can automate some of these or find more efficient approaches?"
        
        if behavioral_patterns.get('motivation_low', False):
            return "Motivation seems low. How about breaking your current task into smaller, more manageable steps?"
        
        # Default intelligent recommendation
        return "Want me to suggest something useful based on your current situation and patterns?"
    
    def recommend_for_stress_relief(self) -> str:
        """Provide stress relief recommendations"""
        stress_relief_options = [
            "Take 5 deep breaths, inhaling for 4 counts and exhaling for 6 counts.",
            "Step away from your screen and look at something 20 feet away for 20 seconds.",
            "Do a quick 2-minute stretch focusing on your neck and shoulders.",
            "Listen to one calming song or nature sounds.",
            "Write down 3 things you're grateful for right now."
        ]
        
        import random
        return random.choice(stress_relief_options)
    
    def recommend_for_productivity(self) -> str:
        """Provide productivity enhancement recommendations"""
        productivity_tips = [
            "Try the Pomodoro technique: 25 minutes of focused work, then 5-minute break.",
            "Clear your workspace and minimize distractions before starting important tasks.",
            "Start with your most challenging task when your energy is highest.",
            "Break large projects into smaller, specific action steps.",
            "Set a timer for tasks to create urgency and maintain focus."
        ]
        
        import random
        return random.choice(productivity_tips)
    
    def update_activity(self):
        """Update last activity time"""
        self.last_activity_time = time.time()
    
    def start_work_session(self):
        """Track work session start time"""
        if not self.work_start_time:
            self.work_start_time = time.time()
    
    def end_work_session(self):
        """Track work session end and analyze patterns"""
        if self.work_start_time:
            session_duration = time.time() - self.work_start_time
            self.productivity_patterns['work_sessions'].append({
                'start': self.work_start_time,
                'duration': session_duration,
                'timestamp': time.time()
            })
            self.work_start_time = None

# Global recommender instance
recommender = LifeRecommender()

def life_recommendation(context: Dict[str, any] = None, specific_need: str = None) -> str:
    """Main life recommendation function with holistic guidance and personalization"""
    if context is None:
        context = {}
    
    # Auto-detect language from command if available
    detected_language = None
    if 'command' in context:
        detected_language = detect_user_language(context['command'])
        if detected_language:
            # Store preference for life category
            update_user_preference('life', context['command'])
    
    # Get adaptive context with preferences
    if PREFERENCE_ENGINE_AVAILABLE:
        adaptive_context = get_adaptive_context('life', context)
        preferences = adaptive_context.get('preferences', {})
        preferred_language = adaptive_context.get('preferred_language', 'english')
    else:
        adaptive_context = {}
        preferences = {}
        preferred_language = 'english'
    
    # Priority 1: Holistic Guidance for "what should I..." questions
    if HOLISTIC_ENGINE_AVAILABLE and 'command' in context:
        command = context['command'].lower()
        if any(phrase in command for phrase in ['what should i', 'what to', 'how to', 'guide me']):
            # Detect if this is a holistic guidance request
            domain, intent = detect_guidance_domain(context['command'])
            
            # Build user context for personalization
            user_context = {
                'tech_interest': any(keyword in command for keyword in ['tech', 'computer', 'programming', 'software']),
                'creative_interest': any(keyword in command for keyword in ['creative', 'art', 'design', 'music', 'writing']),
                'preferred_language': preferred_language,
                'preferences': preferences
            }
            
            # Generate holistic guidance
            holistic_data = generate_holistic_guidance(context['command'], user_context)
            
            if holistic_data and holistic_data.get('sections'):
                # Format holistic response
                holistic_response = format_holistic_response(holistic_data)
                
                # Add language-specific enhancement
                if preferred_language == 'telugu':
                    holistic_response += f"\n\nమీరు తెలుగులో సలహా కావాలంటే, నేను తెలుగులో కూడా సహాయం చేస్తాను."
                
                return format_response(holistic_response, intent="SUGGESTION")
    
    # Priority 2: Language-specific recommendations for non-holistic queries
    if preferred_language == 'telugu' and not specific_need:
        time_context = self.get_time_context()
        behavioral_patterns = self.analyze_behavioral_patterns()
        
        if time_context == "morning":
            recommendation = "Good morning! Starting your day with some positive Telugu thoughts might help set a good tone."
        elif time_context == "afternoon":
            if behavioral_patterns.get('screen_time_high', False):
                recommendation = "You've been using screen for a while. How about some Telugu relaxation tips or a short walk?"
            else:
                recommendation = "Afternoon is perfect time for productivity. Want some Telugu motivational advice?"
        elif time_context == "evening":
            recommendation = "Evening relaxation time! Some calming Telugu music or meditation might be perfect."
        elif time_context == "night":
            recommendation = "Late night is good for rest. Some peaceful Telugu devotional content could help you sleep better."
        else:
            recommendation = "Based on your Telugu preferences, I can suggest something useful. What do you need help with?"
        
        return format_response(recommendation, intent="SUGGESTION")
    
    # Priority 3: Specific need-based recommendations with language awareness
    if specific_need:
        if specific_need.lower() in ['stress', 'overwhelmed']:
            if preferred_language == 'telugu':
                recommendation = "Take deep breaths and try some Telugu calming music. Everything will be okay."
            else:
                recommendation = recommender.recommend_for_stress_relief()
        
        elif specific_need.lower() in ['productivity', 'focus']:
            if preferred_language == 'telugu':
                recommendation = "Try breaking tasks into smaller steps and use some Telugu motivational content."
            else:
                recommendation = recommender.recommend_for_productivity()
        
        elif specific_need.lower() in ['break']:
            if preferred_language == 'telugu':
                recommendation = "Good break! How about some refreshing Telugu content to recharge?"
            else:
                recommendation = "Taking regular breaks is essential for maintaining productivity and well-being."
        
        else:
            # Use original logic with language awareness
            recommendation = recommender.recommend_by_context(context)
            if preferred_language == 'telugu':
                recommendation += " Would you prefer Telugu content for this?"
        
        return format_response(recommendation, intent="SUGGESTION")
    
    # Priority 4: Context-based intelligent recommendation with personalization
    if not specific_need:
        recommendation = recommender.recommend_by_context(context)
        
        # Add language-specific enhancement for English users with Telugu preferences
        if PREFERENCE_ENGINE_AVAILABLE and preferences:
            life_prefs = preferences.get('life', {})
            if life_prefs and preferred_language == 'english' and any('telugu' in key for key in life_prefs.keys() for key in ['telugu']):
                recommendation += " I notice you sometimes prefer Telugu content. Would you like me to suggest that occasionally?"
        
        return format_response(recommendation, intent="SUGGESTION")

def get_holistic_guidance(query: str, user_context: Dict[str, Any] = None) -> str:
    """Specialized function for holistic guidance queries"""
    if user_context is None:
        user_context = {}
    
    if HOLISTIC_ENGINE_AVAILABLE:
        holistic_data = generate_holistic_guidance(query, user_context)
        if holistic_data:
            return format_holistic_response(holistic_data)
    
    return "I can help you with that. Let me provide some guidance based on your situation."

def update_work_session(start: bool = True):
    """Update work session tracking"""
    if start:
        recommender.start_work_session()
    else:
        recommender.end_work_session()

def get_productivity_insights() -> Dict[str, any]:
    """Get insights about user productivity patterns"""
    work_patterns = recommender.analyze_work_patterns()
    behavioral_patterns = recommender.analyze_behavioral_patterns()
    
    return {
        'work_patterns': work_patterns,
        'behavioral_patterns': behavioral_patterns,
        'session_duration': recommender.get_session_duration(),
        'idle_time': recommender.get_idle_time()
    }
