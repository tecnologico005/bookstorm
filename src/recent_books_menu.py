#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Recent Books Menu

Displays the 10 most recently accessed books for quick access.
"""

from pathlib import Path


class RecentBooksMenu:
    """Recent books selection interface"""

    def __init__(self, bookmarkManager, speechEngine=None):
        """
        Initialize recent books menu

        Args:
            bookmarkManager: BookmarkManager instance for fetching recent books
            speechEngine: SpeechEngine instance for accessibility
        """
        self.bookmarkManager = bookmarkManager
        self.speechEngine = speechEngine
        self.currentSelection = 0
        self.inMenu = False
        self.items = []

    def enter_menu(self):
        """Enter the recent books menu"""
        self.inMenu = True
        self.currentSelection = 0

        # Get recent books from bookmarks
        allBookmarks = self.bookmarkManager.list_bookmarks()

        # Limit to 10 most recent, filter out non-existent files
        self.items = []
        for bookmark in allBookmarks[:10]:
            bookPath = Path(bookmark['bookPath']).resolve()
            if bookPath.exists():
                self.items.append({
                    'path': bookPath,
                    'title': bookmark['bookTitle'] or bookPath.name,
                    'lastAccessed': bookmark['lastAccessed']
                })

        if self.speechEngine:
            self.speechEngine.speak("Recent books. Use arrow keys to navigate, Enter to select, Escape to cancel.")

        if self.items:
            self._speak_current_item()
        elif self.speechEngine:
            self.speechEngine.speak("No recent books found")

    def navigate_menu(self, direction):
        """Navigate menu up or down"""
        if not self.items:
            return

        if direction == 'up':
            self.currentSelection = (self.currentSelection - 1) % len(self.items)
        elif direction == 'down':
            self.currentSelection = (self.currentSelection + 1) % len(self.items)

        self._speak_current_item()

    def _speak_current_item(self):
        """Speak current item"""
        if not self.items or not self.speechEngine:
            return

        item = self.items[self.currentSelection]
        # Speak title and position
        text = f"{item['title']}, {self.currentSelection + 1} of {len(self.items)}"
        # speak() has interrupt=True by default, which stops any current speech
        self.speechEngine.speak(text)

    def activate_current_item(self):
        """
        Activate current item (return book path)

        Returns:
            Book path if selected, None if no items
        """
        if not self.items:
            if self.speechEngine:
                self.speechEngine.speak("No items")
            return None

        item = self.items[self.currentSelection]

        if self.speechEngine:
            self.speechEngine.speak(f"Loading: {item['title']}")

        return str(item['path'])

    def is_in_menu(self):
        """Check if currently in menu"""
        return self.inMenu

    def exit_menu(self):
        """Exit the menu"""
        self.inMenu = False
        if self.speechEngine:
            self.speechEngine.speak("Cancelled")
