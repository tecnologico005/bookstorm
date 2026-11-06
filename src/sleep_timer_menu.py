#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sleep Timer Menu

Provides a menu for setting sleep timer or quitting immediately.
"""

import time


class SleepTimerMenu:
    """Sleep timer menu for quit/sleep options"""

    def __init__(self, speechEngine):
        """
        Initialize sleep timer menu

        Args:
            speechEngine: SpeechEngine instance for UI feedback
        """
        self.speechEngine = speechEngine
        self.inMenu = False
        self.currentIndex = 0

        # Menu options: (label, minutes)
        # 0 means quit immediately
        self.menuItems = [
            ("Quit now", 0),
            ("Sleep in 5 minutes", 5),
            ("Sleep in 10 minutes", 10),
            ("Sleep in 15 minutes", 15),
            ("Sleep in 20 minutes", 20),
            ("Sleep in 25 minutes", 25),
            ("Sleep in 30 minutes", 30),
            ("Sleep in 35 minutes", 35),
            ("Sleep in 40 minutes", 40),
            ("Sleep in 45 minutes", 45),
            ("Sleep in 50 minutes", 50),
            ("Sleep in 55 minutes", 55),
            ("Sleep in 60 minutes", 60),
        ]

        # Timer state
        self.timerActive = False
        self.timerEndTime = None
        self.timerMinutes = 0

    def enter_menu(self):
        """Enter the sleep timer menu"""
        self.inMenu = True
        self.currentIndex = 0
        self._speak_current_item()

    def exit_menu(self):
        """Exit the sleep timer menu"""
        self.inMenu = False

    def is_in_menu(self):
        """Check if currently in menu"""
        return self.inMenu

    def navigate_menu(self, direction):
        """
        Navigate menu up or down

        Args:
            direction: 'up' or 'down'
        """
        if direction == 'up':
            self.currentIndex = (self.currentIndex - 1) % len(self.menuItems)
        elif direction == 'down':
            self.currentIndex = (self.currentIndex + 1) % len(self.menuItems)

        self._speak_current_item()

    def activate_current_item(self):
        """
        Activate current menu item

        Returns:
            Tuple: (shouldQuitNow, shouldContinue)
                   shouldQuitNow: True if user selected "Quit now"
                   shouldContinue: True if timer was set (continue reading)
        """
        label, minutes = self.menuItems[self.currentIndex]

        if minutes == 0:
            # Quit now
            self.speechEngine.speak("Quitting now")
            self.inMenu = False
            return (True, False)
        else:
            # Set sleep timer
            self.timerActive = True
            self.timerMinutes = minutes
            self.timerEndTime = time.time() + (minutes * 60)
            self.speechEngine.speak(f"Sleep timer set for {minutes} minutes")
            self.inMenu = False
            return (False, True)

    def check_timer(self):
        """
        Check if sleep timer has expired

        Returns:
            True if timer expired and should quit
        """
        if self.timerActive and time.time() >= self.timerEndTime:
            return True
        return False

    def should_start_fadeout(self):
        """
        Check if we should start fading out (10 seconds before timer expiration)

        Returns:
            True if we're within 10 seconds of timer expiration
        """
        if not self.timerActive:
            return False

        remaining = self.timerEndTime - time.time()
        return 0 < remaining <= 10

    def get_time_remaining(self):
        """
        Get time remaining on sleep timer

        Returns:
            Tuple: (minutes, seconds) or None if no timer active
        """
        if not self.timerActive:
            return None

        remaining = self.timerEndTime - time.time()
        if remaining <= 0:
            return (0, 0)

        minutes = int(remaining // 60)
        seconds = int(remaining % 60)
        return (minutes, seconds)

    def cancel_timer(self):
        """Cancel active sleep timer"""
        if self.timerActive:
            self.timerActive = False
            self.timerEndTime = None
            self.speechEngine.speak("Sleep timer cancelled")

    def reset_fadeout_state(self):
        """
        Reset fade-out state (called when timer is cancelled or new timer set)
        Returns the fade state so the caller can restore volume if needed
        """
        return {'isFadingOut': False, 'fadeStartVolume': None, 'fadeStartTime': None}

    def is_timer_active(self):
        """Check if sleep timer is active"""
        return self.timerActive

    def _speak_current_item(self):
        """Speak the current menu item"""
        label, _ = self.menuItems[self.currentIndex]
        self.speechEngine.speak(label)
