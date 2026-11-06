#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EPUB Parser

Parses EPUB format ebooks and extracts text content.
EPUB files are ZIP archives containing XHTML/HTML content.
"""

import zipfile
import tempfile
import shutil
import re
from pathlib import Path
from urllib.parse import unquote
from bs4 import BeautifulSoup, Tag, NavigableString
from src.book import Book, Chapter


class EpubParser:
    """Parser for EPUB format ebooks"""

    def __init__(self):
        """Initialize EPUB parser"""
        self.tempDir = None

    def parse(self, epubPath):
        """
        Parse EPUB file

        Args:
            epubPath: Path to EPUB file

        Returns:
            Book object
        """
        epubPath = Path(epubPath)

        # Create temp directory for extraction
        self.tempDir = tempfile.mkdtemp(prefix='bookstorm_epub_')
        tempPath = Path(self.tempDir)

        try:
            # Extract EPUB (it's a ZIP file)
            with zipfile.ZipFile(epubPath, 'r') as zipRef:
                zipRef.extractall(tempPath)

            # Find content.opf file
            opfPath = self._find_opf(tempPath)
            if not opfPath:
                raise ValueError("Could not find content.opf in EPUB")

            # Parse OPF to get metadata and spine
            metadata, spine, manifest = self._parse_opf(opfPath)

            # Create book
            book = Book()
            book.title = metadata.get('title', epubPath.stem)
            book.author = metadata.get('creator', 'Unknown')

            # Parse TOC for chapter titles
            opfDir = opfPath.parent
            tocMap = self._build_toc_map(tempPath, opfDir, manifest)

            # Parse content files in spine order (authoritative reading sequence)
            for itemId in spine:
                if itemId in manifest:
                    contentPath = (opfDir / unquote(manifest[itemId])).resolve()
                    if contentPath.exists():
                        chapter = self._parse_content_file(contentPath, tocMap)
                        if chapter:
                            book.add_chapter(chapter)

            return book

        except Exception as e:
            raise Exception(f"Error parsing EPUB: {e}")

    def _find_opf(self, epubDir):
        """
        Find content.opf file in EPUB

        Args:
            epubDir: Extracted EPUB directory

        Returns:
            Path to content.opf or None
        """
        # Check container.xml first
        containerPath = epubDir / 'META-INF' / 'container.xml'
        if containerPath.exists():
            try:
                with open(containerPath, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f.read(), features='xml')
                    rootfile = soup.find('rootfile')
                    if rootfile and rootfile.get('full-path'):
                        return epubDir / rootfile['full-path']
            except Exception:
                pass

        # Fallback: search for .opf files
        for opfFile in epubDir.rglob('*.opf'):
            return opfFile

        return None

    def _parse_opf(self, opfPath):
        """
        Parse OPF file to get metadata, spine, and manifest

        Args:
            opfPath: Path to content.opf

        Returns:
            Tuple of (metadata dict, spine list, manifest dict)
        """
        with open(opfPath, 'r', encoding='utf-8', errors='ignore') as f:
            soup = BeautifulSoup(f.read(), features='xml')

        # Extract metadata
        metadata = {}
        metadataTag = soup.find('metadata')
        if metadataTag:
            title = metadataTag.find('dc:title')
            if title:
                metadata['title'] = title.get_text(strip=True)

            creator = metadataTag.find('dc:creator')
            if creator:
                metadata['creator'] = creator.get_text(strip=True)

        # Extract manifest (id -> href mapping)
        manifest = {}
        manifestTag = soup.find('manifest')
        if manifestTag:
            for item in manifestTag.find_all('item'):
                itemId = item.get('id')
                href = item.get('href')
                if itemId and href:
                    manifest[itemId] = href

        # Extract spine (reading order)
        spine = []
        spineTag = soup.find('spine')
        if spineTag:
            for itemref in spineTag.find_all('itemref'):
                idref = itemref.get('idref')
                linear = itemref.get('linear', 'yes').lower()
                if idref and linear != 'no':
                    spine.append(idref)

        return metadata, spine, manifest

    def _build_toc_map(self, epubDir, opfDir, manifest):
        """
        Build a map of href -> chapter title from TOC

        Args:
            epubDir: Root EPUB directory
            opfDir: Directory containing OPF file
            manifest: Manifest dict from OPF

        Returns:
            Dict mapping href (without anchor) to chapter title
        """
        # Try EPUB 3 nav.xhtml first
        tocMap = self._parse_nav_xhtml_map(epubDir, opfDir, manifest)
        if tocMap:
            return tocMap

        # Try EPUB 2 NCX
        tocMap = self._parse_ncx_map(epubDir, opfDir, manifest)
        if tocMap:
            return tocMap

        return {}

    def _parse_nav_xhtml_map(self, epubDir, opfDir, manifest):
        """
        Parse EPUB 3 nav.xhtml to build href -> title map

        Args:
            epubDir: Root EPUB directory
            opfDir: Directory containing OPF file
            manifest: Manifest dict from OPF

        Returns:
            Dict mapping href to chapter title, or None
        """
        # Find nav document in manifest
        navPath = None
        for itemId, href in manifest.items():
            if 'nav' in href.lower() and href.endswith(('.xhtml', '.html')):
                navPath = opfDir / href
                if navPath.exists():
                    break

        if not navPath or not navPath.exists():
            return None

        try:
            with open(navPath, 'r', encoding='utf-8', errors='ignore') as f:
                soup = BeautifulSoup(f.read(), 'html.parser')

            # Find TOC nav element
            tocNav = soup.find('nav', attrs={'epub:type': 'toc'})
            if not tocNav:
                tocNav = soup.find('nav', id='toc')
            if not tocNav:
                return None

            # Extract href -> title mappings
            tocMap = {}
            for link in tocNav.find_all('a', href=True):
                chapterTitle = link.get_text(strip=True)
                href = link.get('href')

                if not chapterTitle or not href:
                    continue

                contentKey = self._normalize_content_key(navPath.parent, href)
                if contentKey:
                    tocMap[contentKey] = chapterTitle

            return tocMap if tocMap else None

        except Exception as e:
            print(f"Error parsing nav.xhtml: {e}")
            return None

    def _parse_ncx_map(self, epubDir, opfDir, manifest):
        """
        Parse EPUB 2 NCX file to build href -> title map

        Args:
            epubDir: Root EPUB directory
            opfDir: Directory containing OPF file
            manifest: Manifest dict from OPF

        Returns:
            Dict mapping href to chapter title, or None
        """
        # Find NCX file in manifest
        ncxPath = None
        for itemId, href in manifest.items():
            if href.endswith('.ncx'):
                ncxPath = opfDir / href
                if ncxPath.exists():
                    break

        # Fallback: search for any .ncx file
        if not ncxPath or not ncxPath.exists():
            ncxFiles = list(epubDir.rglob('*.ncx'))
            if ncxFiles:
                ncxPath = ncxFiles[0]

        if not ncxPath or not ncxPath.exists():
            return None

        try:
            with open(ncxPath, 'r', encoding='utf-8', errors='ignore') as f:
                soup = BeautifulSoup(f.read(), features='xml')

            # Find all navPoints (including nested)
            navMap = soup.find('navMap')
            if not navMap:
                return None

            tocMap = {}
            for navPoint in navMap.find_all('navPoint'):
                # Get chapter title
                navLabel = navPoint.find('navLabel')
                if navLabel:
                    textTag = navLabel.find('text')
                    chapterTitle = textTag.get_text(strip=True) if textTag else "Untitled"
                else:
                    chapterTitle = "Untitled"

                # Get content source
                content = navPoint.find('content')
                if not content or not content.get('src'):
                    continue

                href = content.get('src')
                contentKey = self._normalize_content_key(ncxPath.parent, href)
                if contentKey:
                    tocMap[contentKey] = chapterTitle

            return tocMap if tocMap else None

        except Exception as e:
            print(f"Error parsing NCX: {e}")
            return None

    def _parse_content_file(self, contentPath, tocMap=None):
        """
        Parse XHTML/HTML content file

        Args:
            contentPath: Path to content file
            tocMap: Optional dict mapping filename to TOC title

        Returns:
            Chapter object, or None if the file has no readable text
        """
        if tocMap is None:
            tocMap = {}

        try:
            with open(contentPath, 'r', encoding='utf-8', errors='ignore') as f:
                soup = BeautifulSoup(f.read(), 'html.parser')
        except Exception as e:
            print(f"Error reading content file {contentPath}: {e}")
            return None

        bodyTag = soup.find('body') or soup
        self._remove_non_readable_elements(bodyTag)

        paragraphs = self._extract_paragraphs(bodyTag)
        if not paragraphs:
            return None

        title = self._resolve_chapter_title(contentPath, bodyTag, tocMap)

        chapter = Chapter(title)
        chapter.paragraphs = paragraphs
        return chapter

    def _normalize_content_key(self, baseDir, href):
        """Normalize TOC hrefs and manifest paths to a comparable absolute key"""
        hrefFile = unquote(href.split('#')[0].strip())
        if not hrefFile:
            return None

        return str((baseDir / hrefFile).resolve())

    def _resolve_chapter_title(self, contentPath, bodyTag, tocMap):
        """Resolve the best title for a spine item"""
        tocTitle = tocMap.get(str(contentPath.resolve()))
        if tocTitle:
            return tocTitle

        for headingName in ['h1', 'h2', 'h3']:
            heading = bodyTag.find(headingName)
            if heading:
                headingText = self._extract_tag_text(heading)
                if headingText:
                    return headingText

        return contentPath.stem

    def _remove_non_readable_elements(self, rootTag):
        """Remove tags that should not contribute spoken text"""
        for element in rootTag.find_all(['script', 'style', 'noscript']):
            element.decompose()

    def _extract_paragraphs(self, rootTag):
        """Extract readable text blocks from XHTML in document order"""
        paragraphs = []
        pendingInlineText = []
        blockTags = {
            'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'p', 'li', 'blockquote', 'pre', 'figcaption',
            'caption', 'td', 'th', 'dd', 'dt', 'address'
        }
        containerTags = {
            'body', 'section', 'article', 'main', 'div',
            'aside', 'nav', 'header', 'footer'
        }
        structuredTags = blockTags | containerTags | {
            'ul', 'ol', 'dl', 'table', 'thead', 'tbody', 'tfoot', 'tr'
        }

        for child in rootTag.children:
            self._collect_paragraphs(
                child,
                paragraphs,
                pendingInlineText,
                blockTags,
                containerTags,
                structuredTags
            )

        self._flush_inline_text(paragraphs, pendingInlineText)
        return paragraphs

    def _collect_paragraphs(self, node, paragraphs, pendingInlineText, blockTags, containerTags, structuredTags):
        """Walk the DOM tree and collect readable blocks without duplicating nested content"""
        if isinstance(node, NavigableString):
            text = self._normalize_text(str(node))
            if text:
                pendingInlineText.append(text)
            return

        if not isinstance(node, Tag):
            return

        if node.name == 'br':
            self._flush_inline_text(paragraphs, pendingInlineText)
            return

        if node.name in blockTags:
            self._flush_inline_text(paragraphs, pendingInlineText)
            text = self._extract_tag_text(node)
            if text:
                paragraphs.append(text)
            return

        if node.name in containerTags or node.name in {'ul', 'ol', 'dl', 'table', 'thead', 'tbody', 'tfoot', 'tr'}:
            if not self._has_structured_children(node, structuredTags):
                self._flush_inline_text(paragraphs, pendingInlineText)
                text = self._extract_tag_text(node)
                if text:
                    paragraphs.append(text)
                return

            for child in node.children:
                self._collect_paragraphs(
                    child,
                    paragraphs,
                    pendingInlineText,
                    blockTags,
                    containerTags,
                    structuredTags
                )

            if node.name in containerTags:
                self._flush_inline_text(paragraphs, pendingInlineText)
            return

        for child in node.children:
            self._collect_paragraphs(
                child,
                paragraphs,
                pendingInlineText,
                blockTags,
                containerTags,
                structuredTags
            )

    def _has_structured_children(self, node, structuredTags):
        """Return True when a container has nested structural elements to recurse into"""
        for child in node.children:
            if isinstance(child, Tag) and child.name in structuredTags:
                return True
        return False

    def _extract_tag_text(self, tag):
        """Extract normalized text from a tag while preserving inline spacing"""
        return self._normalize_text(tag.get_text(' ', strip=True))

    def _flush_inline_text(self, paragraphs, pendingInlineText):
        """Convert accumulated inline text into a paragraph"""
        if not pendingInlineText:
            return

        text = self._normalize_text(' '.join(pendingInlineText))
        pendingInlineText.clear()
        if text:
            paragraphs.append(text)

    def _normalize_text(self, text):
        """Collapse whitespace while keeping natural word boundaries for TTS"""
        text = re.sub(r'\s+', ' ', text).strip()
        if not text:
            return ''

        text = re.sub(r'\s+([,.;:!?])', r'\1', text)
        text = re.sub(r'([\(\[\{])\s+', r'\1', text)
        text = re.sub(r'\s+([\)\]\}])', r'\1', text)
        return text

    def cleanup(self):
        """Clean up temporary files and memory"""
        try:
            # Force garbage collection to clean up local variables
            import gc
            gc.collect()

        except Exception as e:
            print(f"Warning: Error during memory cleanup: {e}")

        # Clean up temp directory
        if self.tempDir and Path(self.tempDir).exists():
            try:
                shutil.rmtree(self.tempDir)
            except Exception as e:
                print(f"Warning: Could not remove temp directory: {e}")
