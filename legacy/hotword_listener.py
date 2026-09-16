# hotword_listener.py
import os
import sys
import time
import traceback
import threading
from collections import deque
from typing import Dict

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except Exception:
    PYAUTOGUI_AVAILABLE = False

# Import thread-safe wake state manager
try:
    from extensions.system.wake_state_manager import (
        get_wake_state_manager, is_wake_mode, is_command_mode,
        enter_command_mode, return_to_wake_mode as state_return_to_wake_mode
    )
    WAKE_STATE_MANAGER = get_wake_state_manager()
except ImportError as e:
    print(f"[HOTWORD] WARNING: Wake state manager not available: {e}")
    WAKE_STATE_MANAGER = None

# Import shutdown manager
try:
    from extensions.system.shutdown_manager import shutdown_manager
except ImportError:
    shutdown_manager = None
    print("[WARNING] Shutdown manager not available")

# Define log function early so it can be used throughout the module
def log(*args, **kwargs):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[HOTWORD {ts}]", *args, **kwargs)

# ============================================================================
# CONFIGURABLE WAKE THRESHOLD
# ============================================================================
def get_wake_threshold():
    """Get wake threshold from config with fallback to default"""
    try:
        from instance.config import settings
        # Use high threshold to prevent false positives
        threshold = settings.get("HOTWORD_WAKE_THRESHOLD", 0.65)
        if isinstance(threshold, str):
            threshold = float(threshold)
        return max(0.5, min(0.95, threshold))  # Clamp to high range [0.5-0.95]
    except Exception:
        return 0.65  # High threshold default

def set_wake_threshold(threshold):
    """Set wake threshold in config"""
    try:
        from instance.config import settings
        threshold = max(0.1, min(0.9, float(threshold)))
        settings["HOTWORD_WAKE_THRESHOLD"] = threshold
        log(f"[CONFIG] Wake threshold updated to {threshold:.2f}")
        return True
    except Exception as e:
        log(f"[CONFIG ERROR] Failed to set threshold: {e}")
        return False

# Global state for hotword service
_hotword_service_state = {
    'initialized': False,
    'enabled': False,
    'porcupine_instance': None,
    'recorder_instance': None,
    'status': 'disabled',
    'is_running': False,
    'audio_buffer': None,
    'latest_confidence': 0.0,
    'microphone_device': None,
    'current_threshold': get_wake_threshold(),
    'model_name': 'openwakeword',
    'wake_loop_active': False
}

def return_to_wake_mode():
    """Return to WAKE mode using thread-safe state manager"""
    try:
        # Use thread-safe state manager
        if WAKE_STATE_MANAGER:
            result = state_return_to_wake_mode()
            if result:
                log("[WAKE] Transitioned to WAKE_MODE via state manager")
        
        # Reset legacy config flag
        try:
            from instance.config import settings as _cfg
            _cfg["HOTWORD_PAUSED"] = False
        except Exception as e:
            log(f"[WAKE ERROR] Failed to reset HOTWORD_PAUSED in config: {e}")
        
        # CRITICAL: Release the detector's wake lock to allow resume
        try:
            global owwModel
            if owwModel and hasattr(owwModel, 'release_wake_lock'):
                owwModel.release_wake_lock()
                log("[WAKE] Detector wake lock released")
        except Exception as e:
            log(f"[WAKE WARNING] Failed to release detector wake lock: {e}")
        
        log("[WAKE] Returned to WAKE_MODE")
        
    except Exception as e:
        log(f"[WAKE ERROR] Failed to return to wake mode: {e}")


mode = "wake"   # DEPRECATED - use WakeStateManager instead
WAKE_LOCK = False
AMBIENT_BASELINE = 0.0  # For adaptive threshold calibration

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
    SOUNDDEVICE_AVAILABLE = False
except ImportError:
    PYAUDIO_AVAILABLE = False
    try:
        import sounddevice as sd
        SOUNDDEVICE_AVAILABLE = True
        print("[INFO] Using sounddevice as alternative to pyaudio")
    except ImportError:
        SOUNDDEVICE_AVAILABLE = False
        print("[WARNING] Neither pyaudio nor sounddevice available - audio features disabled")

