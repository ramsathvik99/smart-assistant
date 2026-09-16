def build_prompt(content_type: str, topic: str) -> str:
    """ Generate structured prompts based on content type and topic """
    content_type = content_type.lower()
    
    if content_type == 'essay':
        return f"Write a comprehensive essay on '{topic}'. Ensure it has a clear title, a captivating introduction, detailed body paragraphs, and a strong conclusion."
    elif content_type == 'story':
        return f"Write a creative and engaging story about '{topic}'. Include interesting characters, a clear narrative flow, and a defined ending."
    elif content_type == 'notes':
        return f"Provide structured, detailed notes on '{topic}'. Use bullet points for key concepts, definitions, and important details."
    elif content_type == 'letter':
        return f"Write a formal letter regarding '{topic}'. Use proper formal letter formatting with clear paragraphs and a professional closing."
    elif content_type == 'speech':
        return f"Write an engaging speech about '{topic}'. Structure it to captivate the audience with a strong opening, clear points, and a powerful conclusion."
    elif content_type == 'summary':
        return f"Provide a brief, comprehensive summary of '{topic}'."
    elif content_type == 'paragraph':
        return f"Write a single, well-structured paragraph about '{topic}'."
    else:
        return f"Write detailed content about '{topic}'."
