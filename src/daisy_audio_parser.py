#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DAISY Audio Book Parser

Handles parsing of DAISY 2.02 and DAISY 3 audio-only books.
Extracts audio segments from SMIL files for playback.
"""

import zipfile
import tempfile
import shutil
from pathlib import Path
from bs4 import BeautifulSoup
import re
import os
from src.audio_parser import AudioBook, AudioChapter


class DaisyAudioParser:
    """Parser for DAISY audio-only books"""

    def __init__(self):
        self.tempDir = None
        self.basePath = None

    def parse(self, daisyPath):
        """
        Parse a DAISY audio book (zip file)

        Args:
            daisyPath: Path to DAISY zip file

        Returns:
            Book object with audio file information
        """
        daisyPath = Path(daisyPath)

        if not daisyPath.exists():
            raise FileNotFoundError(f"DAISY file not found: {daisyPath}")

        # Extract zip to temp directory
        self.tempDir = tempfile.mkdtemp(prefix="daisy_audio_")
        self.basePath = Path(self.tempDir)

        try:
            with zipfile.ZipFile(daisyPath, 'r') as zipRef:
                zipRef.extractall(self.basePath)

            # Find the actual DAISY directory (might be in a subdirectory)
            daisyDir = self._find_daisy_directory(self.basePath)
            if not daisyDir:
                raise ValueError("Unknown DAISY format: no ncc.html or navigation.ncx found")

            # Detect DAISY version and parse accordingly
            if (daisyDir / "ncc.html").exists():
                book = self._parse_daisy2_audio(daisyDir)
            elif (daisyDir / "navigation.ncx").exists() or list(daisyDir.glob("*.ncx")):
                book = self._parse_daisy3_audio(daisyDir)
            else:
                raise ValueError("Unknown DAISY format: no ncc.html or navigation.ncx found")

            # Store temp directory path for cleanup later
            book.tempDir = self.tempDir
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

    def _parse_daisy2_audio(self, basePath):
        """Parse DAISY 2.02 audio format (NCC.html + SMIL)"""
        nccPath = basePath / "ncc.html"

        with open(nccPath, 'r', encoding='utf-8', errors='ignore') as f:
            soup = BeautifulSoup(f.read(), 'html.parser')

        # Get title
        titleTag = soup.find('title')
        bookTitle = titleTag.get_text().strip() if titleTag else "Unknown Title"

        # Find all top-level headings (h1) which represent chapters
        headings = soup.find_all('h1')

        chapters = []
        totalDuration = 0.0

        for heading in headings:
            # Get chapter title
            chapterTitle = heading.get_text().strip()

            # Find linked SMIL file
            link = heading.find('a')
            if not link or not link.get('href'):
                continue

            smilHref = link.get('href')
            smilFile = smilHref.split('#')[0]
            smilPath = basePath / smilFile

            if smilPath.exists():
                # Parse SMIL to get audio info for this chapter
                chapterDuration, mergedAudio = self._process_smil_chapter(smilPath, basePath)

                if mergedAudio and chapterDuration > 0:
                    chapter = AudioChapter(
                        title=chapterTitle,
                        startTime=totalDuration,
                        duration=chapterDuration
                    )
                    # Store merged audio file path
                    chapter.audioPath = mergedAudio
                    chapters.append(chapter)
                    totalDuration += chapterDuration

        book = AudioBook(title=bookTitle, author="Unknown")
        book.totalDuration = totalDuration

        for chapter in chapters:
            book.add_chapter(chapter)

        # Create playlist of all chapter audio files
        book.audioFiles = [chap.audioPath for chap in chapters]
        book.isMultiFile = True

        return book

    def _parse_daisy3_audio(self, basePath):
        """Parse DAISY 3 audio format (NCX + SMIL)"""
        # Find NCX file
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

        # Find all top-level navPoints (chapters)
        navMap = soup.find('navMap')
        if not navMap:
            raise ValueError("No navMap found in NCX")

        chapters = []
        totalDuration = 0.0

        for navPoint in navMap.find_all('navPoint', recursive=False):
            # Get chapter title
            navLabel = navPoint.find('navLabel')
            if navLabel:
                textTag = navLabel.find('text')
                chapterTitle = textTag.get_text().strip() if textTag else "Untitled"
            else:
                chapterTitle = "Untitled"

            # Get content source (SMIL file)
            content = navPoint.find('content')
            if not content or not content.get('src'):
                continue

            contentSrc = content.get('src')
            smilFile = contentSrc.split('#')[0]
            smilPath = basePath / smilFile

            if smilPath.exists():
                # Parse SMIL to get audio info for this chapter
                chapterDuration, mergedAudio = self._process_smil_chapter(smilPath, basePath)

                if mergedAudio and chapterDuration > 0:
                    chapter = AudioChapter(
                        title=chapterTitle,
                        startTime=totalDuration,
                        duration=chapterDuration
                    )
                    # Store merged audio file path
                    chapter.audioPath = mergedAudio
                    chapters.append(chapter)
                    totalDuration += chapterDuration

        book = AudioBook(title=bookTitle, author="Unknown")
        book.totalDuration = totalDuration

        for chapter in chapters:
            book.add_chapter(chapter)

        # Create playlist of all chapter audio files
        book.audioFiles = [chap.audioPath for chap in chapters]
        book.isMultiFile = True

        return book

    def _process_smil_chapter(self, smilPath, basePath):
        """
        Process a SMIL file and extract/merge audio segments for a chapter

        Args:
            smilPath: Path to SMIL file
            basePath: Base directory for resolving relative paths

        Returns:
            Tuple of (duration, audio_file_path)
            - duration: Total duration of chapter in seconds
            - audio_file_path: Path to audio file (merged if needed)
        """
        with open(smilPath, 'r', encoding='utf-8', errors='ignore') as f:
            soup = BeautifulSoup(f.read(), features='xml')

        # Collect all audio segments
        audioSegments = []
        totalDuration = 0.0

        # Find all audio elements
        for audio in soup.find_all('audio'):
            src = audio.get('src')
            if not src:
                continue

            # Resolve audio file path
            audioPath = basePath / src
            if not audioPath.exists():
                continue

            # Parse clip times (NPT format: "npt=123.456s")
            clipBegin = audio.get('clip-begin') or audio.get('clipBegin')
            clipEnd = audio.get('clip-end') or audio.get('clipEnd')

            beginTime = self._parse_npt_time(clipBegin) if clipBegin else None
            endTime = self._parse_npt_time(clipEnd) if clipEnd else None

            segment = {
                'file': str(audioPath.resolve()),
                'clip_begin': beginTime,
                'clip_end': endTime
            }

            # Calculate segment duration
            if beginTime is not None and endTime is not None:
                segmentDuration = endTime - beginTime
            elif endTime is not None:
                segmentDuration = endTime
            else:
                # Will need to get file duration
                segmentDuration = self._get_audio_duration(str(audioPath.resolve()))

            totalDuration += segmentDuration
            audioSegments.append(segment)

        if not audioSegments:
            return (0.0, None)

        # Check if we need to merge segments or can use a single file
        if len(audioSegments) == 1:
            segment = audioSegments[0]
            # Single segment - check if it's the whole file or a clip
            if segment['clip_begin'] is None and segment['clip_end'] is None:
                # Whole file, no processing needed
                return (totalDuration, segment['file'])
            else:
                # Single segment with clips - extract it
                outputFile = self._extract_audio_segment(
                    segment['file'],
                    segment['clip_begin'],
                    segment['clip_end']
                )
                return (totalDuration, outputFile)
        else:
            # Multiple segments - need to merge them
            outputFile = self._merge_audio_segments(audioSegments)
            return (totalDuration, outputFile)

    def _get_audio_duration(self, audioPath):
        """Get duration of audio file using ffprobe"""
        try:
            import subprocess
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', audioPath],
                capture_output=True,  # noqa: F821 - capture_output is a subprocess.run parameter
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except:
            pass
        return 0.0

    def _extract_audio_segment(self, audioPath, clipBegin, clipEnd):
        """
        Extract a segment from an audio file using ffmpeg

        Args:
            audioPath: Path to source audio file
            clipBegin: Start time in seconds (or None)
            clipEnd: End time in seconds (or None)

        Returns:
            Path to extracted segment file
        """
        import subprocess
        import hashlib

        # Create unique filename for this segment
        segmentId = hashlib.md5(
            f"{audioPath}_{clipBegin}_{clipEnd}".encode()
        ).hexdigest()[:16]

        outputPath = os.path.join(
            self.tempDir,
            f"segment_{segmentId}.opus"
        )

        # Build ffmpeg command
        cmd = ['ffmpeg', '-y', '-loglevel', 'error']

        if clipBegin is not None:
            cmd.extend(['-ss', str(clipBegin)])

        cmd.extend(['-i', audioPath])

        if clipEnd is not None:
            duration = clipEnd - (clipBegin or 0.0)
            cmd.extend(['-t', str(duration)])

        # Use opus for efficient compression
        cmd.extend(['-c:a', 'libopus', '-b:a', '64k', outputPath])

        try:
            subprocess.run(cmd, check=True, timeout=300)
            return outputPath
        except Exception as e:
            print(f"Error extracting audio segment: {e}")
            return None

    def _merge_audio_segments(self, audioSegments):
        """
        Merge multiple audio segments into a single file using ffmpeg

        Args:
            audioSegments: List of segment dictionaries

        Returns:
            Path to merged audio file
        """
        import subprocess
        import hashlib

        # Create unique filename for merged output
        segmentIds = "_".join([
            f"{seg['file']}_{seg['clip_begin']}_{seg['clip_end']}"
            for seg in audioSegments
        ])
        mergedId = hashlib.md5(segmentIds.encode()).hexdigest()[:16]

        outputPath = os.path.join(
            self.tempDir,
            f"merged_{mergedId}.opus"
        )

        # Create concat file for ffmpeg
        concatFilePath = os.path.join(self.tempDir, f"concat_{mergedId}.txt")

        # First, extract all segments
        extractedFiles = []
        for segment in audioSegments:
            if segment['clip_begin'] is None and segment['clip_end'] is None:
                # Whole file
                extractedFiles.append(segment['file'])
            else:
                # Extract segment
                extracted = self._extract_audio_segment(
                    segment['file'],
                    segment['clip_begin'],
                    segment['clip_end']
                )
                if extracted:
                    extractedFiles.append(extracted)

        if not extractedFiles:
            return None

        # Create concat file
        with open(concatFilePath, 'w', encoding='utf-8') as f:
            for filepath in extractedFiles:
                # Escape single quotes in path
                escapedPath = filepath.replace("'", "'\\''")
                f.write(f"file '{escapedPath}'\n")

        # Merge using ffmpeg concat
        cmd = [
            'ffmpeg', '-y', '-loglevel', 'error',
            '-f', 'concat', '-safe', '0',
            '-i', concatFilePath,
            '-c:a', 'libopus', '-b:a', '64k',
            outputPath
        ]

        try:
            subprocess.run(cmd, check=True, timeout=600)
            return outputPath
        except Exception as e:
            print(f"Error merging audio segments: {e}")
            return None

    def _parse_npt_time(self, nptString):
        """
        Parse Normal Play Time (NPT) format to seconds

        Examples:
            "npt=123.456s" -> 123.456
            "123.456s" -> 123.456
            "npt=1:23.456" -> 83.456

        Args:
            nptString: NPT formatted time string

        Returns:
            Float seconds, or None if parse fails
        """
        if not nptString:
            return None

        try:
            # Remove "npt=" prefix if present
            timeStr = nptString.replace('npt=', '').strip()

            # Handle seconds format: "123.456s"
            if timeStr.endswith('s'):
                return float(timeStr[:-1])

            # Handle time format: "1:23.456" (minutes:seconds)
            if ':' in timeStr:
                parts = timeStr.split(':')
                if len(parts) == 2:
                    minutes = float(parts[0])
                    seconds = float(parts[1])
                    return minutes * 60 + seconds
                elif len(parts) == 3:
                    # Handle hours:minutes:seconds
                    hours = float(parts[0])
                    minutes = float(parts[1])
                    seconds = float(parts[2])
                    return hours * 3600 + minutes * 60 + seconds

            # Try parsing as plain number
            return float(timeStr)

        except (ValueError, AttributeError):
            return None

    def cleanup(self):
        """
        Clean up temporary files

        This is called when the book is closed and audio files are no longer needed.
        """
        if self.tempDir and Path(self.tempDir).exists():
            try:
                shutil.rmtree(self.tempDir)
            except:
                pass  # Ignore errors during cleanup
            self.tempDir = None


def is_daisy_audio_book(daisyPath):
    """
    Detect if a DAISY book is audio-only

    Args:
        daisyPath: Path to DAISY zip file

    Returns:
        Boolean - True if audio-only, False if text-based
    """
    daisyPath = Path(daisyPath)

    if not daisyPath.exists() or not zipfile.is_zipfile(daisyPath):
        return False

    try:
        with zipfile.ZipFile(daisyPath, 'r') as zipRef:
            fileList = zipRef.namelist()

            # Check for audio file extensions
            audioExtensions = {'.mp3', '.wav', '.mp2', '.m4a', '.m4b', '.aac', '.ogg', '.opus'}
            hasAudioFiles = any(
                Path(f).suffix.lower() in audioExtensions
                for f in fileList
            )

            # Check for SMIL files (strong indicator of audio content)
            hasSmilFiles = any(f.lower().endswith('.smil') for f in fileList)

            # If has SMIL files and audio, it's likely an audio book
            if hasSmilFiles and hasAudioFiles:
                return True

            # For DAISY 3, check package file metadata
            opfFiles = [f for f in fileList if f.lower().endswith('.opf')]
            if opfFiles:
                with zipRef.open(opfFiles[0]) as opfFile:
                    content = opfFile.read().decode('utf-8', errors='ignore')
                    # Check for multimediaType metadata
                    if 'audioOnly' in content or 'audioNCX' in content:
                        return True

            # Check if there are DTBook XML files (text content)
            hasDtbook = any(
                'dtbook' in f.lower() or
                (f.lower().endswith('.xml') and 'navigation.ncx' not in f.lower())
                for f in fileList
            )

            # If has audio and SMIL but no DTBook, likely audio-only
            if hasAudioFiles and hasSmilFiles and not hasDtbook:
                return True

            return False

    except Exception:
        return False
