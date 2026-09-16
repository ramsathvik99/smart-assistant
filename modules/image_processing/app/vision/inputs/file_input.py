from tkinter import Tk, filedialog

class FileInput:
    def execute(self, context):
        try:
            root = Tk()
            root.withdraw()
            root.attributes('-topmost', True)

            try:
                from instance.config import settings as _cfg
                _asst = _cfg.get_assistant_name() or "Assistant"
            except Exception:
                _asst = "Assistant"

            file_path = filedialog.askopenfilename(
                title=f"{_asst} — Select an Image File",
                filetypes=[
                    ("Image files", "*.jpg *.jpeg *.png *.bmp *.tiff *.tif"),
                    ("JPEG files", "*.jpg *.jpeg"),
                    ("PNG files", "*.png"),
                    ("All files", "*.*")
                ]
            )

            root.destroy()
            
            if file_path:
                import cv2
                image = cv2.imread(file_path)
                if image is None:
                    return f"Error: Could not read image file: {file_path}"
                
                context.image = image
                return "Image loaded into memory. What do you want to do next?"
            else:
                return "No file selected."
        except Exception as e:
            return f"File dialog error: {e}"
