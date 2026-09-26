"""
Phone Audio Stream Receiver
Provides an authenticated queue receiver for incoming remote PCM audio streams
(e.g., from paired mobile devices) with bounded queueing and backpressure protection.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class PhoneAudioStreamReceiver:
    """
    Receives PCM audio chunks from an authenticated paired mobile device.
    Buffers incoming PCM chunks with backpressure protection (drops frames on full queue
    to prevent event loop stalling and latency buildup).
    """

    def __init__(self, max_buffered_chunks: int = 200):
        self.max_buffered_chunks = max_buffered_chunks
        self._lock = threading.RLock()
        self._user_queues: Dict[int, asyncio.Queue] = {}
        self._is_active: Dict[int, bool] = {}

    def get_or_create_queue(self, user_id: int) -> asyncio.Queue:
        with self._lock:
            if user_id not in self._user_queues:
                self._user_queues[user_id] = asyncio.Queue(maxsize=self.max_buffered_chunks)
                self._is_active[user_id] = True
            return self._user_queues[user_id]

    def push_pcm_frame(self, user_id: int, pcm_bytes: bytes) -> bool:
        """
        Push incoming PCM audio bytes for user. Drops frame if queue is full.
        """
        if not user_id or not pcm_bytes:
            return False

        q = self.get_or_create_queue(user_id)
        try:
            q.put_nowait({
                "data": pcm_bytes,
                "mime_type": "audio/pcm",
                "sample_rate": 16000,
                "channels": 1,
            })
            return True
        except asyncio.QueueFull:
            # Backpressure guard: drop frame rather than block
            logger.debug(f"[PHONE_AUDIO] User {user_id} queue full — dropped 1 audio frame.")
            return False
        except Exception as e:
            logger.warning(f"[PHONE_AUDIO] Push error for user {user_id}: {e}")
            return False

    def close_stream(self, user_id: int) -> None:
        """Close audio stream for user."""
        with self._lock:
            self._is_active[user_id] = False
            q = self._user_queues.pop(user_id, None)
            if q:
                while not q.empty():
                    try:
                        q.get_nowait()
                    except Exception:
                        break
            logger.info(f"[PHONE_AUDIO] Closed audio stream for user {user_id}")

    def is_streaming(self, user_id: int) -> bool:
        with self._lock:
            return bool(self._is_active.get(user_id, False))


# Singleton instance
_stream_receiver = None

def get_phone_audio_receiver() -> PhoneAudioStreamReceiver:
    global _stream_receiver
    if _stream_receiver is None:
        _stream_receiver = PhoneAudioStreamReceiver()
    return _stream_receiver