import numpy as np

try:
    from legacy.wake_word_detector import ONNXWakeWordDetector as WakeWordDetector
    CUSTOM_DETECTOR_AVAILABLE = True
except ImportError:
    CUSTOM_DETECTOR_AVAILABLE = False
    WakeWordDetector = None

last_trigger_time = 0

# Import resource helper for EXE compatibility
from pathlib import Path

def _get_resource_path(relative_path):
    """Get resource path with fallback"""
    try:
        from core.resource_helper import resource_path
        return resource_path(relative_path)
    except ImportError as e:
        log(f"Resource helper import failed: {e}")
        # Fallback to basic path resolution
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), relative_path)

# Use absolute path from project root (go up two levels from legacy/hotword_listener.py)
BASE_DIR = Path(__file__).resolve().parent.parent
WAKE_WORDS_DIR = BASE_DIR / "legacy" / "wake_words"

def force_model_reload():
    """Force reload of ONNX model to ensure new model is used"""
    try:
        import openwakeword
        import gc
        
        # Clear model cache
        if hasattr(openwakeword, 'model') and hasattr(openwakeword.model, '_models'):
            openwakeword.model._models.clear()
            log("[MODEL] Cleared openwakeword model cache")
        
        # Force garbage collection
        gc.collect()
        
        # Clear any other potential caches
        if hasattr(openwakeword, '_model_cache'):
            openwakeword._model_cache.clear()
            log("[MODEL] Cleared openwakeword global cache")
            
        return True
    except Exception as e:
        log(f"[MODEL ERROR] Failed to clear model cache: {e}")
        return False





def handle_command(buffered_audio, wake_time, detection_count):
    """
    Handle command immediately after wake detection.
    STATE MACHINE: WAKE DETECTED → ACKNOWLEDGE → LISTEN → PROCESS → RETURN TO WAKE
    
    Timeout: If no speech detected within 8 seconds, say "I didn't catch that"
    and automatically return to wake mode.
    
    Thread-safe: Uses WakeStateManager for state transitions.
    """
    # Use thread-safe state manager to enter COMMAND_MODE
    if WAKE_STATE_MANAGER:
        if not enter_command_mode():
            log("[WAKE] ERROR: Failed to enter COMMAND_MODE or already in it")
            return
    else:
        # Fallback to legacy mode setting
        global mode
        mode = "command"
    
    log("[WAKE] Command Mode Active")
    
    try:
        # Pulse floating bubble
        try:
            import legacy.tts as tts
            if hasattr(tts, "floating_ref") and getattr(tts, "floating_ref") is not None:
                if hasattr(tts.floating_ref.start_anim, "emit"):
                    tts.floating_ref.start_anim.emit()
                else:
                    tts.floating_ref.start_anim()
        except Exception as e:
            log(f"UI pulse failed: {e}")
        
        # Start listening immediately with 8-second phrase limit and 5-second wait
        user_text = listen_once(buffered_audio)
        
        # Stop pulse
        try:
            if hasattr(tts, "floating_ref") and getattr(tts, "floating_ref") is not None:
                if hasattr(tts.floating_ref.stop_anim, "emit"):
                    tts.floating_ref.stop_anim.emit()
                else:
                    tts.floating_ref.stop_anim()
        except Exception as e:
            log(f"UI stop pulse failed: {e}")
            
        # If no text captured, return to wake mode (timeout already spoke "I didn't catch that" via coordinator)
        if not user_text:
            return_to_wake_mode()
            return
        
        # Process command if detected
        try:
            import legacy.assistant as assistant
            assistant.process_input(user_text)
        except Exception as e:
            log(f"[CRITICAL ERROR] Command processing failed: {e}")
            
        return_to_wake_mode()
        
    except Exception as e:
        log(f"Command handling error: {e}")
        return_to_wake_mode()

