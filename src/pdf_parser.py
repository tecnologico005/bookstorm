"""PDF parser for BookStorm - extracts text from PDF files."""

import re
from pathlib import Path
from pypdf import PdfReader
from src.book import Book, Chapter


def clean_hyphenated_text(text):
    """Clean up hyphenated line breaks in text.

    Converts 'word-\nword' to 'word' to fix PDF line wrapping.
    """
    # Remove hyphens at end of lines followed by continuation
    text = re.sub(r'-\s*\n\s*', '', text)
    return text


def split_into_paragraphs(text):
    """Split text into paragraphs using double newlines.

    Falls back to single newlines if no double newlines found.
    """
    # Try splitting on double newlines first
    paragraphs = re.split(r'\n\s*\n', text)

    # Clean up whitespace
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    # If we got very few paragraphs, fall back to single newlines
    if len(paragraphs) < 3:
        paragraphs = [p.strip() for p in text.split('\n') if p.strip()]

    return paragraphs


class PdfParser:
    """Parser for PDF files"""

    def __init__(self):
        pass

    def parse(self, pdfPath):
        """Parse a PDF file and return Book object.

        Args:
            pdfPath: Path to the PDF file

        Returns:
            Book object with each page as a chapter
        """
        pdfPath = Path(pdfPath)

        if not pdfPath.exists():
            raise FileNotFoundError(f"PDF file not found: {pdfPath}")

        reader = PdfReader(pdfPath)

        # Use filename as book title (without extension)
        bookTitle = pdfPath.stem
        book = Book(title=bookTitle)

        for pageNum, page in enumerate(reader.pages):
            # Create chapter for this page
            chapterTitle = f"Page {pageNum + 1}"
            chapter = Chapter(title=chapterTitle)

            # Extract text from page
            pageText = page.extract_text()

            if not pageText or not pageText.strip():
                # Empty page, add placeholder
                chapter.add_paragraph(f"Page {pageNum + 1} is empty or contains no extractable text.")
            else:
                # Clean up hyphenated line breaks
                pageText = clean_hyphenated_text(pageText)

                # Split into paragraphs
                paragraphs = split_into_paragraphs(pageText)

                if not paragraphs:
                    chapter.add_paragraph(f"Page {pageNum + 1} contains no readable text.")
                else:
                    for paragraph in paragraphs:
                        chapter.add_paragraph(paragraph)

            book.add_chapter(chapter)

        return book

    def cleanup(self):
        """Cleanup any resources (no-op for PDF parser)"""
        pass

