class InputController:
    def __init__(self, registry):
        self.registry = registry

    def execute(self, context):
        print("Choose input type:\n")
        print("1. upload")
        print("2. camera")
        print("3. screenshot\n")
        
        input_map = {
            "1": "upload",
            "2": "camera",
            "3": "screenshot",
            "upload": "upload",
            "camera": "camera",
            "screenshot": "screenshot"
        }

        while True:
            choice = input("Enter choice: ").strip().lower()
            action = input_map.get(choice)

            if action:
                break

            print("Invalid input. Please choose 1/2/3 or upload/camera/screenshot.")
            
        print(f">>> Selected input module: {action}")
        module = self.registry.get(action)
        
        if not module:
            return f"Module '{action}' not found in registry."

        return module().execute(context)
