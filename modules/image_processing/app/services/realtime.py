import time
import cv2

from ..vision.detection import get_model


def summarize_frame(frame, min_confidence=0.35):
    """
    Create a short natural-language summary of detected objects in a frame.
    """
    model = get_model()
    if model is None:
        return "Object model is unavailable for real-time analysis."

    results = model(frame, verbose=False)
    if not results or len(results[0].boxes) == 0:
        return "I do not detect any clear objects right now."

    names = model.names
    counts = {}
    for box in results[0].boxes:
        confidence = float(box.conf[0])
        if confidence < min_confidence:
            continue
        cls_id = int(box.cls[0])
        label = names[cls_id]
        counts[label] = counts.get(label, 0) + 1

    if not counts:
        return "I see movement, but no high-confidence objects yet."

    ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    top_items = ordered[:4]
    parts = [f"{count} {name}" for name, count in top_items]
    return "I can see " + ", ".join(parts) + "."


def analyze_live_environment(duration_seconds=15, interval_seconds=3, announce=None):
    """
    Analyze live camera frames and provide periodic scene summaries.
    """
    duration_seconds = max(3, int(duration_seconds))
    interval_seconds = max(1, int(interval_seconds))

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return ["Error: Could not open camera for real-time analysis."]

    summaries = []
    try:
        start = time.time()
        next_tick = start
        while time.time() - start < duration_seconds:
            ret, frame = cap.read()
            if not ret:
                summaries.append("Warning: Camera frame capture failed.")
                break

            now = time.time()
            if now >= next_tick:
                summary = summarize_frame(frame)
                summaries.append(summary)
                if announce:
                    try:
                        announce(summary)
                    except Exception:
                        pass
                next_tick = now + interval_seconds

        return summaries if summaries else ["No scene summaries were generated."]
    finally:
        cap.release()