def listen_once(buffered_audio=None):
    """Start listening immediately after wake word — delegates to sst.listen().
    
    Uses configured timeouts:
      timeout=5         → wait up to 5s for speech to start
      phrase_time_limit=8 → capture up to 8s of speech after detection
    
    If no speech detected within these windows, sst.listen() will:
      1. Speak "I didn't catch that"
      2. Return empty string
    
    Returns: Recognized speech as string, or empty string on timeout/failure.
    """
    try:
        # Import here to avoid execution at import time
        from legacy.sst import listen
        log("[LISTEN] Starting speech recognition...")
        
        # Delegate to sst.listen() which has:
        # - 5 second wait for speech to start (timeout=5)
        # - 8 second max phrase capture (phrase_time_limit=8)
        # - Automatic "I didn't catch that" on timeout
        text = listen()
        if text is None:
            return ""
        return text
    except Exception as e:
        log(f"[LISTEN ERROR] listen_once failed: {e}")
        traceback.print_exc()
        return ""

def safe_listen_with_buffer(buffer_frames):
    """Safe speech-to-text with pre-buffer and error handling.
    
    Delegates to sst.listen() which uses configured timeouts:
      timeout=5         → wait up to 5s for speech to start
      phrase_time_limit=8 → capture up to 8s of speech
    
    buffer_frames is accepted for API compatibility but recognition
    settings are managed centrally in sst.py.
    """
    try:
        from legacy.sst import listen
        log("[LISTEN] Starting speech recognition (safe mode)...")
        
        # Delegate fully to sst.listen() — settings managed centrally in sst.py
        text = listen()
        if text is None:
            return ""
        return text
    except Exception as e:
        log("[LISTEN ERROR] listen() raised:", e)
        traceback.print_exc()
        return ""
        return ""

def safe_listen():
    """Safe speech-to-text with error handling"""
    try:
        # Import here to avoid execution at import time
        from legacy.sst import listen
        log("Listening (safe_listen) ...")
        text = listen()
        if text is None:
            return ""
        return text
    except Exception as e:
        log("listen() raised:", e)
        traceback.print_exc()
        return ""

def duck_volume():
    """Duck system volume during speech"""
    try:
        # Import here to avoid execution at import time
        from instance.config import settings as CONFIG
        if not CONFIG.get("ENABLE_DUCKING", False):
            return
        
        intensity = CONFIG.get("DUCKING_INTENSITY", 5)
        log(f"Ducking volume (intensity: {intensity})")
        
        for _ in range(intensity):
            pyautogui.press('volumedown')
            time.sleep(0.01)
    except Exception as e:
        log(f"Volume ducking failed: {e}")

def unduck_volume():
    """Restore system volume after speech"""
    try:
        # Import here to avoid execution at import time
        from instance.config import settings as CONFIG
        if not CONFIG.get("ENABLE_DUCKING", False):
            return
        
        intensity = CONFIG.get("DUCKING_INTENSITY", 5)
        log(f"Restoring volume (intensity: {intensity})")
        
        for _ in range(intensity):
            pyautogui.press('volumeup')
            time.sleep(0.01)
    except Exception as e:
        log(f"Volume restoration failed: {e}")



def validate_hotword_system():
    """Validate hotword system - required by orchestrator"""
    return True

def validate_hotword_prerequisites():
    """Validate all prerequisites for hotword system"""
    global _hotword_service_state
    
    log("[INFO] Running hotword system validation...")
    
    if not WAKE_WORDS_DIR.exists():
        log(f"[ERROR] Wake words directory missing: {WAKE_WORDS_DIR}")
        _hotword_service_state['status'] = 'model_missing'
        return False, f"Directory not found at {WAKE_WORDS_DIR}"
        
    onnx_files = list(WAKE_WORDS_DIR.glob("*.onnx"))
    if not onnx_files:
        log(f"[ERROR] No ONNX models found in: {WAKE_WORDS_DIR}")
        _hotword_service_state['status'] = 'model_missing'
        return False, f"No .onnx models found in {WAKE_WORDS_DIR}"
        
    if not CUSTOM_DETECTOR_AVAILABLE:
        log("[ERROR] Custom ONNX detector not available")
        _hotword_service_state['status'] = 'library_missing'
        return False, "Custom detector not available."
        
    log("[OK] All prerequisites validated")
    return True, "All checks passed"

