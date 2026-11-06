#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regression tests for EPUB parsing behavior.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

from src.epub_parser import EpubParser


def write_text_file(filePath, content):
    """Write a UTF-8 text file"""
    filePath.parent.mkdir(parents=True, exist_ok=True)
    filePath.write_text(content, encoding='utf-8')


def build_test_epub(epubPath):
    """Build a minimal EPUB fixture for parser regression testing"""
    with TemporaryDirectory() as tempDir:
        tempPath = Path(tempDir)

        write_text_file(
            tempPath / 'mimetype',
            'application/epub+zip'
        )
        write_text_file(
            tempPath / 'META-INF' / 'container.xml',
            '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
'''
        )
        write_text_file(
            tempPath / 'OEBPS' / 'content.opf',
            '''<?xml version="1.0" encoding="utf-8"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Parser Regression Book</dc:title>
    <dc:creator>BookStorm Test</dc:creator>
  </metadata>
  <manifest>
    <item id="navdoc" href="nav/toc.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="chap1" href="text/chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chap2" href="text/chapter2.xhtml" media-type="application/xhtml+xml"/>
    <item id="notes" href="text/notes.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
    <itemref idref="notes" linear="no"/>
    <itemref idref="chap2"/>
  </spine>
</package>
'''
        )
        write_text_file(
            tempPath / 'OEBPS' / 'nav' / 'toc.xhtml',
            '''<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <body>
    <nav epub:type="toc">
      <ol>
        <li><a href="../text/chapter1.xhtml">Chapter One</a></li>
        <li><a href="../text/chapter2.xhtml">Chapter Two</a></li>
      </ol>
    </nav>
  </body>
</html>
'''
        )
        write_text_file(
            tempPath / 'OEBPS' / 'text' / 'chapter1.xhtml',
            '''<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body>
    <section>
      <h1>Visible Heading</h1>
      <p>This is <em>very</em> bad.</p>
      <ul>
        <li>First item</li>
        <li>Second item</li>
      </ul>
    </section>
  </body>
</html>
'''
        )
        write_text_file(
            tempPath / 'OEBPS' / 'text' / 'chapter2.xhtml',
            '''<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body>
    <div>Lead in <span>text</span>.</div>
    <div class="section"><p>More text.</p></div>
    <p>Tail text.</p>
  </body>
</html>
'''
        )
        write_text_file(
            tempPath / 'OEBPS' / 'text' / 'notes.xhtml',
            '''<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body>
    <p>This non-linear note should not appear.</p>
  </body>
</html>
'''
        )

        with zipfile.ZipFile(epubPath, 'w') as zipRef:
            mimetypePath = tempPath / 'mimetype'
            zipRef.write(mimetypePath, 'mimetype', compress_type=zipfile.ZIP_STORED)

            for filePath in sorted(tempPath.rglob('*')):
                if filePath.is_file() and filePath != mimetypePath:
                    archivePath = filePath.relative_to(tempPath).as_posix()
                    zipRef.write(filePath, archivePath, compress_type=zipfile.ZIP_DEFLATED)


def test_epub_parser():
    """Verify EPUB parsing follows linear spine order and preserves readable text"""
    with TemporaryDirectory() as tempDir:
        epubPath = Path(tempDir) / 'fixture.epub'
        build_test_epub(epubPath)

        parser = EpubParser()
        try:
            book = parser.parse(epubPath)
        finally:
            parser.cleanup()

    print("Testing spine-based chapter extraction...")
    assert book.title == 'Parser Regression Book'
    assert book.author == 'BookStorm Test'
    assert book.get_total_chapters() == 2
    assert [chapter.title for chapter in book.chapters] == ['Chapter One', 'Chapter Two']
    print("Chapter extraction tests passed")

    print("\nTesting readable text extraction...")
    firstChapter = book.get_chapter(0)
    secondChapter = book.get_chapter(1)

    assert firstChapter is not None
    assert secondChapter is not None

    assert firstChapter.paragraphs == [
        'Visible Heading',
        'This is very bad.',
        'First item',
        'Second item'
    ]
    assert secondChapter.paragraphs == [
        'Lead in text.',
        'More text.',
        'Tail text.'
    ]
    assert all('non-linear note' not in paragraph.lower() for chapter in book.chapters for paragraph in chapter.paragraphs)
    print("Readable text tests passed")

    print("\nAll EPUB parser tests passed!")


if __name__ == "__main__":
    test_epub_parser()
