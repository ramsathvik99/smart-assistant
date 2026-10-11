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
        self.cancellation_reason: Optional[str] = None
        self.timeout_reason: Optional[str] = None
        self.fallback_reason: Optional[str] = None
        self._printed: bool = False

    def record(self, metric_name: str, ts: Optional[float] = None) -> None:
        """Record monotonic timestamp for a pipeline step."""
        now = ts if ts is not None else time.monotonic()
        self.timestamps[metric_name] = now

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

        tts_synth_lat = self._diff_ms("tts_request_timestamp", "tts_first_audio_timestamp")
        tts_first_audio_lat = self._diff_ms("utterance_end_timestamp", "tts_first_audio_timestamp") or tts_synth_lat
        playback_dur = self._diff_ms("tts_playback_start_timestamp", "tts_playback_end_timestamp")
        
        # End-to-end: utterance_end to playback_end (or first_audio if playback ongoing)
        total_e2e = self._diff_ms("utterance_end_timestamp", "tts_playback_end_timestamp")
        if total_e2e is None:
            total_e2e = self._diff_ms("utterance_end_timestamp", "tts_first_audio_timestamp")

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
