"""
NOVA Scene Captioning & Visual Intelligence Module
Generates rich, contextual, multi-layered descriptions of images by combining
AI captioning with deep computer vision analysis for comprehensive scene understanding.
"""
import cv2
import numpy as np
import os

# Global model cache
_processor = None
_model_obj = None
_caption_ready = None  # None = not tried, True = loaded, False = failed


def _load_blip_model():
    """Load BLIP captioning model with direct API."""
    global _processor, _model_obj, _caption_ready

    if _caption_ready is not None:
        return _caption_ready

    try:
#        print("[NOVA] Loading BLIP captioning model...")
        from transformers import BlipProcessor, BlipForConditionalGeneration

        model_name = "Salesforce/blip-image-captioning-base"
        _processor = BlipProcessor.from_pretrained(model_name)
        _model_obj = BlipForConditionalGeneration.from_pretrained(model_name)
        _caption_ready = True
#        print("[NOVA] Caption model ready.")
        return True

    except ImportError as e:
#        print(f"[NOVA] Missing dependency for captioning: {e}")
        _caption_ready = False
        return False
    except Exception as e:
#        print(f"[NOVA] Caption model load failed: {e}")
        _caption_ready = False
        return False


def _generate_captions(image):
    """Generate multiple captions using different prompts for richer context."""
    from PIL import Image
    import torch

    # Convert BGR (OpenCV) to RGB (PIL)
    raw_image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    captions = []

    # Unconditional caption (general)
    try:
        inputs = _processor(raw_image, return_tensors="pt")
        with torch.no_grad():
            ids = _model_obj.generate(**inputs, max_new_tokens=80,
                                      num_beams=5, early_stopping=True)
        captions.append(_processor.decode(ids[0], skip_special_tokens=True).strip())
    except Exception:
        pass

    # Conditional captions with guiding prompts
    prompts = [
        "this image shows",
        "the scene contains",
        "in the foreground",
        "the colors in this image are",
        "the overall mood of this image is",
    ]

    for prompt in prompts:
        try:
            inputs = _processor(raw_image, text=prompt, return_tensors="pt")
            with torch.no_grad():
                ids = _model_obj.generate(**inputs, max_new_tokens=60,
                                          num_beams=4, early_stopping=True)
            text = _processor.decode(ids[0], skip_special_tokens=True).strip()
            if text and text != prompt and len(text) > len(prompt) + 5:
                captions.append(text)
        except Exception:
            continue

    return captions


