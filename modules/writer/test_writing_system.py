import os
import sys

# Ensure project root is in path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from modules.writer.writer_engine import handle_write_command

def test_writing_system():
    commands = [
        "write an essay on women rights",
        "tell me about artificial intelligence",
        "explain about the space exploration"
    ]
    
    print("--- Starting Dynamic Writing System Verification ---")
    
    for cmd in commands:
        print(f"\n[Test] Command: {cmd}")
        result = handle_write_command(cmd)
        print(f"[Test] Result: {result}")
        
        # Verify result message
        if "Writing saved to:" in result:
            file_path = result.split("Writing saved to: ")[1].strip()
            if os.path.exists(file_path):
                print(f"[Test] SUCCESS: File exists at {file_path}")
                # Check some content
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    print(f"[Test] Content Length: {len(content)} characters")
                    
                    # Verify no markdown symbols
                    if "*" in content or "**" in content:
                        print("[Test] FAILURE: Markdown symbols found in content")
                    else:
                        print("[Test] SUCCESS: No markdown symbols found")
                        
                    if len(content) > 100:
                        print("[Test] SUCCESS: Content generated successfully")
                    else:
                        print("[Test] FAILURE: Content too short")
            else:
                print(f"[Test] FAILURE: File NOT found at {file_path}")
        else:
            print(f"[Test] FAILURE: Unexpected result message: {result}")

    print("\n--- Verification Complete ---")

if __name__ == "__main__":
    test_writing_system()
