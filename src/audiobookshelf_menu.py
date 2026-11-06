#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Audiobookshelf Menu

Interactive browser for Audiobookshelf server content.
Browse libraries, audiobooks, series, and collections.
"""

from pathlib import Path
import time


class AudiobookshelfMenu:
    """Audiobookshelf browser interface"""

    def __init__(self, absClient, configManager, speechEngine=None):
        """
        Initialize Audiobookshelf menu

        Args:
            absClient: AudiobookshelfClient instance
            configManager: ConfigManager instance
            speechEngine: SpeechEngine instance for accessibility
        """
        self.absClient = absClient
        self.configManager = configManager
        self.speechEngine = speechEngine

        # Menu state
        self.inMenu = False
        self.currentView = 'libraries'  # 'libraries', 'books', 'stream_download'
        self.currentSelection = 0
        self.items = []
        self.searchBuffer = ''
        self.lastSearchAt = 0.0

        # Context tracking
        self.selectedLibrary = None
        self.selectedBook = None

        # View mode for books list
        self.booksViewMode = 'all'  # 'all', 'series', 'collections'

        # Stream/download submenu options
        self.streamDownloadOptions = [
            {'action': 'stream', 'label': 'Stream from server'},
            {'action': 'download', 'label': 'Download to library'},
            {'action': 'cancel', 'label': 'Cancel'}
        ]

    def enter_menu(self):
        """Enter the Audiobookshelf browser"""
        self.inMenu = True
        self.currentSelection = 0
        self._reset_search()

        # Reset state from previous sessions
        self.selectedLibrary = None
        self.selectedBook = None
        self.booksViewMode = 'all'

        if self.speechEngine:
            self.speechEngine.speak("Audiobookshelf browser. Loading libraries...")

        # Get libraries from server
        libraries = self.absClient.get_libraries()

        if not libraries:
            if self.speechEngine:
                self.speechEngine.speak("Error loading libraries. Check server connection.")
            self.inMenu = False
            return

        # If only one library, skip library selection and go straight to books
        if len(libraries) == 1:
            self.selectedLibrary = libraries[0]
            self._load_books()
        else:
            # Multiple libraries - show library selection
            self.currentView = 'libraries'
            self.items = libraries
            if self.speechEngine:
                self.speechEngine.speak(f"Found {len(libraries)} libraries. Use arrow keys to navigate or type to search.")
            self._speak_current_item()

    def _load_books(self):
        """Load books from selected library"""
        if not self.selectedLibrary:
            return

        libraryId = self.selectedLibrary.get('id')
        if not libraryId:
            if self.speechEngine:
                self.speechEngine.speak("Error: Invalid library")
            return

        if self.speechEngine:
            libraryName = self.selectedLibrary.get('name', 'Library')
            self.speechEngine.speak(f"Loading books from {libraryName}...")

        # Get books from library
        books = self.absClient.get_library_items(libraryId)

        if not books:
            if self.speechEngine:
                self.speechEngine.speak("No books found in library")
            self.items = []
            self.currentView = 'books'
            return

        # Store books without checking local status (too slow)
        # Local check will happen on selection only
        self.items = books
        self.currentView = 'books'
        self.currentSelection = 0
        self._reset_search()

        if self.speechEngine:
            self.speechEngine.speak(f"Loaded {len(books)} books. Use arrow keys to navigate, left-right to change view, or type to search.")
        self._speak_current_item()

    def _check_if_local(self, book):
        """
        Check if book exists locally

        Args:
            book: Book dictionary from server

        Returns:
            True if book exists locally, False otherwise
        """
        # Get library directory
        libraryDir = self.configManager.get_library_directory()
        if not libraryDir:
            return False

        libraryPath = Path(libraryDir)
        if not libraryPath.exists():
            return False

        # Extract book metadata
        media = book.get('media', {})
        metadata = media.get('metadata', {})
        title = metadata.get('title', '')
        author = metadata.get('authorName', '')

        if not title:
            return False

        # Search for matching files in library
        # Look for common audio formats
        audioExtensions = ['.m4b', '.m4a', '.mp3', '.ogg']

        for audioExt in audioExtensions:
            # Try exact title match
            for filePath in libraryPath.rglob(f"*{audioExt}"):
                fileName = filePath.stem.lower()
                if title.lower() in fileName:
                    # Found potential match - could enhance with duration check later
                    return True

        return False

    def navigate_menu(self, direction):
        """Navigate menu up or down"""
        # Handle stream/download submenu separately
        if self.currentView == 'stream_download':
            if direction == 'up':
                self.currentSelection = (self.currentSelection - 1) % len(self.streamDownloadOptions)
            elif direction == 'down':
                self.currentSelection = (self.currentSelection + 1) % len(self.streamDownloadOptions)
            self._speak_current_item()
            return

        if not self.items:
            return

        oldSelection = self.currentSelection
        if direction == 'up':
            self.currentSelection = (self.currentSelection - 1) % len(self.items)
        elif direction == 'down':
            self.currentSelection = (self.currentSelection + 1) % len(self.items)

        self._speak_current_item()

    def _reset_search(self):
        """Reset incremental search state."""
        self.searchBuffer = ''
        self.lastSearchAt = 0.0

    def _get_search_text(self, item):
        """Build searchable text for the current item."""
        if self.currentView == 'libraries':
            return item.get('name', '').lower()

        if self.currentView != 'books':
            return ''

        if self.booksViewMode == 'series':
            return item.get('name', '').lower()

        if self.booksViewMode == 'collections':
            return item.get('name', '').lower()

        media = item.get('media', {})
        metadata = media.get('metadata', {})
        title = metadata.get('title', '')
        author = metadata.get('authorName', '')
        return f"{title} {author}".strip().lower()

    def search_items(self, searchText):
        """
        Jump to the first item whose spoken label starts with the typed text.

        Args:
            searchText: Newly typed character(s)

        Returns:
            True if a match was found
        """
        if self.currentView == 'stream_download' or not self.items:
            return False

        now = time.monotonic()
        if now - self.lastSearchAt > 1.5:
            self.searchBuffer = ''

        self.lastSearchAt = now
        self.searchBuffer = f"{self.searchBuffer}{searchText.lower()}"

        for itemIndex, item in enumerate(self.items):
            if self._get_search_text(item).startswith(self.searchBuffer):
                self.currentSelection = itemIndex
                self._speak_current_item()
                return True

        if self.speechEngine:
            self.speechEngine.speak(f"No match for {self.searchBuffer}")
        return False

    def change_view(self, direction):
        """Change view mode (only in books view)"""
        if self.currentView != 'books':
            return

        views = ['all', 'series', 'collections']
        currentIndex = views.index(self.booksViewMode)

        if direction == 'left':
            newIndex = (currentIndex - 1) % len(views)
        elif direction == 'right':
            newIndex = (currentIndex + 1) % len(views)
        else:
            return

        oldViewMode = self.booksViewMode
        self.booksViewMode = views[newIndex]

        # Announce new view
        if self.speechEngine:
            viewName = {
                'all': 'All books',
                'series': 'Series view',
                'collections': 'Collections view'
            }[self.booksViewMode]
            self.speechEngine.speak(viewName)

        # Reload content for new view
        if self.booksViewMode == 'all':
            self._load_books()
        elif self.booksViewMode == 'series':
            self._load_series()
        elif self.booksViewMode == 'collections':
            self._load_collections()

    def _speak_current_item(self):
        """Speak current item"""
        if not self.speechEngine:
            return

        if self.currentView == 'stream_download':
            # Speak submenu option
            if self.currentSelection < len(self.streamDownloadOptions):
                option = self.streamDownloadOptions[self.currentSelection]
                text = f"{option['label']}, {self.currentSelection + 1} of {len(self.streamDownloadOptions)}"
                self.speechEngine.speak(text)
            return

        if not self.items:
            return

        item = self.items[self.currentSelection]

        if self.currentView == 'libraries':
            # Speak library name
            libraryName = item.get('name', 'Unknown library')
            text = f"{libraryName}, {self.currentSelection + 1} of {len(self.items)}"
            self.speechEngine.speak(text)

        elif self.currentView == 'books':
            # Different handling based on view mode
            if self.booksViewMode == 'series':
                # Speaking a series
                name = item.get('name', 'Unknown series')
                numBooks = item.get('books', [])
                bookCount = len(numBooks) if isinstance(numBooks, list) else item.get('numBooks', 0)
                text = f"{name}, {bookCount} books, {self.currentSelection + 1} of {len(self.items)}"
                self.speechEngine.speak(text)

            elif self.booksViewMode == 'collections':
                # Speaking a collection
                name = item.get('name', 'Unknown collection')
                numBooks = item.get('books', [])
                bookCount = len(numBooks) if isinstance(numBooks, list) else item.get('numBooks', 0)
                text = f"{name}, {bookCount} books, {self.currentSelection + 1} of {len(self.items)}"
                self.speechEngine.speak(text)

            else:
                # Speaking a book (all books view)
                media = item.get('media', {})
                metadata = media.get('metadata', {})
                title = metadata.get('title', 'Unknown title')
                author = metadata.get('authorName', '')

                # Build description
                parts = [title]
                if author:
                    parts.append(f"by {author}")
                parts.append(f"{self.currentSelection + 1} of {len(self.items)}")

                text = ", ".join(parts)
                self.speechEngine.speak(text)

    def activate_current_item(self):
        """
        Activate current item (select library or book)

        Returns:
            None if navigating, dictionary if book selected
        """
        # Handle stream/download submenu
        if self.currentView == 'stream_download':
            if self.currentSelection < len(self.streamDownloadOptions):
                option = self.streamDownloadOptions[self.currentSelection]
                action = option['action']

                if action == 'cancel':
                    # Go back to books list
                    self.currentView = 'books'
                    self.currentSelection = 0
                    self._reset_search()
                    if self.speechEngine:
                        self.speechEngine.speak("Cancelled")
                    self._speak_current_item()
                    return None

                elif action == 'stream':
                    # Return stream action
                    return {
                        'action': 'stream',
                        'serverBook': self.selectedBook
                    }

                elif action == 'download':
                    # Return download action
                    return {
                        'action': 'download',
                        'serverBook': self.selectedBook
                    }

            return None

        if not self.items:
            if self.speechEngine:
                self.speechEngine.speak("No items")
            return None

        item = self.items[self.currentSelection]

        if self.currentView == 'libraries':
            # Library selected - load books from this library
            self.selectedLibrary = item
            self._load_books()
            return None

        elif self.currentView == 'books':
            # Check if we're selecting a series or collection (not a book)
            if self.booksViewMode == 'series':
                # Series selected - show books in this series
                seriesBooks = item.get('books', [])
                if not seriesBooks:
                    if self.speechEngine:
                        self.speechEngine.speak("No books in this series")
                    return None

                # Store books directly (local check too slow)
                self.items = seriesBooks
                self.booksViewMode = 'all'  # Switch to "all books" view
                self.currentSelection = 0
                self._reset_search()

                if self.speechEngine:
                    seriesName = item.get('name', 'Series')
                    self.speechEngine.speak(f"{seriesName}. {len(seriesBooks)} books")
                self._speak_current_item()
                return None

            elif self.booksViewMode == 'collections':
                # Collection selected - show books in this collection
                collectionBooks = item.get('books', [])
                if not collectionBooks:
                    if self.speechEngine:
                        self.speechEngine.speak("No books in this collection")
                    return None

                # Store books directly (local check too slow)
                self.items = collectionBooks
                self.booksViewMode = 'all'  # Switch to "all books" view
                self.currentSelection = 0
                self._reset_search()

                if self.speechEngine:
                    collectionName = item.get('name', 'Collection')
                    self.speechEngine.speak(f"{collectionName}. {len(collectionBooks)} books")
                self._speak_current_item()
                return None

            # Book selected
            self.selectedBook = item

            # For books from series/collections, fetch full details if needed
            # (they might have incomplete metadata)
            if not item.get('media'):
                # Book doesn't have full media details, fetch them
                bookId = item.get('id') or item.get('libraryItemId')
                if bookId:
                    fullDetails = self.absClient.get_library_item_details(bookId)
                    if fullDetails:
                        self.selectedBook = fullDetails
                        item = fullDetails

            # Get metadata for later use
            media = item.get('media', {})
            metadata = media.get('metadata', {})
            title = metadata.get('title', 'Unknown')

            # Check if local copy exists
            isLocal = self._check_if_local(item)

            if isLocal:
                # Book exists locally - return it for direct opening
                if self.speechEngine:
                    media = item.get('media', {})
                    metadata = media.get('metadata', {})
                    title = metadata.get('title', 'Book')
                    self.speechEngine.speak(f"Opening local copy of {title}")

                # Find local file path
                localPath = self._find_local_path(item)
                if localPath:
                    return {
                        'action': 'open_local',
                        'path': localPath,
                        'serverBook': item
                    }
                else:
                    if self.speechEngine:
                        self.speechEngine.speak("Error: Could not find local file")
                    return None
            else:
                # Book not local - enter stream/download submenu
                self.currentView = 'stream_download'
                self.currentSelection = 0
                self._reset_search()
                if self.speechEngine:
                    self.speechEngine.speak("Choose playback option. Use arrow keys to navigate.")
                self._speak_current_item()
                return None

        return None

    def _find_local_path(self, book):
        """
        Find local file path for a book

        Args:
            book: Book dictionary from server

        Returns:
            Path to local file, or None if not found
        """
        libraryDir = self.configManager.get_library_directory()
        if not libraryDir:
            return None

        libraryPath = Path(libraryDir)
        if not libraryPath.exists():
            return None

        # Extract book metadata
        media = book.get('media', {})
        metadata = media.get('metadata', {})
        title = metadata.get('title', '')

        if not title:
            return None

        # Search for matching files
        audioExtensions = ['.m4b', '.m4a', '.mp3', '.ogg']

        for audioExt in audioExtensions:
            for filePath in libraryPath.rglob(f"*{audioExt}"):
                fileName = filePath.stem.lower()
                if title.lower() in fileName:
                    return str(filePath)

        return None

    def go_back(self):
        """Go back to previous view"""
        if self.currentView == 'stream_download':
            # Go back to books list
            self.currentView = 'books'
            self.currentSelection = 0
            self._reset_search()
            if self.speechEngine:
                self.speechEngine.speak("Back to books")
            self._speak_current_item()
        elif self.currentView == 'books':
            # Go back to libraries (if multiple)
            libraries = self.absClient.get_libraries()
            if libraries and len(libraries) > 1:
                self.currentView = 'libraries'
                self.items = libraries
                self.currentSelection = 0
                self.selectedLibrary = None
                self._reset_search()
                if self.speechEngine:
                    self.speechEngine.speak("Back to libraries")
                self._speak_current_item()
            else:
                # Only one library - exit menu
                self.exit_menu()
        else:
            # Already at top level - exit
            self.exit_menu()

    def is_in_menu(self):
        """Check if currently in menu"""
        return self.inMenu

    def _load_series(self):
        """Load series from selected library"""
        if not self.selectedLibrary:
            return

        libraryId = self.selectedLibrary.get('id')
        if not libraryId:
            if self.speechEngine:
                self.speechEngine.speak("Error: Invalid library")
            return

        if self.speechEngine:
            self.speechEngine.speak("Loading series...")

        # Get series from library
        seriesList = self.absClient.get_library_series(libraryId)

        if not seriesList:
            if self.speechEngine:
                self.speechEngine.speak("No series found")
            self.items = []
            self.currentSelection = 0
            return

        self.items = seriesList
        self.currentView = 'books'  # Keep in books view but showing series
        self.currentSelection = 0
        self._reset_search()

        if self.speechEngine:
            self.speechEngine.speak(f"Loaded {len(seriesList)} series")
        self._speak_current_item()

    def _load_collections(self):
        """Load collections from selected library"""
        if not self.selectedLibrary:
            return

        libraryId = self.selectedLibrary.get('id')
        if not libraryId:
            if self.speechEngine:
                self.speechEngine.speak("Error: Invalid library")
            return

        if self.speechEngine:
            self.speechEngine.speak("Loading collections...")

        # Get collections from library
        collectionsList = self.absClient.get_library_collections(libraryId)

        if not collectionsList:
            if self.speechEngine:
                self.speechEngine.speak("No collections found")
            self.items = []
            self.currentSelection = 0
            return

        self.items = collectionsList
        self.currentView = 'books'  # Keep in books view but showing collections
        self.currentSelection = 0
        self._reset_search()

        if self.speechEngine:
            self.speechEngine.speak(f"Loaded {len(collectionsList)} collections")
        self._speak_current_item()

    def exit_menu(self):
        """Exit the menu"""
        self.inMenu = False
        self.currentView = 'libraries'
        self.items = []
        self.selectedLibrary = None
        self.selectedBook = None
        self._reset_search()
        if self.speechEngine:
            self.speechEngine.speak("Closed Audiobookshelf browser")
