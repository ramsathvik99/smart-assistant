"""
End-to-End Latency Instrumentation for Smart Assistant / Friday.

Measures and logs monotonic timestamps across the complete pipeline:
- utterance capture & end-of-speech detection
- speech recognition (ASR)
- intent classification and routing
- external retrieval (if needed)
- LLM time-to-first-token (TTFT) and total generation time
- TTS time-to-first-audio (TTFA) and total synthesis time
- time to first audible output
- total time until visible text answer is available
- audio playback duration
- cancellation, timeout and fallback reasons
"""

import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class RequestLatencyTracker:
    """Tracks latency for a single user turn across microphone-to-playback using monotonic timing."""

    def __init__(self, request_id: Optional[str] = None):
        self.request_id = request_id or f"turn_{int(time.monotonic() * 1000)}"
        self.timestamps: Dict[str, Optional[float]] = {
            "capture_start_timestamp": None,
            "utterance_end_timestamp": None,
            "transcription_complete_timestamp": None,
            "routing_start_timestamp": None,
            "routing_complete_timestamp": None,
            "retrieval_start_timestamp": None,
            "retrieval_complete_timestamp": None,
            "llm_start_timestamp": None,
            "llm_first_token_timestamp": None,
            "llm_complete_timestamp": None,
            "text_answer_available_timestamp": None,
            "tts_request_timestamp": None,
            "tts_first_audio_timestamp": None,
            "tts_playback_start_timestamp": None,
            "tts_playback_end_timestamp": None,
        }
        self.llm_call_count: int = 0
        self.providers_tried: list = []
        self.cancellation_reason: Optional[str] = None
        self.timeout_reason: Optional[str] = None
        self.fallback_reason: Optional[str] = None
        self._printed: bool = False

    def record(self, metric_name: str, ts: Optional[float] = None) -> None:
        """Record monotonic timestamp for a pipeline step with cross-turn sanity validation."""
        now = ts if ts is not None else time.monotonic()
        if metric_name == "tts_first_audio_timestamp":
            t_asr = self.timestamps.get("transcription_complete_timestamp")
            if t_asr is not None and now < t_asr:
                # Discard cross-turn bleed-through from a prior utterance
                return
        if metric_name == "tts_playback_end_timestamp":
            t_first = self.timestamps.get("tts_first_audio_timestamp")
            if t_first is not None and now < t_first:
                return
        self.timestamps[metric_name] = now

    def record_llm_call(self, provider: str) -> None:
        """Record that an LLM provider call was made."""
        self.llm_call_count += 1
        p = str(provider).strip().lower()
        if p and p not in self.providers_tried:
            self.providers_tried.append(p)

    def set_reason(self, cancellation: Optional[str] = None, timeout: Optional[str] = None, fallback: Optional[str] = None) -> None:
        if cancellation:
            self.cancellation_reason = cancellation
        if timeout:
            self.timeout_reason = timeout
        if fallback:
            self.fallback_reason = fallback

    def _diff_ms(self, start_key: str, end_key: str) -> Optional[float]:
        t0 = self.timestamps.get(start_key)
        t1 = self.timestamps.get(end_key)
        if t0 is not None and t1 is not None:
            return max(0.0, (t1 - t0) * 1000.0)
        return None

    def compute_metrics(self) -> Dict[str, Optional[float]]:
        """Compute latency metrics in milliseconds."""
        eos_lat = self._diff_ms("capture_start_timestamp", "utterance_end_timestamp")
        asr_lat = self._diff_ms("utterance_end_timestamp", "transcription_complete_timestamp")
        routing_lat = self._diff_ms("routing_start_timestamp", "routing_complete_timestamp")
        retrieval_lat = self._diff_ms("retrieval_start_timestamp", "retrieval_complete_timestamp")
        llm_ttft = self._diff_ms("llm_start_timestamp", "llm_first_token_timestamp")
        llm_total = self._diff_ms("llm_start_timestamp", "llm_complete_timestamp")
        
        # Text visible latency: transcription_complete or routing_start to text_answer_available
        text_ready_ref = self.timestamps.get("transcription_complete_timestamp") or self.timestamps.get("routing_start_timestamp")
        text_avail_lat = None
        t_ans = self.timestamps.get("text_answer_available_timestamp")
        if text_ready_ref is not None and t_ans is not None:
            text_avail_lat = max(0.0, (t_ans - text_ready_ref) * 1000.0)

        # TTFA: Text ready / TTS request to first audio
        tts_req_ref = self.timestamps.get("text_answer_available_timestamp") or self.timestamps.get("tts_request_timestamp")
        t_first_audio = self.timestamps.get("tts_first_audio_timestamp")
        tts_synth_lat = None
        if tts_req_ref is not None and t_first_audio is not None:
            tts_synth_lat = max(0.0, (t_first_audio - tts_req_ref) * 1000.0)
        elif self.timestamps.get("tts_request_timestamp") is not None and t_first_audio is not None:
            tts_synth_lat = self._diff_ms("tts_request_timestamp", "tts_first_audio_timestamp")

        # Total time to first audible output: from end of speech (or transcription complete) to first sound
        eos_ref = self.timestamps.get("utterance_end_timestamp") or self.timestamps.get("transcription_complete_timestamp") or self.timestamps.get("routing_start_timestamp")
        tts_first_audio_lat = None
        if eos_ref is not None and t_first_audio is not None:
            tts_first_audio_lat = max(0.0, (t_first_audio - eos_ref) * 1000.0)
        elif tts_synth_lat is not None:
            tts_first_audio_lat = tts_synth_lat

        playback_dur = self._diff_ms("tts_playback_start_timestamp", "tts_playback_end_timestamp")
        
        e2e_start = (
            self.timestamps.get("utterance_end_timestamp")
            or self.timestamps.get("transcription_complete_timestamp")
            or self.timestamps.get("routing_start_timestamp")
            or self.timestamps.get("capture_start_timestamp")
        )
        e2e_end = (
            self.timestamps.get("tts_playback_end_timestamp")
            or self.timestamps.get("tts_first_audio_timestamp")
            or self.timestamps.get("text_answer_available_timestamp")
            or self.timestamps.get("routing_complete_timestamp")
        )
        total_e2e = None
        if e2e_start is not None and e2e_end is not None:
            total_e2e = max(0.0, (e2e_end - e2e_start) * 1000.0)

        return {
            "utterance capture & EOS latency": eos_lat,
            "ASR recognition latency": asr_lat,
            "intent classification & routing": routing_lat,
            "external retrieval latency": retrieval_lat,
            "LLM time to first token (TTFT)": llm_ttft,
            "LLM total generation latency": llm_total,
            "visible text answer latency": text_avail_lat,
            "TTS time to first audio (TTFA)": tts_synth_lat,
            "time to first audible output": tts_first_audio_lat,
            "audio playback duration": playback_dur,
            "TOTAL END-TO-END LATENCY": total_e2e,
        }

    def print_breakdown(self) -> None:
        """Print the complete latency report to stdout and log once."""
        if self._printed:
            return
        self._printed = True

        metrics = self.compute_metrics()
        lines = [
            f"==================================================",
            f"PERFORMANCE TELEMETRY [{self.request_id}]",
            f"==================================================",
        ]
        
        # Summary highlights required by user specification:
        asr_ms = metrics.get("ASR recognition latency")
        asr_str = f"{asr_ms:6.1f} ms" if asr_ms is not None else "   N/A"
        lines.append(f"{'end-of-speech to text (Whisper)':<34}: {asr_str}")

        routing_ms = metrics.get("intent classification & routing")
        routing_str = f"{routing_ms:6.1f} ms" if routing_ms is not None else "   N/A"
        lines.append(f"{'routing & LLM processing time':<34}: {routing_str}")

        prov_str = f"{self.llm_call_count} calls {self.providers_tried if self.providers_tried else '[]'}"
        lines.append(f"{'LLM calls & providers tried':<34}: {prov_str}")

        ttfa_ms = metrics.get("TTS time to first audio (TTFA)")
        ttfa_str = f"{ttfa_ms:6.1f} ms" if ttfa_ms is not None else "   N/A"
        lines.append(f"{'text-ready to first audio (TTFA)':<34}: {ttfa_str}")

        sound_ms = metrics.get("time to first audible output")
        sound_str = f"{sound_ms:6.1f} ms" if sound_ms is not None else "   N/A"
        lines.append(f"{'end-of-speech to first sound':<34}: {sound_str}")

        lines.append(f"--------------------------------------------------")
        for name, val in metrics.items():
            val_str = f"{val:6.1f} ms" if val is not None else "   N/A"
            lines.append(f"{name:<34}: {val_str}")

        if self.timeout_reason:
            lines.append(f"{'timeout reason':<34}: {self.timeout_reason}")
        if self.fallback_reason:
            lines.append(f"{'fallback reason':<34}: {self.fallback_reason}")
        if self.cancellation_reason:
            lines.append(f"{'cancellation reason':<34}: {self.cancellation_reason}")

        lines.append(f"==================================================")
        summary = "\n".join(lines)
        print(summary)
        logger.info("\n" + summary)


