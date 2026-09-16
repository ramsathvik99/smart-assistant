class VisionController:
    def __init__(self, flow, registry, context):
        self.flow = flow
        self.registry = registry
        self.context = context

    def start(self):
        print("Choose input type:")
        print("1. upload")
        print("2. camera")
        print("3. screenshot")
        
        choice = input("> ").strip()
        
        input_map = {
            "1": "upload",
            "2": "camera",
            "3": "screenshot"
        }
        
        action = input_map.get(choice)
        if not action:
            print("Invalid selection.")
            return "Invalid selection."
            
        print(self.flow.run(action))
        
        self.operation_stage()

    def operation_stage(self):
        if getattr(self.context, "image", None) is None:
            msg = "No image found. Please select input first."
            print(msg)
            return msg

        op_map = {
            "1": "grayscale",
            "2": "blur",
            "3": "brightness",
            "4": "contrast",
            "5": "edge",
            "6": "sharpen",
            "7": "sepia",
            "8": "invert",
            "9": "threshold",
            "10": "denoise",
            "11": "enhance",
            "12": "detect",
            "13": "describe",
            "14": "ocr",
            "15": "face",
            "16": "count"
        }

        while True:
            print("\n1. grayscale")
            print("2. blur")
            print("3. brightness")
            print("4. contrast")
            print("5. edge")
            print("6. sharpen")
            print("7. sepia")
            print("8. invert")
            print("9. threshold")
            print("10. denoise")
            print("11. enhance")
            print("12. detect")
            print("13. describe")
            print("14. ocr")
            print("15. face")
            print("16. count")

            op_choice = input("> ").strip()
            operation = op_map.get(op_choice)
            
            if not operation:
                print("Invalid selection.")
                continue

            # Verify in registry
            if not self.registry.get(operation):
                print(f"Operation '{operation}' not found in registry.")
                continue

            # Execute
            print(self.flow.run(operation))
            
            again = input("\nDo you want to apply another operation? (yes/no)\n> ").strip().lower()
            if again not in ["yes", "y"]:
                break
