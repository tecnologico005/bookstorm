#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Folder Audiobook Parser

Parses a folder of audio files as a single multi-file audiobook.
Uses metadata (track numbers, disc numbers) and falls back to natural filename sorting.
"""

import re
from pathlib import Path
from src.audio_parser import AudioBook, AudioChapter


class FolderAudiobookParser:
    """Parser for folder-based audiobooks (multiple audio files)"""

    # Supported audio formats (what mpv can handle)
    AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.m4b', '.opus', '.ogg', '.flac', '.wav', '.aac', '.wma'}

    def __init__(self):
        """Initialize folder audiobook parser"""
        self.mutagen = None
        try:
            import mutagen
            import mutagen.mp4
            import mutagen.mp3
            import mutagen.oggopus
            import mutagen.oggvorbis
            import mutagen.flac
            self.mutagen = mutagen
        except ImportError:
            print("Warning: mutagen not installed. Install with: pip install mutagen")

    def parse(self, folderPath):
        """
        Parse folder of audio files as a single audiobook

        Args:
            folderPath: Path to folder containing audio files

        Returns:
            AudioBook object with multiple chapters (one per file)
        """
        if not self.mutagen:
            raise ImportError("mutagen library required for folder audiobooks")

        folderPath = Path(folderPath)
        if not folderPath.is_dir():
            raise ValueError(f"Not a directory: {folderPath}")

        # Find all audio files in folder
        audioFiles = self._find_audio_files(folderPath)
        if not audioFiles:
            raise ValueError(f"No audio files found in: {folderPath}")

        # Extract metadata from each file
        fileMetadata = []
        for audioFile in audioFiles:
            metadata = self._extract_file_metadata(audioFile)
            fileMetadata.append(metadata)

        # Sort files intelligently
        sortedFiles = self._sort_files(fileMetadata)

        # Create audiobook
        folderName = folderPath.name
        book = AudioBook(title=folderName, author="Unknown")

        # Determine book title and author from most common tags
        bookTitle, bookAuthor = self._determine_book_metadata(sortedFiles)
        book.title = bookTitle or folderName
        book.author = bookAuthor

        # Calculate total duration and create chapters
        totalDuration = 0.0
        for fileData in sortedFiles:
            audioPath = fileData['path']
            chapterTitle = fileData['title']
            duration = fileData['duration']

            chapter = AudioChapter(
                title=chapterTitle,
                startTime=totalDuration,
                duration=duration
            )
            # Store file path in chapter for multi-file playback
            chapter.audioPath = str(audioPath)
            book.add_chapter(chapter)

            totalDuration += duration

        book.totalDuration = totalDuration

        # Store all audio file paths in book for playlist playback
        book.audioFiles = [fileData['path'] for fileData in sortedFiles]
        book.isMultiFile = True

        return book

    def _find_audio_files(self, folderPath):
        """
        Find all audio files in folder (non-recursive)

        Args:
            folderPath: Path to folder

        Returns:
            List of Path objects for audio files
        """
        audioFiles = []
        for filePath in folderPath.iterdir():
            if filePath.is_file() and filePath.suffix.lower() in self.AUDIO_EXTENSIONS:
                audioFiles.append(filePath)
        return audioFiles

    def _extract_file_metadata(self, audioPath):
        """
        Extract metadata from audio file

        Args:
            audioPath: Path to audio file

        Returns:
            Dictionary with metadata:
            - path: File path
            - filename: Filename without extension
            - title: Track title (from tags or filename)
            - album: Album name
            - artist: Artist name
            - trackNumber: Track number (int or None)
            - discNumber: Disc number (int or None)
            - duration: Duration in seconds
        """
        metadata = {
            'path': audioPath,
            'filename': audioPath.stem,
            'title': audioPath.stem,
            'album': None,
            'artist': None,
            'trackNumber': None,
            'discNumber': None,
            'duration': 0.0
        }

        try:
            audioFile = self.mutagen.File(audioPath)
            if not audioFile:
                # File format not recognized by mutagen - use filename fallback
                return metadata

            # Get duration
            if hasattr(audioFile.info, 'length'):
                metadata['duration'] = audioFile.info.length

            # Extract tags based on format
            # MP4/M4A/M4B tags
            if '\xa9nam' in audioFile:  # Title
                metadata['title'] = str(audioFile['\xa9nam'][0])
            if '\xa9alb' in audioFile:  # Album
                metadata['album'] = str(audioFile['\xa9alb'][0])
            if '\xa9ART' in audioFile:  # Artist
                metadata['artist'] = str(audioFile['\xa9ART'][0])
            if 'trkn' in audioFile:  # Track number
                try:
                    trackData = audioFile['trkn'][0]
                    if isinstance(trackData, tuple):
                        metadata['trackNumber'] = int(trackData[0])
                    else:
                        metadata['trackNumber'] = int(trackData)
                except:
                    pass
            if 'disk' in audioFile:  # Disc number
                try:
                    discData = audioFile['disk'][0]
                    if isinstance(discData, tuple):
                        metadata['discNumber'] = int(discData[0])
                    else:
                        metadata['discNumber'] = int(discData)
                except:
                    pass

            # MP3 ID3 tags
            if 'TIT2' in audioFile:  # Title
                metadata['title'] = str(audioFile['TIT2'].text[0])
            if 'TALB' in audioFile:  # Album
                metadata['album'] = str(audioFile['TALB'].text[0])
            if 'TPE1' in audioFile:  # Artist
                metadata['artist'] = str(audioFile['TPE1'].text[0])
            if 'TRCK' in audioFile:  # Track number
                try:
                    trackStr = str(audioFile['TRCK'].text[0])
                    # Handle "3/12" format
                    if '/' in trackStr:
                        trackStr = trackStr.split('/')[0]
                    metadata['trackNumber'] = int(trackStr)
                except:
                    pass
            if 'TPOS' in audioFile:  # Disc number
                try:
                    discStr = str(audioFile['TPOS'].text[0])
                    # Handle "1/2" format
                    if '/' in discStr:
                        discStr = discStr.split('/')[0]
                    metadata['discNumber'] = int(discStr)
                except:
                    pass

            # Ogg Vorbis / Opus tags (lowercase)
            if 'title' in audioFile:
                metadata['title'] = str(audioFile['title'][0])
            if 'album' in audioFile:
                metadata['album'] = str(audioFile['album'][0])
            if 'artist' in audioFile:
                metadata['artist'] = str(audioFile['artist'][0])
            if 'tracknumber' in audioFile:
                try:
                    trackStr = str(audioFile['tracknumber'][0])
                    if '/' in trackStr:
                        trackStr = trackStr.split('/')[0]
                    metadata['trackNumber'] = int(trackStr)
                except:
                    pass
            if 'discnumber' in audioFile:
                try:
                    discStr = str(audioFile['discnumber'][0])
                    if '/' in discStr:
                        discStr = discStr.split('/')[0]
                    metadata['discNumber'] = int(discStr)
                except:
                    pass

        except Exception:
            # Silently fall back to filename-based metadata
            # This is normal for files without tags or unsupported formats
            pass

        return metadata

    def _sort_files(self, fileMetadata):
        """
        Sort files intelligently using metadata and filename

        Priority:
        1. Disc number (if present) + Track number
        2. Track number only
        3. Natural filename sorting

        Args:
            fileMetadata: List of metadata dictionaries

        Returns:
            Sorted list of metadata dictionaries
        """
        # Check if any files have disc numbers
        hasDiscNumbers = any(f['discNumber'] is not None for f in fileMetadata)

        # Check if any files have track numbers
        hasTrackNumbers = any(f['trackNumber'] is not None for f in fileMetadata)

        if hasDiscNumbers:
            # Sort by disc number, then track number, then filename
            sortedFiles = sorted(fileMetadata, key=lambda f: (
                f['discNumber'] if f['discNumber'] is not None else 999,
                f['trackNumber'] if f['trackNumber'] is not None else 999,
                self._natural_sort_key(f['filename'])
            ))
        elif hasTrackNumbers:
            # Sort by track number, then filename
            sortedFiles = sorted(fileMetadata, key=lambda f: (
                f['trackNumber'] if f['trackNumber'] is not None else 999,
                self._natural_sort_key(f['filename'])
            ))
        else:
            # Fall back to natural filename sorting
            sortedFiles = sorted(fileMetadata, key=lambda f: self._natural_sort_key(f['filename']))

        return sortedFiles

    def _natural_sort_key(self, filename):
        """
        Generate natural sort key for filename

        Handles: "Chapter 1", "Chapter 2", "Chapter 10" correctly
        Also handles: "1 - Intro", "01-First", "Part 1.mp3"

        Args:
            filename: Filename string

        Returns:
            Tuple of strings and integers for sorting
        """
        def convert(text):
            return int(text) if text.isdigit() else text.lower()

        return [convert(c) for c in re.split('([0-9]+)', filename)]

    def _determine_book_metadata(self, sortedFiles):
        """
        Determine book title and author from file tags

        Uses most common album tag as title and artist tag as author

        Args:
            sortedFiles: Sorted list of file metadata

        Returns:
            Tuple of (title, author)
        """
        # Count album names
        albumCounts = {}
        for fileData in sortedFiles:
            album = fileData['album']
            if album:
                albumCounts[album] = albumCounts.get(album, 0) + 1

        # Count artist names
        artistCounts = {}
        for fileData in sortedFiles:
            artist = fileData['artist']
            if artist:
                artistCounts[artist] = artistCounts.get(artist, 0) + 1

        # Most common album becomes book title
        bookTitle = None
        if albumCounts:
            bookTitle = max(albumCounts, key=albumCounts.get)

        # Most common artist becomes author
        bookAuthor = None
        if artistCounts:
            bookAuthor = max(artistCounts, key=artistCounts.get)

        return bookTitle, bookAuthor

    def cleanup(self):
        """Clean up resources (no temp files for folder audiobooks)"""
        pass
