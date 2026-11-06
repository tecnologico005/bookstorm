#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bookmarks Menu

Interactive menu for managing named bookmarks.
Allows creating, browsing, and jumping to bookmarks.
"""


class BookmarksMenu:
    """Menu for named bookmarks"""

    def __init__(self, bookmarkManager, speechEngine=None):
        """
        Initialize bookmarks menu

        Args:
            bookmarkManager: BookmarkManager instance
            speechEngine: SpeechEngine instance for accessibility
        """
        self.bookmarkManager = bookmarkManager
        self.speechEngine = speechEngine

        # Menu state
        self.inMenu = False
        self.currentView = 'list'  # 'list' or 'create'
        self.currentSelection = 0
        self.bookmarks = []

        # Current book context
        self.currentBookPath = None

        # Menu options for list view
        self.listOptions = []  # Will be populated with bookmarks + "Create new"

    def enter_menu(self, bookPath):
        """
        Enter the bookmarks menu for a specific book

        Args:
            bookPath: Path to current book
        """
        self.inMenu = True
        self.currentBookPath = bookPath
        self.currentView = 'list'
        self.currentSelection = 0

        # Load bookmarks for this book
        self._load_bookmarks()

        if self.speechEngine:
            if len(self.bookmarks) > 0:
                self.speechEngine.speak(f"Bookmarks. {len(self.bookmarks)} bookmarks found. Use arrow keys to navigate.")
            else:
                self.speechEngine.speak("Bookmarks. No bookmarks yet. Press Enter to create one.")

        self._speak_current_item()

    def _load_bookmarks(self):
        """Load bookmarks for current book"""
        if not self.currentBookPath:
            self.bookmarks = []
            self.listOptions = []
            return

        self.bookmarks = self.bookmarkManager.get_named_bookmarks(self.currentBookPath)

        # Build list options: bookmarks + "Create new bookmark"
        self.listOptions = []
        for bookmark in self.bookmarks:
            self.listOptions.append({
                'type': 'bookmark',
                'data': bookmark
            })

        # Add "Create new" option
        self.listOptions.append({
            'type': 'create',
            'data': None
        })

    def navigate_menu(self, direction):
        """Navigate menu up or down"""
        if not self.listOptions:
            return

        if direction == 'up':
            self.currentSelection = (self.currentSelection - 1) % len(self.listOptions)
        elif direction == 'down':
            self.currentSelection = (self.currentSelection + 1) % len(self.listOptions)

        self._speak_current_item()

    def _speak_current_item(self):
        """Speak current item"""
        if not self.speechEngine or not self.listOptions:
            return

        if self.currentSelection >= len(self.listOptions):
            return

        option = self.listOptions[self.currentSelection]

        if option['type'] == 'bookmark':
            bookmark = option['data']
            name = bookmark['name']
            text = f"{name}, bookmark {self.currentSelection + 1} of {len(self.listOptions)}"
            self.speechEngine.speak(text)

        elif option['type'] == 'create':
            text = f"Create new bookmark, {self.currentSelection + 1} of {len(self.listOptions)}"
            self.speechEngine.speak(text)

    def activate_current_item(self):
        """
        Activate current item

        Returns:
            Dictionary with action and bookmark data, or None
        """
        if not self.listOptions:
            return None

        if self.currentSelection >= len(self.listOptions):
            return None

        option = self.listOptions[self.currentSelection]

        if option['type'] == 'bookmark':
            # Jump to bookmark
            bookmark = option['data']
            return {
                'action': 'jump',
                'bookmark': bookmark
            }

        elif option['type'] == 'create':
            # Create new bookmark
            return {
                'action': 'create'
            }

        return None

    def get_current_bookmark(self):
        """
        Get the currently selected bookmark.

        Returns:
            Bookmark dictionary or None if selection is not a bookmark
        """
        if not self.listOptions:
            return None

        if self.currentSelection >= len(self.listOptions):
            return None

        option = self.listOptions[self.currentSelection]
        if option['type'] != 'bookmark':
            return None

        return option['data']

    def remove_bookmark(self, bookmarkId, bookmarkName=None):
        """
        Remove a bookmark from the local menu and database.

        Args:
            bookmarkId: Local bookmark ID
            bookmarkName: Optional spoken name for feedback
        """
        self.bookmarkManager.delete_named_bookmark(bookmarkId)

        if self.speechEngine and bookmarkName:
            self.speechEngine.speak(f"Deleted bookmark: {bookmarkName}")

        self._load_bookmarks()

        if self.currentSelection >= len(self.listOptions):
            self.currentSelection = max(0, len(self.listOptions) - 1)

        self._speak_current_item()

    def delete_current_bookmark(self):
        """
        Delete currently selected bookmark

        Returns:
            True if deleted, False otherwise
        """
        if not self.listOptions:
            return False

        if self.currentSelection >= len(self.listOptions):
            return False

        option = self.listOptions[self.currentSelection]

        if option['type'] == 'bookmark':
            bookmark = option['data']
            bookmarkId = bookmark['id']
            bookmarkName = bookmark['name']
            self.remove_bookmark(bookmarkId, bookmarkName)
            return True

        return False

    def is_in_menu(self):
        """Check if currently in menu"""
        return self.inMenu

    def exit_menu(self):
        """Exit the menu"""
        self.inMenu = False
        self.currentView = 'list'
        self.currentSelection = 0
        self.bookmarks = []
        self.listOptions = []
        if self.speechEngine:
            self.speechEngine.speak("Closed bookmarks")
