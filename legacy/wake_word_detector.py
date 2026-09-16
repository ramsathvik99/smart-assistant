"""
ONNX Wake Word Detector - Production Implementation
Loads the new ONNX model and performs reliable "Hey Nova" detection
"""

import numpy as np
import onnxruntime as ort
from pathlib import Path
import logging
import time

logger = logging.getLogger(__name__)


class ONNXWakeWordDetector:
    """
    ONNX-based wake word detector using the new model
    
    Key features:
    - Auto-scans legacy/wake_words/ for ONNX model
    - Proper mel-spectrogram feature extraction
    - Consecutive frame confirmation (prevents false positives)
    - Wake lock mechanism (prevents detection loops)
    - High confidence threshold (reduces noise sensitivity)
    """
    
    def __init__(self, model_path: str = None):
        """
        Initialize ONNX detector
        
        Args:
            model_path: Optional explicit path. If None, auto-scans legacy/wake_words/
        """
        self.model_path = None
        self.session = None
        self.input_name = None
        self.output_name = None
        
        # Audio parameters (standard for speech recognition)
        self.sample_rate = 16000
        self.n_mels = 16          # Number of mel-spectrogram bins
        self.n_fft = 512          # FFT window size
        self.hop_length = 160     # 10ms hop at 16kHz
        self.n_frames = 96        # Number of frames for model input
        
        # Feature buffer - accumulate actual mel-frames over time
        self.mel_buffer = np.zeros((self.n_mels, self.n_frames), dtype=np.float32)
        self.frame_count = 0
        
        # State management
        self.wake_lock = False
        self.last_detection_time = 0.0
        self.detection_cooldown = 1.5  # Minimum 1.5s between detections
        self.confidence_threshold = 0.55  # High threshold for specificity
        
        # Multi-frame confirmation
        self.consecutive_detections = 0
        self.consecutive_threshold = 2  # Require 2 consecutive high-conf frames
        
        # Load model
        self._load_model(model_path)
    
    def _load_model(self, model_path: str = None):
        """Load ONNX model from path or auto-scan"""
        
        if model_path is None:
            # Auto-scan legacy/wake_words/ for ONNX files
            project_root = Path(__file__).resolve().parent.parent
            wake_words_dir = project_root / "legacy" / "wake_words"
            
            onnx_files = list(wake_words_dir.glob("*.onnx"))
            
            if not onnx_files:
                raise FileNotFoundError(f"No ONNX files found in {wake_words_dir}")
            
            if len(onnx_files) > 1:
                logger.warning(f"Multiple ONNX files found, using first: {onnx_files[0].name}")
            
            model_path = str(onnx_files[0].resolve())
            logger.info(f"Auto-loaded model: {onnx_files[0].name}")
        
        self.model_path = Path(model_path)
        
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")
        
        try:
            # Initialize ONNX runtime session
            self.session = ort.InferenceSession(
                str(self.model_path),
                providers=['CPUExecutionProvider']
            )
            
            # Get model I/O names and shapes
            self.input_name = self.session.get_inputs()[0].name
            self.output_name = self.session.get_outputs()[0].name
            
            input_shape = self.session.get_inputs()[0].shape
            output_shape = self.session.get_outputs()[0].shape
            
            logger.info(f"ONNX model loaded successfully: {self.model_path.name}")
            logger.info(f"  Input: {self.input_name} {input_shape}")
            logger.info(f"  Output: {self.output_name} {output_shape}")
            logger.info(f"  Detector settings: threshold={self.confidence_threshold}, "
                       f"consecutive_frames={self.consecutive_threshold}, "
                       f"cooldown={self.detection_cooldown}s")
            
        except Exception as e:
            logger.error(f"Failed to load ONNX model: {e}")
            raise
    
    def _extract_mel_spectrogram(self, audio: np.ndarray) -> np.ndarray:
        """
        Extract mel-spectrogram from audio chunk using scipy/numpy only
        
        Args:
            audio: Audio data (int16 or float32)
            
        Returns:
            Single frame of mel-spectrogram (n_mels,)
        """
        from scipy import signal
        
        # Ensure float32 in range [-1, 1]
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        else:
            audio = audio.astype(np.float32)
        
        # Ensure we have enough samples
        if len(audio) < self.hop_length:
            audio = np.pad(audio, (0, self.hop_length - len(audio)))
        
        # Take most recent hop_length samples
        audio = audio[-self.hop_length:]
        
        try:
            # Apply window function
            window = signal.hann(len(audio), sym=False)
            windowed = audio * window
            
            # Zero pad to n_fft
            padded = np.pad(windowed, (0, self.n_fft - len(windowed)))
            
            # Compute FFT
            fft = np.abs(np.fft.rfft(padded))
            
            # Create mel-scale filterbank
            freqs = np.fft.rfftfreq(self.n_fft, 1.0 / self.sample_rate)
            
            # Simple mel-scale approximation
            mel_frame = np.zeros(self.n_mels, dtype=np.float32)
            
            for m in range(self.n_mels):
                # Triangular filters
                f_center = 50 + (m / self.n_mels) * (8000 - 50)
                f_width = (8000 - 50) / self.n_mels
                
                # Lower and upper edges
                f_low = f_center - f_width / 2
                f_high = f_center + f_width / 2
                
                # Apply triangular window
                for i, freq in enumerate(freqs):
                    if f_low <= freq <= f_center:
                        weight = (freq - f_low) / (f_center - f_low + 1e-9)
                    elif f_center < freq <= f_high:
                        weight = (f_high - freq) / (f_high - f_center + 1e-9)
                    else:
                        weight = 0.0
                    
                    mel_frame[m] += fft[i] * weight
            
            # Convert to log scale
            mel_frame = np.log(mel_frame + 1e-9)
            
            # Normalize
            mel_frame = (mel_frame - np.mean(mel_frame)) / (np.std(mel_frame) + 1e-9)
            
            return mel_frame.astype(np.float32)
            
        except Exception as e:
            logger.debug(f"Mel-spectrogram extraction failed: {e}, using silence")
            return np.zeros(self.n_mels, dtype=np.float32)
    
    def process_frame(self, audio_chunk: np.ndarray) -> float:
        """
        Process audio frame and return detection confidence
        
        Args:
            audio_chunk: Audio data (typically 1600 samples at 16kHz = 100ms)
            
        Returns:
            Confidence score (0.0 = no detection, >0.0 = detected)
        """
        current_time = time.time()
        
        # Check wake lock
        if self.wake_lock:
            logger.debug("Wake lock active - detection blocked")
            return 0.0
        
        # Check cooldown
        if current_time - self.last_detection_time < self.detection_cooldown:
            logger.debug("Cooldown active")
            return 0.0
        
        if self.session is None:
            logger.warning("ONNX session not available")
            return 0.0
        
        # Extract mel-spectrogram frame
        mel_frame = self._extract_mel_spectrogram(audio_chunk)
        
        # Shift buffer and add new frame
        self.mel_buffer[:, :-1] = self.mel_buffer[:, 1:]
        self.mel_buffer[:, -1] = mel_frame
        self.frame_count += 1
        
        # Need minimum frames before inference
        if self.frame_count < self.n_frames:
            logger.debug(f"Buffering frames: {self.frame_count}/{self.n_frames}")
            return 0.0
        
        # Create model input [1, 16, 96]
        model_input = self.mel_buffer[np.newaxis, :, :].astype(np.float32)
        
        try:
            # Run inference
            output = self.session.run([self.output_name], {self.input_name: model_input})
            raw_confidence = float(output[0][0][0])
            
            logger.debug(f"Raw model output: {raw_confidence:.6f}")
            
            # Apply threshold
            if raw_confidence >= self.confidence_threshold:
                # Track consecutive high-confidence detections
                self.consecutive_detections += 1
                logger.debug(f"High confidence frame {self.consecutive_detections}/{self.consecutive_threshold}: {raw_confidence:.6f}")
                
                # Only trigger after multiple consecutive frames
                if self.consecutive_detections >= self.consecutive_threshold:
                    logger.info(f"WAKE DETECTED! Confidence: {raw_confidence:.6f} "
                               f"(confirmed by {self.consecutive_threshold} frames)")
                    
                    # Set wake lock and cooldown
                    self.wake_lock = True
                    self.last_detection_time = current_time
                    self.consecutive_detections = 0
                    self.frame_count = 0
                    
                    return raw_confidence
            else:
                # Below threshold - reset counter
                if self.consecutive_detections > 0:
                    logger.debug(f"Confidence dropped: {raw_confidence:.6f} < {self.confidence_threshold}")
                    self.consecutive_detections = 0
            
            return 0.0
            
        except Exception as e:
            logger.error(f"Inference failed: {e}")
            return 0.0
    
    def release_wake_lock(self):
        """Release wake lock after command execution"""
        self.wake_lock = False
        self.last_detection_time = time.time()
        self.consecutive_detections = 0
        self.frame_count = 0
        logger.info("Wake lock released - detector ready for next wake word")
    
    def predict(self, audio: np.ndarray) -> dict:
        """Process audio and return prediction"""
        confidence = self.process_frame(audio)
        return {
            "wake_detected": confidence,
            "is_valid_phrase": confidence > 0.0
        }
