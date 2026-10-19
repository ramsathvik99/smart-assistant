"""
Document Tools Module for Smart Assistant.
Provides enterprise-grade document generation for Microsoft Word (.docx), PDF (.pdf),
Excel (.xlsx), PowerPoint (.pptx), full file conversion, real visual charts/diagrams,
document reading, editing, summarization, safe file operations, and quality validation.
"""

# Existing Builders (Strictly Preserved)
from .docx_builder import create_docx_document, create_docx_document as build_docx_document
from .pdf_builder import (
    create_pdf_document, 
    create_pdf_document as build_pdf_document,
    extract_pdf_text, 
    get_pdf_info, 
    split_pdf, 
    merge_pdfs
)
from .excel_builder import create_excel_spreadsheet, create_excel_spreadsheet as build_excel_spreadsheet
from .presentation_builder import create_presentation, create_presentation as build_presentation

# Content Construction & Specification Helpers (Strictly Preserved)
from .content_helper import (
    extract_topic_from_query,
    build_document_content,
    build_presentation_slides,
    build_spreadsheet_spec,
    ArtifactContentSpec,
    construct_content_spec,
    verify_artifact_quality,
    refine_artifact
)
from instance.config import get_branding_author

# New Capabilities: Visual Builder
from .visual_builder import (
    create_chart,
    create_process_flowchart,
    create_neural_network_diagram,
    create_architecture_diagram,
    VisualAssetBuilder
)

# New Capabilities: LLM-Driven Substantive Content Generation
from .llm_content_generator import (
    generate_substantive_document_content,
    generate_substantive_presentation_content,
    generate_substantive_spreadsheet_content
)

# New Capabilities: Conversion System
from .conversion_registry import (
    ConversionRegistry,
    convert_document,
    convert_docx_to_pdf,
    convert_pdf_to_docx,
    convert_docx_to_markdown,
    convert_markdown_to_docx,
    convert_markdown_to_pdf,
    convert_html_to_markdown,
    convert_html_to_pdf,
    convert_xlsx_to_csv,
    convert_csv_to_xlsx,
    convert_xlsx_to_pdf,
    convert_images_to_pdf,
    convert_image_format,
    convert_json_yaml,
    convert_pptx_to_pdf
)

# New Capabilities: Reading, Summarizing, and Section Editing
from .document_editor import (
    read_document_content,
    read_document_content as read_document,
    summarize_existing_document,
    summarize_existing_document as summarize_document,
    edit_document_section,
    edit_document_section as update_document_section
)

# New Capabilities: Quality Validation Pipeline
from .validator import validate_document_artifact

# New Capabilities: Safe File Discovery & Operations
from .safe_file_ops import (
    list_assistant_documents,
    safe_delete_document,
    sanitize_filename,
    SafeFileOps
)

__all__ = [
    # Existing
    'create_docx_document',
    'build_docx_document',
    'create_pdf_document',
    'build_pdf_document',
    'extract_pdf_text',
    'get_pdf_info',
    'split_pdf',
    'merge_pdfs',
    'create_excel_spreadsheet',
    'build_excel_spreadsheet',
    'create_presentation',
    'build_presentation',
    'extract_topic_from_query',
    'build_document_content',
    'build_presentation_slides',
    'build_spreadsheet_spec',
    'ArtifactContentSpec',
    'construct_content_spec',
    'verify_artifact_quality',
    'get_branding_author',
    'refine_artifact',

    # Visuals
    'create_chart',
    'create_process_flowchart',
    'create_neural_network_diagram',
    'create_architecture_diagram',
    'VisualAssetBuilder',

    # LLM Generation
    'generate_substantive_document_content',
    'generate_substantive_presentation_content',
    'generate_substantive_spreadsheet_content',

    # Conversions
    'ConversionRegistry',
    'convert_document',
    'convert_docx_to_pdf',
    'convert_pdf_to_docx',
    'convert_docx_to_markdown',
    'convert_markdown_to_docx',
    'convert_markdown_to_pdf',
    'convert_html_to_markdown',
    'convert_html_to_pdf',
    'convert_xlsx_to_csv',
    'convert_csv_to_xlsx',
    'convert_xlsx_to_pdf',
    'convert_images_to_pdf',
    'convert_image_format',
    'convert_json_yaml',
    'convert_pptx_to_pdf',

    # Reading & Editing
    'read_document_content',
    'read_document',
    'summarize_existing_document',
    'summarize_document',
    'edit_document_section',
    'update_document_section',

    # Validation & File Ops
    'validate_document_artifact',
    'list_assistant_documents',
    'safe_delete_document',
    'sanitize_filename',
    'SafeFileOps'
]

