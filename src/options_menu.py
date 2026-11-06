#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Options Menu

Interactive menu system for BookStorm settings.
Inspired by soundstorm's hierarchical menu system.
"""

from pathlib import Path
from src.tts_engine import TtsEngine
from src.screen_reader_engine import ScreenReaderEngine


class OptionsMenu:
    """Options menu for configuring BookStorm settings"""

    def __init__(self, config, speechEngine, voiceSelector, audioPlayer, ttsReloadCallback=None):
        """
        Initialize options menu

        Args:
            config: ConfigManager instance
            speechEngine: SpeechEngine instance
            voiceSelector: VoiceSelector instance
            audioPlayer: MpvPlayer instance
            ttsReloadCallback: Optional callback to reload TTS engine
        """
        self.config = config
        self.speechEngine = speechEngine
        self.voiceSelector = voiceSelector
        self.audioPlayer = audioPlayer
        self.ttsReloadCallback = ttsReloadCallback
        self.currentSelection = 0
        self.inMenu = False
        self.screenReaderName = None
        self._refresh_screen_reader_target()

    def _refresh_screen_reader_target(self):
        """Detect active supported screen reader for optional engine entry."""
        self.screenReaderName = None
        try:
            detectionEngine = ScreenReaderEngine(quiet=True)
            if detectionEngine.is_available():
                activeName = detectionEngine.get_active_reader_name()
                if activeName and activeName != "Unavailable":
                    self.screenReaderName = activeName
                else:
                    self.screenReaderName = "Screen Reader"
            detectionEngine.close()
        except Exception:
            self.screenReaderName = None

    def _get_engine_labels(self):
        """Return user-facing labels for available engine values."""
        engineLabels = {
            'piper': 'Piper-TTS',
            'speechd': 'Speech-Dispatcher',
            'screenreader': 'Screen Reader'
        }
        if self.screenReaderName:
            engineLabels['screenreader'] = self.screenReaderName
        return engineLabels

    def _get_engine_cycle_order(self):
        """Return engine cycle order, skipping screen-reader mode when unavailable."""
        engineOrder = ['piper', 'speechd']
        if self.screenReaderName:
            engineOrder.append('screenreader')
        return engineOrder

    def show_main_menu(self):
        """
        Show main options menu

        Returns:
            Menu items as list of dicts
        """
        readerEngine = self.config.get_reader_engine()
        engineLabels = self._get_engine_labels()
        readerEngineText = engineLabels.get(readerEngine, str(readerEngine))

        menuItems = [
            {
                'label': f"Reader Engine: {readerEngineText}",
                'action': 'toggle_reader_engine'
            },
            {
                'label': "Select Reader Voice",
                'action': 'select_voice'
            }
        ]

        # Add output module selection only when using speech-dispatcher
        if readerEngine == 'speechd':
            menuItems.append({
                'label': "Select Speech Engine",
                'action': 'select_output_module'
            })

        # Add text display toggle
        showText = self.config.get_show_text()
        showTextLabel = "Show Text Display: On" if showText else "Show Text Display: Off"

        # Add Audiobookshelf setup status
        absConfigured = self.config.is_abs_configured()
        absLabel = "Audiobookshelf: Configured" if absConfigured else "Audiobookshelf: Not Configured"

        menuItems.extend([
            {
                'label': showTextLabel,
                'action': 'toggle_show_text'
            },
            {
                'label': "Speech Rate Settings",
                'action': 'speech_rate'
            },
            {
                'label': absLabel,
                'action': 'audiobookshelf_setup'
            },
            {
                'label': "Back",
                'action': 'back'
            }
        ])

        return menuItems

    def navigate_menu(self, direction):
        """
        Navigate menu up or down

        Args:
            direction: 'up' or 'down'

        Returns:
            Current menu item
        """
        menuItems = self.show_main_menu()

        if direction == 'up':
            self.currentSelection = (self.currentSelection - 1) % len(menuItems)
        elif direction == 'down':
            self.currentSelection = (self.currentSelection + 1) % len(menuItems)

        currentItem = menuItems[self.currentSelection]
        self.speechEngine.speak(currentItem['label'])
        return currentItem

    def activate_current_item(self):
        """
        Activate currently selected menu item

        Returns:
            True to stay in menu, False to exit
        """
        menuItems = self.show_main_menu()
        currentItem = menuItems[self.currentSelection]
        action = currentItem['action']

        if action == 'toggle_reader_engine':
            return self._toggle_reader_engine()
        elif action == 'select_voice':
            return self._select_voice()
        elif action == 'select_output_module':
            return self._select_output_module()
        elif action == 'toggle_show_text':
            return self._toggle_show_text()
        elif action == 'speech_rate':
            return self._speech_rate_info()
        elif action == 'audiobookshelf_setup':
            return self._audiobookshelf_setup()
        elif action == 'back':
            self.speechEngine.speak("Closing options menu")
            return False

        return True

    def _toggle_reader_engine(self):
        """Cycle reader engine: piper-tts, speech-dispatcher, screen reader."""
        self._refresh_screen_reader_target()
        currentEngine = self.config.get_reader_engine()
        validEngines = {'piper', 'speechd', 'screenreader'}
        oldEngine = currentEngine if currentEngine in validEngines else 'piper'
        engineOrder = self._get_engine_cycle_order()
        engineLabels = self._get_engine_labels()

        if currentEngine not in engineOrder:
            currentEngine = 'piper'

        currentIndex = engineOrder.index(currentEngine)
        newEngine = engineOrder[(currentIndex + 1) % len(engineOrder)]
        self.config.set_reader_engine(newEngine)
        message = f"Reader engine: {engineLabels.get(newEngine, newEngine)}."

        # Reload TTS engine if callback available
        needsRestart = False
        if self.ttsReloadCallback:
            try:
                self.ttsReloadCallback()
            except Exception as e:
                print(f"Error reloading TTS engine: {e}")
                needsRestart = True
        else:
            needsRestart = True

        if needsRestart:
            # Show restart confirmation dialog
            self.previousEngine = oldEngine
            self.inRestartMenu = True
            self.restartSelection = 0
            message = "Restart required. Restart now or cancel?"
            self.speechEngine.speak(message)
            print(message)
            # Speak first option
            self.speechEngine.speak("Restart now")
        else:
            finalEngine = self.config.get_reader_engine()
            if finalEngine in engineLabels:
                message = f"Reader engine: {engineLabels[finalEngine]}."
            self.speechEngine.speak(message)
            print(message)

        return True

    def _select_voice(self):
        """Select voice based on current reader engine"""
        readerEngine = self.config.get_reader_engine()

        if readerEngine == 'piper':
            return self._select_piper_voice()
        if readerEngine == 'speechd':
            return self._select_speechd_voice()

        self._refresh_screen_reader_target()
        readerName = self.screenReaderName if self.screenReaderName else "your active screen reader"
        self.speechEngine.speak(f"Voice selection is managed by {readerName}.")
        return True

    def _select_piper_voice(self):
        """Select piper-tts voice"""
        self.speechEngine.speak("Selecting piper voice. Use arrow keys to browse, enter to select, escape to cancel.")

        voices = self.voiceSelector.get_voices()
        if not voices:
            self.speechEngine.speak("No piper voices found.")
            return True

        # Store current selection for voice browsing
        self.voiceSelection = 0
        self.voiceList = voices
        self.inVoiceMenu = True

        # Speak first voice using piper
        try:
            voice = voices[0]
            tts = TtsEngine(voice['path'])

            voiceName = voice['name'].split('(')[0].strip()
            text = f"Hi, my name is {voiceName}"
            wavData = tts.text_to_wav_data(text)

            if wavData:
                self.audioPlayer.play_wav_data(wavData)
        except Exception as e:
            # Fallback to speech-dispatcher
            print(f"Error playing voice sample: {e}")
            self.speechEngine.speak(voices[0]['name'])

        return True

    def _select_speechd_voice(self):
        """Select speech-dispatcher voice"""
        voices = self.speechEngine.list_voices()

        if not voices:
            self.speechEngine.speak("No speech dispatcher voices available.")
            return True

        self.speechEngine.speak("Selecting speech dispatcher voice. Use arrow keys to browse, enter to select, escape to cancel.")

        # Store current selection for voice browsing
        self.voiceSelection = 0
        self.voiceList = voices
        self.inVoiceMenu = True

        # Speak first voice
        if len(voices) > 0:
            voice = voices[0]
            if isinstance(voice, tuple):
                voiceName = f"{voice[0]} ({voice[1]})"
            else:
                voiceName = str(voice)
            self.speechEngine.speak(voiceName)

        return True

    def navigate_voice_menu(self, direction):
        """Navigate voice selection menu"""
        if not hasattr(self, 'voiceList') or not self.voiceList:
            return

        if direction == 'up':
            self.voiceSelection = (self.voiceSelection - 1) % len(self.voiceList)
        elif direction == 'down':
            self.voiceSelection = (self.voiceSelection + 1) % len(self.voiceList)

        # Speak current voice
        voice = self.voiceList[self.voiceSelection]
        readerEngine = self.config.get_reader_engine()

        if readerEngine == 'piper':
            # Use piper to speak the voice name with that voice
            try:
                tts = TtsEngine(voice['path'])

                # Generate voice speaking its own name
                voiceName = voice['name'].split('(')[0].strip()
                text = f"Hi, my name is {voiceName}"
                wavData = tts.text_to_wav_data(text)

                if wavData:
                    self.audioPlayer.play_wav_data(wavData)
            except Exception as e:
                # Fallback to speech-dispatcher if error
                print(f"Error playing voice sample: {e}")
                self.speechEngine.speak(voice['name'])
        else:
            # Format speech-dispatcher voice tuple
            if isinstance(voice, tuple):
                voiceName = f"{voice[0]} ({voice[1]})"
            else:
                voiceName = str(voice)
            self.speechEngine.speak(voiceName)

    def select_current_voice(self):
        """Select the currently highlighted voice"""
        if not hasattr(self, 'voiceList') or not self.voiceList:
            return True

        voice = self.voiceList[self.voiceSelection]
        readerEngine = self.config.get_reader_engine()

        if readerEngine == 'piper':
            # Save piper voice
            self.config.set_voice_model(voice['path'])
            message = f"Voice selected: {voice['name']}."

            # Reload TTS engine if callback available
            if self.ttsReloadCallback:
                try:
                    self.ttsReloadCallback()
                except Exception as e:
                    print(f"Error reloading TTS engine: {e}")
                    message += " Restart required."
            else:
                message += " Restart required."

            self.speechEngine.speak(message)
            print(message)
        else:
            # Save speechd voice - extract name from tuple
            if isinstance(voice, tuple):
                voiceName = voice[0]  # First element is the voice name
                displayName = f"{voice[0]} ({voice[1]})"
            else:
                voiceName = str(voice)
                displayName = voiceName

            self.config.set_speechd_voice(voiceName)
            self.speechEngine.set_voice(voiceName)
            message = f"Voice selected: {displayName}"
            self.speechEngine.speak(message)
            print(message)

        # Exit voice menu
        self.inVoiceMenu = False
        return True

    def _select_output_module(self):
        """Select speech-dispatcher output module"""
        modules = self.speechEngine.list_output_modules()

        if not modules:
            self.speechEngine.speak("No output modules available.")
            return True

        self.speechEngine.speak("Selecting speech engine. Use arrow keys to browse, enter to select, escape to cancel.")

        # Store current selection for module browsing
        self.moduleSelection = 0
        self.moduleList = modules
        self.inModuleMenu = True

        # Speak first module
        if len(modules) > 0:
            self.speechEngine.speak(modules[0])

        return True

    def navigate_module_menu(self, direction):
        """Navigate output module selection menu"""
        if not hasattr(self, 'moduleList') or not self.moduleList:
            return

        if direction == 'up':
            self.moduleSelection = (self.moduleSelection - 1) % len(self.moduleList)
        elif direction == 'down':
            self.moduleSelection = (self.moduleSelection + 1) % len(self.moduleList)

        # Speak current module
        module = self.moduleList[self.moduleSelection]
        self.speechEngine.speak(module)

    def select_current_module(self):
        """Select the currently highlighted output module"""
        if not hasattr(self, 'moduleList') or not self.moduleList:
            return True

        module = self.moduleList[self.moduleSelection]

        # Save and set output module
        self.config.set_speechd_output_module(module)
        self.speechEngine.set_output_module(module)
        message = f"Speech engine selected: {module}"
        self.speechEngine.speak(message)
        print(message)

        # Exit module menu
        self.inModuleMenu = False
        return True

    def exit_module_menu(self):
        """Exit output module selection menu"""
        self.inModuleMenu = False
        self.speechEngine.speak("Cancelled. Back to options menu.")
        # Speak current main menu item
        menuItems = self.show_main_menu()
        if menuItems and self.currentSelection < len(menuItems):
            self.speechEngine.speak(menuItems[self.currentSelection]['label'])

    def is_in_module_menu(self):
        """Check if currently in output module selection submenu"""
        return hasattr(self, 'inModuleMenu') and self.inModuleMenu

    def is_in_restart_menu(self):
        """Check if currently in restart confirmation dialog"""
        return hasattr(self, 'inRestartMenu') and self.inRestartMenu

    def navigate_restart_menu(self, direction):
        """Navigate restart confirmation menu"""
        # Toggle between "Restart now" (0) and "Cancel" (1)
        if direction == 'up' or direction == 'down':
            self.restartSelection = 1 - self.restartSelection

        # Speak current option
        if self.restartSelection == 0:
            self.speechEngine.speak("Restart now")
        else:
            self.speechEngine.speak("Cancel")

    def select_restart_option(self):
        """Handle restart menu selection"""
        if self.restartSelection == 0:
            # Restart now - exit cleanly
            self.speechEngine.speak("Restarting. Please run bookstorm again.")
            import sys
            sys.exit(0)
        else:
            # Cancel - revert engine change
            validEngines = {'piper', 'speechd', 'screenreader'}
            revertEngine = self.previousEngine if self.previousEngine in validEngines else 'piper'
            self.config.set_reader_engine(revertEngine)
            self.inRestartMenu = False
            self.speechEngine.speak("Cancelled. Engine change reverted.")
            # Speak current main menu item
            menuItems = self.show_main_menu()
            if menuItems and self.currentSelection < len(menuItems):
                self.speechEngine.speak(menuItems[self.currentSelection]['label'])
        return True

    def exit_restart_menu(self):
        """Exit restart confirmation menu (same as cancel)"""
        validEngines = {'piper', 'speechd', 'screenreader'}
        revertEngine = self.previousEngine if self.previousEngine in validEngines else 'piper'
        self.config.set_reader_engine(revertEngine)
        self.inRestartMenu = False
        self.speechEngine.speak("Cancelled. Engine change reverted.")
        # Speak current main menu item
        menuItems = self.show_main_menu()
        if menuItems and self.currentSelection < len(menuItems):
            self.speechEngine.speak(menuItems[self.currentSelection]['label'])

    def _toggle_show_text(self):
        """Toggle text display on/off"""
        currentSetting = self.config.get_show_text()
        newSetting = not currentSetting
        self.config.set_show_text(newSetting)

        if newSetting:
            message = "Text display: On"
        else:
            message = "Text display: Off"

        self.speechEngine.speak(message)
        print(message)
        return True

    def _speech_rate_info(self):
        """Show speech rate information"""
        currentRate = self.config.get_speech_rate()
        message = f"Current speech rate: {currentRate}. Use Page Up and Page Down to adjust during reading."
        self.speechEngine.speak(message)
        print(message)
        return True

    def enter_menu(self):
        """Enter the options menu"""
        self._refresh_screen_reader_target()
        self.inMenu = True
        self.currentSelection = 0
        self.inVoiceMenu = False
        self.speechEngine.speak("Options menu. Use arrow keys to navigate, Enter to select, Escape to close.")

        # Speak first item
        menuItems = self.show_main_menu()
        if menuItems:
            self.speechEngine.speak(menuItems[0]['label'])

    def is_in_menu(self):
        """Check if currently in menu"""
        return self.inMenu

    def is_in_voice_menu(self):
        """Check if currently in voice selection submenu"""
        return hasattr(self, 'inVoiceMenu') and self.inVoiceMenu

    def exit_voice_menu(self):
        """Exit voice selection menu"""
        self.inVoiceMenu = False
        self.speechEngine.speak("Cancelled. Back to options menu.")
        # Speak current main menu item
        menuItems = self.show_main_menu()
        if menuItems and self.currentSelection < len(menuItems):
            self.speechEngine.speak(menuItems[self.currentSelection]['label'])

    def _audiobookshelf_setup(self):
        """Setup Audiobookshelf server connection"""
        from src.ui import get_input

        self.speechEngine.speak("Audiobookshelf setup starting.")

        # Show current settings if configured
        currentUrl = ""
        currentUser = ""
        if self.config.is_abs_configured():
            currentUrl = self.config.get_abs_server_url()
            currentUser = self.config.get_abs_username()
            self.speechEngine.speak(f"Current server: {currentUrl}. Current username: {currentUser}. Leave fields blank to keep current values.")

        # Get server URL
        serverUrlPrompt = "Enter Audiobookshelf server URL. Example: https colon slash slash abs dot example dot com"
        serverUrl = get_input(self.speechEngine, serverUrlPrompt, currentUrl)

        if serverUrl is None:
            self.speechEngine.speak("Setup cancelled.")
            return True

        serverUrl = serverUrl.strip()

        if not serverUrl and self.config.is_abs_configured():
            serverUrl = currentUrl
            self.speechEngine.speak(f"Using current URL: {serverUrl}")
        elif not serverUrl:
            self.speechEngine.speak("Server URL required. Setup cancelled.")
            return True

        # Validate URL format
        if not serverUrl.startswith(('http://', 'https://')):
            self.speechEngine.speak("Invalid URL. Must start with http or https. Setup cancelled.")
            return True

        # Get username
        usernamePrompt = "Enter Audiobookshelf username"
        username = get_input(self.speechEngine, usernamePrompt, currentUser)

        if username is None:
            self.speechEngine.speak("Setup cancelled.")
            return True

        username = username.strip()

        if not username and self.config.is_abs_configured():
            username = currentUser
            self.speechEngine.speak(f"Using current username: {username}")
        elif not username:
            self.speechEngine.speak("Username required. Setup cancelled.")
            return True

        # Get password
        passwordPrompt = "Enter password for testing connection. Note: Password is NOT saved, only the authentication token."
        password = get_input(self.speechEngine, passwordPrompt, "")

        if password is None:
            self.speechEngine.speak("Setup cancelled.")
            return True

        if not password:
            self.speechEngine.speak("Password required. Setup cancelled.")
            return True

        # Test connection
        self.speechEngine.speak("Testing connection. Please wait.")

        # Import here to avoid circular dependency
        from src.audiobookshelf_client import AudiobookshelfClient

        # Create temporary client to test
        testClient = AudiobookshelfClient(serverUrl, None)

        if not testClient.login(username, password):
            self.speechEngine.speak("Login failed. Check server URL, username, and password. Make sure the server is reachable and credentials are correct.")
            return True

        # Login successful - get token
        authToken = testClient.authToken

        # Save settings
        self.config.set_abs_server_url(serverUrl)
        self.config.set_abs_username(username)
        self.config.set_abs_auth_token(authToken)

        self.speechEngine.speak("Setup successful. Audiobookshelf configured. You can now press a to browse your Audiobookshelf library.")

        return True

    def exit_menu(self):
        """Exit the menu"""
        self.inMenu = False
        self.inVoiceMenu = False
        self.currentSelection = 0
