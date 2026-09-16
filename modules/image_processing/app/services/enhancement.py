import cv2
import numpy as np

def enhance_image(image):
    """
    Adaptive, condition-based image enhancement.
    Analyzes image properties and applies only necessary corrections.
    """
    try:
        if image is None:
            return "Error: Image buffer is None"
        
        applied_steps = []
        h, w = image.shape[:2]
        
        # ── Step 0: Image Analysis ──────────────────────────
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        
        brightness = np.mean(gray)
        contrast = gray.std()
        sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
        
        # ── Step 1: Brightness Correction ───────────────────
        if brightness < 100:
            # Increase brightness and slightly boost gain
            image = cv2.convertScaleAbs(image, alpha=1.2, beta=30)
            applied_steps.append(f"Brightness boost (mean was {brightness:.1f})")
            
        # ── Step 2: Contrast Correction (CLAHE) ─────────────
        if contrast < 40:
            # Apply CLAHE to lightness channel in LAB space
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
            l = clahe.apply(l)
            image = cv2.merge((l, a, b))
            image = cv2.cvtColor(image, cv2.COLOR_LAB2BGR)
            applied_steps.append(f"Contrast enhancement (std was {contrast:.1f})")
            
        # ── Step 3: Sharpness Correction ────────────────────
        if sharpness < 100:
            # Apply subtle 3x3 sharpening kernel
            kernel = np.array([[0, -1, 0],
                               [-1, 5, -1],
                               [0, -1, 0]])
            image = cv2.filter2D(image, -1, kernel)
            applied_steps.append(f"Edge sharpening (variance was {sharpness:.1f})")
            
        # ── Step 4: Optional Upscale ────────────────────────
        if w < 1000:
            # Slight resize for low-res images
            image = cv2.resize(image, None, fx=1.2, fy=1.2, interpolation=cv2.INTER_CUBIC)
            applied_steps.append(f"Moderate upscale (original width was {w}px)")
            
        if not applied_steps:
            applied_steps.append("No corrections needed (image properties are optimal)")
            
        return image, applied_steps
        
    except Exception as e:
        return f"Error during enhancement: {str(e)}"

def grayscale(image):
    """Convert image to grayscale"""
    try:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    except Exception as e:
        return f"Error during grayscale: {str(e)}"

def brightness(image, value=10):
    """Adjust brightness"""
    try:
        return cv2.convertScaleAbs(image, alpha=1, beta=value)
    except Exception as e:
        return f"Error during brightness: {str(e)}"

def contrast(image, value=1.2):
    """Adjust contrast"""
    try:
        return cv2.convertScaleAbs(image, alpha=value, beta=0)
    except Exception as e:
        return f"Error during contrast: {str(e)}"

def gamma(image, value=1.5):
    """Apply gamma correction"""
    try:
        if value <= 0:
            return "Error during gamma: gamma value must be > 0"
        inv_gamma = 1.0 / value
        table = np.array([((i / 255.0) ** inv_gamma) * 255 
            for i in np.arange(256)]).astype(np.uint8)
        return cv2.LUT(image, table)
    except Exception as e:
        return f"Error during gamma: {str(e)}"

def sepia(image):
    """Apply sepia effect"""
    try:
        kernel = np.array([[0.272, 0.534, 0.131],
                          [0.349, 0.686, 0.168],
                          [0.393, 0.627, 0.189]])
        sepia = cv2.transform(image, kernel)
        return sepia
    except Exception as e:
        return f"Error during sepia: {str(e)}"

def invert(image):
    """Invert image colors"""
    try:
        return cv2.bitwise_not(image)
    except Exception as e:
        return f"Error during invert: {str(e)}"

def threshold(image, value=127):
    """Apply binary threshold"""
    try:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, value, 255, cv2.THRESH_BINARY)
        return thresh
    except Exception as e:
        return f"Error during threshold: {str(e)}"

def posterize(image, levels=5):
    """Posterize image"""
    try:
        # Reduce color levels
        factor = 256 / levels
        image = (image // factor) * factor
        return image.astype(np.uint8)
    except Exception as e:
        return f"Error during posterize: {str(e)}"

def solarize(image, threshold=128):
    """Solarize effect - invert pixels above threshold"""
    try:
        result = image.copy()
        mask = image > threshold
        result[mask] = 255 - result[mask]
        return result
    except Exception as e:
        return f"Error during solarize: {str(e)}"