def _deep_cv_analysis(image):
    """
    Perform deep computer vision analysis to extract comprehensive
    technical and perceptual properties from the image.
    """
    h, w = image.shape[:2]
    channels = image.shape[2] if len(image.shape) == 3 else 1
    total_pixels = h * w
    aspect_ratio = w / h

    analysis = {}

    # ── Dimensions and format ──────────────────────────────
    if aspect_ratio > 1.6:
        orientation = "wide panoramic"
    elif aspect_ratio > 1.2: orientation = "landscape"
    elif aspect_ratio > 0.8: orientation = "square"
    elif aspect_ratio > 0.6: orientation = "portrait"
    else: orientation = "tall narrow"

    megapixels = total_pixels / 1_000_000
    analysis["dimensions"] = (f"{w}x{h} pixels ({megapixels:.1f} megapixels), "
                               f"{orientation} orientation")

    # ── Color analysis ─────────────────────────────────────
    if channels == 3:
        mean_bgr = np.mean(image, axis=(0, 1))
        std_bgr = np.std(image, axis=(0, 1))
        b, g, r = mean_bgr
        sb, sg, sr = std_bgr

        # Dominant color
        if r > g + 20 and r > b + 20:
            dominant = "warm red-orange tones"
        elif g > r + 20 and g > b + 20:
            dominant = "natural green tones"
        elif b > r + 20 and b > g + 20:
            dominant = "cool blue tones"
        elif r > 200 and g > 200 and b > 200:
            dominant = "predominantly white or very light tones"
        elif r < 50 and g < 50 and b < 50:
            dominant = "predominantly dark or black tones"
        elif abs(r - g) < 20 and abs(g - b) < 20:
            dominant = "neutral gray tones"
        elif r > b and g > b:
            dominant = "warm yellow-gold tones"
        elif b > r and g > r:
            dominant = "cool cyan-teal tones"
        elif r > g and b > g:
            dominant = "purple-magenta tones"
        else:
            dominant = "mixed, balanced colors"

        # Color variety
        color_range = max(sr, sg, sb)
        if color_range > 80:
            variety = "highly colorful with rich color variation"
        elif color_range > 50:
            variety = "moderately colorful"
        elif color_range > 25:
            variety = "subtle color palette with muted tones"
        else:
            variety = "very uniform, nearly monochromatic"

        # HSV analysis for saturation
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        avg_sat = np.mean(hsv[:, :, 1])
        if avg_sat > 150:
            saturation = "highly saturated and vivid"
        elif avg_sat > 80:
            saturation = "moderately saturated"
        elif avg_sat > 30:
            saturation = "desaturated and muted"
        else:
            saturation = "nearly grayscale, very low saturation"

        analysis["color"] = (f"The image features {dominant}, appearing {variety}. "
                             f"Color saturation is {saturation}.")
    else:
        analysis["color"] = "The image is in grayscale with no color information."

    # ── Brightness and exposure ────────────────────────────
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if channels == 3 else image
    avg_brightness = float(np.mean(gray))
    std_brightness = float(np.std(gray))

    if avg_brightness > 210:
        bright_desc = "significantly overexposed or washed out"
    elif avg_brightness > 170:
        bright_desc = "brightly lit with high-key lighting"
    elif avg_brightness > 130:
        bright_desc = "well-lit with balanced, natural exposure"
    elif avg_brightness > 90:
        bright_desc = "moderately lit, slightly dim"
    elif avg_brightness > 50:
        bright_desc = "dimly lit with low-key, moody lighting"
    else:
        bright_desc = "very dark, possibly underexposed"

    # Contrast
    if std_brightness > 75:
        contrast_desc = "very high contrast, creating strong visual impact with deep shadows and bright highlights"
    elif std_brightness > 55:
        contrast_desc = "high contrast with clear distinction between light and dark areas"
    elif std_brightness > 35:
        contrast_desc = "moderate contrast with a natural, balanced tonal range"
    elif std_brightness > 18:
        contrast_desc = "low contrast, giving a soft, hazy, or faded appearance"
    else:
        contrast_desc = "very low contrast, extremely flat with almost no tonal variation"

    analysis["exposure"] = (f"The image is {bright_desc} (average brightness: "
                            f"{avg_brightness:.0f}/255). It has {contrast_desc} "
                            f"(standard deviation: {std_brightness:.1f}).")

    # ── Sharpness and detail complexity ────────────────────
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    edges = cv2.Canny(gray, 50, 150)
    edge_ratio = np.count_nonzero(edges) / edges.size

    if laplacian_var > 800:
        sharpness = "exceptionally sharp with crisp, well-defined edges"
    elif laplacian_var > 300:
        sharpness = "reasonably sharp with clearly visible details"
    elif laplacian_var > 80:
        sharpness = "moderately sharp, typical of standard photography"
    elif laplacian_var > 20:
        sharpness = "slightly soft or blurred, with some loss of fine detail"
    else:
        sharpness = "noticeably blurry with very little fine detail"

    if edge_ratio > 0.20:
        complexity = ("extremely complex and densely packed with fine details, "
                      "text, or intricate patterns")
    elif edge_ratio > 0.12:
        complexity = "highly detailed with many distinct features and edges"
    elif edge_ratio > 0.06:
        complexity = "moderately detailed with a good mix of smooth and textured regions"
    elif edge_ratio > 0.02:
        complexity = "relatively simple with few prominent features"
    else:
        complexity = "very simple and minimal, with large uniform areas"

    analysis["sharpness"] = (f"The image is {sharpness} (Laplacian variance: "
                             f"{laplacian_var:.0f}). Scene complexity is "
                             f"{complexity} (edge density: {edge_ratio:.1%}).")

    # ── Spatial composition ────────────────────────────────
    # Divide into quadrants and analyze brightness distribution
    mid_h, mid_w = h // 2, w // 2
    quads = {
        "top-left": gray[:mid_h, :mid_w],
        "top-right": gray[:mid_h, mid_w:],
        "bottom-left": gray[mid_h:, :mid_w],
        "bottom-right": gray[mid_h:, mid_w:],
    }
    quad_brightness = {k: float(np.mean(v)) for k, v in quads.items()}
    brightest = max(quad_brightness, key=quad_brightness.get)
    darkest = min(quad_brightness, key=quad_brightness.get)

    brightness_variance = np.std(list(quad_brightness.values()))
    if brightness_variance > 40:
        distribution = (f"highly uneven lighting — the {brightest} region is significantly "
                        f"brighter than the {darkest} region, suggesting directional light "
                        f"or a compositional focal point")
    elif brightness_variance > 15:
        distribution = (f"somewhat uneven — the {brightest} area is brighter, "
                        f"creating a natural visual flow through the image")
    else:
        distribution = "evenly distributed luminance across the entire frame"

    analysis["composition"] = (f"Spatial composition shows {distribution}.")

    # ── Texture analysis ───────────────────────────────────
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    gradient_mag = np.sqrt(gx**2 + gy**2)
    avg_gradient = float(np.mean(gradient_mag))

    if avg_gradient > 60:
        texture = "rich, pronounced textures with significant surface detail"
    elif avg_gradient > 30:
        texture = "moderate texture, a blend of smooth and textured surfaces"
    elif avg_gradient > 12:
        texture = "subtle textures, mostly smooth with occasional detail"
    else:
        texture = "very smooth, nearly textureless surfaces"

    analysis["texture"] = f"The image contains {texture} (average gradient: {avg_gradient:.1f})."

    # ── Potential content type inference ────────────────────
    content_hints = []
    if edge_ratio > 0.15 and avg_sat < 40:
        content_hints.append("technical diagram, schematic, or text document")
    if edge_ratio > 0.10 and avg_sat < 60 and laplacian_var > 200:
        content_hints.append("chart, flowchart, or UI wireframe")
    if avg_sat > 100 and laplacian_var > 300:
        content_hints.append("vivid photograph or illustrated artwork")
    if avg_brightness > 200 and std_brightness < 30:
        content_hints.append("white background graphic or product photo")
    if avg_brightness < 60 and avg_sat < 40:
        content_hints.append("dark-themed UI, screenshot, or night scene")
    if not content_hints:
        content_hints.append("general image or mixed content")

    analysis["content_type"] = ("Based on visual characteristics, this appears to be: "
                                + "; or ".join(content_hints) + ".")

    return analysis


