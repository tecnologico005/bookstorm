#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Help Menu

Provides navigable help text with line-by-line speech output.
"""


class HelpMenu:
    """Interactive help menu."""

    def __init__(self, speechEngine):
        """
        Initialize help menu.

        Args:
            speechEngine: SpeechEngine instance for UI feedback
        """
        self.speechEngine = speechEngine
        self.inMenu = False
        self.helpLines = []
        self.currentIndex = -1

    def enter_menu(self, helpLines):
        """
        Open help menu with provided lines.

        Args:
            helpLines: List of help lines to navigate
        """
        if isinstance(helpLines, str) or helpLines is None:
            self.helpLines = []
        else:
            try:
                self.helpLines = [str(line) for line in list(helpLines)]
            except Exception:
                self.helpLines = []
        self.currentIndex = -1
        self.inMenu = True

        if not self.helpLines:
            self.speechEngine.speak("Help opened. No help text available.")
            return

        self.speechEngine.speak("Help opened. Press down to hear the first line, then use up or down to navigate.")

    def exit_menu(self):
        """Close help menu."""
        self.inMenu = False

    def is_in_menu(self):
        """Return True when help menu is active."""
        return self.inMenu

    def navigate_menu(self, direction):
        """
        Navigate help text and speak one line.

        Args:
            direction: 'up' or 'down'
        """
        if not self.helpLines:
            self.speechEngine.speak("No help text available.")
            return

        if direction == 'down':
            nextIndex = self.currentIndex + 1
            if nextIndex >= len(self.helpLines):
                self.speechEngine.speak("End of help.")
                return

            self.currentIndex = nextIndex
            self.speechEngine.speak(self.helpLines[self.currentIndex])
            return

        if direction == 'up':
            if self.currentIndex <= 0:
                self.speechEngine.speak("Beginning of help.")
                return

            self.currentIndex -= 1
            self.speechEngine.speak(self.helpLines[self.currentIndex])
