# code_controller.py
import os
import sys
from typing import Optional

# Ensure project root path is in sys
nova_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if nova_root not in sys.path:
    sys.path.insert(0, nova_root)

from .main import process_request
from .generator import generate_code

class CodeController:
    """Controller for code generation operations"""
    
    def __init__(self, llm_engine=None):
        self.llm_engine = llm_engine
    
    def generate_and_process(self, prompt: str) -> str:
        """Generate code and process it"""
        try:
            # Generate code using the main process_request function
            result = process_request(prompt)
            return result
        except Exception as e:
            print(f"[Code Controller] Error: {e}")
            return f"Sorry, I encountered an error: {e}"
    
    def open_vscode(self, file_path: str):
        """Open file in VS Code"""
        try:
            import os
            os.system(f'code "{file_path}"')
            print(f"[Code Controller] Opened {file_path} in VS Code")
        except Exception as e:
            print(f"[Code Controller] Error opening VS Code: {e}")
    
    def save_code_to_file(self, code: str, filename: str, topic: str) -> str:
        """Save code to output/code/ directory"""
        try:
            # Create output directory if it doesn't exist
            output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "output", "code")
            os.makedirs(output_dir, exist_ok=True)
            
            # Create filename based on topic
            safe_topic = "".join(c for c in topic if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_topic = safe_topic.replace(' ', '_').lower()
            if not filename.endswith('.py'):
                filename = f"{safe_topic}.py"
            
            file_path = os.path.join(output_dir, filename)
            
            # Save the code
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(code)
            
            print(f"[Code Controller] Saved code to: {file_path}")
            return file_path
        except Exception as e:
            print(f"[Code Controller] Error saving file: {e}")
            return None

def get_controller(llm_engine=None) -> CodeController:
    """Get code controller instance"""
    return CodeController(llm_engine)
