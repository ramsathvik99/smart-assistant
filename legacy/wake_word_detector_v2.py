#!/usr/bin/env python3
"""
Official OpenWakeWord-based wake word detector
Replaces the broken custom ONNX model
Uses pre-trained TFLite models that actually work
"""

import numpy as np
import logging
import time

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """
    Official OpenWakeWord detector using TFLite models
    Uses pre-trained models that are verified to work
    """
    
    def __init__(self):
        """Initialize with official OpenWakeWord TFLite models"""
        try:
            from openwakeword.model import Model
            
            logger.info(f"Loading official OpenWakeWord TFLite models...")
            
            # Use pre-trained TFLite models - these are well-tested
            # Using "alexa" and "hey_jarvis" for dual detection
            self.model = Model(
                wakeword_models=["alexa", "hey_jarvis"],
                inference_framework="tflite"
            )
            
            logger.info(f"✓ OpenWakeWord initialized with TFLite models")
            for model_name in self.model.models.keys():
                logger.info(f"  - {model_name}")
            
            # Parameters
            self.sample_rate = 16000
            
            # Detection sensitivity
            self.consecutive_threshold = 0.5   # OpenWakeWord's default
            self.consecutive_frame_count = 2   # Require 2 consecutive frames
            self.consecutive_frames_detected = 0
            
            # Cooldown
            self.last_detection_time = 0.0
            self.detection_cooldown = 3.0
            
            # Smoothing
            self.ema_confidence = 0.0
            self.ema_alpha = 0.3
            
        except ImportError as e:
            logger.error(f"OpenWakeWord not available: {e}")
            raise RuntimeError(f"OpenWakeWord required: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize OpenWakeWord: {e}")
            raise RuntimeError(f"OpenWakeWord init failed: {e}")
    
    def process_frame(self, audio_chunk: np.ndarray) -> float:
        """
        Process audio chunk for wake word detection
        
        Args:
            audio_chunk: Audio samples (int16 or float32)
            
        Returns:
            float: Confidence (0-1) or 0 if no detection
        """
        # Ensure float format
        if audio_chunk.dtype == np.int16:
            audio = audio_chunk.astype(np.float32) / 32768.0
        else:
            audio = audio_chunk.astype(np.float32)
        
        # Check cooldown
        current_time = time.time()
        if current_time - self.last_detection_time < self.detection_cooldown:
            self.consecutive_frames_detected = 0
            return 0.0
        
        # Get prediction from OpenWakeWord
        try:
            prediction = self.model.predict(audio)
            
            # Max confidence across all models
            max_confidence = max(prediction.values()) if prediction else 0.0
            
            # Apply EMA smoothing
            self.ema_confidence = (self.ema_alpha * max_confidence + 
                                  (1 - self.ema_alpha) * self.ema_confidence)
            smoothed = max(0.0, min(1.0, self.ema_confidence))
            
            # Consecutive frame check
            if smoothed >= self.consecutive_threshold:
                self.consecutive_frames_detected += 1
            else:
                self.consecutive_frames_detected = 0
            
            # Return confidence only on valid multi-frame detection
            if self.consecutive_frames_detected >= self.consecutive_frame_count:
                self.last_detection_time = current_time
                self.consecutive_frames_detected = 0
                return smoothed
            
            return 0.0
            
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return 0.0
    
    def predict(self, audio: np.ndarray) -> dict:
        """Compatibility method - returns dict with confidence"""
        confidence = self.process_frame(audio)
        return {"wake_word": confidence, "is_valid": confidence > 0.0}