def start_hotword_service():
    """Initialize and start hotword service safely"""
    global _hotword_service_state
    
    if _hotword_service_state.get('is_running', False):
        return True
        
    log("[START] Starting hotword service (Custom ONNX detector mode)...")
    
    can_start, message = validate_hotword_prerequisites()
    if not can_start:
        log(f"[ERROR] Hotword service disabled: {message}")
        _hotword_service_state.update({
            'status': 'disabled',
            'initialized': True,
            'enabled': False
        })
        return False
        
    _hotword_service_state.update({
        'initialized': True,
        'enabled': True,
        'is_running': True,
        'status': 'enabled'
    })
    
    log("[READY] Hotword service ready and enabled")
    return True

def stop_hotword_service():
    """Stop hotword service cleanly"""
    global _hotword_service_state
    _hotword_service_state['initialized'] = False
    _hotword_service_state['enabled'] = False
    _hotword_service_state['is_running'] = False
    _hotword_service_state['status'] = 'stopped'
    log("[OK] Hotword service stopped cleanly")

def get_hotword_status():
    """Get current hotword service status - comprehensive diagnostic"""
    return {
        'initialized': _hotword_service_state.get('initialized', False),
        'enabled': _hotword_service_state.get('enabled', False),
        'is_running': _hotword_service_state.get('is_running', False),
        'status': _hotword_service_state.get('status', 'stopped'),
        'porcupine_available': False,
        'microphone_device': _hotword_service_state.get('microphone_device', 'Not set'),
        'current_threshold': _hotword_service_state.get('current_threshold', get_wake_threshold()),
        'latest_confidence': round(_hotword_service_state.get('latest_confidence', 0.0), 3),
        'model_name': _hotword_service_state.get('model_name', 'unknown'),
        'hotword_paused': False,  # Would need to read from config
        'wake_loop_active': _hotword_service_state.get('wake_loop_active', False)
    }



