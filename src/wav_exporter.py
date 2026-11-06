#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WAV Exporter - Export text books to WAV audio files

Converts text books (DAISY, EPUB, PDF, TXT) to WAV files split by chapter
using piper-tts for speech synthesis.
"""

from pathlib import Path

from src.daisy_parser import DaisyParser
from src.epub_parser import EpubParser
from src.pdf_parser import PdfParser
from src.txt_parser import TxtParser
from src.tts_engine import TtsEngine


class WavExporter:
    """Export text books to WAV audio files"""

    def __init__(self, config):
        """
        Initialize WAV exporter

        Args:
            config: ConfigManager instance
        """
        self.config = config

    def export(self, bookPath, outputDir=None):
        """
        Export book to WAV files split by chapter

        Args:
            bookPath: Path to book file
            outputDir: Output directory (optional, defaults to ./{bookname}_audio)

        Returns:
            Exit code (0 for success, 1 for error)
        """
        print(f"Exporting book to WAV: {bookPath}")

        # Parse book using appropriate parser
        bookPath = Path(bookPath)
        parser = self._create_parser(bookPath)
        if not parser:
            return 1

        try:
            book = parser.parse(bookPath)
        except Exception as e:
            print(f"Error parsing book: {e}")
            return 1

        # Determine output directory
        if outputDir is None:
            bookName = bookPath.stem
            outputDir = Path(f"./{bookName}_audio")
        else:
            outputDir = Path(outputDir)

        outputDir.mkdir(parents=True, exist_ok=True)
        print(f"Output directory: {outputDir}")

        # Initialize TTS engine
        tts = self._create_tts_engine()
        if not tts:
            return 1

        voiceModel = self.config.get_voice_model()
        print(f"Using voice: {voiceModel}")
        print(f"Chapters: {book.get_total_chapters()}")
        print()

        # Export each chapter
        successCount = 0
        for chapterIdx in range(book.get_total_chapters()):
            chapter = book.get_chapter(chapterIdx)
            if not chapter:
                continue

            if self._export_chapter(chapter, chapterIdx, book.get_total_chapters(), tts, outputDir):
                successCount += 1

        parser.cleanup()

        if successCount > 0:
            print(f"\nExport complete! {successCount} chapters saved to: {outputDir}")
            return 0
        else:
            print("\nExport failed! No chapters were successfully exported.")
            return 1

    def _create_parser(self, bookPath):
        """
        Create appropriate parser for book format

        Args:
            bookPath: Path to book file

        Returns:
            Parser instance or None if unsupported format
        """
        suffix = bookPath.suffix.lower()

        if suffix in ['.epub']:
            return EpubParser()
        elif suffix in ['.zip']:
            return DaisyParser()
        elif suffix in ['.pdf']:
            return PdfParser()
        elif suffix in ['.txt']:
            return TxtParser()
        else:
            print(f"Error: Unsupported book format: {suffix}")
            print("Supported formats: .epub, .zip (DAISY), .pdf, .txt")
            return None

    def _create_tts_engine(self):
        """
        Create TTS engine for export

        Returns:
            TtsEngine instance or None if not available
        """
        readerEngine = self.config.get_reader_engine()
        if readerEngine != 'piper':
            print("Error: WAV export requires piper-tts. Set reader_engine=piper in config.")
            return None

        voiceModel = self.config.get_voice_model()
        try:
            return TtsEngine(voiceModel)
        except Exception as e:
            print(f"Error initializing TTS engine: {e}")
            return None

    def _export_chapter(self, chapter, chapterIdx, totalChapters, tts, outputDir):
        """
        Export a single chapter to WAV file

        Args:
            chapter: Chapter object
            chapterIdx: Chapter index (0-based)
            totalChapters: Total number of chapters
            tts: TtsEngine instance
            outputDir: Output directory path

        Returns:
            True if successful, False otherwise
        """
        chapterNum = chapterIdx + 1
        print(f"Exporting Chapter {chapterNum}/{totalChapters}: {chapter.title}")

        # Combine all paragraphs in chapter
        chapterText = "\n\n".join(chapter.paragraphs)

        # Generate audio
        try:
            wavData = tts.text_to_wav_data(chapterText)
            if not wavData:
                print(f"  Warning: No audio generated for chapter {chapterNum}")
                return False

            # Save to file
            sanitizedTitle = self._sanitize_filename(chapter.title)
            if not sanitizedTitle:
                sanitizedTitle = f"Chapter_{chapterNum}"

            outputFile = outputDir / f"{chapterNum:03d}_{sanitizedTitle}.wav"
            with open(outputFile, 'wb') as f:
                f.write(wavData)

            print(f"  Saved: {outputFile.name}")
            return True

        except Exception as e:
            print(f"  Error generating audio for chapter {chapterNum}: {e}")
            return False

    def _sanitize_filename(self, title):
        """
        Sanitize chapter title for use as filename

        Args:
            title: Chapter title

        Returns:
            Sanitized filename string
        """
        return "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
