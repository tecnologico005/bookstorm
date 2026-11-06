#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Audio Book Parser

Parses audio book files (M4B, M4A, MP3) and extracts chapter information.
Uses mutagen for metadata extraction.
"""

from pathlib import Path
from src.book import Book, Chapter


class AudioChapter(Chapter):
    """Chapter with audio-specific metadata"""

    def __init__(self, title="Untitled", startTime=0.0, duration=0.0):
        """
        Initialize audio chapter

        Args:
            title: Chapter title
            startTime: Start time in seconds
            duration: Duration in seconds
        """
        super().__init__(title)
        self.startTime = startTime
        self.duration = duration
        # Add placeholder paragraph for compatibility
        self.paragraphs = [f"Audio chapter: {title}"]


class AudioBook(Book):
    """Book with audio-specific metadata"""

    def __init__(self, title="Untitled", author="Unknown", audioPath=None):
        """
        Initialize audio book

        Args:
            title: Book title
            author: Book author
            audioPath: Path to audio file
        """
        super().__init__(title, author)
        self.audioPath = audioPath
        self.isAudioBook = True
        self.totalDuration = 0.0


class AudioParser:
    """Parser for audio book files (M4B, M4A, MP3)"""

    def __init__(self):
        """Initialize audio parser"""
        self.mutagen = None
        try:
            import mutagen
            import mutagen.mp4
            import mutagen.mp3
            self.mutagen = mutagen
        except ImportError:
            print("Warning: mutagen not installed. Install with: pip install mutagen")

    def parse(self, audioPath):
        """
        Parse audio file and extract chapters

        Args:
            audioPath: Path to audio file

        Returns:
            AudioBook object
        """
        if not self.mutagen:
            raise ImportError("mutagen library required for audio books")

        audioPath = Path(audioPath)

        # Try to load the audio file
        try:
            audioFile = self.mutagen.File(audioPath)
            if audioFile is None:
                raise ValueError(f"Could not read audio file: {audioPath}")
        except Exception as e:
            raise Exception(f"Error loading audio file: {e}")

        # Create audio book
        book = AudioBook(audioPath=str(audioPath))

        # Extract metadata
        title = self._extract_title(audioFile, audioPath)
        author = self._extract_author(audioFile)
        book.title = title
        book.author = author

        # Get duration
        if hasattr(audioFile.info, 'length'):
            book.totalDuration = audioFile.info.length

        # Extract chapters
        chapters = self._extract_chapters(audioFile, audioPath)

        if chapters:
            # Add parsed chapters
            for chapter in chapters:
                book.add_chapter(chapter)
        else:
            # No chapter markers - treat entire file as one chapter
            singleChapter = AudioChapter(
                title=title,
                startTime=0.0,
                duration=book.totalDuration
            )
            book.add_chapter(singleChapter)

        return book

    def _extract_title(self, audioFile, audioPath):
        """Extract title from metadata"""
        # Try various title tags
        titleTags = ['\xa9nam', 'TIT2', 'title', 'TITLE']

        for tag in titleTags:
            if tag in audioFile:
                value = audioFile[tag]
                if isinstance(value, list):
                    return str(value[0])
                return str(value)

        # Fallback to filename
        return audioPath.stem

    def _extract_author(self, audioFile):
        """Extract author from metadata"""
        # Try various author tags
        authorTags = ['\xa9ART', 'TPE1', 'artist', 'ARTIST', 'author', 'AUTHOR']

        for tag in authorTags:
            if tag in audioFile:
                value = audioFile[tag]
                if isinstance(value, list):
                    return str(value[0])
                return str(value)

        return "Unknown"

    def _extract_chapters(self, audioFile, audioPath):
        """Extract chapter information from audio file"""
        chapters = []

        # Try MP4 chapter format (M4B, M4A) - check chapters attribute directly
        if hasattr(audioFile, 'chapters') and audioFile.chapters:
            chapters = self._parse_mp4_chapters(audioFile.chapters, audioFile.info.length)

        # Try MP3 chapter format (ID3 CHAP frames)
        if not chapters and hasattr(audioFile, 'tags'):
            # Look for CHAP frames in ID3 tags
            if hasattr(audioFile.tags, 'getall'):
                chapFrames = audioFile.tags.getall('CHAP')
                if chapFrames:
                    chapters = self._parse_id3_chapters(chapFrames)

        return chapters

    def _parse_mp4_chapters(self, mp4Chapters, totalDuration):
        """
        Parse MP4 chapter list

        Args:
            mp4Chapters: List of mutagen.mp4.Chapter objects
            totalDuration: Total duration of audio file in seconds

        Returns:
            List of AudioChapter objects
        """
        chapters = []

        for i, chapterObj in enumerate(mp4Chapters):
            # Chapter objects have .start (float, seconds) and .title (string) attributes
            startTime = chapterObj.start
            chapterTitle = chapterObj.title if chapterObj.title else f"Chapter {i + 1}"

            # Calculate duration (will be updated when we know the next chapter's start)
            duration = 0.0

            chapter = AudioChapter(
                title=chapterTitle,
                startTime=startTime,
                duration=duration
            )
            chapters.append(chapter)

        # Calculate durations based on next chapter's start time
        for i in range(len(chapters) - 1):
            chapters[i].duration = chapters[i + 1].startTime - chapters[i].startTime

        # Last chapter duration extends to end of file
        if chapters:
            chapters[-1].duration = totalDuration - chapters[-1].startTime

        return chapters

    def _parse_id3_chapters(self, chapFrames):
        """Parse ID3 CHAP frames (MP3 chapters)"""
        chapters = []

        for i, chapFrame in enumerate(chapFrames):
            startTime = 0.0
            chapterTitle = f"Chapter {i + 1}"

            # Extract start time and title from CHAP frame
            # Note: start_time and sub_frames are external library attributes
            if hasattr(chapFrame, 'start_time'):
                # pylint: disable=no-member
                startTime = chapFrame.start_time / 1000.0  # Convert ms to seconds

            if hasattr(chapFrame, 'sub_frames'):
                # pylint: disable=no-member
                for subFrame in chapFrame.sub_frames:
                    if hasattr(subFrame, 'text'):
                        chapterTitle = str(subFrame.text[0]) if subFrame.text else chapterTitle

            chapter = AudioChapter(
                title=chapterTitle,
                startTime=startTime,
                duration=0.0
            )
            chapters.append(chapter)

        # Calculate durations
        for i in range(len(chapters) - 1):
            chapters[i].duration = chapters[i + 1].startTime - chapters[i].startTime

        return chapters

    def cleanup(self):
        """Clean up resources (no temp files for audio)"""
        pass
