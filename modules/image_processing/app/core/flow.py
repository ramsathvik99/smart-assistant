from app.services.dispatcher import dispatch
from app.core.utils import auto_save_result

class AssistantFlow:
    """
    Execution flow engine for the Assistant's natural language pipelines.
    Converts a parsed intent into sequential image processing and analysis steps.
    """

    def __init__(self, registry):
        self.registry = registry

    def run(self, intent, context, on_step_start=None, on_step_complete=None):
        """
        Run the parsed intent against the provided context and registry.
        """
        results = []
        
        # ── 1. Step: Image Sourcing ────────────────────────────
        method = intent.get("method")
        filename = intent.get("filename")
        
        if method == "upload" or filename:
            msg = f"Loading file: {filename or 'Requested Upload'}"
            if on_step_start: on_step_start(msg)
            else: print(f"  📥 {msg}")
            
            input_handler = self.registry.get("upload")()
            if filename:
                import cv2
                img = cv2.imread(filename)
                if img is not None:
                    context.image = img
                else:
                    return f"Error: Could not load file {filename}"
            else:
                input_handler.execute(context)
                
        elif method == "camera":
            msg = "Image captured"
            if on_step_start: on_step_start(msg)
            else: print(f"  📸 {msg}")
            
            input_handler = self.registry.get("camera")()
            input_handler.execute(context)
            
        elif method == "screenshot":
            msg = "Screenshot captured"
            if on_step_start: on_step_start(msg)
            else: print(f"  🖼️  {msg}")
            
            input_handler = self.registry.get("screenshot")()
            input_handler.execute(context)

        # ── 2. Step: Action Pipeline ───────────────────────────
        if getattr(context, 'image', None) is None:
             return "Error: No image source was provided or loaded."

        actions = intent.get("actions", [])
        if not actions:
            return "Command recognized, but no specific actions found."

        for action in actions:
            result = dispatch(
                operation=action,
                context=context,
                value=None
            )
            
            # Print result directly if not an error
            if result and not (isinstance(result, str) and result.startswith("Error")):
                if not on_step_start:
                    print(f"  {result}")
                results.append(result)
            else:
                if not on_step_start:
                    print(f"  ❌ {result}")
                results.append(f"Error: {result}")
                break
            
            # Auto-save results if allowed for this operation
            no_save_ops = ["describe", "extract_text"]
            if action not in no_save_ops and context.image is not None:
                auto_save_result(action, context.image)

        return "Pipeline execution finished."
    
def execute_flow(context):
    """
    Convenience function to execute the full DIP flow from a context.
    Standardized entry point for NOVA integration.
    """
    from app.core.registry import Registry
    from app.core.parser import AssistantParser
    from app.vision.inputs import FileInput, CaptureCamera, CaptureScreenshot
    
    # 1. Initialize Registry & Vision Inputs
    registry = Registry()
    registry.register("upload", FileInput)
    registry.register("camera", CaptureCamera)
    registry.register("screenshot", CaptureScreenshot)
    
    # 2. Parse Intent
    parser = AssistantParser()
    intent = parser.parse(context.input_text)
    
    # 3. Handle Pre-resolved Image Path (if any)
    if hasattr(context, 'image_path') and context.image_path:
        intent["filename"] = context.image_path
        intent["method"] = "upload" # Force upload method if path is provided
        
    # 4. Run Flow
    flow = AssistantFlow(registry)
    return flow.run(intent, context)
