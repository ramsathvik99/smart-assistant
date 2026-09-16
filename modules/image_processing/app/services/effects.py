import cv2
import numpy as np

def vignette(image, intensity=0.5):
    """Apply vignette effect"""
    rows, cols = image.shape[:2]
    
    # Create vignette mask
    X_resultant_kernel = cv2.getGaussianKernel(cols, cols/2)
    Y_resultant_kernel = cv2.getGaussianKernel(rows, rows/2)
    kernel = Y_resultant_kernel * X_resultant_kernel.T
    mask = kernel / kernel.max()
    
    if len(image.shape) == 3:
        mask = np.dstack([mask] * 3)
    
    # Apply vignette
    result = image * (1 - intensity * (1 - mask))
    return result.astype(np.uint8)

def sharpen(image, amount=1.0):
    """Apply sharpening filter"""
    try:
        kernel = np.array([[-1, -1, -1],
                           [-1, 9, -1],
                           [-1, -1, -1]], dtype=np.float32)
        kernel[1, 1] = 8 * amount + 1
        result = cv2.filter2D(image, -1, kernel)
        return result.astype(np.uint8)
    except Exception as e:
        print(f"Sharpen error: {e}")
        # Fallback: simple sharpen
        return cv2.addWeighted(image, 1.5, image, -0.5, 0)

def unsharp_mask(image, amount=1.0, radius=1.0, threshold=0):
    """Apply unsharp mask"""
    blurred = cv2.GaussianBlur(image, (0, 0), radius)
    sharpened = cv2.addWeighted(image, 1 + amount, blurred, -amount, 0)
    
    if threshold > 0:
        diff = cv2.absdiff(image, blurred)
        mask = diff >= threshold
        sharpened = np.where(mask, sharpened, image)
    
    return sharpened.astype(np.uint8)

def adjust_hue(image, degrees):
    """Adjust hue by degrees (-180 to 180)"""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    
    # Convert degrees to OpenCV hue units (0-179)
    hue_shift = int(degrees * 179 / 180)
    h_new = (h.astype(np.int16) + hue_shift) % 180
    h_new = h_new.astype(np.uint8)
    
    hsv_new = cv2.merge([h_new, s, v])
    return cv2.cvtColor(hsv_new, cv2.COLOR_HSV2BGR)

def adjust_saturation(image, factor):
    """Adjust saturation. Factor: 0 to 2.0"""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    
    s_new = np.clip(s * factor, 0, 255).astype(np.uint8)
    hsv_new = cv2.merge([h, s_new, v])
    return cv2.cvtColor(hsv_new, cv2.COLOR_HSV2BGR)

def adjust_temperature(image, kelvin_change):
    """Adjust color temperature. Positive = warmer, Negative = cooler"""
    # Simple temperature adjustment using color balance
    result = image.copy().astype(np.float32)
    
    if kelvin_change > 0:  # Warmer
        result[:, :, 2] = np.clip(result[:, :, 2] * (1 + kelvin_change/1000), 0, 255)  # Red
        result[:, :, 0] = np.clip(result[:, :, 0] * (1 - kelvin_change/2000), 0, 255)  # Blue
    else:  # Cooler
        result[:, :, 0] = np.clip(result[:, :, 0] * (1 - kelvin_change/1000), 0, 255)  # Blue
        result[:, :, 2] = np.clip(result[:, :, 2] * (1 + kelvin_change/2000), 0, 255)  # Red
    
    return result.astype(np.uint8)

def rgb_balance(image, r=0, g=0, b=0):
    """Adjust RGB balance. Values: -50 to 50"""
    result = image.copy().astype(np.float32)
    result[:, :, 2] = np.clip(result[:, :, 2] + r, 0, 255)  # Red
    result[:, :, 1] = np.clip(result[:, :, 1] + g, 0, 255)  # Green
    result[:, :, 0] = np.clip(result[:, :, 0] + b, 0, 255)  # Blue
    return result.astype(np.uint8)

def highlights_shadows(image, strength=0.5):
    """Adjust highlights and shadows. Strength: -1.0 to 1.0"""
    if len(image.shape) == 3:
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
    else:
        l = image
    
    # Apply curve to L channel
    l_float = l.astype(np.float32) / 255.0
    
    if strength > 0:  # Brighten shadows
        mask = l_float < 0.5
        l_float[mask] = l_float[mask] * (1 + strength)
    else:  # Darken highlights
        mask = l_float > 0.5
        l_float[mask] = 0.5 + (l_float[mask] - 0.5) * (1 + strength)
    
    l_new = np.clip(l_float * 255, 0, 255).astype(np.uint8)
    
    if len(image.shape) == 3:
        lab_new = cv2.merge([l_new, a, b])
        return cv2.cvtColor(lab_new, cv2.COLOR_LAB2BGR)
    else:
        return l_new
