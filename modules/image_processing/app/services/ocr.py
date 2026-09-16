"""
NOVA OCR Module
Extracts text from images using Tesseract OCR with fallback for missing binary.
"""
import cv2
import numpy as np
import os
import sys


def _find_tesseract():
    """Attempt to locate and configure Tesseract binary."""
    try:
        import pytesseract

        # Common Windows install paths
        common_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.join(os.path.expanduser("~"), "AppData", "Local",
                         "Programs", "Tesseract-OCR", "tesseract.exe"),
        ]

        for path in common_paths:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                return True

        # Try default (on PATH)
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            pass

        return False
    except ImportError:
        return False


def _ocr_fallback(image):
    """
    Basic text region detection when Tesseract is unavailable.
    Uses morphological ops to find text-like regions and reports them.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    h, w = gray.shape[:2]

    # Adaptive threshold to find dark regions on light background
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 15, 10)

    # Dilate to connect text characters
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))
    dilated = cv2.dilate(binary, kernel, iterations=2)

    # Find contours of text regions
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Filter for text-like regions (wide, not too tall)
    text_regions = []
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        aspect = cw / max(ch, 1)
        if area > 200 and aspect > 1.5 and ch < h * 0.5:
            text_regions.append((x, y, cw, ch))

    if text_regions:
        # Sort by vertical position
        text_regions.sort(key=lambda r: r[1])
        count = len(text_regions)
        return (f"Text Detection (Tesseract not installed — using shape analysis):\n"
                f"Found {count} text-like region{'s' if count != 1 else ''} in the image.\n"
                f"Install Tesseract OCR for full text extraction:\n"
                f"  Download: https://github.com/tesseract-ocr/tesseract\n"
                f"  Windows: https://github.com/UB-Mannheim/tesseract/wiki")
    else:
        return ("No text-like regions detected in the image.\n"
                "For full OCR, install Tesseract: "
                "https://github.com/tesseract-ocr/tesseract")


def extract_text(image):
    """
    Extract text from image using OCR with specialized preprocessing.
    Saves a debug image `debug_ocr.jpg` for verification.
    """
    if image is None:
        return "Error: Image buffer is None"

    # Try Tesseract
    if _find_tesseract():
        try:
            import pytesseract

            # Preprocessing Pipeline
            # 1. Convert to grayscale
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
            
            # 2. Apply denoising
            denoised = cv2.medianBlur(gray, 3)
            
            # 3. Apply thresholding (Otsu's Binarization)
            _, thresh = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # Extract text
            text = pytesseract.image_to_string(thresh)
            
            # Clean and return
            cleaned_text = text.strip()
            if cleaned_text:
                return cleaned_text
            else:
                return "No text detected"

        except Exception as e:
            return "Error during text extraction: " + str(e)
    else:
        # Fallback: shape-based detection
        return _ocr_fallback(image)
