import cv2
import numpy as np

def denoise(image, method='bilateral'):
    """
    Denoise image using various methods
    Returns denoised image
    """
    try:
        if image is None:
            return "Error: Image buffer is None"
        
        if method == 'bilateral':
            # Bilateral filter - preserves edges while reducing noise
            denoised = cv2.bilateralFilter(image, 9, 75, 75)
        elif method == 'gaussian':
            # Gaussian blur
            denoised = cv2.GaussianBlur(image, (5, 5), 0)
        elif method == 'median':
            # Median filter - good for salt and pepper noise
            denoised = cv2.medianBlur(image, 5)
        else:
            # Default to bilateral
            denoised = cv2.bilateralFilter(image, 9, 75, 75)
        
        return denoised
        
    except Exception as e:
        return f"Error during denoising: {str(e)}"
