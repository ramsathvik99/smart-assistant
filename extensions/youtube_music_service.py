# youtube_music_service.py
import requests
import webbrowser
import logging
from typing import List, Dict, Optional
import re

logger = logging.getLogger(__name__)

class YouTubeMusicService:
    """YouTube-native music service using YouTube Data API"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://www.googleapis.com/youtube/v3"
        self.current_playlist = []
        self.current_index = 0
        self.browser = None
        
    def search_and_play_playlist(self, query: str, max_results: int = 10) -> bool:
        """Search YouTube and open as playlist"""
        try:
            video_ids = self._search_videos(query, max_results)
            if not video_ids:
                logger.error(f"No videos found for: {query}")
                return False
            
            # Create playlist URL
            playlist_url = f"https://www.youtube.com/watch_videos?video_ids={','.join(video_ids)}"
            
            # Open in browser
            self._open_in_browser(playlist_url)
            
            # Store for navigation
            self.current_playlist = video_ids
            self.current_index = 0
            
            logger.info(f"Opened playlist for: {query} ({len(video_ids)} videos)")
            return True
            
        except Exception as e:
            logger.error(f"Error playing playlist: {e}")
            return False
    
    def play_next(self) -> bool:
        """Play next video in current playlist"""
        try:
            if not self.current_playlist:
                logger.warning("No current playlist")
                return False
            
            self.current_index = (self.current_index + 1) % len(self.current_playlist)
            video_id = self.current_playlist[self.current_index]
            
            # Open next video in same tab
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            self._open_in_browser(video_url, new_tab=False)
            
            logger.info(f"Playing next video: {video_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error playing next: {e}")
            return False
    
    def play_previous(self) -> bool:
        """Play previous video in current playlist"""
        try:
            if not self.current_playlist:
                logger.warning("No current playlist")
                return False
            
            self.current_index = (self.current_index - 1) % len(self.current_playlist)
            video_id = self.current_playlist[self.current_index]
            
            # Open previous video in same tab
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            self._open_in_browser(video_url, new_tab=False)
            
            logger.info(f"Playing previous video: {video_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error playing previous: {e}")
            return False
    
    def _search_videos(self, query: str, max_results: int) -> List[str]:
        """Search YouTube and return video IDs"""
        try:
            # Search endpoint
            search_url = f"{self.base_url}/search"
            params = {
                'part': 'id,snippet',
                'q': query,
                'type': 'video',
                'maxResults': max_results,
                'key': self.api_key,
                'videoCategoryId': '10',  # Music category
                'videoDuration': 'medium',  # Medium duration (4-20 minutes)
                'order': 'relevance'
            }
            
            response = requests.get(search_url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract video IDs
            video_ids = []
            for item in data.get('items', []):
                if item['id']['kind'] == 'youtube#video':
                    video_ids.append(item['id']['videoId'])
            
            return video_ids[:max_results]
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []
    
    def _open_in_browser(self, url: str, new_tab: bool = True):
        """Open URL in browser"""
        try:
            if new_tab or self.browser is None:
                webbrowser.open(url, new=2)  # new tab
            else:
                # Reuse same browser instance
                webbrowser.open(url, new=1)  # same window
        except Exception as e:
            logger.error(f"Browser error: {e}")
    
    def get_current_status(self) -> Dict:
        """Get current playback status"""
        return {
            'has_playlist': len(self.current_playlist) > 0,
            'current_index': self.current_index,
            'total_videos': len(self.current_playlist),
            'current_video_id': self.current_playlist[self.current_index] if self.current_playlist else None
        }

# Global service instance
_youtube_service = None

def get_youtube_service() -> YouTubeMusicService:
    """Get or create YouTube service instance"""
    global _youtube_service
    if _youtube_service is None:
        # Load API key from environment
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        api_key = os.getenv('YOUTUBE_API_KEY_3') or os.getenv('YOUTUBE_API_KEY_2') or os.getenv('YOUTUBE_API_KEY_1') or os.getenv('YOUTUBE_API_KEY')
        
        if not api_key:
            logger.error("YOUTUBE_API_KEY not found in environment")
            raise ValueError("YOUTUBE_API_KEY required")
        
        _youtube_service = YouTubeMusicService(api_key)
    return _youtube_service
