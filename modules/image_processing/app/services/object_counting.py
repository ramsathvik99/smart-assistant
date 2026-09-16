import cv2
import numpy as np

def count_objects(image):
    """
    Count objects in image using contour detection
    Returns count and annotated image
    """
    try:
        if image is None:
            return "Error: Image buffer is None"
        
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Apply threshold
        _, thresh = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
        
        # Find contours
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Filter small contours (noise)
        min_area = 100
        significant_contours = [c for c in contours if cv2.contourArea(c) > min_area]
        
        # Draw contours on original image
        result_image = image.copy()
        cv2.drawContours(result_image, significant_contours, -1, (0, 255, 0), 2)
        
        # Add count text
        count_text = f"Objects Found: {len(significant_contours)}"
        cv2.putText(result_image, count_text, (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        
        return result_image
        
    except Exception as e:
        return f"Error during object counting: {str(e)}"
