#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DAISY Book Parser

Handles parsing of DAISY 2.02 and DAISY 3 book formats.
Extracts structure and content for text-to-speech playback.
"""

import zipfile
import tempfile
import shutil
from pathlib import Path
from bs4 import BeautifulSoup
import re
from src.book import Book, Chapter
from src.daisy_audio_parser import DaisyAudioParser, is_daisy_audio_book


class DaisyParser:
    """Parser for DAISY format books"""

    def __init__(self):
        self.tempDir = None

    def parse(self, daisyPath):
        """
        Parse a DAISY book (zip file)

        Args:
            daisyPath: Path to DAISY zip file

        Returns:
            Book object (or AudioBook if audio-only)
        """
        daisyPath = Path(daisyPath)

        if not daisyPath.exists():
            raise FileNotFoundError(f"DAISY file not found: {daisyPath}")

        # Check if this is an audio-only DAISY book
        if is_daisy_audio_book(daisyPath):
            # Delegate to audio parser
            audioParser = DaisyAudioParser()
            return audioParser.parse(daisyPath)

        # Text-based DAISY book - continue with normal parsing
        # Extract zip to temp directory
        self.tempDir = tempfile.mkdtemp(prefix="daisy_")
        tempPath = Path(self.tempDir)

        try:
            with zipfile.ZipFile(daisyPath, 'r') as zipRef:
                zipRef.extractall(tempPath)

            # Find the actual DAISY directory (might be in a subdirectory)
            daisyDir = self._find_daisy_directory(tempPath)
            if not daisyDir:
                raise ValueError("Unknown DAISY format: no ncc.html or navigation.ncx found")

            # Detect DAISY version and parse accordingly
            if (daisyDir / "ncc.html").exists():
                book = self._parse_daisy2(daisyDir)
            elif (daisyDir / "navigation.ncx").exists() or list(daisyDir.glob("*.ncx")):
                book = self._parse_daisy3(daisyDir)
            else:
                raise ValueError("Unknown DAISY format: no ncc.html or navigation.ncx found")

            # Cleanup before returning
            self.cleanup()
            return book

        except Exception as e:
            # Ensure cleanup on error
            self.cleanup()
            raise e

    def _find_daisy_directory(self, basePath):
        """
        Find the actual DAISY directory within extracted files.
        Some DAISY books are packaged with a subdirectory inside the zip.

        Args:
            basePath: Path to extracted directory

        Returns:
            Path to directory containing ncc.html or navigation.ncx, or None if not found
        """
        # Check if ncc.html or .ncx is at root level
        if (basePath / "ncc.html").exists():
            return basePath
        if (basePath / "navigation.ncx").exists() or list(basePath.glob("*.ncx")):
            return basePath

        # Check subdirectories (only one level deep)
        for item in basePath.iterdir():
            if item.is_dir():
                if (item / "ncc.html").exists():
                    return item
                if (item / "navigation.ncx").exists() or list(item.glob("*.ncx")):
                    return item

        return None

    def _parse_daisy2(self, basePath):
        """Parse DAISY 2.02 format (NCC.html based)"""
        nccPath = basePath / "ncc.html"

        with open(nccPath, 'r', encoding='utf-8', errors='ignore') as f:
            soup = BeautifulSoup(f.read(), 'html.parser')

        # Get title
        titleTag = soup.find('title')
        bookTitle = titleTag.get_text().strip() if titleTag else "Unknown Title"

        # Find all headings (h1-h6) which represent navigation points
        headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])

        chapters = []
        for heading in headings:
            # Get chapter title
            chapterTitle = heading.get_text().strip()

            # Find linked content file
            link = heading.find('a')
            if not link or not link.get('href'):
                continue

            contentHref = link.get('href')
            contentPath = basePath / contentHref.split('#')[0]

            if contentPath.exists():
                paragraphs = self._extract_paragraphs(contentPath)
                if paragraphs:
                    chapter = Chapter(chapterTitle)
                    chapter.paragraphs = paragraphs
                    chapters.append(chapter)

        book = Book(bookTitle)
        for chapter in chapters:
            book.add_chapter(chapter)
        return book

    def _parse_daisy3(self, basePath):
        """Parse DAISY 3 format (NCX based)"""
        # Find NCX file for title
        ncxFiles = list(basePath.glob("*.ncx"))
        if not ncxFiles:
            ncxFiles = [basePath / "navigation.ncx"]

        ncxPath = ncxFiles[0]

        with open(ncxPath, 'r', encoding='utf-8', errors='ignore') as f:
            soup = BeautifulSoup(f.read(), features='xml')

        # Get title
        titleTag = soup.find('docTitle')
        if titleTag:
            textTag = titleTag.find('text')
            bookTitle = textTag.get_text().strip() if textTag else "Unknown Title"
        else:
            bookTitle = "Unknown Title"

        # Find DTBook XML file (main content)
        dtbookFiles = list(basePath.glob("*.xml"))
        # Exclude navigation.ncx if it was named .xml
        dtbookFiles = [f for f in dtbookFiles if not f.name.endswith('.ncx')]

        if dtbookFiles:
            # Try to parse DTBook using NCX navigation structure first
            chapters = self._parse_dtbook_with_ncx(dtbookFiles[0], basePath, soup)

            if not chapters:
                # Fallback: Parse DTBook XML directly for content
                chapters = self._parse_dtbook(dtbookFiles[0])
        else:
            # Fallback to old method for HTML-based DAISY
            chapters = self._parse_daisy3_html(basePath, soup)

        book = Book(bookTitle)
        for chapter in chapters:
            book.add_chapter(chapter)
        return book

    def _parse_daisy3_html(self, basePath, ncxSoup):
        """Parse DAISY 3 with HTML content files (fallback)"""
        navPoints = ncxSoup.find_all('navPoint')

        chapters = []
        for navPoint in navPoints:
            # Get chapter title
            navLabel = navPoint.find('navLabel')
            if navLabel:
                textTag = navLabel.find('text')
                chapterTitle = textTag.get_text().strip() if textTag else "Untitled Chapter"
            else:
                chapterTitle = "Untitled Chapter"

            # Find content source
            content = navPoint.find('content')
            if not content or not content.get('src'):
                continue

            contentSrc = content.get('src')
            contentPath = basePath / contentSrc.split('#')[0]

            if contentPath.exists():
                paragraphs = self._extract_paragraphs(contentPath)
                if paragraphs:
                    chapter = Chapter(chapterTitle)
                    chapter.paragraphs = paragraphs
                    chapters.append(chapter)

        return chapters

    def _parse_dtbook_with_ncx(self, dtbookPath, basePath, ncxSoup):
        """
        Parse DTBook using NCX navigation structure

        Args:
            dtbookPath: Path to DTBook XML file
            basePath: Base directory path
            ncxSoup: BeautifulSoup object of parsed NCX

        Returns:
            List of Chapter objects or None if parsing fails
        """
        try:
            # Load DTBook content
            with open(dtbookPath, 'r', encoding='utf-8', errors='ignore') as f:
                dtbookSoup = BeautifulSoup(f.read(), features='xml')

            # Find all top-level navPoints (chapters)
            navMap = ncxSoup.find('navMap')
            if not navMap:
                return None

            chapters = []
            for navPoint in navMap.find_all('navPoint', recursive=False):
                # Get chapter title
                navLabel = navPoint.find('navLabel')
                if navLabel:
                    textTag = navLabel.find('text')
                    chapterTitle = textTag.get_text().strip() if textTag else "Untitled"
                else:
                    chapterTitle = "Untitled"

                # Get content source
                content = navPoint.find('content')
                if not content or not content.get('src'):
                    continue

                contentSrc = content.get('src')

                # Extract fragment identifier (anchor)
                parts = contentSrc.split('#')
                anchor = parts[1] if len(parts) > 1 else None

                if not anchor:
                    continue

                # Find the element in DTBook by ID
                section = dtbookSoup.find(id=anchor)
                if not section:
                    continue

                # Extract paragraphs from this section
                paragraphs = []
                for p in section.find_all('p'):
                    text = p.get_text().strip()
                    text = re.sub(r'\s+', ' ', text)
                    if text:
                        paragraphs.append(text)

                if paragraphs:
                    chapter = Chapter(chapterTitle)
                    chapter.paragraphs = paragraphs
                    chapters.append(chapter)

            return chapters if chapters else None

        except Exception as e:
            print(f"Error parsing DTBook with NCX: {e}")
            return None

    def _parse_dtbook(self, dtbookPath):
        """Parse DTBook XML format"""
        with open(dtbookPath, 'r', encoding='utf-8', errors='ignore') as f:
            soup = BeautifulSoup(f.read(), features='xml')

        chapters = []

        # Find all level1 elements (top-level sections)
        level1Elements = soup.find_all('level1')

        for level1 in level1Elements:
            # Get chapter title from h1, h2, or id
            chapterTitle = None

            # Try to find heading
            for hTag in ['h1', 'h2', 'h3']:
                heading = level1.find(hTag)
                if heading:
                    chapterTitle = heading.get_text().strip()
                    break

            # Fallback to id
            if not chapterTitle:
                chapterTitle = level1.get('id', 'Untitled Chapter')

            # Extract paragraphs from this level1
            paragraphs = []
            for p in level1.find_all('p'):
                text = p.get_text().strip()
                text = re.sub(r'\s+', ' ', text)
                if text:
                    paragraphs.append(text)

            if paragraphs:
                chapter = Chapter(chapterTitle)
                chapter.paragraphs = paragraphs
                chapters.append(chapter)

        return chapters

    def _extract_paragraphs(self, htmlPath):
        """Extract paragraphs from HTML content file"""
        with open(htmlPath, 'r', encoding='utf-8', errors='ignore') as f:
            soup = BeautifulSoup(f.read(), 'html.parser')

        paragraphs = []

        # Find all paragraph tags
        for p in soup.find_all('p'):
            text = p.get_text().strip()
            # Clean up whitespace
            text = re.sub(r'\s+', ' ', text)
            if text:
                paragraphs.append(text)

        # If no <p> tags, try divs or just get all text
        if not paragraphs:
            # Try divs
            for div in soup.find_all('div'):
                text = div.get_text().strip()
                text = re.sub(r'\s+', ' ', text)
                if text and len(text) > 10:  # Avoid tiny fragments
                    paragraphs.append(text)

        # Last resort: split body text by double newlines
        if not paragraphs:
            body = soup.find('body')
            if body:
                text = body.get_text()
                # Split on multiple newlines or periods followed by newline
                chunks = re.split(r'\n\n+', text)
                for chunk in chunks:
                    chunk = chunk.strip()
                    chunk = re.sub(r'\s+', ' ', chunk)
                    if chunk:
                        paragraphs.append(chunk)

        return paragraphs

    def cleanup(self):
        """Clean up temporary files"""
        if self.tempDir and Path(self.tempDir).exists():
            shutil.rmtree(self.tempDir)
            self.tempDir = None
