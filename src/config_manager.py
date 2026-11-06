#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Config Manager

Manages BookStorm settings using INI format.
Settings stored in ~/.config/stormux/bookstorm/settings.ini
"""

import configparser
from pathlib import Path


class ConfigManager:
    """Manages application configuration"""

    def __init__(self, configPath=None):
        """
        Initialize config manager

        Args:
            configPath: Path to config file (optional)
        """
        if configPath is None:
            homePath = Path.home()
            configDir = homePath / ".config" / "stormux" / "bookstorm"
            configDir.mkdir(parents=True, exist_ok=True)
            configPath = configDir / "settings.ini"

        self.configPath = Path(configPath)
        self.config = configparser.ConfigParser()

        # Load or create config
        if self.configPath.exists():
            self.config.read(self.configPath)
        else:
            self._create_default_config()

    def _create_default_config(self):
        """Create default configuration"""
        self.config['TTS'] = {
            'voice_model': '/usr/share/piper-voices/en/en_US/hfc_male/medium/en_US-hfc_male-medium.onnx',
            'voice_dir': '/usr/share/piper-voices/en/en_US',
            'reader_engine': 'piper',
            'speechd_voice': '',
            'speechd_output_module': '',
            'speech_rate': '0'
        }

        self.config['Reading'] = {
            'auto_advance': 'true',
            'auto_save_bookmark': 'true'
        }

        self.config['Display'] = {
            'show_text': 'true'
        }

        self.config['Audio'] = {
            'playback_speed': '1.0',
            'volume': '100'
        }

        self.config['Paths'] = {
            'last_book': '',
            'books_directory': str(Path.home()),
            'library_directory': ''
        }

        self.config['Audiobookshelf'] = {
            'server_url': '',
            'username': '',
            'auth_token': '',
            'auto_sync': 'true',
            'sync_interval': '30',
            'prefer_local': 'true',
            'stream_cache_limit': '500'
        }

        self.save()

    def get(self, section, key, fallback=None):
        """
        Get configuration value

        Args:
            section: Config section
            key: Config key
            fallback: Default value if not found

        Returns:
            Configuration value
        """
        try:
            return self.config.get(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback

    def get_bool(self, section, key, fallback=False):
        """
        Get boolean configuration value

        Args:
            section: Config section
            key: Config key
            fallback: Default value if not found

        Returns:
            Boolean configuration value
        """
        try:
            return self.config.getboolean(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback

    def set(self, section, key, value):
        """
        Set configuration value

        Args:
            section: Config section
            key: Config key
            value: Value to set
        """
        if not self.config.has_section(section):
            self.config.add_section(section)

        self.config.set(section, key, str(value))

    def save(self):
        """Save configuration to file"""
        with open(self.configPath, 'w') as configFile:
            self.config.write(configFile)

    def get_voice_model(self):
        """Get configured voice model path"""
        return self.get('TTS', 'voice_model')

    def set_voice_model(self, modelPath):
        """Set voice model path"""
        self.set('TTS', 'voice_model', str(modelPath))
        self.save()

    def get_voice_dir(self):
        """Get voice models directory"""
        return self.get('TTS', 'voice_dir', '/usr/share/piper-voices/en/en_US')

    def set_voice_dir(self, voiceDir):
        """Set voice models directory"""
        self.set('TTS', 'voice_dir', str(voiceDir))
        self.save()

    def get_last_book(self):
        """Get last opened book path"""
        lastBook = self.get('Paths', 'last_book')
        return lastBook if lastBook else None

    def set_last_book(self, bookPath):
        """Set last opened book path"""
        self.set('Paths', 'last_book', str(bookPath))
        self.save()

    def get_books_directory(self):
        """Get books directory for file browser"""
        return self.get('Paths', 'books_directory', str(Path.home()))

    def set_books_directory(self, booksDir):
        """Set books directory"""
        self.set('Paths', 'books_directory', str(booksDir))
        self.save()

    def get_auto_advance(self):
        """Get auto-advance setting"""
        return self.get_bool('Reading', 'auto_advance', True)

    def get_auto_save(self):
        """Get auto-save bookmark setting"""
        return self.get_bool('Reading', 'auto_save_bookmark', True)

    def get_reader_engine(self):
        """Get reader engine (piper, speechd, or screenreader)"""
        return self.get('TTS', 'reader_engine', 'piper')

    def set_reader_engine(self, engine):
        """Set reader engine (piper, speechd, or screenreader)"""
        if engine in ['piper', 'speechd', 'screenreader']:
            self.set('TTS', 'reader_engine', engine)
            self.save()

    def get_speechd_voice(self):
        """Get speech-dispatcher voice"""
        return self.get('TTS', 'speechd_voice', '')

    def set_speechd_voice(self, voice):
        """Set speech-dispatcher voice"""
        self.set('TTS', 'speechd_voice', str(voice))
        self.save()

    def get_speechd_output_module(self):
        """Get speech-dispatcher output module"""
        return self.get('TTS', 'speechd_output_module', '')

    def set_speechd_output_module(self, module):
        """Set speech-dispatcher output module"""
        self.set('TTS', 'speechd_output_module', str(module))
        self.save()

    def get_speech_rate(self):
        """Get speech rate"""
        try:
            return int(self.get('TTS', 'speech_rate', '0'))
        except ValueError:
            return 0

    def set_speech_rate(self, rate):
        """Set speech rate"""
        self.set('TTS', 'speech_rate', str(rate))
        self.save()

    def get_show_text(self):
        """Get show text display setting"""
        return self.get_bool('Display', 'show_text', True)

    def set_show_text(self, enabled):
        """Set show text display setting"""
        self.set('Display', 'show_text', str(enabled).lower())
        self.save()

    def get_library_directory(self):
        """Get library directory (default starting point for book browser)"""
        return self.get('Paths', 'library_directory', '')

    def set_library_directory(self, libraryDir):
        """Set library directory"""
        self.set('Paths', 'library_directory', str(libraryDir))
        self.save()

    # Audiobookshelf settings

    def get_abs_server_url(self):
        """Get Audiobookshelf server URL"""
        return self.get('Audiobookshelf', 'server_url', '')

    def set_abs_server_url(self, serverUrl):
        """Set Audiobookshelf server URL"""
        self.set('Audiobookshelf', 'server_url', str(serverUrl))
        self.save()

    def get_abs_username(self):
        """Get Audiobookshelf username"""
        return self.get('Audiobookshelf', 'username', '')

    def set_abs_username(self, username):
        """Set Audiobookshelf username"""
        self.set('Audiobookshelf', 'username', str(username))
        self.save()

    def get_abs_auth_token(self):
        """Get Audiobookshelf authentication token"""
        return self.get('Audiobookshelf', 'auth_token', '')

    def set_abs_auth_token(self, token):
        """Set Audiobookshelf authentication token"""
        self.set('Audiobookshelf', 'auth_token', str(token))
        self.save()

    def get_abs_auto_sync(self):
        """Get Audiobookshelf auto-sync setting"""
        return self.get_bool('Audiobookshelf', 'auto_sync', True)

    def set_abs_auto_sync(self, enabled):
        """Set Audiobookshelf auto-sync setting"""
        self.set('Audiobookshelf', 'auto_sync', str(enabled).lower())
        self.save()

    def get_abs_sync_interval(self):
        """Get Audiobookshelf sync interval in seconds"""
        try:
            return int(self.get('Audiobookshelf', 'sync_interval', '30'))
        except ValueError:
            return 30

    def set_abs_sync_interval(self, seconds):
        """Set Audiobookshelf sync interval in seconds"""
        self.set('Audiobookshelf', 'sync_interval', str(seconds))
        self.save()

    def get_abs_prefer_local(self):
        """Get Audiobookshelf prefer local books setting"""
        return self.get_bool('Audiobookshelf', 'prefer_local', True)

    def set_abs_prefer_local(self, enabled):
        """Set Audiobookshelf prefer local books setting"""
        self.set('Audiobookshelf', 'prefer_local', str(enabled).lower())
        self.save()

    def get_abs_stream_cache_limit(self):
        """Get Audiobookshelf stream cache limit in MB"""
        try:
            return int(self.get('Audiobookshelf', 'stream_cache_limit', '500'))
        except ValueError:
            return 500

    def set_abs_stream_cache_limit(self, limitMb):
        """Set Audiobookshelf stream cache limit in MB"""
        self.set('Audiobookshelf', 'stream_cache_limit', str(limitMb))
        self.save()

    def is_abs_configured(self):
        """Check if Audiobookshelf server is configured"""
        serverUrl = self.get_abs_server_url()
        username = self.get_abs_username()
        return bool(serverUrl and username)

    def get_playback_speed(self):
        """Get audio playback speed (0.5 to 2.0)"""
        try:
            speed = float(self.get('Audio', 'playback_speed', '1.0'))
            # Clamp to valid range
            return max(0.5, min(2.0, speed))
        except ValueError:
            return 1.0

    def set_playback_speed(self, speed):
        """Set audio playback speed (0.5 to 2.0)"""
        # Clamp to valid range
        speed = max(0.5, min(2.0, float(speed)))
        self.set('Audio', 'playback_speed', str(speed))
        self.save()

    def get_volume(self):
        """Get audio volume (0-200, 100 is normal)"""
        try:
            volume = int(self.get('Audio', 'volume', '100'))
            # Clamp to valid range
            return max(0, min(200, volume))
        except ValueError:
            return 100

    def set_volume(self, volume):
        """Set audio volume (0-200, 100 is normal)"""
        # Clamp to valid range
        volume = max(0, min(200, int(volume)))
        self.set('Audio', 'volume', str(volume))
        self.save()

    def save_settings(self):
        """Alias for save() - for backward compatibility"""
        self.save()