def run_hotword_loop():
    """Main hotword listening loop - using openwakeword"""
    global _hotword_service_state, last_trigger_time, WAKE_LOCK

    if not _hotword_service_state['enabled']:
        log("Hotword service not enabled - cannot start loop")
        return False

    if not PYAUDIO_AVAILABLE and not SOUNDDEVICE_AVAILABLE:
        log("[ERROR] No audio library available - hotword detection disabled")
        return False

    try:
        log(f"[WAKE] Initializing wake word detector")
        
        # Initialize detector - will auto-scan and load the new ONNX model
        if CUSTOM_DETECTOR_AVAILABLE:
            try:
                owwModel = WakeWordDetector()  # Auto-scans wake_words/ folder
                log(f"[WAKE] ONNX detector initialized")
                log(f"[WAKE] Model: {owwModel.model_path.name}")
                log(f"[WAKE] Settings: threshold={owwModel.confidence_threshold}, "
                    f"consecutive_frames={owwModel.consecutive_threshold}, "
                    f"cooldown={owwModel.detection_cooldown}s")
                _hotword_service_state['status'] = 'ready'
            except Exception as model_load_error:
                log(f"[ERROR] Detector initialization failed: {model_load_error}")
                log("[INFO] Falling back to keyboard mode")
                # Fallback to keyboard mode for testing
                keyboard_fallback()
                return False
        else:
            log(f"[ERROR] Detector not available")
            raise ImportError("WakeWordDetector not available")
        
        audio = None
        mic_stream = None
        CHUNK = 1536  # 96ms at 16kHz (matching model's 96 frames requirement)

        def test_device_capture(p, device_idx):
            test_stream = None
            try:
                test_stream = p.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=16000,
                    input=True,
                    input_device_index=device_idx,
                    frames_per_buffer=CHUNK
                )
                data = test_stream.read(CHUNK, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)
                rms = np.sqrt(np.mean(audio_data.astype(np.float32)**2))
                unique_len = len(np.unique(audio_data))
                
                # Active/Working mics have dynamic signals with varied sample values and non-zero RMS
                if unique_len > 5 and rms > 1.0:
                    return True
                else:
                    return False
            except Exception as e:
                return False
            finally:
                if test_stream:
                    try:
                        test_stream.stop_stream()
                        test_stream.close()
                    except Exception:
                        pass

        def find_best_input_device(p):
            device_count = p.get_device_count()
            
            # 1. Search for 'Primary Sound Capture Driver' on Windows DirectSound API
            for i in range(device_count):
                try:
                    info = p.get_device_info_by_index(i)
                    max_inputs = info.get('maxInputChannels', 0)
                    if max_inputs > 0:
                        name = info.get('name', '')
                        api_idx = info.get('hostApi', -1)
                        api_name = p.get_host_api_info_by_index(api_idx).get('name', '') if api_idx >= 0 else ''
                        
                        if "DirectSound" in api_name and "Primary Sound Capture Driver" in name:
                            if test_device_capture(p, i):
                                return i
                except Exception:
                    pass

            # 2. Search for any DirectSound device that receives audio
            for i in range(device_count):
                try:
                    info = p.get_device_info_by_index(i)
                    max_inputs = info.get('maxInputChannels', 0)
                    if max_inputs > 0:
                        name = info.get('name', '')
                        api_idx = info.get('hostApi', -1)
                        api_name = p.get_host_api_info_by_index(api_idx).get('name', '') if api_idx >= 0 else ''
                        
                        if "DirectSound" in api_name:
                            if test_device_capture(p, i):
                                return i
                except Exception:
                    pass

            # 3. Fallback: Scan all input devices and pick the first one that receives actual audio
            for i in range(device_count):
                try:
                    info = p.get_device_info_by_index(i)
                    max_inputs = info.get('maxInputChannels', 0)
                    if max_inputs > 0:
                        if test_device_capture(p, i):
                            return i
                except Exception:
                    pass

            # 4. Ultimate fallback: default input device
            try:
                default_idx = p.get_default_input_device_info().get('index')
                return default_idx
            except Exception as e:
                return None

        def init_mic():
            nonlocal audio, mic_stream
            if PYAUDIO_AVAILABLE:
                try:
                    if audio is None:
                        log("[MIC] Initializing PyAudio client...")
                        audio = pyaudio.PyAudio()
                    if mic_stream is None:
                        best_idx = find_best_input_device(audio)
                        log(f"[MIC] Opening PyAudio mic stream on device index {best_idx} (rate=16000, channels=1, chunk=1280)...")
                        mic_stream = audio.open(
                            format=pyaudio.paInt16,
                            channels=1,
                            rate=16000,
                            input=True,
                            input_device_index=best_idx,
                            frames_per_buffer=CHUNK
                        )
                        log("[MIC] PyAudio stream opened successfully.")
                    return True
                except Exception as e:
                    log(f"[MIC ERROR] Exception in init_mic: {e}")
                    cleanup_mic()
                    return False
            elif SOUNDDEVICE_AVAILABLE:
                sd.default.samplerate = 16000
                sd.default.channels = 1
                log("[MIC] Sounddevice configuration applied.")
                return True
            return False


        def cleanup_mic():
            nonlocal audio, mic_stream
            log("[MIC] Cleaning up and releasing microphone resources...")
            if mic_stream is not None:
                try:
                    mic_stream.stop_stream()
                except Exception as e:
                    log(f"[MIC] Exception while stopping stream: {e}")
                try:
                    mic_stream.close()
                except Exception as e:
                    log(f"[MIC] Exception while closing stream: {e}")
                mic_stream = None
            if audio is not None:
                try:
                    audio.terminate()
                except Exception as e:
                    log(f"[MIC] Exception while terminating PyAudio: {e}")
                audio = None
            log("[MIC] Microphone resources fully released.")

        log("[WAKE] Wake Mode Active")
        log("[WAKE] Listening for wake word...")
        
        # 6. ADAPTIVE THRESHOLD CALIBRATION (first 3 seconds)
        log("[CALIBRATION] Starting ambient noise calibration (3 seconds)...")
        calibration_scores = []
        calibration_start = time.time()
        ambient_baseline = 0.0
        
    except Exception as e:
        log(f"Error starting hotword loop: {e}")
        return False

    try:
        from legacy.tts import speak, wait_until_spoken
        import legacy.assistant as assistant
        from instance.config import settings as CONFIG
        
        last_thread_alive_log = 0
        while True:
            # Periodically log thread alive (every 60 seconds)
            current_time = time.time()
            if current_time - last_thread_alive_log > 60:
                log("[WAKE] Listening for wake word")
                last_thread_alive_log = current_time
                
            shutdown_check = False
            if shutdown_manager:
                shutdown_check = shutdown_manager.should_shutdown()
                
            if CONFIG.get("HOTWORD_PAUSED") or shutdown_check:
                time.sleep(0.5)
                continue
                
            try:
                # Ensure microphone is initialized
                if PYAUDIO_AVAILABLE and mic_stream is None:
                    if not init_mic():
                        log("[WAKE] Mic initialization failed. Retrying in 2 seconds...")
                        time.sleep(2)
                        continue
                elif SOUNDDEVICE_AVAILABLE:
                    init_mic()
                
                if PYAUDIO_AVAILABLE:
                    audio_data = np.frombuffer(mic_stream.read(CHUNK, exception_on_overflow=False), dtype=np.int16)
                elif SOUNDDEVICE_AVAILABLE:
                    audio_data = sd.rec(CHUNK, samplerate=16000, channels=1, dtype='int16')
                    sd.wait()
                    audio_data = audio_data.flatten()
                else:
                    time.sleep(0.1)
                    continue
                
                # Get prediction from custom detector
                # Returns 0.0 if below threshold or in cooldown
                # Returns confidence if valid multi-frame detection
                confidence = owwModel.process_frame(audio_data)
                
                # Store latest confidence for diagnostic access only (no logging)
                _hotword_service_state['latest_confidence'] = confidence
                
                # Check if this is a valid wake detection
                # (detector already applies threshold and consecutive frame requirement)
                if confidence > 0.0:
                    if WAKE_LOCK:
                        continue
                        
                    WAKE_LOCK = True
                    last_trigger_time = time.time()
                    
                    try:
                        from modules.translation.controller import MODE, controller
                        if MODE == "translation":
                            controller.exit_translation_mode()
                            WAKE_LOCK = False
                            continue
                    except Exception:
                        pass

                    log("[WAKE] Wake word detected")
                    wake_time = time.time()
                    
                    # CRITICAL FIX: Pause hotword detection so mic resource is not contested
                    # by both the hotword loop and the STT listen() call simultaneously.
                    from instance.config import settings as _cfg
                    _cfg["HOTWORD_PAUSED"] = True
                    log("[WAKE] HOTWORD_PAUSED=True — releasing mic before TTS/STT")
                    
                    # Release microphone resources before speaking acknowledgment and handing off
                    cleanup_mic()
                    
                    # Small delay so OS audio subsystem fully releases the device
                    time.sleep(0.3)
                    
                    try:
                        try:
                            from legacy.tts import speak
                            log("[WAKE] Acknowledging wake word")
                            speak("Yes?", block=False)
                            time.sleep(0.2)
                        except Exception as e:
                            log(f"[WAKE ERROR] Failed to speak acknowledgment: {e}")
                            
                        log("[WAKE] Starting command recognition")
                        handle_command([], wake_time, 1)
                        
                    finally:
                        # CRITICAL FIX: Resume hotword detection and reinitialize mic
                        return_to_wake_mode()
                        last_trigger_time = time.time()
                        
                        # Give OS audio device time to be released by STT before we re-open it
                        time.sleep(0.5)
                        
                        # Force mic re-init so next detection cycle starts fresh
                        cleanup_mic()
                        if not init_mic():
                            log("[WAKE] Microphone reinitialization will retry next cycle")
                    continue

            except Exception as audio_error:
                log(f"[WAKE ERROR] Audio stream error: {audio_error}")
                cleanup_mic()
                return_to_wake_mode()
                time.sleep(2)

    except Exception as e:
        log(f"Hotword loop error: {e}")
        return False
        
    return True

