import os
import sys
import cv2
from pathlib import Path

# Add the current directory (modules/image_processing) to sys.path 
# so we can import 'app' directly as the DIP engine expects.
DIP_ROOT = Path(__file__).parent.resolve()
if str(DIP_ROOT) not in sys.path:
    sys.path.append(str(DIP_ROOT))

from app.core.context import Context
from app.core.registry import Registry
from app.services.dispatcher import dispatch
from app.core.parser import AssistantParser
from app.vision.inputs import FileInput, CaptureCamera, CaptureScreenshot

class DIPBridgeContext:
    """
    Requested Context object structure:
    ctx.input_text = user command
    ctx.image_path = image path
    """
    def __init__(self):
        self.input_text = ""
        self.image_path = ""
        self.image = None # Internal field for DIP engine

def execute_flow(ctx):
    """
    Bridge function to the extracted DIP engine.
    Wraps AssistantFlow logic to fulfill the user's requested API.
    Treats the DIP engine as a BLACK BOX.
    """
    print(f"[DIP ENGINE] Executing flow for command: '{ctx.input_text}'")
    
    # 1. Initialize Registry and Context
    registry = Registry()
    registry.register("upload", FileInput)
    registry.register("camera", CaptureCamera)
    registry.register("screenshot", CaptureScreenshot)
    
    # Use the extracted Context object internally
    engine_ctx = Context()
    
    # 2. Parse command into intent
    parser = AssistantParser()
    intent = parser.parse(ctx.input_text)
    
    # Force the image path into the intent if provided
    if ctx.image_path and os.path.exists(ctx.image_path):
        intent["filename"] = ctx.image_path
        intent["method"] = "upload"
        # Pre-load for dispatch safety
        img = cv2.imread(ctx.image_path)
        if img is not None:
            engine_ctx.image = img
            
    # 3. Use the pipeline (dispatch logic from the DIP engine)
    actions = intent.get("actions", [])
    if not actions:
        # Fallback if parser missed it but we have a normalized command
        simple_cmd = ctx.input_text.lower().strip()
        if simple_cmd in ["enhance", "denoise", "ocr", "detect faces", "describe image", "count objects", "detect_objects"]:
            actions = [simple_cmd.replace(" ", "_").replace("ocr", "extract_text").replace("describe_image", "describe")]
        else:
            return "Command recognized, but no specific actions found."

    final_result = None
    for action in actions:
        # Map ocr to extract_text
        action_op = action if action != "ocr" else "extract_text"
        if action == "describe image": action_op = "describe"
        
        result = dispatch(
            operation=action_op,
            context=engine_ctx,
            value=None
        )
        
        if result and not (isinstance(result, str) and result.startswith("Error")):
            final_result = result
        else:
            return f"Error during {action}: {result}"

    # 4. Handle output according to requested rules:
    if final_result:
        # If it's a success message for an image op, capture the saved path
        if isinstance(final_result, str) and "completed successfully" in final_result:
            from app.core.utils import auto_save_result
            processed_path = auto_save_result(actions[-1], engine_ctx.image)
            return processed_path or final_result
            
        return final_result

    return "Pipeline execution finished."
