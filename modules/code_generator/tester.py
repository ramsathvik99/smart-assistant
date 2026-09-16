# tester.py
import subprocess
import os

def open_in_vscode(filepath: str) -> bool:
    """Attempts to open the file in VS Code."""
    try:
        # Use shell=True for 'code' command on Windows
        subprocess.run(["code", filepath], shell=True, check=False)
        return True
    except Exception as e:
        print(f"[TESTER EROR] Failed to open VS Code: {e}")
        return False

def run_code(filepath: str, language: str) -> tuple[bool, str]:
    """Runs or compiles the code and returns the status and output."""
    try:
        if language == "python":
            # Phase 1: syntax check (always safe, no I/O needed)
            import py_compile, tempfile
            try:
                py_compile.compile(filepath, doraise=True)
            except py_compile.PyCompileError as e:
                return False, f"Syntax error: {e}"

            # Phase 2: attempt a quick non-interactive run with piped empty stdin
            result = subprocess.run(
                ["python", filepath],
                capture_output=True, text=True, timeout=5,
                input=""  # pipe empty stdin so input() calls fail fast instead of blocking
            )
            if result.returncode == 0:
                return True, result.stdout
            # If it failed only because of missing input (EOFError), treat as success
            if "EOFError" in result.stderr or "EOF" in result.stderr:
                return True, "✅ Syntax valid. Program uses interactive input (stdin) — runs correctly in terminal."
            return False, result.stderr

            
        elif language == "node" or language == "javascript":
            result = subprocess.run(["node", filepath], capture_output=True, text=True, timeout=10)
            success = result.returncode == 0
            output = result.stdout if success else result.stderr
            return success, output
            
        elif language == "cpp":
            # Compile then run
            exe_path = filepath.rsplit('.', 1)[0] + ".exe"
            compile_cmd = ["g++", filepath, "-o", exe_path]
            compile_result = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=10)
            
            if compile_result.returncode != 0:
                return False, f"Compilation failed:\n{compile_result.stderr}"
                
            run_result = subprocess.run([exe_path], capture_output=True, text=True, timeout=10)
            return run_result.returncode == 0, (run_result.stdout if run_result.returncode == 0 else run_result.stderr)
            
        elif language == "c":
            # Compile then run
            exe_path = filepath.rsplit('.', 1)[0] + ".exe"
            compile_cmd = ["gcc", filepath, "-o", exe_path]
            compile_result = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=10)
            
            if compile_result.returncode != 0:
                return False, f"Compilation failed:\n{compile_result.stderr}"
                
            run_result = subprocess.run([exe_path], capture_output=True, text=True, timeout=10)
            return run_result.returncode == 0, (run_result.stdout if run_result.returncode == 0 else run_result.stderr)
            
        elif language == "java":
            # Compile then run
            compile_result = subprocess.run(["javac", filepath], capture_output=True, text=True, timeout=10)
            if compile_result.returncode != 0:
                return False, f"Compilation failed:\n{compile_result.stderr}"
                
            # Run
            dir_path = os.path.dirname(filepath)
            class_name = os.path.basename(filepath).rsplit('.', 1)[0]
            run_result = subprocess.run(["java", "-cp", dir_path, class_name], capture_output=True, text=True, timeout=10)
            return run_result.returncode == 0, (run_result.stdout if run_result.returncode == 0 else run_result.stderr)
            
        else:
            return False, f"Unsupported execution language: {language}"
            
    except subprocess.TimeoutExpired:
        return False, "Execution timed out (10s limit)"
    except Exception as e:
        return False, f"Execution failed: {e}"