_active_tracker: Optional[RequestLatencyTracker] = None


def get_current_tracker() -> RequestLatencyTracker:
    global _active_tracker
    if _active_tracker is None:
        _active_tracker = RequestLatencyTracker()
    return _active_tracker


def start_new_tracker(request_id: Optional[str] = None) -> RequestLatencyTracker:
    global _active_tracker
    _active_tracker = RequestLatencyTracker(request_id=request_id)
    return _active_tracker


class ActionExecutionTelemetry:
    """Phase 8: Action Execution Telemetry Tracker."""

    def __init__(self, command_id: str, user_input: str):
        self.command_id: str = command_id
        self.user_input: str = user_input
        self.resolved_intent: str = ""
        self.target_device: str = "windows"
        self.selected_function: str = ""
        self.t_input_received: float = time.monotonic()
        self.t_routing_start: float = time.monotonic()
        self.t_routing_end: float = 0.0
        self.t_dispatch_start: float = 0.0
        self.t_dispatch_end: float = 0.0
        self.t_execution_start: float = 0.0
        self.t_execution_end: float = 0.0
        self.t_verification_start: float = 0.0
        self.t_verification_end: float = 0.0
        self.success: bool = False
        self.details: str = ""

    def mark_routed(self, intent: str, target_device: str, selected_func: str):
        self.t_routing_end = time.monotonic()
        self.resolved_intent = intent
        self.target_device = target_device
        self.selected_function = selected_func

    def start_execution(self):
        self.t_execution_start = time.monotonic()

    def end_execution(self, success: bool = True, details: str = ""):
        self.t_execution_end = time.monotonic()
        self.success = success
        self.details = details

    def start_verification(self):
        self.t_verification_start = time.monotonic()

    def end_verification(self):
        self.t_verification_end = time.monotonic()

    def log_telemetry(self):
        now = time.monotonic()
        routing_ms = (self.t_routing_end - self.t_routing_start) * 1000 if self.t_routing_end else 0.0
        exec_ms = (self.t_execution_end - self.t_execution_start) * 1000 if self.t_execution_end else 0.0
        verif_ms = (self.t_verification_end - self.t_verification_start) * 1000 if self.t_verification_end else 0.0
        total_ms = (now - self.t_input_received) * 1000

        print(
            f"[ACTION TELEMETRY] [{self.command_id}] target={self.target_device} "
            f"intent={self.resolved_intent} func={self.selected_function} "
            f"routing={routing_ms:.1f}ms exec={exec_ms:.1f}ms verif={verif_ms:.1f}ms "
            f"total_completion={total_ms:.1f}ms success={self.success}"
        )
        logger.info(
            f"[ACTION TELEMETRY] [{self.command_id}] target={self.target_device} "
            f"intent={self.resolved_intent} func={self.selected_function} "
            f"routing={routing_ms:.1f}ms exec={exec_ms:.1f}ms verif={verif_ms:.1f}ms "
            f"total_completion={total_ms:.1f}ms success={self.success}"
        )
