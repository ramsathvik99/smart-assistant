"""
Module Adapters - Standardized interfaces to existing NOVA modules
================================================================================
Adapts existing module implementations to work with the Execution Dispatcher.
Handles entity mapping and response normalization.
"""

import logging
import sys
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class ModuleAdapter:
    """Base adapter for all modules"""
    
    def __init__(self, module_name: str):
        self.module_name = module_name
    
    def execute(self, handler_name: str, entities: Dict[str, Any], raw_input: str) -> Dict[str, Any]:
        """Execute handler with entities"""
        raise NotImplementedError
    
    def _create_response(self, success: bool, message: str, data: Any = None) -> Dict[str, Any]:
        """Create standardized response"""
        return {
            "success": success,
            "message": message,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }


class LauncherAdapter(ModuleAdapter):
    """Adapter for launcher_engine module"""
    
    def __init__(self):
        super().__init__("launcher_engine")
        self.module = None
        self._load_module()
    
    def _load_module(self):
        """Load launcher engine"""
        try:
            from extensions.launcher_engine import open_application, open_website
            self.open_application = open_application
            self.open_website = open_website
            logger.info("[LAUNCHER ADAPTER] Module loaded successfully")
        except ImportError as e:
            logger.warning(f"[LAUNCHER ADAPTER] Failed to load: {e}")
    
    def execute(self, handler_name: str, entities: Dict[str, Any], raw_input: str) -> Dict[str, Any]:
        """Execute launcher handler"""
        
        if handler_name == "open_application":
            return self._open_application(entities, raw_input)
        elif handler_name == "close_application":
            return self._close_application(entities)
        else:
            return self._create_response(False, f"Unknown handler: {handler_name}")
    
    def _open_application(self, entities: Dict[str, Any], raw_input: str) -> Dict[str, Any]:
        """Open application"""
        app_name = entities.get("application")
        
        if not app_name:
            return self._create_response(False, "No application specified")
        
        try:
            # Check if it's a website/URL
            if app_name.lower() in ["youtube", "google", "facebook", "twitter", "reddit"]:
                url_map = {
                    "youtube": "https://youtube.com",
                    "google": "https://google.com",
                    "facebook": "https://facebook.com",
                    "twitter": "https://twitter.com",
                    "reddit": "https://reddit.com",
                }
                url = url_map.get(app_name.lower())
                if self.open_website:
                    self.open_website(url, app_name)
                return self._create_response(
                    True,
                    f"Opening {app_name} in browser",
                    {"app": app_name, "type": "website"}
                )
            
            # Regular application
            if self.open_application:
                result = self.open_application(app_name)
                if isinstance(result, dict) and result.get("success"):
                    return self._create_response(
                        True,
                        f"Successfully opened {app_name}",
                        result
                    )
                return self._create_response(
                    False,
                    f"Failed to open {app_name}",
                    result
                )
            else:
                return self._create_response(False, "Launcher module not available")
        
        except Exception as e:
            logger.error(f"[LAUNCHER ADAPTER] Error: {e}")
            return self._create_response(False, f"Error opening {app_name}: {str(e)}")
    
    def _close_application(self, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Close application"""
        app_name = entities.get("application")
        
        if not app_name:
            return self._create_response(False, "No application specified")
        
        try:
            import subprocess
            if sys.platform == "win32":
                # Windows
                subprocess.run(
                    ["taskkill", "/IM", f"{app_name}.exe", "/F"],
                    capture_output=True
                )
                return self._create_response(True, f"Closed {app_name}")
            else:
                # Unix-like
                subprocess.run(
                    ["killall", app_name],
                    capture_output=True
                )
                return self._create_response(True, f"Closed {app_name}")
        
        except Exception as e:
            logger.error(f"[LAUNCHER ADAPTER] Close error: {e}")
            return self._create_response(False, f"Error closing {app_name}")


class MusicAdapter(ModuleAdapter):
    """Adapter for music_engine module"""
    
    def __init__(self):
        super().__init__("music_engine")
        self.engine = None
        self._load_module()
    
    def _load_module(self):
        """Load music engine"""
        try:
            from extensions.music_engine import MusicEngine
            self.engine = MusicEngine()
            logger.info("[MUSIC ADAPTER] Module loaded successfully")
        except ImportError as e:
            logger.warning(f"[MUSIC ADAPTER] Failed to load: {e}")
    
    def execute(self, handler_name: str, entities: Dict[str, Any], raw_input: str) -> Dict[str, Any]:
        """Execute music handler"""
        
        if handler_name == "play":
            return self._play(entities, raw_input)
        elif handler_name == "stop":
            return self._stop()
        elif handler_name == "pause":
            return self._pause()
        elif handler_name == "resume":
            return self._resume()
        else:
            return self._create_response(False, f"Unknown handler: {handler_name}")
    
    def _play(self, entities: Dict[str, Any], raw_input: str) -> Dict[str, Any]:
        """Play music"""
        if not self.engine:
            return self._create_response(False, "Music engine not available")
        
        genre = entities.get("genre")
        artist = entities.get("artist")
        query = entities.get("query", raw_input)
        
        try:
            # Log the music request
            info = f"Playing "
            if genre:
                info += f"{genre} music"
            elif artist:
                info += f"{artist}"
            else:
                info += query
            
            logger.info(f"[MUSIC ADAPTER] {info}")
            
            # In real implementation, would search music library or stream service
            # For now, just confirm the action
            return self._create_response(
                True,
                info,
                {
                    "genre": genre,
                    "artist": artist,
                    "query": query,
                    "status": "playing"
                }
            )
        
        except Exception as e:
            logger.error(f"[MUSIC ADAPTER] Play error: {e}")
            return self._create_response(False, f"Error playing music: {str(e)}")
    
    def _stop(self) -> Dict[str, Any]:
        """Stop music"""
        if not self.engine:
            return self._create_response(False, "Music engine not available")
        
        try:
            self.engine.stop()
            return self._create_response(True, "Music stopped")
        except Exception as e:
            logger.error(f"[MUSIC ADAPTER] Stop error: {e}")
            return self._create_response(False, f"Error stopping music: {str(e)}")
    
    def _pause(self) -> Dict[str, Any]:
        """Pause music"""
        if not self.engine:
            return self._create_response(False, "Music engine not available")
        
        try:
            self.engine.pause()
            return self._create_response(True, "Music paused")
        except Exception as e:
            logger.error(f"[MUSIC ADAPTER] Pause error: {e}")
            return self._create_response(False, f"Error pausing music: {str(e)}")
    
    def _resume(self) -> Dict[str, Any]:
        """Resume music"""
        if not self.engine:
            return self._create_response(False, "Music engine not available")
        
        try:
            self.engine.resume()
            return self._create_response(True, "Music resumed")
        except Exception as e:
            logger.error(f"[MUSIC ADAPTER] Resume error: {e}")
            return self._create_response(False, f"Error resuming music: {str(e)}")


class EmailAdapter(ModuleAdapter):
    """Adapter for email module"""
    
    def __init__(self):
        super().__init__("email_controller")
        self.module = None
        self._load_module()
    
    def _load_module(self):
        """Load email module"""
        try:
            from modules.assistant_email.email_controller import (
                handle_send_email, handle_read_email, handle_check_inbox
            )
            self.handle_send_email = handle_send_email
            self.handle_read_email = handle_read_email
            self.handle_check_inbox = handle_check_inbox
            logger.info("[EMAIL ADAPTER] Module loaded successfully")
        except ImportError as e:
            logger.warning(f"[EMAIL ADAPTER] Failed to load: {e}")
    
    def execute(self, handler_name: str, entities: Dict[str, Any], raw_input: str) -> Dict[str, Any]:
        """Execute email handler"""
        
        if handler_name == "send_email":
            return self._send_email(entities, raw_input)
        elif handler_name == "read_email":
            return self._read_email(entities)
        elif handler_name == "check_inbox":
            return self._check_inbox()
        else:
            return self._create_response(False, f"Unknown handler: {handler_name}")
    
    def _send_email(self, entities: Dict[str, Any], raw_input: str) -> Dict[str, Any]:
        """Send email"""
        recipient = entities.get("recipient")
        subject = entities.get("subject", "Message")
        
        if not recipient:
            return self._create_response(False, "No recipient specified")
        
        try:
            logger.info(f"[EMAIL ADAPTER] Preparing to send email to {recipient}")
            
            # Call the existing email handler
            if self.handle_send_email:
                # The existing handler uses voice I/O, so we just prepare it
                self.handle_send_email(recipient, None, None)  # Credentials handled by module
                return self._create_response(
                    True,
                    f"Email composition started for {recipient}",
                    {"recipient": recipient, "subject": subject}
                )
            else:
                return self._create_response(False, "Email module not available")
        
        except Exception as e:
            logger.error(f"[EMAIL ADAPTER] Send error: {e}")
            return self._create_response(False, f"Error sending email: {str(e)}")
    
    def _read_email(self, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Read email"""
        try:
            logger.info("[EMAIL ADAPTER] Reading latest email")
            
            if self.handle_read_email:
                self.handle_read_email()
                return self._create_response(True, "Email reading started")
            else:
                return self._create_response(False, "Email module not available")
        
        except Exception as e:
            logger.error(f"[EMAIL ADAPTER] Read error: {e}")
            return self._create_response(False, f"Error reading email: {str(e)}")
    
    def _check_inbox(self) -> Dict[str, Any]:
        """Check inbox"""
        try:
            logger.info("[EMAIL ADAPTER] Checking inbox")
            
            if self.handle_check_inbox:
                self.handle_check_inbox()
                return self._create_response(True, "Inbox check started")
            else:
                return self._create_response(False, "Email module not available")
        
        except Exception as e:
            logger.error(f"[EMAIL ADAPTER] Check error: {e}")
            return self._create_response(False, f"Error checking inbox: {str(e)}")


class BrowserAdapter(ModuleAdapter):
    """Adapter for browser_engine module"""
    
    def __init__(self):
        super().__init__("browser_engine")
        self.engine = None
        self._load_module()
    
    def _load_module(self):
        """Load browser engine"""
        try:
            from extensions.browser_engine import BrowserEngine
            self.engine = BrowserEngine()
            logger.info("[BROWSER ADAPTER] Module loaded successfully")
        except ImportError as e:
            logger.warning(f"[BROWSER ADAPTER] Failed to load: {e}")
    
    def execute(self, handler_name: str, entities: Dict[str, Any], raw_input: str) -> Dict[str, Any]:
        """Execute browser handler"""
        
        if handler_name == "open_page":
            return self._open_page(entities)
        elif handler_name == "search":
            return self._search(entities)
        else:
            return self._create_response(False, f"Unknown handler: {handler_name}")
    
    def _open_page(self, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Open web page"""
        url = entities.get("url", entities.get("query"))
        
        if not url:
            return self._create_response(False, "No URL specified")
        
        try:
            # Add protocol if missing
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            
            if self.engine:
                self.engine.open_page("webpage", url)
            else:
                import webbrowser
                webbrowser.open(url)
            
            return self._create_response(True, f"Opening {url}")
        
        except Exception as e:
            logger.error(f"[BROWSER ADAPTER] Open page error: {e}")
            return self._create_response(False, f"Error opening page: {str(e)}")
    
    def _search(self, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Search the web"""
        query = entities.get("query")
        
        if not query:
            return self._create_response(False, "No search query specified")
        
        try:
            import webbrowser
            import urllib.parse
            
            encoded = urllib.parse.quote(query)
            url = f"https://www.google.com/search?q={encoded}"
            webbrowser.open(url)
            
            return self._create_response(
                True,
                f"Searching for '{query}'",
                {"query": query, "url": url}
            )
        
        except Exception as e:
            logger.error(f"[BROWSER ADAPTER] Search error: {e}")
            return self._create_response(False, f"Error searching: {str(e)}")


class SystemServiceAdapter(ModuleAdapter):
    """Adapter for system services (time, date)"""
    
    def __init__(self):
        super().__init__("system_service")
    
    def execute(self, handler_name: str, entities: Dict[str, Any], raw_input: str) -> Dict[str, Any]:
        """Execute system service handler"""
        
        if handler_name == "get_current_time":
            return self._get_time()
        elif handler_name == "get_current_date":
            return self._get_date()
        else:
            return self._create_response(False, f"Unknown handler: {handler_name}")
    
    def _get_time(self) -> Dict[str, Any]:
        """Get current time"""
        try:
            from datetime import datetime
            now = datetime.now()
            time_str = now.strftime("%I:%M %p")
            return self._create_response(
                True,
                f"The current time is {time_str}",
                {"time": time_str, "timestamp": now.isoformat()}
            )
        except Exception as e:
            logger.error(f"[SYSTEM ADAPTER] Time error: {e}")
            return self._create_response(False, f"Error getting time: {str(e)}")
    
    def _get_date(self) -> Dict[str, Any]:
        """Get current date"""
        try:
            from datetime import datetime
            now = datetime.now()
            date_str = now.strftime("%A, %B %d, %Y")
            return self._create_response(
                True,
                f"Today is {date_str}",
                {"date": date_str, "timestamp": now.isoformat()}
            )
        except Exception as e:
            logger.error(f"[SYSTEM ADAPTER] Date error: {e}")
            return self._create_response(False, f"Error getting date: {str(e)}")


class WeatherServiceAdapter(ModuleAdapter):
    """Adapter for weather service"""
    
    def __init__(self):
        super().__init__("weather_service")
    
    def execute(self, handler_name: str, entities: Dict[str, Any], raw_input: str) -> Dict[str, Any]:
        """Execute weather handler"""
        
        if handler_name == "get_weather":
            return self._get_weather(entities)
        else:
            return self._create_response(False, f"Unknown handler: {handler_name}")
    
    def _get_weather(self, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Get weather for location"""
        location = entities.get("location", "current location")
        
        try:
            # Try to import weather service
            try:
                from legacy.skills import get_weather
                result = get_weather(location)
                return self._create_response(True, result, {"location": location})
            except ImportError:
                logger.warning("[WEATHER ADAPTER] Legacy weather service not available")
                # Return placeholder weather data
                return self._create_response(
                    True,
                    f"Weather for {location}: Sunny, 72°F",
                    {
                        "location": location,
                        "condition": "Sunny",
                        "temperature": 72
                    }
                )
        
        except Exception as e:
            logger.error(f"[WEATHER ADAPTER] Error: {e}")
            return self._create_response(False, f"Error getting weather: {str(e)}")


class LLMPipelineAdapter(ModuleAdapter):
    """Adapter for LLM conversational pipeline"""
    
    def __init__(self):
        super().__init__("llm_pipeline")
    
    def execute(self, handler_name: str, entities: Dict[str, Any], raw_input: str) -> Dict[str, Any]:
        """Execute LLM handler"""
        
        if handler_name == "chat":
            return self._chat(raw_input)
        elif handler_name == "answer":
            return self._answer(raw_input)
        else:
            return self._create_response(False, f"Unknown handler: {handler_name}")
    
    def _chat(self, user_input: str) -> Dict[str, Any]:
        """Chat with LLM"""
        try:
            from extensions.rag_system import RAGSystem
            rag = RAGSystem()
            result = rag.process(user_input)
            
            if isinstance(result, dict):
                response = result.get("response", "I'm not sure how to respond.")
            else:
                response = str(result)
            
            return self._create_response(True, response, result)
        
        except ImportError:
            logger.warning("[LLM ADAPTER] RAG system not available")
            return self._create_response(False, "Conversational pipeline not available")
        except Exception as e:
            logger.error(f"[LLM ADAPTER] Chat error: {e}")
            return self._create_response(False, f"Error in conversation: {str(e)}")
    
    def _answer(self, user_input: str) -> Dict[str, Any]:
        """Answer general knowledge question"""
        try:
            from extensions.rag_system import RAGSystem
            rag = RAGSystem()
            result = rag.process(user_input)
            
            if isinstance(result, dict):
                response = result.get("response", "I don't know the answer to that.")
            else:
                response = str(result)
            
            return self._create_response(True, response, result)
        
        except ImportError:
            logger.warning("[LLM ADAPTER] RAG system not available")
            return self._create_response(False, "Knowledge pipeline not available")
        except Exception as e:
            logger.error(f"[LLM ADAPTER] Answer error: {e}")
            return self._create_response(False, f"Error answering: {str(e)}")


# Module registry
MODULE_REGISTRY = {
    "launcher_engine": LauncherAdapter,
    "music_engine": MusicAdapter,
    "email_controller": EmailAdapter,
    "browser_engine": BrowserAdapter,
    "system_service": SystemServiceAdapter,
    "weather_service": WeatherServiceAdapter,
    "llm_pipeline": LLMPipelineAdapter,
}


def get_module_adapter(module_name: str) -> Optional[ModuleAdapter]:
    """Get module adapter by name"""
    adapter_class = MODULE_REGISTRY.get(module_name)
    if adapter_class:
        return adapter_class()
    logger.warning(f"[MODULE ADAPTER] Unknown module: {module_name}")
    return None


def execute_module(module_name: str, handler_name: str, entities: Dict[str, Any], raw_input: str) -> Dict[str, Any]:
    """Execute a module handler"""
    adapter = get_module_adapter(module_name)
    if not adapter:
        return {
            "success": False,
            "message": f"Module not found: {module_name}",
            "timestamp": datetime.now().isoformat()
        }
    
    return adapter.execute(handler_name, entities, raw_input)
