#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BookStorm - Accessible Book Reader

A book reader with text-to-speech support for DAISY, EPUB, and PDF formats.
Uses piper-tts for high-quality speech synthesis.
"""

import sys
import argparse
import threading
import gc
import os
import time
from pathlib import Path
import subprocess

try:
    from setproctitle import setproctitle
    HAS_SETPROCTITLE = True
except ImportError:
    HAS_SETPROCTITLE = False

try:
    import pygame
    HAS_PYGAME = True
    # Define custom pygame event for speech-dispatcher callbacks
    SPEECH_FINISHED_EVENT = pygame.USEREVENT + 1
except ImportError:
    HAS_PYGAME = False
    SPEECH_FINISHED_EVENT = None

from src.daisy_parser import DaisyParser
from src.epub_parser import EpubParser
from src.pdf_parser import PdfParser
from src.txt_parser import TxtParser
from src.mobi_parser import MobiParser
from src.audio_parser import AudioParser
from src.folder_audiobook_parser import FolderAudiobookParser
from src.bookmark_manager import BookmarkManager
from src.tts_engine import TtsEngine
from src.config_manager import ConfigManager
from src.voice_selector import VoiceSelector
from src.book_selector import BookSelector
from src.mpv_player import MpvPlayer
from src.speech_engine import SpeechEngine
from src.screen_reader_engine import ScreenReaderEngine
from src.options_menu import OptionsMenu
from src.sleep_timer_menu import SleepTimerMenu
from src.help_menu import HelpMenu
from src.recent_books_menu import RecentBooksMenu
from src.audiobookshelf_client import AudiobookshelfClient
from src.audiobookshelf_menu import AudiobookshelfMenu
from src.server_link_manager import ServerLinkManager
from src.audiobookshelf_sync import AudiobookshelfSync
from src.bookmarks_menu import BookmarksMenu
from src.wav_exporter import WavExporter
from src.ui import get_input


class BookReader:
    """Main book reader class"""

    def __init__(self, bookPath, config=None):
        """
        Initialize book reader

        Args:
            bookPath: Path to book file (or None for server streaming)
            config: ConfigManager instance
        """
        self.bookPath = Path(bookPath) if bookPath else None
        self.book = None
        self.currentChapter = 0
        self.currentParagraph = 0
        self.config = config or ConfigManager()

        # Initialize components
        self.parser = None  # Will be set based on file type
        self.bookmarkManager = BookmarkManager()
        self.speechEngine = SpeechEngine()  # UI feedback
        self.audioPlayer = MpvPlayer()  # Used for both audio books and TTS playback

        # Configure audio player from saved settings
        savedVolume = self.config.get_volume()
        self.audioPlayer.set_volume(savedVolume)

        # Configure speech engine from saved settings
        speechRate = self.config.get_speech_rate()
        self.speechEngine.set_rate(speechRate)

        # Initialize options menu
        voiceSelector = VoiceSelector(self.config.get_voice_dir())
        # Create callback reference for TTS engine reloading
        reloadCallback = self.reload_tts_engine
        self.optionsMenu = OptionsMenu(
            self.config,
            self.speechEngine,
            voiceSelector,
            self.audioPlayer,
            ttsReloadCallback=reloadCallback
        )

        # Initialize book selector
        # Use library directory if set, otherwise use last books directory
        libraryDir = self.config.get_library_directory()
        if libraryDir and Path(libraryDir).exists():
            booksDir = libraryDir
        else:
            booksDir = self.config.get_books_directory()
        supportedFormats = ['.zip', '.epub', '.mobi', '.pdf', '.txt', '.m4b', '.m4a', '.mp3']
        self.bookSelector = BookSelector(booksDir, supportedFormats, self.speechEngine)

        # Initialize sleep timer menu
        self.sleepTimerMenu = SleepTimerMenu(self.speechEngine)

        # Initialize help menu
        self.helpMenu = HelpMenu(self.speechEngine)

        # Initialize recent books menu
        self.recentBooksMenu = RecentBooksMenu(self.bookmarkManager, self.speechEngine)

        # Initialize bookmarks menu
        self.bookmarksMenu = BookmarksMenu(self.bookmarkManager, self.speechEngine)

        # Initialize Audiobookshelf client and menu (lazy init - only create when accessed)
        self.absClient = None
        self.absMenu = None
        self.serverLinkManager = ServerLinkManager()
        self.absSync = None  # Sync manager (created when absClient initialized)
        self.serverBook = None  # Server book metadata for streaming
        self.isStreaming = False  # Track if currently streaming
        self.sessionId = None  # Active listening session ID (legacy, now managed by absSync)
        self.lastAbsSyncAt = 0.0  # Last periodic Audiobookshelf sync timestamp

        # Initialize reading engine based on config
        readerEngine = self.config.get_reader_engine()
        if readerEngine == 'speechd':
            # Use separate speech-dispatcher session for reading
            # (UI uses self.speechEngine, reading uses self.readingEngine)
            self.ttsEngine = None
            self.readingEngine = SpeechEngine()  # Separate session for book reading

            # Apply saved speech-dispatcher settings to reading engine
            savedModule = self.config.get_speechd_output_module()
            if savedModule:
                self.readingEngine.set_output_module(savedModule)

            savedVoice = self.config.get_speechd_voice()
            if savedVoice:
                self.readingEngine.set_voice(savedVoice)

            # Apply speech rate to reading engine
            self.readingEngine.set_rate(speechRate)
        elif readerEngine == 'screenreader':
            # Use active desktop screen reader via D-Bus
            self.ttsEngine = None
            self.readingEngine = ScreenReaderEngine()
            self.readingEngine.set_rate(speechRate)

            if not self.readingEngine.is_available():
                message = "Warning: No supported screen reader detected. Falling back to speech-dispatcher."
                print(message)
                self.speechEngine.speak(message)

                # Switch to speech-dispatcher mode
                self.readingEngine = SpeechEngine()

                savedModule = self.config.get_speechd_output_module()
                if savedModule:
                    self.readingEngine.set_output_module(savedModule)

                savedVoice = self.config.get_speechd_voice()
                if savedVoice:
                    self.readingEngine.set_voice(savedVoice)

                self.readingEngine.set_rate(speechRate)
                self.config.set_reader_engine('speechd')
        else:
            # Use piper-tts (check if available first)
            if not TtsEngine.is_available():
                # piper-tts not found, fall back to speech-dispatcher
                message = "Warning: piper-tts not found. Falling back to speech-dispatcher."
                print(message)
                self.speechEngine.speak(message)

                # Switch to speech-dispatcher mode
                self.ttsEngine = None
                self.readingEngine = SpeechEngine()
                self.readingEngine.set_rate(speechRate)

                # Update config to remember this fallback
                self.config.set_reader_engine('speechd')
            else:
                # piper-tts is available
                self.readingEngine = None
                voiceModel = self.config.get_voice_model()
                self.ttsEngine = TtsEngine(voiceModel)

        # Playback state
        self.isRunning = False
        self.isPlaying = False
        self.hasPendingSpeechCompletion = False
        self.pendingSpeechCompletionToken = None
        self.expectedSpeechCompletionToken = 0

        # Sleep timer fade-out state
        self.isFadingOut = False
        self.fadeStartVolume = None
        self.fadeStartTime = None

        # Audio buffering for seamless playback
        self.bufferedAudio = None  # Pre-generated next paragraph
        self.bufferedChapter = -1  # Which chapter this buffer is for
        self.bufferedParagraph = -1  # Which paragraph this buffer is for
        self.bufferThread = None
        self.cancelBuffer = False
        self.bufferLock = threading.Lock()

        # Audio bookmark state
        self.savedAudioPosition = 0.0  # Saved audio position for resume
        self.bookmarkCleared = False  # Track if user explicitly cleared bookmark

    def load_book(self):
        """Load and parse the book"""
        # Check if bookPath is a directory (folder audiobook)
        if self.bookPath.is_dir():
            self.speechEngine.speak(f"Loading audiobook folder {self.bookPath.name}")

            # Use folder audiobook parser
            self.parser = FolderAudiobookParser()
            self.book = self.parser.parse(self.bookPath)
        else:
            message = f"Loading book {self.bookPath.stem}"
            print(message)
            self.speechEngine.speak(message)

            # Detect format and create appropriate parser
            suffix = self.bookPath.suffix.lower()
            if suffix in ['.epub']:
                self.parser = EpubParser()
                self.book = self.parser.parse(self.bookPath)
            elif suffix in ['.mobi']:
                self.parser = MobiParser()
                self.book = self.parser.parse(self.bookPath)
            elif suffix in ['.zip']:
                # Assume DAISY format for zip files
                self.parser = DaisyParser()
                self.book = self.parser.parse(self.bookPath)
            elif suffix in ['.pdf']:
                self.parser = PdfParser()
                self.book = self.parser.parse(self.bookPath)
            elif suffix in ['.txt']:
                self.parser = TxtParser()
                self.book = self.parser.parse(self.bookPath)
            elif suffix in ['.m4b', '.m4a', '.mp3']:
                # Audio book file
                self.parser = AudioParser()
                self.book = self.parser.parse(self.bookPath)
            else:
                raise ValueError(f"Unsupported book format: {self.bookPath.suffix}")

        # If it's an audio book, load it into the player
        if hasattr(self.book, 'isAudioBook') and self.book.isAudioBook:
            # Get saved playback speed from config
            playbackSpeed = self.config.get_playback_speed()

            # Check if multi-file audiobook (folder)
            if hasattr(self.book, 'isMultiFile') and self.book.isMultiFile:
                # Multi-file audiobook - load playlist into player
                if not self.audioPlayer.load_audio_playlist(self.book.audioFiles, playbackSpeed=playbackSpeed):
                    raise Exception("Failed to load audio playlist")
            else:
                # Single-file audiobook
                if not self.audioPlayer.load_audio_file(self.book.audioPath, playbackSpeed=playbackSpeed):
                    raise Exception("Failed to load audio file")

            # Restore saved volume setting
            savedVolume = self.config.get_volume()
            self.audioPlayer.set_volume(savedVolume)

            # Inform user about navigation capabilities
            if self.book.get_total_chapters() == 1:
                self.speechEngine.speak("Audio book loaded. No chapter markers found. Only basic playback controls available.")
            else:
                self.speechEngine.speak(f"Audio book loaded with {self.book.get_total_chapters()} chapters. Chapter navigation enabled.")

        # Check if this book is linked to Audiobookshelf server
        # If so, prioritize server progress over local bookmark
        serverLink = self.serverLinkManager.get_link(str(self.bookPath))
        serverProgressLoaded = False

        if serverLink and self.absClient and self.absClient.is_authenticated():
            serverId = serverLink.get('server_id')
            if serverId:
                try:
                    serverProgress = self.absClient.get_progress(serverId)
                    if serverProgress:
                        progressTime = serverProgress.get('currentTime', 0.0)
                        if progressTime > 0:
                            # For audio books, save exact position
                            if hasattr(self.book, 'isAudioBook') and self.book.isAudioBook:
                                self.savedAudioPosition = progressTime
                                self._set_position_from_audio_time(progressTime)
                            else:
                                # Text book - use chapter/paragraph from server if available
                                # (Audiobookshelf doesn't track paragraph, so we'd need to enhance this)
                                pass

                            serverProgressLoaded = True
                except:
                    pass

        # Fall back to local bookmark if no server progress
        if not serverProgressLoaded:
            bookmark = self.bookmarkManager.get_bookmark(self.bookPath)
            if bookmark:
                self.currentChapter = bookmark['chapterIndex']
                self.currentParagraph = bookmark['paragraphIndex']
                self.savedAudioPosition = bookmark.get('audioPosition', 0.0)
            else:
                self.currentChapter = 0
                self.currentParagraph = 0
                self.savedAudioPosition = 0.0

    def read_current_paragraph(self):
        """Read the current paragraph aloud"""
        chapter = self.book.get_chapter(self.currentChapter)
        if not chapter:
            return False

        paragraph = chapter.get_paragraph(self.currentParagraph)
        if not paragraph:
            return False

        # Show what we're reading
        print(f"\n[Chapter {self.currentChapter + 1}/{self.book.get_total_chapters()}: {chapter.title}]")
        print(f"[Paragraph {self.currentParagraph + 1}/{chapter.get_total_paragraphs()}]")
        print(f"\n{paragraph}\n")

        try:
            wavData = self.ttsEngine.text_to_wav_data(paragraph)
            if wavData:
                completed = self.audioPlayer.play_wav_data(wavData, blocking=True)
                return completed
        except Exception as e:
            print(f"Error during playback: {e}")
            return False

        return True

    def next_paragraph(self):
        """Move to next paragraph"""
        chapter = self.book.get_chapter(self.currentChapter)
        if not chapter:
            return False

        if self.currentParagraph < chapter.get_total_paragraphs() - 1:
            self.currentParagraph += 1
            return True
        else:
            # Move to next chapter
            return self.next_chapter()

    def previous_paragraph(self):
        """Move to previous paragraph"""
        if self.currentParagraph > 0:
            self.currentParagraph -= 1
            return True
        else:
            # Move to previous chapter
            if self.previous_chapter():
                # Go to last paragraph of previous chapter
                chapter = self.book.get_chapter(self.currentChapter)
                if chapter:
                    self.currentParagraph = chapter.get_total_paragraphs() - 1
                return True
        return False

    def next_chapter(self):
        """Move to next chapter"""
        if self.currentChapter < self.book.get_total_chapters() - 1:
            self.currentChapter += 1
            self.currentParagraph = 0
            return True
        return False

    def previous_chapter(self):
        """Move to previous chapter"""
        if self.currentChapter > 0:
            self.currentChapter -= 1
            self.currentParagraph = 0
            return True
        return False

    def _get_audio_duration(self):
        """Get total duration for the current audio book."""
        if not self.book or not hasattr(self.book, 'isAudioBook') or not self.book.isAudioBook:
            return 0.0
        return getattr(self.book, 'totalDuration', 0.0) or 0.0

    def _get_current_audio_position(self):
        """Get the best-known absolute playback position in seconds."""
        if not self.book or not hasattr(self.book, 'isAudioBook') or not self.book.isAudioBook:
            return 0.0

        chapter = self.book.get_chapter(self.currentChapter)
        chapterStartTime = chapter.startTime if chapter and hasattr(chapter, 'startTime') else 0.0

        if self.audioPlayer.is_audio_file_loaded():
            if self.audioPlayer.is_audio_file_playing() or self.audioPlayer.is_paused():
                playbackPos = self.audioPlayer.get_audio_position()
                return max(0.0, chapterStartTime + playbackPos)

        if self.savedAudioPosition > 0.0:
            return self.savedAudioPosition

        return max(0.0, chapterStartTime)

    def _set_position_from_audio_time(self, audioPosition):
        """Update chapter tracking from an absolute audio time."""
        if not self.book or not hasattr(self.book, 'isAudioBook') or not self.book.isAudioBook:
            return

        targetPosition = max(0.0, float(audioPosition))
        lastChapterIndex = max(0, self.book.get_total_chapters() - 1)

        for chapterIndex, chapter in enumerate(self.book.chapters):
            if not hasattr(chapter, 'startTime'):
                continue

            chapterEnd = chapter.startTime + getattr(chapter, 'duration', 0.0)
            if chapterIndex == lastChapterIndex:
                if targetPosition >= chapter.startTime:
                    self.currentChapter = chapterIndex
                    return
            elif chapter.startTime <= targetPosition < chapterEnd:
                self.currentChapter = chapterIndex
                return

        self.currentChapter = lastChapterIndex

    def _has_server_sync_target(self):
        """Return True if the current book is linked to Audiobookshelf."""
        if self.isStreaming and self.absSync and self.absSync.is_active():
            return True
        if not self.bookPath:
            return False
        serverLink = self.serverLinkManager.get_link(str(self.bookPath))
        return bool(serverLink and serverLink.get('server_id'))

    def _sync_progress_to_server(self, audioPosition=0.0, updateSession=False, isFinished=None):
        """
        Sync progress to Audiobookshelf server.

        Args:
            audioPosition: Current audio position in seconds
            updateSession: Whether to send live session heartbeat data
            isFinished: Optional finished flag override
        """
        if not self.absClient or not self.absClient.is_authenticated():
            return

        currentTime = max(0.0, float(audioPosition))

        if self.isStreaming and self.absSync and self.absSync.is_active():
            self.absSync.sync_progress(currentTime, updateSession=updateSession, isFinished=isFinished)
            return

        if not self.bookPath:
            return

        serverLink = self.serverLinkManager.get_link(str(self.bookPath))
        if not serverLink:
            return

        serverId = serverLink.get('server_id')
        if not serverId:
            return

        duration = self._get_audio_duration()
        if duration <= 0:
            return

        progress = min(currentTime / duration, 1.0) if duration > 0 else 0.0
        if isFinished is None:
            isFinished = progress >= 0.999

        success = self.absClient.update_progress(serverId, currentTime, duration, progress=progress, isFinished=isFinished)
        if success:
            print(f"Progress synced to server: {progress * 100:.1f}%")

    def _maybe_sync_abs_progress(self, force=False):
        """Sync progress periodically while audio is playing."""
        if not self._has_server_sync_target():
            return

        if not self.book or not hasattr(self.book, 'isAudioBook') or not self.book.isAudioBook:
            return

        syncInterval = max(5, self.config.get_abs_sync_interval())
        now = time.monotonic()
        if not force and self.lastAbsSyncAt and (now - self.lastAbsSyncAt) < syncInterval:
            return

        audioPosition = self._get_current_audio_position()
        self._sync_progress_to_server(audioPosition, updateSession=self.isStreaming)
        self.lastAbsSyncAt = now

    def _close_abs_session(self, finalPosition=None, isFinished=None):
        """Close the active Audiobookshelf session with final progress data."""
        currentTime = self._get_current_audio_position() if finalPosition is None else max(0.0, float(finalPosition))

        if self.absSync and self.absSync.is_active():
            self.absSync.close_session(currentTime=currentTime, isFinished=isFinished)
            self.sessionId = None
            self.lastAbsSyncAt = 0.0
            return

        if self.sessionId and self.absClient:
            duration = self._get_audio_duration()
            progress = min(currentTime / duration, 1.0) if duration > 0 else 0.0
            self.absClient.close_session(
                self.sessionId,
                currentTime=currentTime,
                duration=duration,
                progress=progress,
                timeListened=0.0
            )
            self.sessionId = None
            self.lastAbsSyncAt = 0.0

    def _save_audio_bookmark(self, audioPosition, speakFeedback=True, isFinished=None):
        """Persist the current audio bookmark locally and remotely."""
        if not self.book or not self.bookPath:
            return

        targetPosition = max(0.0, float(audioPosition))
        self._set_position_from_audio_time(targetPosition)
        self.savedAudioPosition = targetPosition

        self.bookmarkManager.save_bookmark(
            self.bookPath,
            self.book.title,
            self.currentChapter,
            self.currentParagraph,
            audioPosition=targetPosition
        )

        self._sync_progress_to_server(targetPosition, updateSession=False, isFinished=isFinished)
        if self.isStreaming and self.absSync:
            self.absSync.mark_progress_checkpoint(targetPosition)

        if speakFeedback:
            self.speechEngine.speak("Bookmark saved")

    def _handle_finished_audiobook(self):
        """Persist completion state when an audiobook reaches the end."""
        duration = self._get_audio_duration()
        finalPosition = duration if duration > 0 else self._get_current_audio_position()

        self.displayText = "End of book reached"
        self.speechEngine.speak("Book finished. To clear bookmarks and restart from beginning, press shift home.")
        self.isPlaying = False
        self._save_audio_bookmark(finalPosition, speakFeedback=False, isFinished=True)
        self._close_abs_session(finalPosition=finalPosition, isFinished=True)

        if self.audioPlayer.is_audio_file_loaded():
            self.audioPlayer.stop_audio_file()

    def _get_current_server_item_id(self):
        """Get the Audiobookshelf item ID for the current book, if any."""
        if self.isStreaming and self.serverBook:
            return self.serverBook.get('id') or self.serverBook.get('libraryItemId')

        if not self.bookPath:
            return None

        serverLink = self.serverLinkManager.get_link(str(self.bookPath))
        if not serverLink:
            return None

        return serverLink.get('server_id')

    def _can_sync_named_bookmarks(self):
        """Return True if named bookmarks can sync for the current book."""
        isAudioBook = self.book and hasattr(self.book, 'isAudioBook') and self.book.isAudioBook
        return bool(
            isAudioBook and
            self.absClient and
            self.absClient.is_authenticated() and
            self._get_current_server_item_id()
        )

    def _sync_named_bookmarks_from_server(self):
        """Fetch Audiobookshelf named bookmarks for the current item and cache them locally."""
        if not self._can_sync_named_bookmarks():
            return False

        itemId = self._get_current_server_item_id()
        serverBookmarks = self.absClient.get_bookmarks(itemId)
        if serverBookmarks is None:
            return False

        originalChapter = self.currentChapter
        originalParagraph = self.currentParagraph

        for serverBookmark in serverBookmarks:
            if not isinstance(serverBookmark, dict):
                continue

            bookmarkTime = int(serverBookmark.get('time', 0) or 0)
            bookmarkTitle = serverBookmark.get('title') or f"Bookmark {bookmarkTime}"
            chapterIndex = self.currentChapter
            paragraphIndex = 0
            if self.book and hasattr(self.book, 'isAudioBook') and self.book.isAudioBook:
                self._set_position_from_audio_time(float(bookmarkTime))
                chapterIndex = self.currentChapter

            self.bookmarkManager.upsert_named_bookmark_from_server(
                self.bookPath,
                bookmarkTitle,
                chapterIndex,
                paragraphIndex,
                audioPosition=float(bookmarkTime),
                serverLibraryItemId=itemId,
                serverTime=bookmarkTime,
                serverCreatedAt=serverBookmark.get('createdAt')
            )

        self.currentChapter = originalChapter
        self.currentParagraph = originalParagraph
        return True

    def _save_named_bookmark_to_server(self, bookmarkName, audioPosition):
        """Create or update a named bookmark on Audiobookshelf for the current item."""
        if not self._can_sync_named_bookmarks():
            return None

        itemId = self._get_current_server_item_id()
        bookmarkTime = int(round(max(0.0, float(audioPosition))))
        return self.absClient.save_bookmark(itemId, bookmarkTime, bookmarkName)

    def _delete_named_bookmark_from_server(self, bookmark):
        """Delete a synced named bookmark from Audiobookshelf."""
        itemId = bookmark.get('serverLibraryItemId') or self._get_current_server_item_id()
        bookmarkTime = bookmark.get('serverTime')
        if not itemId or bookmarkTime is None:
            return True

        if not self.absClient or not self.absClient.is_authenticated():
            return False

        return self.absClient.delete_bookmark(itemId, int(bookmarkTime))

    def save_bookmark(self, speakFeedback=True):
        """Save current position as bookmark

        Args:
            speakFeedback: Whether to speak "Bookmark saved" (default True)
        """
        # Don't save if no book is loaded
        if not self.book:
            return

        # Don't save if user explicitly cleared bookmark
        if self.bookmarkCleared:
            return

        # For multi-file audiobooks, sync currentChapter with mpv playlist position FIRST
        # This prevents saving bookmarks with stale chapter indices
        if hasattr(self.book, 'isMultiFile') and self.book.isMultiFile:
            if self.audioPlayer.is_audio_file_loaded():
                playlistIndex = self.audioPlayer.get_current_playlist_index()
                if playlistIndex != self.currentChapter:
                    self.currentChapter = playlistIndex

        if hasattr(self.book, 'isAudioBook') and self.book.isAudioBook:
            audioPosition = self._get_current_audio_position()
            self._save_audio_bookmark(audioPosition, speakFeedback=speakFeedback)
            return

        self.bookmarkManager.save_bookmark(
            self.bookPath,
            self.book.title,
            self.currentChapter,
            self.currentParagraph,
            audioPosition=0.0
        )

        if speakFeedback:
            self.speechEngine.speak("Bookmark saved")

    def reload_tts_engine(self):
        """Reload TTS engine with current config settings"""
        readerEngine = self.config.get_reader_engine()
        if readerEngine == 'speechd':
            # Using speech-dispatcher, apply settings to reading engine
            self.ttsEngine = None

            # Recreate reading engine
            self.readingEngine = SpeechEngine()

            # Apply saved speech-dispatcher settings
            savedModule = self.config.get_speechd_output_module()
            if savedModule:
                self.readingEngine.set_output_module(savedModule)

            savedVoice = self.config.get_speechd_voice()
            if savedVoice:
                self.readingEngine.set_voice(savedVoice)

            # Apply speech rate
            speechRate = self.config.get_speech_rate()
            self.readingEngine.set_rate(speechRate)

            message = "Speech-dispatcher settings reloaded successfully"
            print(message)
            self.speechEngine.speak(message)
        elif readerEngine == 'screenreader':
            # Route reading through active screen reader via D-Bus
            self.ttsEngine = None
            self.readingEngine = ScreenReaderEngine()
            speechRate = self.config.get_speech_rate()
            self.readingEngine.set_rate(speechRate)

            if not self.readingEngine.is_available():
                message = "Warning: No supported screen reader detected. Falling back to speech-dispatcher."
                print(message)
                self.speechEngine.speak(message)

                self.readingEngine = SpeechEngine()
                savedModule = self.config.get_speechd_output_module()
                if savedModule:
                    self.readingEngine.set_output_module(savedModule)

                savedVoice = self.config.get_speechd_voice()
                if savedVoice:
                    self.readingEngine.set_voice(savedVoice)

                self.readingEngine.set_rate(speechRate)
                self.config.set_reader_engine('speechd')
            else:
                message = f"Screen reader engine active: {self.readingEngine.get_active_reader_name()}"
                print(message)
        else:
            # Reload piper-tts with new voice (check if available first)
            if not TtsEngine.is_available():
                # piper-tts not found, fall back to speech-dispatcher
                message = "Warning: piper-tts not found. Falling back to speech-dispatcher."
                print(message)
                self.speechEngine.speak(message)

                # Switch to speech-dispatcher mode
                self.ttsEngine = None
                self.readingEngine = SpeechEngine()
                speechRate = self.config.get_speech_rate()
                self.readingEngine.set_rate(speechRate)

                # Update config to remember this fallback
                self.config.set_reader_engine('speechd')
            else:
                # piper-tts is available
                self.readingEngine = None
                voiceModel = self.config.get_voice_model()
                self.ttsEngine = TtsEngine(voiceModel)
                message = "Voice reloaded successfully"
                print(message)
                self.speechEngine.speak(message)

    def run_interactive(self):
        """Run in interactive mode with pygame event loop"""
        if not HAS_PYGAME:
            print("\nError: pygame is required for BookStorm")
            print("Install with: pip install pygame")
            return

        if not self.audioPlayer.is_available():
            print("\nError: Could not initialize pygame audio")
            return

        # Initialize pygame display with larger window for large print text
        pygame.init()
        self.screen = pygame.display.set_mode((1600, 900))

        # Set caption - handle case where no book is loaded yet
        if self.book:
            pygame.display.set_caption(f"BookStorm - {self.book.title}")
        else:
            pygame.display.set_caption("BookStorm - Press A/B/R to load book")

        # Initialize font for large print display (72pt for severe visual impairment)
        self.font = pygame.font.Font(None, 96)  # 96 pixels ≈ 72pt
        self.smallFont = pygame.font.Font(None, 36)  # For status info (27pt)

        # Colors
        self.bgColor = (0, 0, 0)  # Black background
        self.textColor = (255, 255, 255)  # White text
        self.statusColor = (180, 180, 180)  # Gray for status

        # Current display text
        if self.book:
            self.displayText = "Press SPACE to start reading"
            self.statusText = f"Book: {self.book.title}"

            # Determine book type for message
            isAudioBook = hasattr(self.book, 'isAudioBook') and self.book.isAudioBook
            bookType = "Audio book" if isAudioBook else "Book"
            self.speechEngine.speak(f"{bookType} loaded, press F1 or question mark for help.")
        else:
            self.displayText = "No book loaded"
            self.statusText = "Press A for Audiobookshelf, B for local books, R for recent books"
            # Speech message already given earlier

        # Cached rendered surfaces to prevent memory leak from re-rendering 30 FPS
        self.cachedDisplayText = None
        self.cachedStatusText = None
        self.cachedSurfaces = []

        self._run_pygame_loop()

    def _render_screen(self):
        """Render text to pygame window"""
        self.screen.fill(self.bgColor)

        # Check if text display is enabled
        showText = self.config.get_show_text()

        if showText:
            # Only re-render if text changed (prevents massive Surface object leak)
            if self.cachedDisplayText != self.displayText or self.cachedStatusText != self.statusText:
                # Explicitly delete old cached surfaces before clearing
                for surfaceType, surface, position in self.cachedSurfaces:
                    del surface
                self.cachedSurfaces.clear()

                # Render status text at top
                statusSurface = self.smallFont.render(self.statusText, True, self.statusColor)
                self.cachedSurfaces.append(('status', statusSurface, (20, 20)))

                # Render main text with word wrapping
                words = self.displayText.split(' ')
                lines = []
                currentLine = []

                for word in words:
                    testLine = ' '.join(currentLine + [word])
                    testSurface = self.font.render(testLine, True, self.textColor)
                    if testSurface.get_width() < 1560:  # Leave 40px margin (1600-40)
                        currentLine.append(word)
                        del testSurface  # Delete test surface immediately
                    else:
                        del testSurface  # Delete test surface immediately
                        if currentLine:
                            lines.append(' '.join(currentLine))
                        currentLine = [word]

                if currentLine:
                    lines.append(' '.join(currentLine))

                # Render wrapped lines and cache them
                yPos = 100
                for line in lines:
                    if yPos > 850:  # Don't render beyond window (900-50 margin)
                        break
                    textSurface = self.font.render(line, True, self.textColor)
                    self.cachedSurfaces.append(('text', textSurface, (20, yPos)))
                    yPos += 110  # Line spacing for 96px font

                # Update cache markers
                self.cachedDisplayText = self.displayText
                self.cachedStatusText = self.statusText

            # Blit cached surfaces
            for surfaceType, surface, position in self.cachedSurfaces:
                self.screen.blit(surface, position)
        else:
            # Show simple message when text display is off
            message = "Text display off (press O for options)"
            textSurface = self.smallFont.render(message, True, self.statusColor)
            textRect = textSurface.get_rect(center=(800, 450))
            self.screen.blit(textSurface, textRect)
            del textSurface

        pygame.display.flip()

    def _run_pygame_loop(self):
        """Main pygame event loop"""
        self.isRunning = True
        self.isPlaying = False
        clock = pygame.time.Clock()
        gcCounter = 0  # Counter for periodic garbage collection
        memoryWarningShown = False  # Track if we've warned about high memory

        try:
            while self.isRunning:
                # Process pygame events
                events = pygame.event.get()
                for event in events:
                    if event.type == pygame.QUIT:
                        self.isRunning = False

                    elif event.type == pygame.KEYDOWN:
                        self._handle_pygame_key(event)

                    elif event.type == SPEECH_FINISHED_EVENT:
                        completionToken = getattr(event, 'completionToken', None)
                        self._process_speech_completion(completionToken)

                # Explicitly delete event objects to help GC
                del events

                # Handle sleep timer fade-out (10 seconds before expiration)
                if not self.isFadingOut and self.sleepTimerMenu.should_start_fadeout():
                    # Start fade-out
                    self.isFadingOut = True
                    self.fadeStartVolume = self.audioPlayer.get_volume()
                    self.fadeStartTime = time.time()

                # Update volume during fade-out
                if self.isFadingOut:
                    elapsed = time.time() - self.fadeStartTime
                    fadeProgress = elapsed / 10.0  # 10 second fade
                    if fadeProgress >= 1.0:
                        # Fade complete - stop at 25% volume
                        targetVolume = int(self.fadeStartVolume * 0.25)
                        self.audioPlayer.set_volume(targetVolume)
                    else:
                        # Calculate current volume (linear fade from start to 25%)
                        # Formula: startVolume - (startVolume * 0.75 * progress)
                        # This fades from 100% → 25% over 10 seconds
                        currentVolume = int(self.fadeStartVolume * (1.0 - 0.75 * fadeProgress))
                        self.audioPlayer.set_volume(currentVolume)

                # Check if sleep timer has expired
                if self.sleepTimerMenu.check_timer():
                    self.speechEngine.speak("Sleep timer expired. Goodbye.")
                    self.isRunning = False
                    self.isPlaying = False

                # Check if we need to advance to next paragraph/chapter
                # Callback-driven engines use SPEECH_FINISHED_EVENT for auto-advance
                isAudioBook = self.book and hasattr(self.book, 'isAudioBook') and self.book.isAudioBook
                readerEngine = self.config.get_reader_engine()
                # Don't auto-advance if in any menu
                inAnyMenu = self._is_in_any_menu()

                self._flush_pending_speech_completion()

                if self.isPlaying and not inAnyMenu and self.book:
                    if isAudioBook:
                        self._maybe_sync_abs_progress()

                        # For multi-file audiobooks, sync playlist position periodically
                        # This keeps currentChapter in sync with mpv's actual position
                        if hasattr(self.book, 'isMultiFile') and self.book.isMultiFile:
                            if self.audioPlayer.is_audio_file_loaded():
                                playlistIndex = self.audioPlayer.get_current_playlist_index()
                                if playlistIndex != self.currentChapter:
                                    self.currentChapter = playlistIndex
                                    # Update status display with new chapter info
                                    chapter = self.book.get_chapter(self.currentChapter)
                                    if chapter:
                                        self.statusText = f"Ch {self.currentChapter + 1}/{self.book.get_total_chapters()}: {chapter.title}"

                        # Check if audio file playback finished
                        if not self.audioPlayer.is_audio_file_playing() and not self.audioPlayer.is_paused():
                            # Audio chapter finished, advance to next chapter
                            if not self.next_chapter():
                                self._handle_finished_audiobook()
                            else:
                                # Start next chapter
                                self._start_paragraph_playback()
                    elif readerEngine == 'piper':
                        # Check if TTS audio has finished playing
                        # Only auto-advance if NOT paused (to avoid skipping when user pauses)
                        if not self.audioPlayer.is_paused():
                            playbackFinished = not self.audioPlayer.is_audio_file_playing()

                            if playbackFinished:
                                # Current paragraph finished, advance
                                if not self.next_paragraph():
                                    self.displayText = "End of book reached"
                                    self.isPlaying = False
                                    self.save_bookmark(speakFeedback=False)
                                else:
                                    # Start next paragraph with error recovery
                                    try:
                                        self._start_paragraph_playback()
                                    except Exception as e:
                                        print(f"Error starting playback: {e}")
                                        self.speechEngine.speak("Playback error")
                                        self.isPlaying = False

                # Render the screen
                self._render_screen()

                # Periodic garbage collection to prevent memory creep
                # Every ~10 seconds (300 frames at 30 FPS) run GC
                gcCounter += 1
                if gcCounter >= 300:
                    # Alternate between fast (gen 0) and full GC
                    # At 300: gen 0 only (fast)
                    # At 600: full collection (all generations)
                    if gcCounter >= 600:
                        gc.collect()  # Full collection every 20 seconds
                        gcCounter = 0  # Reset counter after full GC
                    else:
                        gc.collect(generation=0)  # Fast collection at 10 seconds
                        # Don't reset - let it reach 600 for full GC

                    # Memory watchdog: warn if using 50% of available system memory
                    try:
                        # Get CURRENT memory usage (not peak) from /proc/self/status
                        currentMemMb = None
                        try:
                            with open('/proc/self/status', 'r') as statusFile:
                                for line in statusFile:
                                    if line.startswith('VmRSS:'):
                                        # VmRSS is in kB
                                        currentMemMb = int(line.split()[1]) / 1024
                                        break
                        except (FileNotFoundError, IOError):
                            # Fall back to resource module (gives peak, not current)
                            import resource
                            # pylint: disable=no-member
                            currentMemMb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

                        # Get total system memory from /proc/meminfo
                        totalMemMb = 8192  # Default 8GB if can't read
                        try:
                            with open('/proc/meminfo', 'r') as meminfoFile:
                                for line in meminfoFile:
                                    if line.startswith('MemTotal:'):
                                        # MemTotal is in kB
                                        totalMemMb = int(line.split()[1]) / 1024
                                        break
                        except (FileNotFoundError, IOError):
                            pass

                        # Calculate thresholds as percentages of total memory
                        cleanupThreshold = totalMemMb * 0.4  # 40% triggers cleanup
                        warningThreshold = totalMemMb * 0.5  # 50% triggers warning

                        if currentMemMb and currentMemMb > cleanupThreshold:
                            if not memoryWarningShown:
                                print(f"Memory usage: {currentMemMb:.0f}MB ({currentMemMb/totalMemMb*100:.1f}% of {totalMemMb:.0f}MB) - performing aggressive cleanup")
                                # Force aggressive cleanup
                                if hasattr(self, 'parser') and self.parser:
                                    self.parser.cleanup()
                                # Clear any cached pygame surfaces
                                if hasattr(self, 'cachedSurfaces'):
                                    for surfaceType, surface, position in self.cachedSurfaces:
                                        del surface
                                    self.cachedSurfaces.clear()
                                # Force mpv player cleanup
                                if hasattr(self, 'audioPlayer') and self.audioPlayer:
                                    self.audioPlayer._cleanup_temp_files()
                                # Additional garbage collection
                                gc.collect()
                                gc.collect()  # Second pass

                            if currentMemMb > warningThreshold and not memoryWarningShown:
                                memoryWarningShown = True
                                self.speechEngine.speak("Warning: High memory usage detected. Consider restarting BookStorm soon.")
                    except Exception as e:
                        print(f"Memory monitoring error: {e}")
                        pass

                # Limit to 30 FPS to avoid CPU spinning
                clock.tick(30)

        except KeyboardInterrupt:
            print("\n\nInterrupted")
        finally:
            # Save bookmark BEFORE stopping (so we can get current position)
            self.save_bookmark(speakFeedback=False)
            self._close_abs_session()

            # Stop playback
            readerEngine = self.config.get_reader_engine()
            if readerEngine in ['speechd', 'screenreader']:
                if self.readingEngine:
                    self.readingEngine.cancel_reading()
            else:
                # Stop audio player (handles both TTS and audio books)
                self.audioPlayer.stop()
                if self.audioPlayer.is_audio_file_loaded():
                    self.audioPlayer.stop_audio_file()

            # Clean up speech engines
            if self.speechEngine:
                self.speechEngine.close()
            if readerEngine in ['speechd', 'screenreader'] and self.readingEngine:
                self.readingEngine.close()

            # Clean up audio player
            if self.audioPlayer:
                try:
                    self.audioPlayer.cleanup()
                except Exception as e:
                    print(f"Error cleaning up audio player: {e}")

            # Clear pygame resources
            self.cachedSurfaces.clear()
            pygame.quit()

    def _handle_pygame_key(self, event):
        """Handle pygame key event"""
        # Check if in Audiobookshelf menu
        if self.absMenu and self.absMenu.is_in_menu():
            self._handle_audiobookshelf_key(event)
            return

        # Check if in recent books menu
        if self.recentBooksMenu.is_in_menu():
            self._handle_recent_books_key(event)
            return

        # Check if in bookmarks menu
        if self.bookmarksMenu.is_in_menu():
            self._handle_bookmarks_key(event)
            return

        # Check if in book browser
        if self.bookSelector.is_in_browser():
            self._handle_browser_key(event)
            return

        # Check if in sleep timer menu
        if self.sleepTimerMenu.is_in_menu():
            self._handle_sleep_timer_key(event)
            return

        # Check if in help menu
        if self.helpMenu.is_in_menu():
            self._handle_help_menu_key(event)
            return

        # Check if in options menu
        if self.optionsMenu.is_in_menu():
            self._handle_menu_key(event)
            return

        # Check for shift modifier
        mods = pygame.key.get_mods()
        shiftPressed = mods & pygame.KMOD_SHIFT

        # Control key by itself: Stop speech-dispatcher (interrupt speech)
        if event.key == pygame.K_LCTRL or event.key == pygame.K_RCTRL:
            if self.speechEngine:
                self.speechEngine.stop()
            return

        if event.key == pygame.K_SPACE:
            # Toggle play/pause (only if book is loaded)
            if not self.book:
                self.speechEngine.speak("No book loaded. Press A for Audiobookshelf, B for local books, or R for recent books.")
                return

            isAudioBook = hasattr(self.book, 'isAudioBook') and self.book.isAudioBook
            readerEngine = self.config.get_reader_engine()

            if not self.isPlaying:
                self.isPlaying = True
                self._start_paragraph_playback()
            else:
                # Toggle pause/resume
                if isAudioBook:
                    # Handle audio book pause/resume
                    if self.audioPlayer.is_paused():
                        self.audioPlayer.resume_audio_file()
                        if self.isStreaming and self.absSync:
                            self.absSync.mark_progress_checkpoint(self._get_current_audio_position())
                    else:
                        self._sync_progress_to_server(self._get_current_audio_position(), updateSession=False)
                        self.audioPlayer.pause_audio_file()
                        if self.isStreaming and self.absSync:
                            self.absSync.mark_progress_checkpoint(self._get_current_audio_position())
                elif readerEngine in ['speechd', 'screenreader']:
                    # Handle callback-driven text reading pause/resume
                    if self.readingEngine.is_reading_paused():
                        self.readingEngine.resume_reading()
                    else:
                        self.readingEngine.pause_reading()
                else:
                    # Handle piper-tts pause/resume (now uses audio file methods)
                    if self.audioPlayer.is_paused():
                        self.audioPlayer.resume_audio_file()
                    else:
                        self.audioPlayer.pause_audio_file()

        elif event.key == pygame.K_n:
            if not self.book:
                self.speechEngine.speak("No book loaded")
                return

            isAudioBook = hasattr(self.book, 'isAudioBook') and self.book.isAudioBook

            if shiftPressed or isAudioBook:
                # Next chapter (or for audio books, always go to next chapter)
                wasPlaying = self.isPlaying

                # For audio books, just pause - don't stop
                if isAudioBook:
                    if self.audioPlayer.is_audio_file_playing():
                        self.audioPlayer.pause_audio_file()
                else:
                    self._stop_playback()

                if self.next_chapter():
                    if wasPlaying:
                        self.isPlaying = True
                        self._start_paragraph_playback()
                else:
                    self.speechEngine.speak("No next chapter")
                    self.isPlaying = False
            else:
                # Next paragraph (text books only)
                self._stop_playback()
                if self.next_paragraph():
                    self.speechEngine.speak(f"Paragraph {self.currentParagraph + 1}")
                    if self.isPlaying:
                        self._start_paragraph_playback()
                else:
                    self.speechEngine.speak("End of book")
                    self.isPlaying = False

        elif event.key == pygame.K_p:
            if not self.book:
                self.speechEngine.speak("No book loaded")
                return

            isAudioBook = hasattr(self.book, 'isAudioBook') and self.book.isAudioBook

            if shiftPressed or isAudioBook:
                # Previous chapter (or for audio books, always go to previous chapter)
                wasPlaying = self.isPlaying

                # For audio books, just pause - don't stop
                if isAudioBook:
                    if self.audioPlayer.is_audio_file_playing():
                        self.audioPlayer.pause_audio_file()
                else:
                    self._stop_playback()

                if self.previous_chapter():
                    if wasPlaying:
                        self.isPlaying = True
                        self._start_paragraph_playback()
                else:
                    self.speechEngine.speak("No previous chapter")
            else:
                # Previous paragraph (text books only)
                self._stop_playback()
                if self.previous_paragraph():
                    self.speechEngine.speak(f"Paragraph {self.currentParagraph + 1}")
                    if self.isPlaying:
                        self._start_paragraph_playback()
                else:
                    self.speechEngine.speak("Beginning of book")

        elif event.key == pygame.K_s:
            if not self.book:
                self.speechEngine.speak("No book loaded")
                return

            isAudioBook = hasattr(self.book, 'isAudioBook') and self.book.isAudioBook
            readerEngine = self.config.get_reader_engine()

            # Pause playback while saving
            wasPaused = False
            if isAudioBook:
                wasPaused = self.audioPlayer.is_paused()
                if not wasPaused and self.audioPlayer.is_audio_file_playing():
                    self.audioPlayer.pause_audio_file()
            elif readerEngine in ['speechd', 'screenreader']:
                wasPaused = self.readingEngine.is_reading_paused()
                if not wasPaused and self.readingEngine.is_reading_active():
                    self.readingEngine.pause_reading()
            else:
                wasPaused = self.audioPlayer.is_paused()
                if not wasPaused and self.audioPlayer.is_audio_file_playing():
                    self.audioPlayer.pause_audio_file()

            # Re-enable auto-saving if it was disabled
            self.bookmarkCleared = False

            # Speak feedback (safe with separate sessions)
            self.save_bookmark(speakFeedback=True)

            # Resume playback
            if not wasPaused and self.isPlaying:
                if isAudioBook:
                    self.audioPlayer.resume_audio_file()
                elif readerEngine in ['speechd', 'screenreader']:
                    self.readingEngine.resume_reading()
                else:
                    self.audioPlayer.resume_audio_file()

        elif event.key == pygame.K_PAGEUP:
            # Increase speech rate
            readerEngine = self.config.get_reader_engine()
            currentRate = self.config.get_speech_rate()
            newRate = min(100, currentRate + 10)
            self.config.set_speech_rate(newRate)
            self.speechEngine.set_rate(newRate)
            # Apply to reading engine as well
            if readerEngine in ['speechd', 'screenreader']:
                self.readingEngine.set_rate(newRate)
                # If currently reading, restart paragraph to apply new rate immediately
                if self.isPlaying and self.readingEngine.is_reading_active():
                    self._restart_current_paragraph()
            self.speechEngine.speak(f"Speech rate: {newRate}")

        elif event.key == pygame.K_PAGEDOWN:
            # Decrease speech rate
            readerEngine = self.config.get_reader_engine()
            currentRate = self.config.get_speech_rate()
            newRate = max(-100, currentRate - 10)
            self.config.set_speech_rate(newRate)
            self.speechEngine.set_rate(newRate)
            # Apply to reading engine as well
            if readerEngine in ['speechd', 'screenreader']:
                self.readingEngine.set_rate(newRate)
                # If currently reading, restart paragraph to apply new rate immediately
                if self.isPlaying and self.readingEngine.is_reading_active():
                    self._restart_current_paragraph()
            self.speechEngine.speak(f"Speech rate: {newRate}")

        elif event.key == pygame.K_b:
            # Open book browser - reset to library directory if set
            libraryDir = self.config.get_library_directory()
            if libraryDir and Path(libraryDir).exists():
                self.bookSelector.reset_to_directory(libraryDir)
            self.bookSelector.enter_browser()

        elif event.key == pygame.K_r:
            # Open recent books menu
            self.recentBooksMenu.enter_menu()

        elif event.key == pygame.K_k:
            # Open bookmarks menu
            if self.book:
                self._sync_named_bookmarks_from_server()
                self.bookmarksMenu.enter_menu(str(self.bookPath))
            else:
                self.speechEngine.speak("No book loaded")

        elif event.key == pygame.K_a:
            # Open Audiobookshelf browser
            self._open_audiobookshelf_browser()

        elif event.key == pygame.K_o:
            # Open options menu
            self.optionsMenu.enter_menu()

        elif self._is_help_key(event):
            self.helpMenu.enter_menu(self._get_help_lines())

        elif event.key == pygame.K_i:
            if not self.book:
                self.speechEngine.speak("No book loaded. Press F1 or question mark for help.")
                return

            # Speak current position info
            chapter = self.book.get_chapter(self.currentChapter)
            if chapter:
                info = f"{self.book.title}. {self.book.get_total_chapters()} chapters. Currently at chapter {self.currentChapter + 1}: {chapter.title}. Paragraph {self.currentParagraph + 1} of {chapter.get_total_paragraphs()}"
                self.speechEngine.speak(info)

        elif event.key == pygame.K_t:
            # Speak time remaining on sleep timer
            if self.sleepTimerMenu.is_timer_active():
                timeRemaining = self.sleepTimerMenu.get_time_remaining()
                if timeRemaining:
                    minutes, seconds = timeRemaining
                    if minutes > 0:
                        self.speechEngine.speak(f"{minutes} minutes {seconds} seconds remaining")
                    else:
                        self.speechEngine.speak(f"{seconds} seconds remaining")
            else:
                self.speechEngine.speak("No sleep timer active")

        elif event.key == pygame.K_q or event.key == pygame.K_ESCAPE:
            # Open sleep timer menu
            self.sleepTimerMenu.enter_menu()

        elif event.key == pygame.K_RIGHTBRACKET:
            # Increase playback speed (works for all books!)
            if self.book:
                currentSpeed = self.config.get_playback_speed()
                newSpeed = min(2.0, currentSpeed + 0.1)
                newSpeed = round(newSpeed, 1)  # Round to 1 decimal place
                self._change_playback_speed(newSpeed)
            else:
                self.speechEngine.speak("No book loaded")

        elif event.key == pygame.K_LEFTBRACKET:
            # Decrease playback speed (works for all books!)
            if self.book:
                currentSpeed = self.config.get_playback_speed()
                newSpeed = max(0.5, currentSpeed - 0.1)
                newSpeed = round(newSpeed, 1)  # Round to 1 decimal place
                self._change_playback_speed(newSpeed)
            else:
                self.speechEngine.speak("No book loaded")

        elif event.key == pygame.K_BACKSPACE:
            # Reset playback speed to 1.0
            # Only if not in a menu (menus handle backspace themselves)
            if not (self.optionsMenu.is_in_menu() or
                   self.bookSelector.is_in_browser() or
                   self.sleepTimerMenu.is_in_menu() or
                   self.recentBooksMenu.is_in_menu() or
                   (self.absMenu and self.absMenu.is_in_menu())):
                if self.book:
                    self._change_playback_speed(1.0)
                else:
                    self.speechEngine.speak("No book loaded")

        elif event.key == pygame.K_0:
            # Increase volume (audio books and Piper-TTS - mpv handles volume control)
            if self.book:
                isAudioBook = hasattr(self.book, 'isAudioBook') and self.book.isAudioBook
                isPiperMode = self.config.get_reader_engine() == 'piper'
                if isAudioBook or isPiperMode:
                    newVolume = self.audioPlayer.increase_volume(5)
                    self.config.set_volume(newVolume)
                    self.speechEngine.speak(f"Volume {newVolume}")
                else:
                    self.speechEngine.speak("Volume control only works for audio books and Piper TTS mode")
            else:
                self.speechEngine.speak("No book loaded")

        elif event.key == pygame.K_9:
            # Decrease volume (audio books and Piper-TTS - mpv handles volume control)
            if self.book:
                isAudioBook = hasattr(self.book, 'isAudioBook') and self.book.isAudioBook
                isPiperMode = self.config.get_reader_engine() == 'piper'
                if isAudioBook or isPiperMode:
                    newVolume = self.audioPlayer.decrease_volume(5)
                    self.config.set_volume(newVolume)
                    self.speechEngine.speak(f"Volume {newVolume}")
                else:
                    self.speechEngine.speak("Volume control only works for audio books and Piper TTS mode")
            else:
                self.speechEngine.speak("No book loaded")

        elif event.key == pygame.K_HOME and shiftPressed:
            # Shift+Home: Clear ALL bookmarks and jump to beginning of book (fresh start)
            if not self.book:
                self.speechEngine.speak("No book loaded")
            else:
                # Stop current playback
                wasPlaying = self.isPlaying
                self.isPlaying = False
                self._stop_playback()

                namedBookmarks = self.bookmarkManager.get_named_bookmarks(self.bookPath)
                serverDeleteFailed = False
                for bookmark in namedBookmarks:
                    if bookmark.get('serverTime') is None:
                        continue
                    if not self._delete_named_bookmark_from_server(bookmark):
                        serverDeleteFailed = True
                        break

                # Delete ALL bookmarks for current book (auto-save + named)
                self.bookmarkManager.delete_bookmark(self.bookPath)  # Auto-save bookmark
                if not serverDeleteFailed:
                    self.bookmarkManager.delete_all_named_bookmarks(self.bookPath)  # Named bookmarks
                self.bookmarkCleared = True  # Mark that bookmark was explicitly cleared

                if serverDeleteFailed:
                    self.speechEngine.speak("Could not clear server bookmarks")
                    return

                # Jump to beginning
                self.currentChapter = 0
                self.currentParagraph = 0
                self.savedAudioPosition = 0.0

                # For audio books, we need to restart playback from position 0
                # We can't just seek when stopped - mpv won't load the file metadata when idle
                if hasattr(self.book, 'isAudioBook') and self.book.isAudioBook:
                    if hasattr(self.book, 'isMultiFile') and self.book.isMultiFile:
                        # Multi-file: Start playing first file from beginning
                        if self.audioPlayer.is_audio_file_loaded():
                            # Stop completely to reset state
                            self.audioPlayer.stop_audio_file()
                            # Set playlist to first file (don't wait for load - play will trigger it)
                            self.audioPlayer.seek_to_playlist_index(0, waitForLoad=False)
                            # Start playback from position 0
                            self.audioPlayer.play_audio_file(startPosition=0.0)
                    else:
                        # Single-file: restart from beginning
                        if self.audioPlayer.is_audio_file_loaded():
                            self.audioPlayer.stop_audio_file()
                            self.audioPlayer.play_audio_file(startPosition=0.0)

                    # Mark as playing
                    self.isPlaying = True
                    self.isAudioBook = True

                # Update display
                if self.config.get_show_text():
                    self._render_screen()

                self.speechEngine.speak("All bookmarks cleared. Playing from beginning of book.")

                # Note: For audio books, we auto-start playback from the beginning
                # For text books, this is just a position reset and user needs to press space

        elif event.key == pygame.K_LEFT:
            # Left arrow: Seek backward (audio books) or previous paragraph (text books)
            if not self.book:
                self.speechEngine.speak("No book loaded")
                return

            isAudioBook = hasattr(self.book, 'isAudioBook') and self.book.isAudioBook

            if isAudioBook:
                # Audio book: Seek backward by 5 or 30 seconds
                seekTime = -30 if shiftPressed else -5
                self._seek_audio_by_time(seekTime)
            else:
                # Text book: Previous paragraph or chapter
                if shiftPressed:
                    # Shift+Left: Previous chapter
                    self._stop_playback()
                    if self.previous_chapter():
                        if self.isPlaying:
                            self._start_paragraph_playback()
                    else:
                        self.speechEngine.speak("No previous chapter")
                else:
                    # Left: Previous paragraph
                    self._stop_playback()
                    if self.previous_paragraph():
                        self.speechEngine.speak(f"Paragraph {self.currentParagraph + 1}")
                        if self.isPlaying:
                            self._start_paragraph_playback()
                    else:
                        self.speechEngine.speak("Beginning of book")

        elif event.key == pygame.K_RIGHT:
            # Right arrow: Seek forward (audio books) or next paragraph (text books)
            if not self.book:
                self.speechEngine.speak("No book loaded")
                return

            isAudioBook = hasattr(self.book, 'isAudioBook') and self.book.isAudioBook

            if isAudioBook:
                # Audio book: Seek forward by 5 or 30 seconds
                seekTime = 30 if shiftPressed else 5
                self._seek_audio_by_time(seekTime)
            else:
                # Text book: Next paragraph or chapter
                if shiftPressed:
                    # Shift+Right: Next chapter
                    self._stop_playback()
                    if self.next_chapter():
                        if self.isPlaying:
                            self._start_paragraph_playback()
                    else:
                        self.speechEngine.speak("No next chapter")
                        self.isPlaying = False
                else:
                    # Right: Next paragraph
                    self._stop_playback()
                    if self.next_paragraph():
                        self.speechEngine.speak(f"Paragraph {self.currentParagraph + 1}")
                        if self.isPlaying:
                            self._start_paragraph_playback()
                    else:
                        self.speechEngine.speak("End of book")
                        self.isPlaying = False

        elif event.key == pygame.K_UP:
            # Up arrow: Seek backward (audio books) or skip paragraphs backward (text books)
            if not self.book:
                self.speechEngine.speak("No book loaded")
                return

            isAudioBook = hasattr(self.book, 'isAudioBook') and self.book.isAudioBook

            if isAudioBook:
                # Audio book: Seek backward by 1 or 5 minutes
                seekTime = -300 if shiftPressed else -60
                self._seek_audio_by_time(seekTime)
            else:
                # Text book: Jump to first paragraph of chapter (Shift) or skip back 5 paragraphs
                if shiftPressed:
                    # Shift+Up: Jump to first paragraph of chapter
                    if self.currentParagraph > 0:
                        self._stop_playback()
                        self.currentParagraph = 0
                        self.speechEngine.speak(f"First paragraph")
                        if self.isPlaying:
                            self._start_paragraph_playback()
                    else:
                        self.speechEngine.speak("Already at first paragraph")
                else:
                    # Up: Skip back 5 paragraphs
                    self._stop_playback()
                    targetParagraph = max(0, self.currentParagraph - 5)
                    moved = self.currentParagraph != targetParagraph
                    self.currentParagraph = targetParagraph

                    if moved:
                        self.speechEngine.speak(f"Paragraph {self.currentParagraph + 1}")
                        if self.isPlaying:
                            self._start_paragraph_playback()
                    else:
                        self.speechEngine.speak("Beginning of chapter")

        elif event.key == pygame.K_DOWN:
            # Down arrow: Seek forward (audio books) or skip paragraphs forward (text books)
            if not self.book:
                self.speechEngine.speak("No book loaded")
                return

            isAudioBook = hasattr(self.book, 'isAudioBook') and self.book.isAudioBook

            if isAudioBook:
                # Audio book: Seek forward by 1 or 5 minutes
                seekTime = 300 if shiftPressed else 60
                self._seek_audio_by_time(seekTime)
            else:
                # Text book: Jump to last paragraph of chapter (Shift) or skip forward 5 paragraphs
                chapter = self.book.get_chapter(self.currentChapter)
                if not chapter:
                    return

                if shiftPressed:
                    # Shift+Down: Jump to last paragraph of chapter
                    lastParagraph = chapter.get_total_paragraphs() - 1
                    if self.currentParagraph < lastParagraph:
                        self._stop_playback()
                        self.currentParagraph = lastParagraph
                        self.speechEngine.speak(f"Last paragraph")
                        if self.isPlaying:
                            self._start_paragraph_playback()
                    else:
                        self.speechEngine.speak("Already at last paragraph")
                else:
                    # Down: Skip forward 5 paragraphs
                    self._stop_playback()
                    maxParagraph = chapter.get_total_paragraphs() - 1
                    targetParagraph = min(maxParagraph, self.currentParagraph + 5)
                    moved = self.currentParagraph != targetParagraph
                    self.currentParagraph = targetParagraph

                    if moved:
                        self.speechEngine.speak(f"Paragraph {self.currentParagraph + 1}")
                        if self.isPlaying:
                            self._start_paragraph_playback()
                    else:
                        self.speechEngine.speak("End of chapter")

    def _is_in_any_menu(self):
        """Return True when any modal menu/browser is active."""
        return (
            self.optionsMenu.is_in_menu() or
            self.bookmarksMenu.is_in_menu() or
            self.bookSelector.is_in_browser() or
            self.sleepTimerMenu.is_in_menu() or
            self.helpMenu.is_in_menu() or
            self.recentBooksMenu.is_in_menu() or
            (self.absMenu and self.absMenu.is_in_menu())
        )

    def _queue_pending_speech_completion(self, completionToken=None):
        """Store a completion event to process after menus close."""
        self.hasPendingSpeechCompletion = True
        self.pendingSpeechCompletionToken = completionToken

    def _process_speech_completion(self, completionToken=None):
        """Advance paragraph/chapter for callback-driven completion events."""
        if not (self.isPlaying and self.book):
            return
        if hasattr(self.book, 'isAudioBook') and self.book.isAudioBook:
            return

        readerEngine = self.config.get_reader_engine()
        if readerEngine not in ['speechd', 'screenreader']:
            return

        if completionToken is None:
            return
        try:
            tokenInt = int(completionToken)
        except Exception:
            return
        if tokenInt != self.expectedSpeechCompletionToken:
            return

        if self._is_in_any_menu():
            self._queue_pending_speech_completion(tokenInt)
            return

        if self.readingEngine and self.readingEngine.is_reading_paused():
            return
        if self.readingEngine:
            tokenCheck = getattr(self.readingEngine, 'is_completion_token_current', None)
            if callable(tokenCheck) and not tokenCheck(tokenInt):
                return

        if not self.next_paragraph():
            self.displayText = "End of book reached"
            self.isPlaying = False
            self.save_bookmark(speakFeedback=False)
        else:
            self._start_paragraph_playback()

    def _flush_pending_speech_completion(self):
        """Process a deferred completion event once menus are closed."""
        if not self.hasPendingSpeechCompletion:
            return
        if self._is_in_any_menu():
            return

        completionToken = self.pendingSpeechCompletionToken
        self.hasPendingSpeechCompletion = False
        self.pendingSpeechCompletionToken = None
        self._process_speech_completion(completionToken)

    def _is_help_key(self, event):
        """Return True when the key event should open or close help."""
        if event.key == pygame.K_F1:
            return True
        return getattr(event, 'unicode', '') == '?'

    def _get_help_lines(self):
        """Return help lines for the current reading mode."""
        isAudioBook = bool(self.book and hasattr(self.book, 'isAudioBook') and self.book.isAudioBook)

        if isAudioBook:
            return [
                "Space: play or pause.",
                "N: next chapter.",
                "P: previous chapter.",
                "Left or right arrow: seek 5 seconds.",
                "Shift left or right arrow: seek 30 seconds.",
                "Up or down arrow: seek 1 minute.",
                "Shift up or down arrow: seek 5 minutes.",
                "S: save bookmark.",
                "K: bookmarks menu.",
                "R: recent books.",
                "B: browse local books.",
                "A: Audiobookshelf browser.",
                "O: options menu.",
                "I: current info.",
                "Right bracket: increase playback speed.",
                "Left bracket: decrease playback speed.",
                "Backspace: reset playback speed.",
                "0: increase volume.",
                "9: decrease volume.",
                "Shift home: clear bookmark and restart at beginning.",
                "Control: stop speech.",
                "T: time remaining.",
                "F1 or question mark: help.",
                "Q or escape: quit or sleep timer."
            ]

        return [
            "Space: play or pause.",
            "N: next paragraph.",
            "P: previous paragraph.",
            "Shift N: next chapter.",
            "Shift P: previous chapter.",
            "Left or right arrow: previous or next paragraph.",
            "Shift left or right arrow: previous or next chapter.",
            "Up or down arrow: skip 5 paragraphs.",
            "Shift up: first paragraph.",
            "Shift down: last paragraph.",
            "S: save bookmark.",
            "K: bookmarks menu.",
            "R: recent books.",
            "B: browse local books.",
            "A: Audiobookshelf browser.",
            "O: options menu.",
            "I: current info.",
            "Page up or page down: adjust speech rate.",
            "Right bracket: increase playback speed.",
            "Left bracket: decrease playback speed.",
            "Backspace: reset playback speed.",
            "Shift home: clear bookmark and restart at beginning.",
            "Control: stop speech.",
            "T: time remaining.",
            "F1 or question mark: help.",
            "Q or escape: quit or sleep timer."
        ]

    def _handle_help_menu_key(self, event):
        """Handle key events when in help menu."""
        if event.key == pygame.K_UP:
            self.helpMenu.navigate_menu('up')
        elif event.key == pygame.K_DOWN:
            self.helpMenu.navigate_menu('down')
        elif event.key == pygame.K_ESCAPE or event.key == pygame.K_RETURN or self._is_help_key(event):
            self.helpMenu.exit_menu()
            self.speechEngine.speak("Help closed.")

    def _handle_recent_books_key(self, event):
        """Handle key events when in recent books menu"""
        if event.key == pygame.K_UP:
            self.recentBooksMenu.navigate_menu('up')
        elif event.key == pygame.K_DOWN:
            self.recentBooksMenu.navigate_menu('down')
        elif event.key == pygame.K_RETURN:
            # Select book
            selectedBook = self.recentBooksMenu.activate_current_item()
            if selectedBook:
                # Book was selected, load it
                self.recentBooksMenu.exit_menu()
                self._load_new_book(selectedBook)
        elif event.key == pygame.K_ESCAPE:
            self.recentBooksMenu.exit_menu()

    def _handle_bookmarks_key(self, event):
        """Handle key events when in bookmarks menu"""
        if event.key == pygame.K_UP:
            self.bookmarksMenu.navigate_menu('up')
        elif event.key == pygame.K_DOWN:
            self.bookmarksMenu.navigate_menu('down')
        elif event.key == pygame.K_RETURN:
            # Activate current item
            result = self.bookmarksMenu.activate_current_item()
            if result:
                action = result.get('action')

                if action == 'jump':
                    # Jump to bookmark
                    bookmark = result.get('bookmark')
                    self._jump_to_bookmark(bookmark)
                    self.bookmarksMenu.exit_menu()

                elif action == 'create':
                    # Create new bookmark
                    self._create_named_bookmark()

        elif event.key == pygame.K_DELETE or event.key == pygame.K_d:
            # Delete current bookmark
            bookmark = self.bookmarksMenu.get_current_bookmark()
            if not bookmark:
                self.bookmarksMenu.delete_current_bookmark()
                return

            if bookmark.get('serverTime') is not None:
                if not self._delete_named_bookmark_from_server(bookmark):
                    self.speechEngine.speak("Could not delete bookmark from Audiobookshelf")
                    return

            self.bookmarksMenu.remove_bookmark(bookmark['id'], bookmark.get('name'))

        elif event.key == pygame.K_ESCAPE:
            self.bookmarksMenu.exit_menu()

    def _jump_to_bookmark(self, bookmark):
        """
        Jump to a named bookmark

        Args:
            bookmark: Bookmark dictionary
        """
        chapterIndex = bookmark['chapterIndex']
        paragraphIndex = bookmark['paragraphIndex']
        audioPosition = bookmark.get('audioPosition', 0.0)
        bookmarkName = bookmark['name']

        # Check if this is an audio book
        isAudioBook = hasattr(self.book, 'isAudioBook') and self.book.isAudioBook

        # For text books, stop playback before jumping
        # For audio books, we'll pause and seek without stopping (to keep mpv active)
        if not isAudioBook:
            self.isPlaying = False
            if self.ttsEngine:
                self.audioPlayer.stop()
            else:
                self.readingEngine.stop()
            self.audioPlayer.stop_audio_file()

        # Update position
        self.currentChapter = chapterIndex
        self.currentParagraph = paragraphIndex

        # For audio books, we need to seek to the bookmark position
        if isAudioBook:
            # Check if audio is currently playing or has been played before
            wasPlaying = self.isPlaying
            hasBeenPlayed = self.audioPlayer.is_audio_file_playing() or self.audioPlayer.is_paused()

            # If never played, we'll start playback at the bookmark position
            # If already playing/paused, we'll seek to the position
            if hasBeenPlayed:
                # Pause if playing (keeps mpv active for seeking)
                if self.audioPlayer.is_audio_file_playing():
                    self.audioPlayer.pause_audio_file()

            # Find chapter that contains this audio position
            for i, chapter in enumerate(self.book.chapters):
                if hasattr(chapter, 'startTime'):
                    chapterEnd = chapter.startTime + chapter.duration
                    if chapter.startTime <= audioPosition < chapterEnd:
                        self.currentChapter = i
                        # Position within chapter
                        positionInChapter = audioPosition - chapter.startTime

                        # For multi-file audiobooks, seek to correct file in playlist
                        if hasattr(self.book, 'isMultiFile') and self.book.isMultiFile:
                            if self.audioPlayer.is_audio_file_loaded():
                                if hasBeenPlayed:
                                    # Already playing/paused - just seek
                                    if self.audioPlayer.seek_to_playlist_index(self.currentChapter, waitForLoad=False):
                                        self.audioPlayer.seek_audio(positionInChapter)
                                else:
                                    # Never played - start playback at the bookmark position
                                    self.audioPlayer.seek_to_playlist_index(self.currentChapter, waitForLoad=False)
                                    self.audioPlayer.play_audio_file(startPosition=positionInChapter)
                                    self.isPlaying = True
                        else:
                            # Single-file audiobook
                            if self.audioPlayer.is_audio_file_loaded():
                                if hasBeenPlayed:
                                    # Already playing/paused - just seek
                                    self.audioPlayer.seek_audio(audioPosition)
                                else:
                                    # Never played - start playback at the bookmark position
                                    self.audioPlayer.play_audio_file(startPosition=audioPosition)
                                    self.isPlaying = True
                        break

            # Resume playback if it was playing before (but not if we just started it)
            if hasBeenPlayed and wasPlaying:
                self.audioPlayer.resume_audio_file()
                self.isPlaying = True

        # Speak feedback
        if self.speechEngine:
            chapter = self.book.get_chapter(self.currentChapter)
            chapterTitle = chapter.title if chapter else "Unknown"
            self.speechEngine.speak(f"Jumped to bookmark: {bookmarkName}. Chapter: {chapterTitle}")

        # Update display
        if self.config.get_show_text():
            self._render_screen()

    def _create_named_bookmark(self):
        """Create a new named bookmark"""
        # Use accessible text input dialog
        bookmarkName = get_input(self.speechEngine, prompt="Enter bookmark name")

        if not bookmarkName:
            # User cancelled or entered empty name
            return

        # Calculate audio position if audio book
        audioPosition = 0.0
        if hasattr(self.book, 'isAudioBook') and self.book.isAudioBook:
            # For multi-file audiobooks, sync currentChapter with playlist position
            if hasattr(self.book, 'isMultiFile') and self.book.isMultiFile:
                playlistIndex = self.audioPlayer.get_current_playlist_index()
                self.currentChapter = playlistIndex

            chapter = self.book.get_chapter(self.currentChapter)
            if chapter and hasattr(chapter, 'startTime'):
                chapterStartTime = chapter.startTime
            else:
                chapterStartTime = 0.0

            if self.audioPlayer.is_audio_file_playing() or self.audioPlayer.is_paused():
                playbackPos = self.audioPlayer.get_audio_position()
                audioPosition = chapterStartTime + playbackPos

        bookmarkId = self.bookmarkManager.create_named_bookmark(
            self.bookPath,
            bookmarkName,
            self.currentChapter,
            self.currentParagraph,
            audioPosition=audioPosition
        )

        if bookmarkId is None:
            if self.speechEngine:
                self.speechEngine.speak(f"Bookmark name already exists: {bookmarkName}")
            print(f"ERROR: Bookmark with name '{bookmarkName}' already exists")
            return

        serverBookmark = self._save_named_bookmark_to_server(bookmarkName, audioPosition)
        if serverBookmark:
            itemId = serverBookmark.get('libraryItemId') or self._get_current_server_item_id()
            serverTime = int(serverBookmark.get('time', round(audioPosition)))
            self.bookmarkManager.update_named_bookmark_server_data(
                bookmarkId,
                serverLibraryItemId=itemId,
                serverTime=serverTime,
                serverCreatedAt=serverBookmark.get('createdAt')
            )
            message = f"Bookmark created: {bookmarkName}"
        else:
            message = f"Bookmark created locally: {bookmarkName}"

        if self.speechEngine:
            self.speechEngine.speak(message)
        print(message)

        # Reload bookmarks in menu
        self.bookmarksMenu._load_bookmarks()
        self.bookmarksMenu._speak_current_item()

    def _open_audiobookshelf_browser(self):
        """Open Audiobookshelf browser"""
        # Check if server is configured
        if not self.config.is_abs_configured():
            self.speechEngine.speak("Audiobookshelf not configured. Please set server URL and username in config.")
            print("\nAudiobookshelf not configured.")
            print("Edit ~/.config/stormux/bookstorm/settings.ini and add:")
            print("[Audiobookshelf]")
            print("server_url = https://your-server.com")
            print("username = your-username")
            print("\nThen login with password when prompted.")
            return

        # Initialize client if needed
        if not self.absClient:
            serverUrl = self.config.get_abs_server_url()
            self.absClient = AudiobookshelfClient(serverUrl, self.config)
            # Initialize sync manager with the client
            self.absSync = AudiobookshelfSync(self.absClient, self.serverLinkManager)

        # Check if already authenticated
        if not self.absClient.is_authenticated():
            # Need to login
            self.speechEngine.speak("Audiobookshelf login required. Check terminal for password prompt.")
            print("\n=== Audiobookshelf Login ===")
            username = self.config.get_abs_username()
            print(f"Username: {username}")

            # Get password from user
            import getpass
            password = getpass.getpass("Password: ")

            if not self.absClient.login(username, password):
                self.speechEngine.speak("Login failed. Check username and password.")
                return

            self.speechEngine.speak("Login successful")

        # Test connection
        if not self.absClient.test_connection():
            self.speechEngine.speak("Connection test failed. Check server URL.")
            return

        # Initialize menu if needed
        if not self.absMenu:
            self.absMenu = AudiobookshelfMenu(self.absClient, self.config, self.speechEngine)

        # Open browser
        self.absMenu.enter_menu()

    def _handle_audiobookshelf_key(self, event):
        """Handle key events when in Audiobookshelf menu"""
        # Control key: Stop speech
        if event.key == pygame.K_LCTRL or event.key == pygame.K_RCTRL:
            if self.speechEngine:
                self.speechEngine.stop()
            return

        if event.key == pygame.K_UP:
            self.absMenu.navigate_menu('up')
        elif event.key == pygame.K_DOWN:
            self.absMenu.navigate_menu('down')
        elif event.key == pygame.K_LEFT:
            self.absMenu.change_view('left')
        elif event.key == pygame.K_RIGHT:
            self.absMenu.change_view('right')
        elif event.key == pygame.K_RETURN:
            # Select item (library or book)
            result = self.absMenu.activate_current_item()
            if result:
                action = result.get('action')
                if action == 'open_local':
                    # Open local copy of book
                    localPath = result.get('path')
                    if localPath:
                        if self.absMenu:
                            self.absMenu.exit_menu()
                        self._load_new_book(localPath)

                elif action == 'stream':
                    # Stream from server
                    serverBook = result.get('serverBook')
                    if serverBook:
                        self._stream_audiobook(serverBook)

                elif action == 'download':
                    # Download book to library
                    serverBook = result.get('serverBook')
                    if serverBook:
                        self._download_audiobook(serverBook)
        elif event.key == pygame.K_BACKSPACE:
            # Go back
            if self.absMenu:
                self.absMenu.go_back()
        elif event.key == pygame.K_ESCAPE:
            if self.absMenu:
                self.absMenu.exit_menu()
        elif event.unicode and event.unicode.isprintable() and not event.unicode.isspace():
            if self.absMenu:
                self.absMenu.search_items(event.unicode)

    def _handle_browser_key(self, event):
        """Handle key events when in book browser"""
        if event.key == pygame.K_UP:
            self.bookSelector.navigate_browser('up')
        elif event.key == pygame.K_DOWN:
            self.bookSelector.navigate_browser('down')
        elif event.key == pygame.K_RETURN:
            # Select item (book or directory)
            selectedBook = self.bookSelector.activate_current_item()
            if selectedBook:
                # Book was selected, load it
                self.bookSelector.exit_browser()
                self._load_new_book(selectedBook)
        elif event.key == pygame.K_BACKSPACE or event.key == pygame.K_LEFT:
            # Go to parent directory
            self.bookSelector.go_parent_directory()
        elif event.key == pygame.K_l and (event.mod & pygame.KMOD_SHIFT):
            # Set current directory as library directory
            currentDir = self.bookSelector.get_current_directory()
            self.config.set_library_directory(str(currentDir))
            dirName = currentDir.name if currentDir.name else str(currentDir)
            self.speechEngine.speak(f"Library set to {dirName}")
        elif event.unicode and event.unicode.isprintable() and not event.unicode.isspace():
            self.bookSelector.search_items(event.unicode)
        elif event.key == pygame.K_ESCAPE:
            self.bookSelector.exit_browser()

    def _handle_menu_key(self, event):
        """Handle key events when in options menu"""
        # Check if in restart confirmation dialog
        if self.optionsMenu.is_in_restart_menu():
            if event.key == pygame.K_UP:
                self.optionsMenu.navigate_restart_menu('up')
            elif event.key == pygame.K_DOWN:
                self.optionsMenu.navigate_restart_menu('down')
            elif event.key == pygame.K_RETURN:
                self.optionsMenu.select_restart_option()
            elif event.key == pygame.K_ESCAPE:
                self.optionsMenu.exit_restart_menu()
        # Check if in voice selection submenu
        elif self.optionsMenu.is_in_voice_menu():
            if event.key == pygame.K_UP:
                self.optionsMenu.navigate_voice_menu('up')
            elif event.key == pygame.K_DOWN:
                self.optionsMenu.navigate_voice_menu('down')
            elif event.key == pygame.K_RETURN:
                self.optionsMenu.select_current_voice()
            elif event.key == pygame.K_ESCAPE:
                self.optionsMenu.exit_voice_menu()
        # Check if in output module selection submenu
        elif self.optionsMenu.is_in_module_menu():
            if event.key == pygame.K_UP:
                self.optionsMenu.navigate_module_menu('up')
            elif event.key == pygame.K_DOWN:
                self.optionsMenu.navigate_module_menu('down')
            elif event.key == pygame.K_RETURN:
                self.optionsMenu.select_current_module()
            elif event.key == pygame.K_ESCAPE:
                self.optionsMenu.exit_module_menu()
        else:
            # Main options menu
            if event.key == pygame.K_UP:
                self.optionsMenu.navigate_menu('up')
            elif event.key == pygame.K_DOWN:
                self.optionsMenu.navigate_menu('down')
            elif event.key == pygame.K_RETURN:
                # Activate current menu item
                stayInMenu = self.optionsMenu.activate_current_item()
                if not stayInMenu:
                    self.optionsMenu.exit_menu()
            elif event.key == pygame.K_ESCAPE:
                self.speechEngine.speak("Closing options menu")
                self.optionsMenu.exit_menu()

    def _handle_sleep_timer_key(self, event):
        """Handle key events when in sleep timer menu"""
        if event.key == pygame.K_UP:
            self.sleepTimerMenu.navigate_menu('up')
        elif event.key == pygame.K_DOWN:
            self.sleepTimerMenu.navigate_menu('down')
        elif event.key == pygame.K_RETURN:
            # Activate current menu item
            shouldQuitNow, shouldContinue = self.sleepTimerMenu.activate_current_item()
            if shouldQuitNow:
                # User selected "Quit now"
                self.isRunning = False
                self.isPlaying = False
            elif shouldContinue:
                # New timer set - reset fade-out state and restore volume if needed
                if self.isFadingOut and self.fadeStartVolume is not None:
                    self.audioPlayer.set_volume(self.fadeStartVolume)
                self.isFadingOut = False
                self.fadeStartVolume = None
                self.fadeStartTime = None
        elif event.key == pygame.K_ESCAPE:
            self.speechEngine.speak("Cancelled")
            self.sleepTimerMenu.exit_menu()

    def _stream_audiobook(self, serverBook):
        """
        Stream audiobook from Audiobookshelf server

        Args:
            serverBook: Server book dictionary from API
        """
        if self.book:
            self.save_bookmark(speakFeedback=False)
            self._close_abs_session()
            if self.readingEngine and hasattr(self.readingEngine, 'cancel_reading'):
                self.readingEngine.cancel_reading()
            self.expectedSpeechCompletionToken += 1
            self.hasPendingSpeechCompletion = False
            self.pendingSpeechCompletionToken = None
            self.audioPlayer.stop()
            if self.audioPlayer.is_audio_file_loaded():
                self.audioPlayer.stop_audio_file()
            self.isPlaying = False

        # Extract book metadata
        # Try different ID fields (structure varies by API endpoint)
        serverId = serverBook.get('id') or serverBook.get('libraryItemId')

        if not serverId:
            self.speechEngine.speak("Error: Book ID not found")
            print(f"\nERROR: No valid ID found in book metadata")
            print(f"Available keys: {list(serverBook.keys())}")
            return

        media = serverBook.get('media', {})
        metadata = media.get('metadata', {})
        title = metadata.get('title', 'Unknown')
        author = metadata.get('authorName', '')
        duration = media.get('duration', 0.0)

        # Get streaming URL and start session via sync manager
        # This single call creates the session and returns stream info with saved position
        self.speechEngine.speak(f"Loading stream for {title}. Please wait.")
        print(f"\nGetting stream URL for: {title}")

        sessionData = self.absSync.start_streaming_session(serverBook)
        if not sessionData:
            self.speechEngine.speak("Failed to get stream URL. Check terminal for errors.")
            print("\nERROR: Could not start streaming session")
            print(f"Book structure keys: {list(serverBook.keys())}")
            if 'media' in serverBook:
                print(f"Media keys: {list(serverBook['media'].keys())}")
            return

        streamUrl = sessionData.get('streamUrl')
        streamUrls = sessionData.get('streamUrls') or ([streamUrl] if streamUrl else [])
        startPosition = sessionData.get('startPosition', 0.0)
        playData = sessionData.get('playData', {})

        # Store session ID for backward compatibility
        self.sessionId = sessionData.get('sessionId')

        # Get chapters from server (from the book details we already have)
        serverChapters = media.get('chapters', [])
        audioTracks = playData.get('audioTracks', []) if isinstance(playData, dict) else []

        # Create AudioBook object with stream URL
        from src.audio_parser import AudioBook, AudioChapter
        book = AudioBook(title=title, author=author, audioPath=streamUrl)
        book.totalDuration = duration
        book.audioFiles = streamUrls
        book.isMultiFile = len(streamUrls) > 1

        # Add chapters from server
        if serverChapters:
            for chapterData in serverChapters:
                chapterTitle = chapterData.get('title', 'Untitled')
                chapterStart = chapterData.get('start', 0.0)
                chapterDuration = chapterData.get('end', 0.0) - chapterStart

                chapter = AudioChapter(
                    title=chapterTitle,
                    startTime=chapterStart,
                    duration=chapterDuration
                )
                book.add_chapter(chapter)
        elif len(streamUrls) > 1:
            cumulativeStart = 0.0
            for trackIndex, trackUrl in enumerate(streamUrls):
                trackData = audioTracks[trackIndex] if trackIndex < len(audioTracks) and isinstance(audioTracks[trackIndex], dict) else {}
                trackStart = trackData.get('startOffset')
                if trackStart is None:
                    trackStart = trackData.get('offset')
                if trackStart is None:
                    trackStart = trackData.get('start')
                if trackStart is None:
                    trackStart = cumulativeStart

                trackDuration = trackData.get('duration')
                if trackDuration is None:
                    trackDuration = trackData.get('length')
                if trackDuration is None:
                    trackDuration = 0.0

                chapter = AudioChapter(
                    title=trackData.get('title', f"Part {trackIndex + 1}"),
                    startTime=float(trackStart),
                    duration=float(trackDuration)
                )
                chapter.audioPath = trackUrl
                book.add_chapter(chapter)
                cumulativeStart = float(trackStart) + float(trackDuration)
        else:
            # No chapters - treat entire book as single chapter
            chapter = AudioChapter(
                title=title,
                startTime=0.0,
                duration=duration
            )
            book.add_chapter(chapter)

        if len(streamUrls) > 1 and duration <= 0:
            book.totalDuration = sum(getattr(chapter, 'duration', 0.0) for chapter in book.chapters)

        # Store server metadata for progress sync
        self.serverBook = serverBook
        self.isStreaming = True
        self.lastAbsSyncAt = 0.0

        # Load the book
        self.book = book
        self.bookPath = streamUrl  # Store URL as path for tracking

        # Set book path in sync manager for progress updates
        self.absSync.set_book_path(streamUrl)

        # Save server book reference for resume on restart
        # Use special format: abs://{server_id} so we can detect and resume
        self.config.set_last_book(f"abs://{serverId}")

        # Save session and server metadata to server link manager
        # This allows resuming the stream with the same session
        self.serverLinkManager.create_link(
            bookPath=streamUrl,
            serverUrl=self.absClient.serverUrl,
            serverId=serverId,
            libraryId=serverBook.get('libraryId', ''),
            title=title,
            author=author,
            duration=duration,
            chapters=len(book.chapters),
            sessionId=self.sessionId,
            serverBook=serverBook
        )

        # Use position from server (already retrieved during session start)
        if startPosition > 0:
            self.savedAudioPosition = startPosition
            self._set_position_from_audio_time(startPosition)
        else:
            # No server progress, start from beginning
            self.currentChapter = 0
            self.savedAudioPosition = 0.0

        # Initialize position
        self.currentParagraph = 0

        # Load stream URL directly - mpv will handle streaming natively
        # Pass start position when loading (more reliable for streams than seeking after)
        startPos = startPosition if startPosition > 0 else 0.0
        if startPos > 0:
            minutes = int(startPos // 60)
            seconds = int(startPos % 60)
            print(f"Loading stream from {minutes}m {seconds}s: {streamUrl[:60]}...")
        else:
            print(f"Loading stream: {streamUrl[:80]}...")
        self.speechEngine.speak("Loading stream. This may take a moment.")

        playbackSpeed = self.config.get_playback_speed()
        if len(streamUrls) > 1:
            loadSuccess = self.audioPlayer.load_audio_playlist(streamUrls, authToken=self.absClient.authToken,
                                                               playbackSpeed=playbackSpeed)
        else:
            loadSuccess = self.audioPlayer.load_audio_file(streamUrl, authToken=self.absClient.authToken,
                                                           playbackSpeed=playbackSpeed, startPosition=startPos)

        if not loadSuccess:
            self.speechEngine.speak("Failed to load stream. Check terminal for errors.")
            print("\nERROR: Failed to load stream from server")
            print("Make sure mpv is installed: sudo pacman -S mpv")
            self._close_abs_session(finalPosition=startPos)
            self.isStreaming = False
            return

        # Restore saved volume setting
        savedVolume = self.config.get_volume()
        self.audioPlayer.set_volume(savedVolume)

        # Success! Start playing
        self.speechEngine.speak(f"Now streaming {title}. Press space to pause.")
        print(f"\nNow streaming: {title} by {author}")
        print(f"Chapters: {len(book.chapters)}")

        # Exit menu (if we came from menu - not needed when resuming from startup)
        if self.absMenu:
            self.absMenu.exit_menu()

        # Update UI if enabled (only if screen is initialized)
        if self.config.get_show_text() and hasattr(self, 'screen') and self.screen:
            self._render_screen()

        self.isPlaying = True
        self.isAudioBook = True
        self._start_audio_chapter_playback(self.book.get_chapter(self.currentChapter))

    def _download_audiobook(self, serverBook):
        """
        Download audiobook from Audiobookshelf server

        Args:
            serverBook: Server book dictionary from API
        """
        # Check library directory is set
        libraryDir = self.config.get_library_directory()
        if not libraryDir:
            self.speechEngine.speak("Library directory not set. Please set library directory first. Press B then Shift L.")
            print("\nERROR: Library directory not set.")
            print("Press 'b' to browse files, then 'Shift+L' to set library directory.")
            return

        libraryPath = Path(libraryDir)
        if not libraryPath.exists():
            self.speechEngine.speak("Library directory does not exist.")
            print(f"\nERROR: Library directory does not exist: {libraryDir}")
            return

        # Extract book metadata
        # Try different ID fields (structure varies by API endpoint)
        serverId = serverBook.get('id') or serverBook.get('libraryItemId')

        if not serverId:
            self.speechEngine.speak("Error: Book ID not found")
            print(f"\nERROR: No valid ID found in book metadata")
            print(f"Available keys: {list(serverBook.keys())}")
            return

        media = serverBook.get('media', {})
        metadata = media.get('metadata', {})
        title = metadata.get('title', 'Unknown')
        author = metadata.get('authorName', '')
        duration = media.get('duration', 0.0)
        numChapters = media.get('numChapters', 0)


        # Create sanitized filename
        safeTitle = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
        safeTitle = safeTitle.replace(' ', '_')

        # Determine file extension from server
        audioFiles = media.get('audioFiles', [])
        if audioFiles:
            firstFile = audioFiles[0]
            fileMetadata = firstFile.get('metadata', {})
            fileName = fileMetadata.get('filename', '')
            fileExt = Path(fileName).suffix if fileName else '.m4b'
        else:
            fileExt = '.m4b'

        outputPath = libraryPath / f"{safeTitle}{fileExt}"

        # Check if file already exists
        if outputPath.exists():
            self.speechEngine.speak("Book already downloaded.")
            print(f"\nBook already exists: {outputPath}")
            # Open it anyway
            if self.absMenu:
                self.absMenu.exit_menu()
            self._load_new_book(str(outputPath))
            return

        # Notify user
        self.speechEngine.speak(f"Downloading {title}. This may take several minutes.")
        print(f"\nDownloading: {title}")
        print(f"Output: {outputPath}")
        print("Please wait...")

        # Progress callback
        lastPercent = 0
        def progress_callback(percent):
            nonlocal lastPercent
            # Only update every 10%
            if percent >= lastPercent + 10:
                print(f"Progress: {percent}%")
                lastPercent = percent

        # Download file
        success = self.absClient.download_audio_file(serverId, str(outputPath), progress_callback)

        if not success:
            self.speechEngine.speak("Download failed. Check terminal for errors.")
            print("\nDownload failed!")
            return

        # Create server link
        serverUrl = self.config.get_abs_server_url()
        libraryId = serverBook.get('libraryId', '')

        self.serverLinkManager.create_link(
            bookPath=str(outputPath),
            serverUrl=serverUrl,
            serverId=serverId,
            libraryId=libraryId,
            title=title,
            author=author,
            duration=duration,
            chapters=numChapters
        )

        # Success!
        self.speechEngine.speak(f"Download complete. Opening {title}.")
        print(f"\nDownload complete! Opening book...")

        # Exit menu and open the book
        if self.absMenu:
            self.absMenu.exit_menu()
        self._load_new_book(str(outputPath))

    def _change_playback_speed(self, newSpeed):
        """
        Change audio playback speed (instant with mpv!)

        Args:
            newSpeed: New playback speed (0.5 to 2.0)
        """
        # Clamp speed to valid range
        newSpeed = max(0.5, min(2.0, float(newSpeed)))

        # Save to config
        self.config.set_playback_speed(newSpeed)

        # Apply speed change based on reader engine and book type
        readerEngine = self.config.get_reader_engine()
        isAudioBook = self.book and hasattr(self.book, 'isAudioBook') and self.book.isAudioBook

        if isAudioBook or (readerEngine == 'piper' and self.isPlaying):
            # Both audio books and Piper-TTS use MpvPlayer: instant speed change
            self.audioPlayer.set_speed(newSpeed)
            # For Piper-TTS, restart current paragraph to apply new speed immediately
            if not isAudioBook and self.isPlaying:
                self.audioPlayer.stop_audio_file()
                self._start_paragraph_playback()

        # Speak feedback
        speedPercent = int(newSpeed * 100)
        self.speechEngine.speak(f"Speed {speedPercent} percent")

    def _seek_audio_by_time(self, seconds):
        """
        Seek audio forward/backward by specified seconds (audio books only)

        Args:
            seconds: Number of seconds to seek (positive = forward, negative = backward)

        Returns:
            True if seek successful, False otherwise
        """
        # Only works for audio books
        if not self.book:
            return False

        isAudioBook = hasattr(self.book, 'isAudioBook') and self.book.isAudioBook
        if not isAudioBook:
            return False

        # Check if audio is actually loaded/playing
        if not self.audioPlayer.is_audio_file_loaded():
            self.speechEngine.speak("Nothing playing")
            return False

        # Get current position
        currentPos = self.audioPlayer.get_audio_position()

        # Calculate new position
        newPos = max(0.0, currentPos + seconds)

        # Seek to new position silently (audio feedback is enough)
        return self.audioPlayer.seek_audio(newPos)

    def _load_new_book(self, bookPath):
        """
        Load a new book from file path

        Args:
            bookPath: Path to new book file
        """
        # Save bookmark for current book BEFORE stopping playback
        # (so we can capture the current audio position)
        if self.book:
            self.save_bookmark(speakFeedback=False)
            self._close_abs_session()

        # Stop current playback
        if self.readingEngine and hasattr(self.readingEngine, 'cancel_reading'):
            self.readingEngine.cancel_reading()
        self.expectedSpeechCompletionToken += 1
        self.hasPendingSpeechCompletion = False
        self.pendingSpeechCompletionToken = None
        self.audioPlayer.stop()
        self._cancel_buffer()
        self.isPlaying = False

        # Update book path and config
        self.bookPath = Path(bookPath)
        self.config.set_last_book(bookPath)
        self.config.set_books_directory(str(self.bookPath.parent))

        # Reset audio position state
        self.savedAudioPosition = 0.0
        self.bookmarkCleared = False
        self.isStreaming = False
        self.serverBook = None
        self.lastAbsSyncAt = 0.0
        if self.absSync:
            self.absSync.reset()

        # Load new book (which will restore bookmark if it exists)
        try:
            self.load_book()
            self.speechEngine.speak("Ready")
        except Exception as e:
            message = f"Error loading book: {e}"
            print(message)
            self.speechEngine.speak(message)

    def _stop_playback(self):
        """Stop current playback (audio books, piper-tts, and callback-driven engines)."""
        # Handle case where no book is loaded
        if not self.book:
            return

        isAudioBook = hasattr(self.book, 'isAudioBook') and self.book.isAudioBook
        readerEngine = self.config.get_reader_engine()

        if isAudioBook or readerEngine == 'piper':
            # Stop audio playback (audio books or TTS via MpvPlayer)
            if readerEngine == 'piper':
                self._cancel_buffer()
            if self.audioPlayer.is_audio_file_loaded():
                self.audioPlayer.stop_audio_file()
            else:
                self.audioPlayer.stop()
        elif readerEngine in ['speechd', 'screenreader']:
            # Cancel callback-driven text reading
            self.readingEngine.cancel_reading()

    def _restart_current_paragraph(self):
        """
        Restart current paragraph playback after speech-rate changes.

        Callback-driven engines apply rate changes only to the next utterance.
        """
        # Cancel current speech
        self.readingEngine.cancel_reading()

        # Restart from current paragraph
        self._start_paragraph_playback()

    def _start_paragraph_playback(self):
        """Start playing current paragraph"""
        chapter = self.book.get_chapter(self.currentChapter)
        if not chapter:
            print("ERROR: No chapter found!")
            return

        # Check if this is an audio book
        if hasattr(self.book, 'isAudioBook') and self.book.isAudioBook:
            # Audio book playback
            self._start_audio_chapter_playback(chapter)
            return

        paragraph = chapter.get_paragraph(self.currentParagraph)
        if not paragraph:
            print("ERROR: No paragraph found!")
            return

        # Update display text and status
        self.displayText = paragraph
        self.statusText = f"Ch {self.currentChapter + 1}/{self.book.get_total_chapters()}: {chapter.title} | Para {self.currentParagraph + 1}/{chapter.get_total_paragraphs()}"

        # Use configured reader engine
        readerEngine = self.config.get_reader_engine()

        if readerEngine in ['speechd', 'screenreader']:
            # Use callback-driven reading engines
            self.expectedSpeechCompletionToken += 1
            paragraphToken = self.expectedSpeechCompletionToken

            def on_speech_finished(finishType, completionToken=None):
                """
                Callback when a paragraph finishes speaking.
                Post pygame event instead of mutating state in callback thread.
                """
                if finishType == 'COMPLETED' and self.isPlaying:
                    # Post pygame event to handle in main loop
                    eventData = {'completionToken': paragraphToken}
                    if completionToken is not None:
                        try:
                            eventData['completionToken'] = int(completionToken)
                        except Exception:
                            pass
                    pygame.event.post(pygame.event.Event(SPEECH_FINISHED_EVENT, eventData))

            self.readingEngine.speak_reading(paragraph, callback=on_speech_finished)
        else:
            # Use piper-tts for reading with buffering

            wavData = None
            try:
                # Check if we have buffered audio ready for THIS paragraph
                with self.bufferLock:
                    if (self.bufferedAudio is not None and
                        self.bufferedChapter == self.currentChapter and
                        self.bufferedParagraph == self.currentParagraph):
                        # Use pre-generated audio (matches current position)
                        wavData = self.bufferedAudio
                        self.bufferedAudio = None
                        self.bufferedChapter = -1
                        self.bufferedParagraph = -1
                    else:
                        # Discard stale buffer if present (wrong paragraph)
                        if self.bufferedAudio is not None:
                            print(f"Discarding stale buffer (expected ch{self.currentChapter}p{self.currentParagraph}, got ch{self.bufferedChapter}p{self.bufferedParagraph})")
                            del self.bufferedAudio
                            self.bufferedAudio = None
                            self.bufferedChapter = -1
                            self.bufferedParagraph = -1
                            # Force GC to reclaim buffer memory immediately
                            gc.collect()
                        # Generate audio now (first paragraph or after navigation)
                        wavData = self.ttsEngine.text_to_wav_data(paragraph)

                if wavData:
                    # Stop any existing audio file (playing, paused, or idle)
                    # This ensures temp files are cleaned up immediately
                    if self.audioPlayer.is_audio_file_loaded():
                        self.audioPlayer.stop_audio_file()

                    # Get current playback speed from config
                    playbackSpeed = self.config.get_playback_speed()

                    # Play WAV data through MpvPlayer (which supports pause/resume)
                    if self.audioPlayer.play_wav_data(wavData, playbackSpeed=playbackSpeed):
                        # Start buffering next paragraph in background
                        self._buffer_next_paragraph()
                    else:
                        print("Error: Failed to start TTS playback")
                        self.isPlaying = False

                    # Explicitly delete wavData after playback starts to free memory
                    del wavData
                    wavData = None
                else:
                    print("Warning: No audio data generated")
            except Exception as e:
                print(f"Error during playback: {e}")
                # Stop playback on error to prevent infinite error loop
                self.isPlaying = False
                raise
            finally:
                # The variable is already set to None in all relevant paths
                pass

    def _start_audio_chapter_playback(self, chapter):
        """Start playing audio book chapter"""
        # Update display text and status
        self.displayText = f"Playing: {chapter.title}"
        self.statusText = f"Ch {self.currentChapter + 1}/{self.book.get_total_chapters()}: {chapter.title}"

        # Check if multi-file audiobook (each chapter is a separate file)
        isMultiFile = hasattr(self.book, 'isMultiFile') and self.book.isMultiFile

        # Determine start position
        # If we have a saved audio position and we're on the saved chapter, use it
        # Save the position before clearing it (we'll need it later for multi-file)
        resumePosition = self.savedAudioPosition
        if resumePosition > 0.0:
            startTime = resumePosition
            # Clear saved position so we don't use it again (only for initial resume)
            self.savedAudioPosition = 0.0
            minutes = int(startTime // 60)
            seconds = int(startTime % 60)
        else:
            # Get start time from audio chapter
            if hasattr(chapter, 'startTime'):
                startTime = chapter.startTime
            else:
                startTime = 0.0

        # Seek to position and play
        if self.audioPlayer.audioFileLoaded:
            if isMultiFile:
                # For multi-file audiobooks, seek to the correct file in playlist
                # Chapter index = file index (each file is a chapter)

                # Validate chapter index is within bounds
                totalChapters = self.book.get_total_chapters()
                if self.currentChapter < 0 or self.currentChapter >= totalChapters:
                    print(f"ERROR: Invalid chapter index {self.currentChapter} (total chapters: {totalChapters})")
                    self.currentChapter = 0
                    print(f"Reset to chapter 0")

                if self.audioPlayer.seek_to_playlist_index(self.currentChapter):
                    # Calculate position within current file
                    # If resuming (saved position > 0), use position relative to chapter start
                    positionInFile = 0.0
                    if resumePosition > 0.0:
                        # Get current chapter's start time to calculate position within file
                        chapter = self.book.get_chapter(self.currentChapter)
                        if chapter and hasattr(chapter, 'startTime'):
                            positionInFile = resumePosition - chapter.startTime
                            # Ensure position is within file bounds
                            if positionInFile < 0:
                                positionInFile = 0.0
                            elif hasattr(chapter, 'duration') and positionInFile > chapter.duration:
                                positionInFile = chapter.duration
                    # Start playback at calculated position
                    self.audioPlayer.play_audio_file(startPosition=positionInFile)
                else:
                    print(f"ERROR: Could not seek to playlist index {self.currentChapter}")
                    self.isPlaying = False
            else:
                # Single-file audiobook with chapter markers
                self.audioPlayer.play_audio_file(startPosition=startTime)
        else:
            print("ERROR: Audio file not loaded!")
            self.isPlaying = False

    def _buffer_next_paragraph(self):
        """Start buffering next paragraph in background thread"""
        # Only for piper-tts (speech-dispatcher handles buffering internally)
        readerEngine = self.config.get_reader_engine()
        if readerEngine != 'piper':
            return

        # Don't start a new buffer thread if one is already running
        # This prevents thread accumulation when playback outruns buffering
        if self.bufferThread and self.bufferThread.is_alive():
            return

        # CRITICAL: Clear any stale buffered audio before starting new thread
        # This shouldn't normally happen now that we track buffer position
        with self.bufferLock:
            if self.bufferedAudio is not None:
                # This is now a safety check - should rarely trigger
                print(f"Warning: Clearing existing buffer before buffering next (ch{self.bufferedChapter}p{self.bufferedParagraph})")
                del self.bufferedAudio
                self.bufferedAudio = None
                self.bufferedChapter = -1
                self.bufferedParagraph = -1
                # Force immediate garbage collection
                gc.collect()

        # Calculate next paragraph position
        nextChapter = self.currentChapter
        nextParagraph = self.currentParagraph + 1

        chapter = self.book.get_chapter(nextChapter)
        if not chapter:
            return

        # Check if we need to move to next chapter
        if nextParagraph >= chapter.get_total_paragraphs():
            nextChapter += 1
            nextParagraph = 0
            chapter = self.book.get_chapter(nextChapter)
            if not chapter:
                return  # End of book

        # Get the paragraph to buffer
        paragraph = chapter.get_paragraph(nextParagraph)
        if not paragraph:
            return

        def buffer_thread():
            """Background thread to generate audio"""
            _wavData_to_cleanup = None
            try:
                # Generate audio
                wavData_generated = self.ttsEngine.text_to_wav_data(paragraph)
                _wavData_to_cleanup = wavData_generated

                # Check if cancelled
                if self.cancelBuffer:
                    del _wavData_to_cleanup
                    _wavData_to_cleanup = None
                    return

                # Store buffered audio with position tracking
                with self.bufferLock:
                    if not self.cancelBuffer:
                        self.bufferedAudio = _wavData_to_cleanup
                        self.bufferedChapter = nextChapter
                        self.bufferedParagraph = nextParagraph
                        _wavData_to_cleanup = None  # Transfer ownership
            except Exception as e:
                print(f"Error buffering paragraph: {e}")
                with self.bufferLock:
                    self.bufferedAudio = None
                    self.bufferedChapter = -1
                    self.bufferedParagraph = -1
                if _wavData_to_cleanup is not None:
                    del _wavData_to_cleanup
                _wavData_to_cleanup = None
            finally:
                # The variable is already set to None in all relevant paths
                pass

        # Clear any cancelled buffer state
        with self.bufferLock:
            self.cancelBuffer = False

        # Clean up previous buffer thread reference before starting new one
        if self.bufferThread and not self.bufferThread.is_alive():
            self.bufferThread = None

        # Start new buffer thread
        self.bufferThread = threading.Thread(target=buffer_thread, daemon=True)
        self.bufferThread.start()

    def _cancel_buffer(self):
        """Cancel in-progress buffering"""
        if self.bufferThread and self.bufferThread.is_alive():
            self.cancelBuffer = True
            # Wait longer for TTS generation to finish (piper-tts can be slow)
            # If thread doesn't finish, it will be abandoned (daemon thread)
            self.bufferThread.join(timeout=3.0)
            if self.bufferThread.is_alive():
                print("Warning: Buffer thread did not finish in time")

        # Clear buffered audio and explicitly delete to free memory
        with self.bufferLock:
            if self.bufferedAudio is not None:
                del self.bufferedAudio
            self.bufferedAudio = None
            self.cancelBuffer = False
            # Force garbage collection if we discarded a buffer
            gc.collect()

        # Reset thread reference
        self.bufferThread = None

    def cleanup(self):
        """Cleanup resources"""
        self._close_abs_session()

        # Save current volume setting if audio book or Piper-TTS was used
        if self.book:
            isAudioBook = hasattr(self.book, 'isAudioBook') and self.book.isAudioBook
            isPiperMode = self.config.get_reader_engine() == 'piper'
            if isAudioBook or isPiperMode:
                # If we're fading out, save the original volume (not the faded volume)
                if self.isFadingOut and self.fadeStartVolume is not None:
                    currentVolume = self.fadeStartVolume
                else:
                    currentVolume = self.audioPlayer.get_volume()
                self.config.set_volume(currentVolume)

        self._cancel_buffer()
        # Cleanup audio player (handles both TTS and audio books)
        self.audioPlayer.cleanup()
        self.speechEngine.cleanup()
        if self.readingEngine:
            self.readingEngine.cleanup()
        if self.parser:
            self.parser.cleanup()


def main():
    """Main entry point"""
    # Set process title for easier identification
    if HAS_SETPROCTITLE:
        setproctitle("BookStorm")

    parser = argparse.ArgumentParser(
        description="BookStorm - Accessible book reader with TTS",
        epilog="Press 'o' in the reader for options menu"
    )
    parser.add_argument(
        'book',
        nargs='?',
        help='Path to book file (EPUB, PDF, TXT, or DAISY zip). If not provided, will resume last book'
    )
    parser.add_argument(
        '--wav',
        action='store_true',
        help='Export book to WAV files (by chapter) instead of interactive reading'
    )
    parser.add_argument(
        '--output-dir',
        dest='outputDir',
        help='Output directory for exported audio (default: ./book_audio/)',
        default=None
    )

    args = parser.parse_args()

    # Load configuration
    config = ConfigManager()

    # Determine which book to use
    bookPath = None

    if args.book:
        # Book provided on command line
        bookPath = args.book
    else:
        # Try to use last book
        lastBook = config.get_last_book()

        # Check if last book was an Audiobookshelf stream
        if lastBook and lastBook.startswith('abs://'):
            # Extract server book ID
            serverId = lastBook[6:]  # Remove 'abs://' prefix

            # Try to restore from cached server link
            from src.server_link_manager import ServerLinkManager
            serverLinkManager = ServerLinkManager()

            # Try to find cached server book metadata by server ID
            # The bookPath in the link will be the stream URL from last session
            cachedLink = None
            for sidecarPath in (Path.home() / ".bookstorm" / "server_links").glob("*.json"):
                try:
                    import json
                    with open(sidecarPath, 'r') as f:
                        linkData = json.load(f)
                        if linkData.get('server_id') == serverId:
                            cachedLink = linkData
                            break
                except:
                    continue

            if cachedLink and cachedLink.get('server_book'):
                # We have cached metadata - try to resume using it
                print(f"Found cached server book metadata, resuming stream...")

                if config.is_abs_configured():
                    try:
                        # Initialize Audiobookshelf client
                        from src.audiobookshelf_client import AudiobookshelfClient
                        serverUrl = config.get_abs_server_url()
                        absClient = AudiobookshelfClient(serverUrl, config)

                        if absClient.is_authenticated() and absClient.test_connection():
                            # Use cached server book metadata instead of re-fetching
                            serverBook = cachedLink['server_book']
                            print(f"Restoring from cached metadata...")

                            try:
                                from src.speech_engine import SpeechEngine
                                speechEngine = SpeechEngine()

                                reader = BookReader(None, config)
                                reader.absClient = absClient
                                reader.absSync = AudiobookshelfSync(absClient, reader.serverLinkManager)
                                reader._stream_audiobook(serverBook)
                                reader.run_interactive()
                                return 0

                            except Exception as e:
                                print(f"Error resuming stream: {e}")
                                import traceback
                                traceback.print_exc()
                                print("Opening BookStorm anyway - use 'a' to browse server or 'b' for local books")
                        else:
                            print("Cannot connect to Audiobookshelf server or session expired")
                            print("Opening BookStorm anyway - use 'a' to reconnect or 'b' for local books")

                    except Exception as e:
                        print(f"Error connecting to Audiobookshelf: {e}")
                        print("Opening BookStorm anyway - use 'a' to reconnect or 'b' for local books")
                else:
                    print("Audiobookshelf not configured")
                    print("Opening BookStorm anyway - use 'o' to configure server or 'b' for local books")
            else:
                # No cached metadata - try fetching from server
                print(f"No cached metadata, fetching from server...")

                if config.is_abs_configured():
                    try:
                        # Initialize Audiobookshelf client
                        from src.audiobookshelf_client import AudiobookshelfClient
                        serverUrl = config.get_abs_server_url()
                        absClient = AudiobookshelfClient(serverUrl, config)

                        if absClient.is_authenticated() and absClient.test_connection():
                            # Get book details
                            print(f"Fetching book details from server...")
                            bookDetails = absClient.get_library_item_details(serverId)

                            if bookDetails:
                                # Successfully got book details - try to stream
                                print(f"Found book on server, preparing to stream...")
                                try:
                                    from src.speech_engine import SpeechEngine
                                    speechEngine = SpeechEngine()

                                    reader = BookReader(None, config)
                                    reader.absClient = absClient
                                    reader.absSync = AudiobookshelfSync(absClient, reader.serverLinkManager)
                                    reader._stream_audiobook(bookDetails)
                                    reader.run_interactive()
                                    return 0

                                except Exception as e:
                                    print(f"Error resuming stream: {e}")
                                    print("Opening BookStorm anyway - use 'a' to browse server or 'b' for local books")
                            else:
                                print(f"Book not found on server (may have been deleted)")
                                print("Opening BookStorm anyway - use 'a' to browse server or 'b' for local books")
                        else:
                            print("Cannot connect to Audiobookshelf server or session expired")
                            print("Opening BookStorm anyway - use 'a' to reconnect or 'b' for local books")

                    except Exception as e:
                        print(f"Error connecting to Audiobookshelf: {e}")
                        print("Opening BookStorm anyway - use 'a' to reconnect or 'b' for local books")
                else:
                    print("Audiobookshelf not configured")
                    print("Opening BookStorm anyway - use 'o' to configure server or 'b' for local books")

            # Fall through to open BookStorm in interactive mode
            # Clear last_book so we don't loop on this error
            config.set_last_book('')

            # Open BookStorm without a book - user can browse
            print("\nStarting BookStorm in interactive mode...")
            print("Press 'a' for Audiobookshelf, 'b' for local books, 'r' for recent books")

            try:
                from src.speech_engine import SpeechEngine
                speechEngine = SpeechEngine()
                speechEngine.speak("Could not resume stream. Press A for Audiobookshelf, B for local books, or R for recent books.")

                # Create a minimal book to satisfy BookReader initialization
                # We'll use a dummy book that tells user what to do
                reader = BookReader(None, config)
                reader.book = None  # No book loaded yet
                reader.run_interactive()  # User can use menus to load a book
                return 0

            except Exception as e:
                print(f"Error starting BookStorm: {e}")
                import traceback
                traceback.print_exc()
                return 1

        elif lastBook and Path(lastBook).exists():
            bookPath = lastBook
        else:
            # No book available - open in interactive mode
            print("BookStorm - Accessible Book Reader")

            if lastBook:
                print(f"\nNote: Last book no longer exists: {lastBook}")
            else:
                print("\nNo previous book found")

            print("Starting in interactive mode...")
            print("Press 'a' for Audiobookshelf, 'b' for local books, 'r' for recent books\n")

            try:
                from src.speech_engine import SpeechEngine
                speechEngine = SpeechEngine()
                speechEngine.speak("BookStorm ready. Press A for Audiobookshelf, B for local books, or R for recent books.")

                reader = BookReader(None, config)
                reader.book = None
                reader.run_interactive()
                return 0

            except Exception as e:
                print(f"Error starting BookStorm: {e}")
                import traceback
                traceback.print_exc()
                print("\nUsage:")
                print("  python bookstorm.py <book.epub>   # Read EPUB book")
                print("  python bookstorm.py <book.pdf>    # Read PDF book")
                print("  python bookstorm.py <book.txt>    # Read TXT book")
                print("  python bookstorm.py <book.zip>    # Read DAISY book")
                print("  python bookstorm.py book.epub --wav # Export to WAV files")
                return 1

    # Check if book exists (only for local books)
    if bookPath and not Path(bookPath).exists():
        print(f"Error: Book file not found: {bookPath}")
        return 1

    # Handle export mode
    if args.wav:
        exporter = WavExporter(config)
        return exporter.export(bookPath, args.outputDir)

    # Interactive reading mode
    config.set_last_book(bookPath)

    try:
        reader = BookReader(bookPath, config)
        reader.load_book()
        reader.run_interactive()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        if 'reader' in locals():
            reader.cleanup()

    return 0


if __name__ == '__main__':
    sys.exit(main())
