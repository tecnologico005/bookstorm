#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MOBI Parser

Parses MOBI/Mobipocket format ebooks and extracts text content.
Uses Calibre's ebook-convert to convert MOBI to EPUB, then parses the EPUB.
"""

import tempfile
import shutil
import subprocess
import os
from pathlib import Path

from src.book import Book, Chapter
from src.epub_parser import EpubParser


class MobiParser:
    """Parser for MOBI/Mobipocket format ebooks"""

    def __init__(self):
        """Initialize MOBI parser"""
        self.tempDir = None
        self.epubParser = None

    def _find_ebook_convert(self):
        """Locate Calibre's ebook-convert binary."""
        overridePath = os.environ.get('BOOKSTORM_EBOOK_CONVERT') or os.environ.get('EBOOK_CONVERT')
        if overridePath:
            overrideCandidate = Path(overridePath).expanduser()
            if overrideCandidate.exists() and os.access(overrideCandidate, os.X_OK):
                return str(overrideCandidate)

        pathCandidate = shutil.which('ebook-convert')
        if pathCandidate:
            return pathCandidate

        commonCandidates = [
            Path('/opt/calibre/ebook-convert'),
            Path('/opt/calibre/bin/ebook-convert'),
            Path('/opt/bin/ebook-convert'),
        ]
        for binaryPath in commonCandidates:
            if binaryPath.exists() and os.access(binaryPath, os.X_OK):
                return str(binaryPath)

        return None

    def parse(self, mobiPath):
        """
        Parse MOBI file

        Args:
            mobiPath: Path to MOBI file

        Returns:
            Book object

        Raises:
            Exception: If parsing fails
        """
        mobiPath = Path(mobiPath)

        # Create temp directory for conversion
        self.tempDir = tempfile.mkdtemp(prefix='bookstorm_mobi_')
        tempPath = Path(self.tempDir)

        try:
            # Convert MOBI to EPUB using Calibre's ebook-convert
            epubPath = tempPath / f"{mobiPath.stem}.epub"

            convertBinary = self._find_ebook_convert()
            if not convertBinary:
                raise Exception(
                    "Calibre's ebook-convert tool is required for MOBI support, but it was not found in PATH or common /opt locations. "
                    "Set BOOKSTORM_EBOOK_CONVERT to the full path if needed."
                )

            convertCmd = [convertBinary, str(mobiPath), str(epubPath)]

            try:
                # Run ebook-convert with error capture
                result = subprocess.run(
                    convertCmd,
                    capture_output=True,  # pylint: disable=subprocess-run-check
                    text=True,
                    timeout=60
                )

                if result.returncode != 0:
                    raise Exception(f"ebook-convert failed: {result.stderr}")

            except FileNotFoundError:
                raise Exception("ebook-convert binary was found but could not be executed")
            except subprocess.TimeoutExpired:
                raise Exception("MOBI conversion timed out (>60 seconds)")

            # Verify the EPUB was created
            if not epubPath.exists():
                raise Exception("Failed to convert MOBI to EPUB")

            # Parse the converted EPUB
            self.epubParser = EpubParser()
            book = self.epubParser.parse(epubPath)

            # Set the original MOBI path as the book path
            book.path = mobiPath

            return book

        except Exception as e:
            raise Exception(f"Error parsing MOBI: {e}")

    def cleanup(self):
        """Clean up temporary files"""
        # Clean up EPUB parser
        if self.epubParser:
            self.epubParser.cleanup()

        # Clean up our temp directory
        if self.tempDir and Path(self.tempDir).exists():
            try:
                shutil.rmtree(self.tempDir)
            except Exception as e:
                print(f"Warning: Could not remove temp directory: {e}")
