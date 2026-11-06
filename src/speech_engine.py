#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Speech Engine

Handles text-to-speech for UI feedback using speech-dispatcher.
Based on soundstorm's speech.py implementation.
"""

import threading

try:
    import speechd
    HAS_SPEECHD = True
except ImportError:
    HAS_SPEECHD = False

from .text_validator import is_valid_text


class SpeechEngine:
    """Text-to-speech engine for UI accessibility using speech-dispatcher"""

    def __init__(self):
        """Initialize speech engine"""
        self.client = None
        self.speechLock = threading.Lock()
        self.isAvailable = False

        # Reading state tracking with callback support
        self.isReading = False
        self.isPausedReading = False
        self.readingCallback = None  # Callback for when reading finishes

        # Track UI speech thread to prevent accumulation
        self.uiSpeechThread = None

        if HAS_SPEECHD:
            try:
                self.client = speechd.SSIPClient('bookstorm')
                self.isAvailable = True
            except Exception as e:
                print(f"Warning: Could not initialize speech-dispatcher: {e}")
                self.isAvailable = False
        else:
            print("Warning: python3-speechd not installed. UI will not be accessible.")

    def close(self):
        """Close speech-dispatcher connection"""
        if self.client:
            try:
                self.client.close()
            except:
                pass
            self.client = None
            self.isAvailable = False

    def speak(self, text, interrupt=True):
        """
        Speak text using speech-dispatcher

        Args:
            text: Text to speak
            interrupt: If True, stop current speech first (default: True)
        """
        if not self.isAvailable or not is_valid_text(text):
            return

        # Safety: Wait for previous UI speech thread to finish if still running
        # This prevents thread accumulation on rapid UI feedback calls
        if self.uiSpeechThread and self.uiSpeechThread.is_alive():
            # Don't wait forever - if thread is stuck, let it die (daemon thread)
            self.uiSpeechThread.join(timeout=0.1)

        def speak_thread():
            with self.speechLock:
                try:
                    if interrupt:
                        self.client.stop()
                    self.client.speak(str(text))
                except Exception as e:
                    print(f"Speech error: {e}")

        self.uiSpeechThread = threading.Thread(target=speak_thread)
        self.uiSpeechThread.daemon = True
        self.uiSpeechThread.start()

    def stop(self):
        """Stop current speech"""
        if self.isAvailable:
            try:
                self.client.stop()
            except Exception:
                pass

    def speak_reading(self, text, callback=None):
        """
        Speak text for book reading with callback support

        Args:
            text: Text to speak
            callback: Optional callback function to call when speech finishes
                      Callback receives one argument: finish_type (COMPLETED or INTERRUPTED)
        """
        if not self.isAvailable:
            print("ERROR: Speech-dispatcher not available")
            return

        if not is_valid_text(text):
            print("ERROR: No valid text to speak (empty or no alphanumeric characters)")
            return

        try:
            # Only cancel if we're already reading
            if self.isReading:
                try:
                    self.client.cancel()
                except Exception:
                    pass

            # Normalize text - replace newlines with spaces
            # (speech-dispatcher may stop at newlines)
            textStr = str(text).replace('\n', ' ').replace('\r', ' ')

            # Clean up multiple spaces
            import re
            textStr = re.sub(r'\s+', ' ', textStr).strip()

            print(f"Speech-dispatcher: Speaking {len(textStr)} characters")

            self.isReading = True
            self.isPausedReading = False
            self.readingCallback = callback

            # Define callback function for speech-dispatcher
            def speech_callback(callbackType, indexMark=None):
                """Callback from speech-dispatcher when speech events occur"""
                if callbackType == speechd.CallbackType.END:
                    # Speech completed normally
                    self.isReading = False
                    self.isPausedReading = False
                    if self.readingCallback:
                        self.readingCallback('COMPLETED')
                elif callbackType == speechd.CallbackType.CANCEL:
                    # Speech was interrupted/cancelled
                    self.isReading = False
                    self.isPausedReading = False
                    if self.readingCallback:
                        self.readingCallback('INTERRUPTED')

            # Speak with callback (event_types is speechd API parameter)
            # pylint: disable=no-member
            self.client.speak(
                textStr,
                callback=speech_callback,
                event_types=[speechd.CallbackType.END, speechd.CallbackType.CANCEL]
            )
        except Exception as e:
            print(f"Speech error: {e}")
            import traceback
            traceback.print_exc()
            self.isReading = False

    def pause_reading(self):
        """Pause current reading"""
        if not self.isAvailable:
            return

        if self.isReading and not self.isPausedReading:
            try:
                self.client.pause()
                self.isPausedReading = True
                print("Speech-dispatcher: Paused")
            except Exception as e:
                print(f"Pause error: {e}")
                # Reset state on error
                self.isReading = False
                self.isPausedReading = False

    def resume_reading(self):
        """Resume paused reading"""
        if not self.isAvailable:
            return

        if self.isPausedReading:
            try:
                self.client.resume()
                self.isPausedReading = False
                print("Speech-dispatcher: Resumed")
            except Exception as e:
                print(f"Resume error: {e}")
                # Reset state on error
                self.isReading = False
                self.isPausedReading = False

    def cancel_reading(self):
        """Cancel current reading"""
        if not self.isAvailable:
            return

        try:
            self.client.cancel()
            # Note: Canceling will trigger the CANCEL callback
        except Exception as e:
            print(f"Cancel error: {e}")
        finally:
            # Reset state
            self.isReading = False
            self.isPausedReading = False
            self.readingCallback = None

    def is_reading_active(self):
        """Check if currently reading (not paused)"""
        return self.isReading and not self.isPausedReading

    def is_reading_paused(self):
        """Check if reading is paused"""
        return self.isPausedReading

    def set_rate(self, rate):
        """
        Set speech rate

        Args:
            rate: Speech rate (-100 to 100, 0 is normal)
        """
        if self.isAvailable:
            try:
                rate = max(-100, min(100, rate))
                self.client.set_rate(rate)
            except Exception as e:
                print(f"Error setting speech rate: {e}")

    def set_voice(self, voiceName):
        """
        Set speech voice

        Args:
            voiceName: Voice name (e.g., 'Lyubov')
        """
        if self.isAvailable:
            try:
                self.client.set_synthesis_voice(voiceName)
            except Exception as e:
                print(f"Error setting voice: {e}")

    def list_voices(self):
        """
        List available voices

        Returns:
            List of voice tuples (name, language, variant)
        """
        if self.isAvailable:
            try:
                voices = self.client.list_synthesis_voices()
                # Return list of tuples: (name, language, variant)
                return list(voices) if voices else []
            except Exception as e:
                print(f"Error listing voices: {e}")
                return []
        return []

    def list_output_modules(self):
        """
        List available output modules (speech synthesizers)

        Returns:
            List of output module names (e.g., 'espeak-ng', 'festival', 'flite')
        """
        if self.isAvailable:
            try:
                modules = self.client.list_output_modules()
                return list(modules) if modules else []
            except Exception as e:
                print(f"Error listing output modules: {e}")
                return []
        return []

    def set_output_module(self, moduleName):
        """
        Set the output module (speech synthesizer)

        Args:
            moduleName: Name of the output module (e.g., 'espeak-ng')
        """
        if self.isAvailable:
            try:
                self.client.set_output_module(moduleName)
            except Exception as e:
                print(f"Error setting output module: {e}")

    def is_available(self):
        """Check if speech-dispatcher is available"""
        return self.isAvailable

    def cleanup(self):
        """Cleanup resources - alias for close()"""
        self.close()
