#!/usr/bin/env python3
"""
Music Engine - Local music playback system
"""
import os
import logging
import time
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

class MusicEngine:
    """Local music playback engine using VLC"""
    
    def __init__(self):
        self.vlc_instance = None
        self.player = None
        self.current_track = None
        self.playlist = []
        self.current_index = 0
        self.volume = 70
        self.is_playing = False
        self.is_paused = False
        
        # VLC initialization disabled per user request
        # try:
        #     self._initialize_vlc()
        # except Exception as e:
        #     logger.error(f"Failed to initialize VLC: {e}")
        #     self.vlc_instance = None
        self.vlc_instance = None
        logger.info("VLC initialization manually disabled")
    
    def _initialize_vlc(self):
        """Initialize VLC instance"""
        try:
            import vlc
            self.vlc_instance = vlc.Instance()
            self.player = self.vlc_instance.media_player_new()
            logger.info("VLC initialized successfully")
        except ImportError:
            logger.error("VLC Python bindings not available")
            raise
        except Exception as e:
            logger.error(f"VLC initialization failed: {e}")
            raise
    
    def play_file(self, file_path: str) -> bool:
        """Play a single music file"""
        if not self.vlc_instance:
            logger.error("VLC not initialized")
            return False
        
        try:
            if not os.path.exists(file_path):
                logger.error(f"File not found: {file_path}")
                return False
            
            media = self.vlc_instance.media_new(file_path)
            self.player.set_media(media)
            self.player.play()
            self.current_track = file_path
            self.is_playing = True
            self.is_paused = False
            
            # Set volume
            self.player.audio_set_volume(self.volume)
            
            logger.info(f"Playing: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error playing file: {e}")
            return False
    
    def play_playlist(self, playlist: List[str]) -> bool:
        """Play a playlist of music files"""
        if not playlist:
            logger.error("Empty playlist")
            return False
        
        self.playlist = playlist
        self.current_index = 0
        
        return self.play_file(playlist[0])
    
    def pause(self) -> bool:
        """Pause playback"""
        if not self.player:
            return False
        
        try:
            if self.is_playing and not self.is_paused:
                self.player.pause()
                self.is_paused = True
                logger.info("Playback paused")
                return True
            return False
        except Exception as e:
            logger.error(f"Error pausing: {e}")
            return False
    
    def resume(self) -> bool:
        """Resume playback"""
        if not self.player:
            return False
        
        try:
            if self.is_paused:
                self.player.pause()  # VLC uses pause() as toggle
                self.is_paused = False
                logger.info("Playback resumed")
                return True
            return False
        except Exception as e:
            logger.error(f"Error resuming: {e}")
            return False
    
    def stop(self) -> bool:
        """Stop playback"""
        if not self.player:
            return False
        
        try:
            self.player.stop()
            self.is_playing = False
            self.is_paused = False
            logger.info("Playback stopped")
            return True
        except Exception as e:
            logger.error(f"Error stopping: {e}")
            return False
    
    def next_track(self) -> bool:
        """Play next track in playlist"""
        if not self.playlist:
            return False
        
        try:
            self.current_index = (self.current_index + 1) % len(self.playlist)
            return self.play_file(self.playlist[self.current_index])
        except Exception as e:
            logger.error(f"Error playing next track: {e}")
            return False
    
    def previous_track(self) -> bool:
        """Play previous track in playlist"""
        if not self.playlist:
            return False
        
        try:
            self.current_index = (self.current_index - 1) % len(self.playlist)
            return self.play_file(self.playlist[self.current_index])
        except Exception as e:
            logger.error(f"Error playing previous track: {e}")
            return False
    
    def set_volume(self, volume: int) -> bool:
        """Set volume (0-100)"""
        if not self.player:
            return False
        
        try:
            volume = max(0, min(100, volume))
            self.player.audio_set_volume(volume)
            self.volume = volume
            logger.info(f"Volume set to {volume}")
            return True
        except Exception as e:
            logger.error(f"Error setting volume: {e}")
            return False
    
    def increase_volume(self, increment: int = 10) -> bool:
        """Increase volume"""
        return self.set_volume(self.volume + increment)
    
    def decrease_volume(self, decrement: int = 10) -> bool:
        """Decrease volume"""
        return self.set_volume(self.volume - decrement)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current playback status"""
        return {
            'is_playing': self.is_playing,
            'is_paused': self.is_paused,
            'current_track': self.current_track,
            'current_index': self.current_index,
            'playlist_length': len(self.playlist),
            'volume': self.volume,
            'vlc_available': self.vlc_instance is not None
        }
    
    def is_available(self) -> bool:
        """Check if music engine is available"""
        return self.vlc_instance is not None

# Global music engine instance
_music_engine = None

def get_music_engine() -> MusicEngine:
    """Get global music engine instance"""
    global _music_engine
    if _music_engine is None:
        _music_engine = MusicEngine()
    return _music_engine

def is_music_available() -> bool:
    """Check if music engine is available"""
    try:
        engine = get_music_engine()
        return engine.is_available()
    except Exception as e:
        logger.error(f"[MusicEngine] Availability check failed: {e}")
        return False
