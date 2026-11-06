"""TXT parser for BookStorm - extracts text from plain text files."""

import re
from pathlib import Path
from src.book import Book, Chapter


def detect_chapter_breaks(text):
    """Detect chapter breaks in text using various heuristics.

    Returns:
        list of tuples: [(chapterTitle, chapterText), ...]
    """
    chapters = []

    # Pattern 1: Common chapter headings (case insensitive)
    # Matches: "Chapter 1", "Chapter One", "CHAPTER 1:", etc.
    chapterPattern = re.compile(
        r'^(Chapter\s+[IVXLCDM\d]+[:\-\s]*.*)$',
        re.MULTILINE | re.IGNORECASE
    )

    # Pattern 2: Markdown-style headings
    # Matches: "# Chapter Title", "## Section Title"
    markdownPattern = re.compile(
        r'^(#{1,3}\s+.+)$',
        re.MULTILINE
    )

    # Pattern 3: Page breaks (form feed character)
    pageBreakPattern = re.compile(r'\f+')

    # Pattern 4: Multiple blank lines (3+)
    multiBlankPattern = re.compile(r'\n\s*\n\s*\n\s*\n+')

    # Try chapter headings first
    chapterMatches = list(chapterPattern.finditer(text))
    if len(chapterMatches) >= 2:
        # Found multiple chapter markers
        for i, match in enumerate(chapterMatches):
            title = match.group(1).strip()
            start = match.start()
            end = chapterMatches[i + 1].start() if i + 1 < len(chapterMatches) else len(text)
            chapterText = text[start:end].strip()
            # Remove title from chapter text
            chapterText = chapterText[len(match.group(0)):].strip()
            chapters.append((title, chapterText))
        return chapters

    # Try markdown headings
    markdownMatches = list(markdownPattern.finditer(text))
    if len(markdownMatches) >= 2:
        for i, match in enumerate(markdownMatches):
            title = match.group(1).strip()
            # Remove leading # symbols for title
            title = re.sub(r'^#+\s*', '', title)
            start = match.start()
            end = markdownMatches[i + 1].start() if i + 1 < len(markdownMatches) else len(text)
            chapterText = text[start:end].strip()
            chapterText = chapterText[len(match.group(0)):].strip()
            chapters.append((title, chapterText))
        return chapters

    # Try page breaks
    pageBreakParts = pageBreakPattern.split(text)
    if len(pageBreakParts) >= 2:
        for i, part in enumerate(pageBreakParts):
            if part.strip():
                title = f"Section {i + 1}"
                chapters.append((title, part.strip()))
        if chapters:
            return chapters

    # Try multiple blank lines as separators
    multiBlankParts = multiBlankPattern.split(text)
    if len(multiBlankParts) >= 3:  # At least 3 sections
        for i, part in enumerate(multiBlankParts):
            if part.strip():
                # Try to extract a title from first line
                lines = part.strip().split('\n', 1)
                if len(lines) > 1 and len(lines[0]) < 100:
                    # First line might be a title
                    title = lines[0].strip()
                    content = lines[1].strip() if len(lines) > 1 else ""
                else:
                    title = f"Section {i + 1}"
                    content = part.strip()
                chapters.append((title, content))
        if chapters:
            return chapters

    # No clear chapter breaks found, treat as single chapter
    return [("Full Text", text.strip())]


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


class TxtParser:
    """Parser for plain text files"""

    def __init__(self):
        pass

    def parse(self, txtPath):
        """Parse a TXT file and return Book object.

        Args:
            txtPath: Path to the TXT file

        Returns:
            Book object with detected chapters or single chapter
        """
        txtPath = Path(txtPath)

        if not txtPath.exists():
            raise FileNotFoundError(f"TXT file not found: {txtPath}")

        # Read file with encoding detection
        try:
            with open(txtPath, 'r', encoding='utf-8') as f:
                text = f.read()
        except UnicodeDecodeError:
            # Try with latin-1 as fallback
            with open(txtPath, 'r', encoding='latin-1') as f:
                text = f.read()

        # Use filename as book title
        bookTitle = txtPath.stem
        book = Book(title=bookTitle)

        # Detect chapters
        detectedChapters = detect_chapter_breaks(text)

        # Process each chapter
        for chapterTitle, chapterText in detectedChapters:
            chapter = Chapter(title=chapterTitle)

            # Split into paragraphs
            paragraphs = split_into_paragraphs(chapterText)

            if not paragraphs:
                chapter.add_paragraph("(Empty chapter)")
            else:
                for paragraph in paragraphs:
                    chapter.add_paragraph(paragraph)

            book.add_chapter(chapter)

        return book

    def cleanup(self):
        """Cleanup any resources (no-op for TXT parser)"""
        pass
