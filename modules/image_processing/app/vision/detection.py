"""
NOVA Vision Detection Module
YOLO-based object detection and counting with lazy model loading.
"""
import cv2
import numpy as np

# Global model variable — loaded lazily
_model = None


def get_model():
    """
    Lazy-load the YOLO model once and cache it.
    Handles PyTorch 2.6+ weights_only=True breaking change by registering
    ultralytics classes as safe globals before model loading.
    """
    global _model
    if _model is not None:
        return _model
    try:
        # ── PyTorch 2.6+ compatibility fix ─────────────────────────────
        # torch.load now defaults to weights_only=True, which rejects
        # ultralytics model classes. Register them as safe globals first.
        try:
            import torch
            import torch.serialization as ts
            from ultralytics.nn.tasks import DetectionModel
            from ultralytics.nn.modules import (
                Conv, C2f, SPPF, Detect, DFL
            )
            ts.add_safe_globals([
                DetectionModel,
                Conv, C2f, SPPF, Detect, DFL,
            ])
        except Exception:
            pass  # Older PyTorch versions — safe globals API may not exist

        from ultralytics import YOLO
        _model = YOLO("yolov8n.pt")
        return _model

    except ImportError:
        print("[VISION] ultralytics not installed. Object detection unavailable.")
        return None
    except Exception as exc:
        print(f"[VISION] YOLO model load failed: {exc}")
        return None


def detect_objects(image):
    """
    Detect objects and draw labeled bounding boxes.
    Only returns detections with confidence >= 0.5.
    Returns (annotated_image, detections_list).
    """
    try:
        model = get_model()
        if model is None:
            return "Error: YOLO model is not available."

        if image is None:
            return "Error: Image buffer is None"

        working_image = image.copy()
        results = model(working_image, verbose=False) # Suppress model logs

        detections = []
        if len(results) > 0 and len(results[0].boxes) > 0:
            boxes = results[0].boxes
            names = model.names

            for box in boxes:
                confidence = float(box.conf[0])
                if confidence < 0.5: # User required threshold
                    continue

                cls_id = int(box.cls[0])
                label = names[cls_id]
                x1, y1, x2, y2 = map(int, box.xyxy[0])

                detections.append({
                    'class': label,
                    'confidence': confidence,
                    'bbox': [x1, y1, x2, y2],
                })

                # Draw clean bounding box
                cv2.rectangle(working_image, (x1, y1), (x2, y2), (0, 255, 0), 2)
                label_text = f"{label} {confidence:.2f}"
                cv2.putText(working_image, label_text, (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        return working_image, detections

    except Exception as e:
        return f"Error during object detection: {str(e)}"


def count_objects(image):
    """
    Count objects in image using a 0.5 confidence threshold.
    Returns (total_count, {class_name: count}).
    """
    try:
        model = get_model()
        if model is None:
            return "Error: YOLO model is not available."

        if image is None:
            return "Error: Image buffer is None"

        results = model(image, verbose=False) # Suppress model logs

        if len(results) == 0 or len(results[0].boxes) == 0:
            return 0, {}

        boxes = results[0].boxes
        names = model.names

        class_counts = {}
        for box in boxes:
            confidence = float(box.conf[0])
            if confidence >= 0.5: # Maintain consistency
                cls_id = int(box.cls[0])
                label = names[cls_id]
                class_counts[label] = class_counts.get(label, 0) + 1

        total = sum(class_counts.values())
        return total, class_counts

    except Exception as e:
        return f"Error during object counting: {str(e)}"
