import cv2
import numpy as np

def gaussian_filter(image, kernel_size=5):
    """Apply Gaussian blur"""
    return cv2.GaussianBlur(image, (kernel_size, kernel_size), 0)

def mean_filter(image, kernel_size=3):
    """Apply mean/average filter"""
    kernel = np.ones((kernel_size, kernel_size), np.float32) / (kernel_size * kernel_size)
    return cv2.filter2D(image, -1, kernel)

def median_filter(image, kernel_size=5):
    """Apply median filter for noise reduction"""
    return cv2.medianBlur(image, kernel_size)

def box_blur(image, kernel_size=3):
    """Apply box blur"""
    return cv2.boxFilter(image, -1, (kernel_size, kernel_size))

def weighted_filter(image):
    """Apply weighted average filter"""
    kernel = np.array([[1, 2, 1],
                       [2, 4, 2],
                       [1, 2, 1]]) / 16
    return cv2.filter2D(image, -1, kernel)

def min_filter(image, kernel_size=3):
    """Apply morphological erosion (min filter)"""
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    return cv2.erode(image, kernel)

def max_filter(image, kernel_size=3):
    """Apply morphological dilation (max filter)"""
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    return cv2.dilate(image, kernel)
