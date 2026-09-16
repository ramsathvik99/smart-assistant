import cv2
import numpy as np

def sobel_edge(image):
    """Apply Sobel edge detection"""
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    
    sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    
    magnitude = np.sqrt(sobelx**2 + sobely**2)
    magnitude = np.clip(magnitude, 0, 255).astype(np.uint8)
    
    return magnitude

def laplacian_edge(image):
    """Apply Laplacian edge detection"""
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    laplacian = np.clip(laplacian, 0, 255).astype(np.uint8)
    
    return laplacian

def emboss(image):
    """Apply emboss effect"""
    kernel = np.array([[-2, -1, 0],
                       [-1, 1, 1],
                       [0, 1, 2]])
    return cv2.filter2D(image, -1, kernel)

def canny_edge(image, low_threshold=50, high_threshold=150):
    """Apply Canny edge detection"""
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    
    return cv2.Canny(gray, low_threshold, high_threshold)
