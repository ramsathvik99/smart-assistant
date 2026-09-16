from app.services.capture import capture_screenshot

class CaptureScreenshot:
    def execute(self, context):
        import numpy as np
        result = capture_screenshot()
        
        # If it's a numpy array, it's a successful capture
        if isinstance(result, np.ndarray):
            context.image = result
            return "Screenshot captured successfully and loaded into memory."
            
        # If it's a string, it's either an error or a message
        return result
