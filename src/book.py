#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Book Data Structures

Common book and chapter classes used by all parsers.
"""


class Book:
    """Represents a parsed book with navigation and content"""

    def __init__(self, title="Untitled", author="Unknown"):
        """
        Initialize book

        Args:
            title: Book title
            author: Book author
        """
        self.title = title
        self.author = author
        self.chapters = []  # List of Chapter objects

    def add_chapter(self, chapter):
        """Add a chapter to the book"""
        self.chapters.append(chapter)

    def get_chapter(self, index):
        """Get chapter by index"""
        if 0 <= index < len(self.chapters):
            return self.chapters[index]
        return None

    def get_total_chapters(self):
        """Get total number of chapters"""
        return len(self.chapters)


class Chapter:
    """Represents a single chapter with paragraphs"""

    def __init__(self, title="Untitled"):
        """
        Initialize chapter

        Args:
            title: Chapter title
        """
        self.title = title
        self.paragraphs = []  # List of paragraph strings

    def add_paragraph(self, text):
        """Add a paragraph to the chapter"""
        if text and text.strip():
            self.paragraphs.append(text.strip())

    def get_paragraph(self, index):
        """Get paragraph by index"""
        if 0 <= index < len(self.paragraphs):
            return self.paragraphs[index]
        return None

    def get_total_paragraphs(self):
        """Get total number of paragraphs"""
        return len(self.paragraphs)