def describe_image(image):
    """
    Generate a minimal AI-powered description of an image.
    Returns only the raw description string without any prefixes or formatting.
    """
    if image is None:
        return "Error: Image buffer is None"

    if _load_blip_model():
        try:
            captions = _generate_captions(image)
            if captions:
                # Use primary caption (first result)
                caption = captions[0]
                
                # Cleanup prefixes as requested
                prefixes = ["This image shows", "The image shows", "this image shows", "the image shows"]
                for p in prefixes:
                    caption = caption.replace(p, "")
                
                # Strip and clean
                caption = caption.strip().capitalize()
                
                return caption
            else:
                return "Could not generate description."
        except Exception as e:
            return f"Capture generation error: {e}"
    
    return "Intelligence model not loaded."


def describe_image_simple(image_path, command=None):
    """Quick image analysis returning basic properties."""
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
        image = cv2.imread(image_path)
        if image is None:
            return "Error: Could not read image"

        h, w, c = image.shape
        avg_color = np.mean(image, axis=(0, 1))
        brightness = np.mean(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
        dominant = ['Blue', 'Green', 'Red'][np.argmax(avg_color)]

        return (
            f"Image Analysis:\n"
            f"  Dimensions: {w}x{h} pixels\n"
            f"  Channels: {c}\n"
            f"  Average color (BGR): {avg_color.astype(int)}\n"
            f"  Brightness: {brightness:.1f}/255\n"
            f"  Dominant channel: {dominant}\n"
            f"  Color space: {'Color' if c == 3 else 'Grayscale'}"
        )
    except Exception as e:
        return f"Error during analysis: {str(e)}"