# Fallback keyboard mode
def keyboard_fallback():
    """Fallback keyboard-based wake word simulation"""
    log("Falling back to keyboard-simulated wake-word mode. Type 'wake' to simulate wake detection.")
    
    try:
        # Import here to avoid execution at import time
        from legacy.tts import speak
        import legacy.assistant as assistant
        
        while True:
            cmd = input("type (or press Enter to wait): ").strip().lower()
            
            if cmd in ("wake", "hey", "listen"):
                # 🔴 PRIORITY INTERRUPT FOR TRANSLATION MODE (FALLBACK)
                try:
                    from modules.translation.controller import MODE, controller
                    if MODE == "translation":
                        print("[WAKE] Global Interrupt: Stopping Translation Mode (Keyboard)")
                        controller.exit_translation_mode()
                        continue 
                except Exception as e:
                    print(f"[WAKE] Interrupt check failed (Fallback): {e}")

                log("Simulated wake word detected.")
                
                # STEP 2: Insert Immediate Acknowledgment
                try:
                    from legacy.tts import speak
                    speak("Yes Boss.")
                    log("[WAKE] Acknowledgment spoken")
                except Exception as e:
                    print(f"[WAKE ERROR] Failed to speak acknowledgment: {e}")
                    log(f"[WAKE ERROR] Failed to speak acknowledgment: {e}")
                
                # STEP 3: Prevent Audio Conflict
                time.sleep(0.1)
                
                try:
                    import legacy.tts as tts
                    if hasattr(tts, "floating_ref") and getattr(tts, "floating_ref") is not None:
                        try:
                            if hasattr(tts.floating_ref.start_anim, "emit"):
                                tts.floating_ref.start_anim.emit()
                            else:
                                tts.floating_ref.start_anim()
                        except Exception as anim_e:
                            log(f"Fallback anim start failed: {anim_e}")
                except Exception as e:
                    log(f"Fallback bubble check failed: {e}")

                global mode
                mode = "command"
                user_text = listen_once()
                
                try:
                    if hasattr(tts, "floating_ref") and getattr(tts, "floating_ref") is not None:
                        try:
                            if hasattr(tts.floating_ref.stop_anim, "emit"):
                                tts.floating_ref.stop_anim.emit()
                            else:
                                tts.floating_ref.stop_anim()
                        except Exception as anim_e:
                            log(f"Fallback anim stop failed: {anim_e}")
                except Exception as e:
                    log(f"Fallback bubble stop check failed: {e}")

                if not user_text:
                    return_to_wake_mode()
                    continue
                    
                try:
                    assistant.process_input(user_text)
                except Exception as e:
                    log(f"[CRITICAL ERROR] {e}")
                    traceback.print_exc()
                    
                return_to_wake_mode()

    except KeyboardInterrupt:
        pass
    except Exception as e:
        log("Wake-word listener crashed:", e)
        traceback.print_exc()

def run_conversation_loop():
    """Main conversation loop entry point for orchestrator compatibility"""
    try:
        # Try hotword service first, fallback to keyboard
        if start_hotword_service():
            run_hotword_loop()
        else:
            keyboard_fallback()
    except KeyboardInterrupt:
        log("Conversation loop interrupted by user")
    except Exception as e:
        log(f"Conversation loop error: {e}")
        traceback.print_exc()
    finally:
        stop_hotword_service()
        # Final exit after cleanup
        try:
            from extensions.system.shutdown_manager import shutdown_manager
            shutdown_manager.force_exit()
        except ImportError:
            import sys
            sys.exit(0)

            sys.exit(0)

