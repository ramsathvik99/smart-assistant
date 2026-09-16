import os
import re
import subprocess
from instance.config import settings
from extensions.llm_engine import LLMEngine
from .file_handler import save_writing

# Shared engine instance
_engine = LLMEngine()


def generate_writing(writing_type: str, topic: str) -> str:
    """Generates high-quality structured writing responses using the central LLMEngine.

    BEFORE: direct OpenAI → Groq → Gemini chain
    AFTER:  LLMEngine.get_completion() → configured provider → fallback
    """

    system_prompt = """
You are a professional writer.

Write a well-structured response with:

- A clear title at the top
- 3 to 5 meaningful subheadings
- A paragraph under each subheading
- A short conclusion at the end

Formatting rules:
- Do NOT use symbols like *, -, or markdown
- Use plain text only
- Subheadings should be written as normal lines (no symbols)
- Maintain a natural and readable tone
"""

    user_prompt = f"Write a {writing_type} about {topic}"

    content = _engine.get_completion(
        prompt=user_prompt,
        system_prompt=system_prompt,
        max_tokens=1000
    )

    if content is None:
        return "Sorry, I could not generate the response."

    
    # Clean the content
    cleaned_content = clean_writing_content(content, topic)
    
    # Extract and clean the topic for filename
    cleaned_topic = extract_topic_from_input(topic)
    formatted_topic = format_topic_for_filename(cleaned_topic)
    
    # Create filename and save to Downloads
    filename = f"{formatted_topic}.txt"
    downloads_path = os.path.join(os.path.expanduser("~"), "Downloads")
    file_path = os.path.join(downloads_path, filename)
    
    try:
        # Write content to file with UTF-8 encoding
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(cleaned_content)
        
        print(f"[Writer] Saved to: {file_path}")
        
        # Automatically open the file using Notepad
        try:
            subprocess.Popen(["notepad.exe", file_path])
            print(f"[Writer] Opened in Notepad: {file_path}")
        except Exception as e:
            print(f"[Writer] Could not open in Notepad: {e}")
        
        # Return confirmation message instead of raw text
        return f"I have written the {writing_type} and saved it in your Downloads folder."
        
    except Exception as e:
        print(f"[Writer ERROR] Failed to save writing: {e}")
        return f"Sorry, I could not save the {writing_type}."

def clean_writing_content(content: str, topic: str) -> str:
    """Cleans the AI output by removing markdown while enforcing structural integrity."""
    if not content:
        return ""
        
    # Remove markdown bold/italic/symbols
    content = content.replace("**", "").replace("*", "")
    
    # Split into lines and remove markdown bullet symbols
    lines = content.split('\n')
    cleaned_lines = []
    for line in lines:
        # Remove symbols like -, +, * at the start of lines
        cleaned_line = re.sub(r'^\s*[-*+]\s+', '', line).strip()
        if cleaned_line:
            cleaned_lines.append(cleaned_line)
        else:
            cleaned_lines.append("") # Keep empty lines for spacing
            
    # 1. Ensure first line is a Title
    title = topic.title()
    # Find first non-empty line
    first_line_idx = 0
    while first_line_idx < len(cleaned_lines) and not cleaned_lines[first_line_idx]:
        first_line_idx += 1
        
    if first_line_idx < len(cleaned_lines):
        if title.lower() not in cleaned_lines[first_line_idx].lower():
            cleaned_lines.insert(first_line_idx, title)
            cleaned_lines.insert(first_line_idx + 1, "")
    else:
        cleaned_lines = [title, ""]
        
    # 2. Structural Validation - Check for subheadings
    # Subheadings are typically short lines followed by a paragraph
    subheading_count = 0
    for i in range(1, len(cleaned_lines)):
        line = cleaned_lines[i]
        if 1 < len(line) < 60 and not line.endswith('.') and not line.endswith('?'):
            subheading_count += 1
            
    # If AI output is poor (less than 3 headings), we insert generic one if there's enough content
    if subheading_count < 3:
        paragraphs = [i for i, l in enumerate(cleaned_lines) if len(l) > 150]
        if len(paragraphs) >= 3:
            cleaned_lines.insert(paragraphs[0], "Introduction")
            cleaned_lines.insert(paragraphs[1] + 1, "Key Insights")
            cleaned_lines.insert(paragraphs[2] + 2, "Detailed Explanation")
            if len(paragraphs) > 3:
                cleaned_lines.insert(paragraphs[-1] + 3, "Conclusion")
            elif "Conclusion" not in cleaned_lines[-3:]:
                cleaned_lines.append("")
                cleaned_lines.append("Conclusion")
                cleaned_lines.append("The goal of this discussion is to provide a comprehensive understanding of the topic.")

    return '\n'.join(cleaned_lines).strip()

def handle_write_command(command: str) -> str:
    """
    Main controller for writing tasks. Adapts style and structure to the command.
    """
    topic = extract_topic(command)
    
    print(f"[Writer] Generating structured response for: {command}")
    content = generate_writing(command, topic)
    
    if "Sorry, I could not generate" in content:
        return content
        
    file_path = save_writing(topic, content)
    if file_path:
        # 5. Return user success message
        return "I’ve written that for you."
    else:
        return "Failed to save the writing."

def extract_topic(command: str) -> str:
    """ Extracts the core topic from the command for naming purposes. """
    command_lower = command.lower().strip()
    
    # Define prefixes to remove (ordered by length longest to shortest)
    prefixes = [
        "write an essay on ", "write a story about ", "write notes on ",
        "write a letter to ", "write something about ", "write about ",
        "write an ", "write a ", "write some ", "write ",
        "tell me about ", "explain ", "give me information on ", 
        "give information on ", "information on "
    ]
    
    topic = command_lower
    for prefix in prefixes:
        if topic.startswith(prefix):
            topic = command[len(prefix):].strip() # Use original case for the topic
            return topic
            
    return command.strip()

def extract_topic_from_input(topic: str) -> str:
    """Extract and clean the topic from the user input."""
    if not topic:
        return "General"
    
    # Remove common extra words and clean up
    topic = topic.strip()
    
    # Remove articles and common prepositions
    words_to_remove = ["a", "an", "the", "about", "on", "in", "for", "of", "with", "by"]
    topic_words = topic.split()
    cleaned_words = [word for word in topic_words if word.lower() not in words_to_remove]
    
    # Join back and limit length
    cleaned_topic = " ".join(cleaned_words)
    
    # Limit to reasonable length for filename
    if len(cleaned_topic) > 30:
        cleaned_topic = cleaned_topic[:30].rstrip()
    
    return cleaned_topic.strip() if cleaned_topic.strip() else "General"

def format_topic_for_filename(topic: str) -> str:
    """Format the topic properly for filename (e.g., "ai" → "AI")."""
    if not topic:
        return "Writing"
    
    # Capitalize each word
    formatted = " ".join(word.capitalize() for word in topic.split())
    
    # Remove any characters that are invalid in filenames
    import re
    formatted = re.sub(r'[<>:"/\\|?*]', '', formatted)
    
    # Replace spaces with nothing for cleaner filename
    formatted = formatted.replace(" ", "")
    
    return formatted if formatted else "Writing"
