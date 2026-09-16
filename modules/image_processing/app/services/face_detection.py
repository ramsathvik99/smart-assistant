"""
NOVA Face Detection Module
Detects human faces using OpenCV Haar cascades.
"""
import cv2
import numpy as np


def detect_faces(image):
    """
    Detect faces in image using OpenCV Haar cascades.
    Returns (annotated_image, face_count) or error string.
    """
    try:
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )

        if image is None:
            return "Error: Image buffer is None"

        working_image = image.copy()
        gray = cv2.cvtColor(working_image, cv2.COLOR_BGR2GRAY)

        faces = face_cascade.detectMultiScale(gray, 1.1, 4)

        face_count = len(faces)

        for (x, y, w, h) in faces:
            cv2.rectangle(working_image, (x, y), (x + w, y + h), (0, 120, 255), 2)
            cv2.putText(working_image, "Face", (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 120, 255), 2)

        return working_image, face_count

    except Exception as e:
        return f"Error during face detection: {str(e)}"
