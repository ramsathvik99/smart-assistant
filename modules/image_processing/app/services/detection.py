"""
NOVA Object Detection Service
Wraps YOLO for object detection with bounding boxes and structured results.
"""
import cv2
import numpy as np


def detect_objects(image_path, confidence=0.5, command=None):
    """
    Detect objects in image using YOLO.
    Returns (annotated_image, detections_list) or error string.
    Each detection: {'class': str, 'confidence': float, 'bbox': [x1,y1,x2,y2]}
    """
    import sys
    from pathlib import Path
    DIP_ROOT = Path(__file__).resolve().parent.parent.parent
    if str(DIP_ROOT) not in sys.path:
        sys.path.append(str(DIP_ROOT))
    from input_handler import resolve_image

    image_path = resolve_image(command or "", image_path)

    if not image_path:
        print("[ERROR] No valid image")
        return "Error: No valid image"
    try:
        from ultralytics import YOLO

        model = YOLO('yolov8n.pt')

        image = cv2.imread(image_path)
        if image is None:
            return "Error: Could not read image"

        results = model(image, conf=confidence)

        detections = []
        for result in results:
            boxes = result.boxes
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                conf = box.conf[0].cpu().numpy()
                cls = int(box.cls[0].cpu().numpy())
                name = model.names[cls]

                detections.append({
                    'class': name,
                    'confidence': float(conf),
                    'bbox': [int(x1), int(y1), int(x2), int(y2)]
                })

                # Draw on image
                cv2.rectangle(image, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
                label_text = f"{name} {float(conf):.2f}"
                cv2.putText(image, label_text, (int(x1), int(y1) - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        return image, detections

    except ImportError:
        return "Error: ultralytics package not installed. Install with: pip install ultralytics"
    except Exception as e:
        if "download" in str(e).lower() or "connection" in str(e).lower():
            return "Error: Model download failed. Please check internet connection and try again."
        return f"Error during detection: {str(e)}"


def draw_detections(image_path, detections, output_path, command=None):
    """Draw bounding boxes on image"""
    import sys
    from pathlib import Path
    DIP_ROOT = Path(__file__).resolve().parent.parent.parent
    if str(DIP_ROOT) not in sys.path:
        sys.path.append(str(DIP_ROOT))
    from input_handler import resolve_image

    image_path = resolve_image(command or "", image_path)

    if not image_path:
        print("[ERROR] No valid image")
        return "Error: No valid image"

    image = cv2.imread(image_path)
    if image is None:
        return "Error: Could not read image"

    for detection in detections:
        if isinstance(detection, dict):
            x1, y1, x2, y2 = detection['bbox']
            class_name = detection['class']
            confidence = detection['confidence']

            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)

            label = f"{class_name}: {confidence:.2f}"
            label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)[0]
            cv2.rectangle(image, (x1, y1 - label_size[1] - 10),
                         (x1 + label_size[0], y1), (0, 255, 0), -1)
            cv2.putText(image, label, (x1, y1 - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)

    cv2.imwrite(output_path, image)
    return f"Detections saved to {output_path}"
