"""
NOVA Central Dispatcher
Routes all image processing and AI operations with rich, detailed output.
Every operation produces comprehensive, contextual descriptions.
"""
import cv2
import numpy as np
import os

# Import all service modules
from .enhancement import (
    grayscale, brightness, contrast, gamma, sepia, invert,
    threshold, posterize, solarize, enhance_image
)
from .filters import (
    gaussian_filter, mean_filter, median_filter, box_blur,
    weighted_filter, min_filter, max_filter
)
from .edges import (
    sobel_edge, laplacian_edge, emboss, canny_edge
)
from .noise import (
    salt_pepper_noise, gaussian_noise
)
from .effects import sharpen
from .denoise import denoise
from .ocr import extract_text
from .face_detection import detect_faces
from ..vision.detection import detect_objects, count_objects as yolo_count_objects
from .captioning import describe_image, describe_image_simple


def get_desktop_path():
    """Get the actual Desktop path (handles OneDrive Desktop)"""
    onedrive_desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
    if os.path.exists(onedrive_desktop):
        return onedrive_desktop
    return os.path.join(os.path.expanduser("~"), "Desktop")


def _image_summary(image):
    """Generate a brief summary of image properties for operation reports."""
    if image is None or not isinstance(image, np.ndarray):
        return ""
    h, w = image.shape[:2]
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    brightness = float(np.mean(gray))
    return f"{w}x{h}px, avg brightness {brightness:.0f}/255"


def dispatch(operation, context=None, value=None, **kwargs):
    """
    Central dispatcher for all NOVA operations.
    Every operation returns detailed, contextual results.
    """
    operation = (operation or "").strip().lower()

    # ── Validate context image ────────────────────────────
    image = getattr(context, 'image', None)
        
    if image is None:
        return "No image found. Please use input first."
        
    if not isinstance(image, np.ndarray):
        return "Error: context.image is not a valid image buffer."

    # ── Scene Description ──────────────────────────────────
    if operation == 'describe':
        try:
            from .captioning import describe_image
            return describe_image(image)
        except Exception as e:
            return f"Error during description: {str(e)}"

    # ── Extract Text (OCR) ─────────────────────────────────
    if operation == 'extract_text':
        try:
            from .ocr import extract_text
            result = extract_text(image)
            return result
        except Exception as e:
            return f"Error during text extraction: {str(e)}"

    # ── Object Detection ───────────────────────────────────
    if operation == 'detect_objects':
        try:
            from ..vision.detection import detect_objects
            result = detect_objects(image)
            if isinstance(result, str) and result.startswith("Error"):
                return result
            if isinstance(result, tuple) and len(result) == 2:
                annotated_img, detections = result
                context.image = annotated_img
                
                if not detections:
                    return "No objects detected"
                
                # Format: Detected: person (2), chair (1)
                counts = {}
                for d in detections:
                    counts[d['class']] = counts.get(d['class'], 0) + 1
                
                detect_str = ", ".join([f"{cls} ({count})" for cls, count in sorted(counts.items())])
                return f"Detected: {detect_str}"
            return result
        except Exception as e:
            return f"Error during object detection: {str(e)}"

    # ── Face Detection ─────────────────────────────────────
    if operation == 'detect_faces':
        try:
            from .face_detection import detect_faces
            result = detect_faces(image)
            if isinstance(result, str) and result.startswith("Error"):
                return result
            if isinstance(result, tuple) and len(result) == 2:
                annotated_img, face_count = result
                context.image = annotated_img
                return f"Detected {face_count} faces"
            return result
        except Exception as e:
            return f"Error during face detection: {str(e)}"

    # ── Object Counting ────────────────────────────────────
    if operation == 'count_objects':
        try:
            from ..vision.detection import count_objects as yolo_count_objects
            result = yolo_count_objects(image)
            if isinstance(result, str) and result.startswith("Error"):
                return result
            if isinstance(result, tuple) and len(result) == 2:
                total, class_counts = result
                
                # Format: Total objects: 5 (person: 3, chair: 2)
                breakdown = ", ".join([f"{cls}: {count}" for cls, count in sorted(class_counts.items())])
                return f"Total objects: {total} ({breakdown})"
            return result
        except Exception as e:
            return f"Error during object counting: {str(e)}"

    # ── Enhancement ────────────────────────────────────────
    if operation == 'enhance':
        try:
            from .enhancement import enhance_image
            result = enhance_image(image)
            if isinstance(result, str) and result.startswith("Error"):
                return result
            
            # Handle adaptive enhancement results (image, steps)
            if isinstance(result, tuple) and len(result) == 2:
                final_image, _ = result
                context.image = final_image
                return "Image enhanced successfully"
            else:
                context.image = result
                return "Image enhanced successfully"
        except Exception as e:
            return f"Error during enhancement: {str(e)}"

    # ── Denoise ───────────────────────────────────────────
    if operation == 'denoise':
        try:
            from .denoise import denoise
            result = denoise(image, 'bilateral')
            if isinstance(result, str) and result.startswith("Error"):
                return result
            
            context.image = result
            return "Noise reduction completed"
        except Exception as e:
            return f"Error during denoising: {str(e)}"

    operations_map = {
        'grayscale': lambda: grayscale(image),
        'blur': lambda: gaussian_filter(image, value if value is not None else 5),
        'brightness': lambda: brightness(image, value if value is not None else 10),
        'contrast': lambda: contrast(image, value if value is not None else 1.2),
        'edges': lambda: sobel_edge(image),
        'sharpen': lambda: sharpen(image, value if value is not None else 1.0),
        'sepia': lambda: sepia(image),
        'invert': lambda: invert(image),
        'threshold': lambda: threshold(image, value if value is not None else 127),
    }

    if operation not in operations_map:
        available_ops = [
            'grayscale', 'blur', 'brightness', 'contrast', 'edges',
            'sharpen', 'sepia', 'invert', 'threshold', 'denoise', 'enhance',
            'detect_objects', 'describe', 'extract_text', 'detect_faces', 'count_objects'
        ]
        return f"Error: Unknown operation '{operation}'. Available: {available_ops}"

    try:
        result = operations_map[operation]()

        if isinstance(result, str) and result.startswith("Error"):
            return result
        if not isinstance(result, np.ndarray):
            return f"Error: Operation '{operation}' did not produce an image."

        context.image = result
        # Return only the title + success for clean output
        title = operation.title()
        return f"{title} completed successfully"

    except Exception as e:
        return f"Error during operation '{operation}': {str(e)}"


def list_operations():
    """List all available NOVA operations"""
    return [
        'grayscale', 'blur', 'brightness', 'contrast', 'edges',
        'sharpen', 'sepia', 'invert', 'threshold', 'denoise', 'enhance',
        'detect_objects', 'describe', 'extract_text', 'detect_faces', 'count_objects'
    ]
