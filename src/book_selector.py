#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Book Selector

Interactive file browser for selecting book files.
Supports navigation and filtering by supported formats.
"""

from pathlib import Path
import time
import zipfile


class BookSelector:
    """Book file selection interface"""

    def __init__(self, startDir=None, supportedFormats=None, speechEngine=None):
        """
        Initialize book selector

        Args:
            startDir: Starting directory (default: home)
            supportedFormats: List of supported file extensions (default: ['.zip', '.epub'])
            speechEngine: SpeechEngine instance for accessibility
        """
        if startDir is None:
            startDir = Path.home()

        if supportedFormats is None:
            supportedFormats = ['.zip', '.epub']

        self.currentDir = Path(startDir).resolve()
        self.supportedFormats = supportedFormats
        self.speechEngine = speechEngine
        self.currentSelection = 0
        self.inBrowser = False
        self.items = []
        self.searchBuffer = ''
        self.lastSearchAt = 0.0


    def _list_items(self):
        """
        List directories and supported book files in current directory

        Returns:
            List of item dictionaries
        """
        items = []

        # Supported audio formats for folder audiobooks
        audioFormats = {'.mp3', '.m4a', '.m4b', '.opus', '.ogg', '.flac', '.wav', '.aac', '.wma'}

        try:
            # Add directories (excluding hidden)
            for item in sorted(self.currentDir.iterdir()):
                if item.name.startswith('.'):
                    continue

                if item.is_dir():
                    # Check if directory contains audio files (audiobook folder)
                    audioFileCount = self._count_audio_files(item, audioFormats)
                    items.append({
                        'name': item.name,
                        'path': item,
                        'isDir': True,
                        'isAudiobookFolder': audioFileCount >= 2,  # At least 2 files for multi-file audiobook
                        'audioFileCount': audioFileCount
                    })

            # Add supported book files
            for item in sorted(self.currentDir.iterdir()):
                if item.name.startswith('.'):
                    continue

                if item.is_file() and item.suffix.lower() in self.supportedFormats:
                    # For zip files, validate that they're actually DAISY books
                    if item.suffix.lower() == '.zip':
                        if not self._is_daisy_zip(item):
                            continue  # Skip non-DAISY zip files

                    items.append({
                        'name': item.name,
                        'path': item,
                        'isDir': False,
                        'isAudiobookFolder': False,
                        'audioFileCount': 0
                    })

        except PermissionError:
            print(f"Permission denied: {self.currentDir}")

        return items

    def _is_daisy_zip(self, zipPath):
        """
        Check if a zip file contains a DAISY book

        Args:
            zipPath: Path to zip file

        Returns:
            True if zip contains DAISY book markers, False otherwise
        """
        try:
            with zipfile.ZipFile(zipPath, 'r') as zf:
                fileList = zf.namelist()

                # Check for DAISY 2.02 marker (ncc.html)
                if 'ncc.html' in fileList:
                    return True

                # Check for DAISY 3 marker (.ncx file)
                for filename in fileList:
                    if filename.lower().endswith('.ncx'):
                        return True

                return False
        except (zipfile.BadZipFile, PermissionError, OSError):
            # If we can't read it, don't show it
            return False

    def _count_audio_files(self, folderPath, audioFormats):
        """
        Count audio files in a folder (non-recursive)
        Also checks if folder has subdirectories.

        Args:
            folderPath: Path to folder
            audioFormats: Set of audio file extensions

        Returns:
            Number of audio files found (0 if folder contains subdirectories)
        """
        count = 0
        hasSubdirs = False
        try:
            for item in folderPath.iterdir():
                # Skip hidden items
                if item.name.startswith('.'):
                    continue

                # If folder has subdirectories, don't treat it as audiobook folder
                if item.is_dir():
                    hasSubdirs = True
                    break

                if item.is_file() and item.suffix.lower() in audioFormats:
                    count += 1
                    # Stop counting after finding 2 (enough to determine if it's a folder audiobook)
                    if count >= 2:
                        break
        except (PermissionError, OSError):
            return 0

        # If folder has subdirectories, return 0 (treat as regular folder)
        if hasSubdirs:
            return 0

        return count

    def reset_to_directory(self, directory):
        """
        Reset browser to a specific directory

        Args:
            directory: Path to directory to reset to
        """
        dirPath = Path(directory).resolve()
        if dirPath.exists() and dirPath.is_dir():
            self.currentDir = dirPath

    def get_current_directory(self):
        """
        Get current directory path

        Returns:
            Path object of current directory
        """
        return self.currentDir

    def enter_browser(self):
        """Enter the book browser"""
        self.inBrowser = True
        self.currentSelection = 0
        self.items = self._list_items()
        self._reset_search()

        if self.speechEngine:
            self.speechEngine.speak("Book browser. Use arrow keys to navigate, type to search, Enter to select, Backspace for parent directory, Shift L to set library, Escape to cancel.")

        # Speak current directory and first item
        if self.speechEngine:
            dirName = self.currentDir.name if self.currentDir.name else str(self.currentDir)
            self.speechEngine.speak(f"Directory: {dirName}")

        if self.items:
            self._speak_current_item()
        elif self.speechEngine:
            self.speechEngine.speak("Empty directory")

    def navigate_browser(self, direction):
        """Navigate browser up or down"""
        if not self.items:
            return

        if direction == 'up':
            self.currentSelection = (self.currentSelection - 1) % len(self.items)
        elif direction == 'down':
            self.currentSelection = (self.currentSelection + 1) % len(self.items)

        self._speak_current_item()

    def _reset_search(self):
        """Reset incremental search state."""
        self.searchBuffer = ''
        self.lastSearchAt = 0.0

    def search_items(self, searchText):
        """
        Jump to the first item whose name starts with the typed text.

        Args:
            searchText: Text typed by the user

        Returns:
            True if a match was found
        """
        if not self.items:
            return False

        now = time.monotonic()
        if now - self.lastSearchAt > 1.5:
            self.searchBuffer = ''

        self.lastSearchAt = now
        self.searchBuffer = f"{self.searchBuffer}{searchText.lower()}"

        for itemIndex, item in enumerate(self.items):
            if item.get('name', '').lower().startswith(self.searchBuffer):
                self.currentSelection = itemIndex
                self._speak_current_item()
                return True

        if self.speechEngine:
            self.speechEngine.speak(f"No match for {self.searchBuffer}")
        return False

    def _speak_current_item(self):
        """Speak current item with name first, then type"""
        if not self.items or not self.speechEngine:
            return

        item = self.items[self.currentSelection]
        if item['isDir']:
            if item.get('isAudiobookFolder', False):
                audioCount = item.get('audioFileCount', 0)
                text = f"{item['name']}, audiobook folder, {audioCount} files"
            else:
                text = f"{item['name']}, directory"
        else:
            text = f"{item['name']}, book"

        self.speechEngine.speak(text)

    def activate_current_item(self):
        """
        Activate current item (enter directory or return book path)

        Returns:
            Book path if selected, None if navigating or empty
        """
        if not self.items:
            if self.speechEngine:
                self.speechEngine.speak("No items")
            return None

        item = self.items[self.currentSelection]

        if item['isDir']:
            # Check if it's an audiobook folder
            if item.get('isAudiobookFolder', False):
                # Treat audiobook folder as a book (return path to folder)
                if self.speechEngine:
                    self.speechEngine.speak(f"Loading audiobook folder: {item['name']}")
                return str(item['path'])
            else:
                # Navigate into directory
                self.currentDir = item['path']
                self.currentSelection = 0
                self.items = self._list_items()
                self._reset_search()

                if self.speechEngine:
                    dirName = self.currentDir.name if self.currentDir.name else str(self.currentDir)
                    self.speechEngine.speak(f"Entered directory: {dirName}")

                if self.items:
                    self._speak_current_item()
                elif self.speechEngine:
                    self.speechEngine.speak("Empty directory")

                return None
        else:
            # Book selected
            if self.speechEngine:
                self.speechEngine.speak(f"Loading: {item['name']}")
            return str(item['path'])

    def go_parent_directory(self):
        """Go to parent directory"""
        parent = self.currentDir.parent
        if parent != self.currentDir:
            self.currentDir = parent
            self.currentSelection = 0
            self.items = self._list_items()
            self._reset_search()

            if self.speechEngine:
                dirName = self.currentDir.name if self.currentDir.name else str(self.currentDir)
                self.speechEngine.speak(f"Parent directory: {dirName}")

            if self.items:
                self._speak_current_item()
            elif self.speechEngine:
                self.speechEngine.speak("Empty directory")
        else:
            if self.speechEngine:
                self.speechEngine.speak("Already at root")

    def is_in_browser(self):
        """Check if currently in browser"""
        return self.inBrowser

    def exit_browser(self):
        """Exit the browser"""
        self.inBrowser = False
        self._reset_search()
        if self.speechEngine:
            self.speechEngine.speak("Cancelled")
