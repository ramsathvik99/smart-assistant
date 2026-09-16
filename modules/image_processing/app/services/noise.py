import cv2
import numpy as np

def salt_pepper_noise(image, salt_prob=0.01, pepper_prob=0.01):
    """Add salt and pepper noise to image"""
    noisy = image.copy()
    
    # Salt noise (white pixels)
    salt_coords = np.random.random(image.shape[:2]) < salt_prob
    if len(noisy.shape) == 3:
        noisy[salt_coords] = [255, 255, 255]
    else:
        noisy[salt_coords] = 255
    
    # Pepper noise (black pixels)
    pepper_coords = np.random.random(image.shape[:2]) < pepper_prob
    if len(noisy.shape) == 3:
        noisy[pepper_coords] = [0, 0, 0]
    else:
        noisy[pepper_coords] = 0
    
    return noisy

def gaussian_noise(image, mean=0, std=25):
    """Add Gaussian noise to image"""
    noisy = image.copy().astype(np.float32)
    noise = np.random.normal(mean, std, image.shape)
    noisy = noisy + noise
    noisy = np.clip(noisy, 0, 255).astype(np.uint8)
    return noisy
