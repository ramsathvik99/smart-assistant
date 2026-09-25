"""
Document Tools Module for Nova Smart Assistant.
Provides document generation for Microsoft Word (.docx), PDF (.pdf), and Excel (.xlsx).
"""

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

__all__ = [
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
    'build_presentation'
]
