#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Voice Selector

Interactive voice selection interface for piper-tts voices.
Allows browsing, testing, and selecting voice models.
"""

from pathlib import Path
from src.tts_engine import TtsEngine
from src.mpv_player import MpvPlayer


class VoiceSelector:
    """Voice selection interface"""

    def __init__(self, voiceDir=None):
        """
        Initialize voice selector

        Args:
            voiceDir: Directory containing voice models
        """
        if voiceDir is None:
            voiceDir = "/usr/share/piper-voices/en/en_US"

        self.voiceDir = Path(voiceDir)
        self.voices = []
        self._scan_voices()

    def _scan_voices(self):
        """Scan for available voice models"""
        self.voices = []

        if not self.voiceDir.exists():
            return

        # Find all .onnx files recursively
        for onnxFile in self.voiceDir.rglob("*.onnx"):
            voiceName = self._extract_voice_name(onnxFile)
            self.voices.append({
                'name': voiceName,
                'path': str(onnxFile),
                'relPath': str(onnxFile.relative_to(self.voiceDir))
            })

        # Sort by name
        self.voices.sort(key=lambda v: v['name'])

    def _extract_voice_name(self, voicePath):
        """
        Extract readable voice name from path

        Args:
            voicePath: Path to voice model file

        Returns:
            Human-readable voice name
        """
        voicePath = Path(voicePath)

        # Get parts of the path
        parts = voicePath.parts

        # Try to extract from filename pattern: en_US-voicename-quality.onnx
        filename = voicePath.stem  # Remove .onnx
        nameParts = filename.split('-')

        if len(nameParts) >= 2:
            # nameParts[1] is usually the voice name
            voiceName = nameParts[1].replace('_', ' ').title()
            quality = nameParts[2] if len(nameParts) > 2 else ''

            if quality:
                return f"{voiceName} ({quality})"
            return voiceName

        # Fallback to filename
        return voicePath.stem

    def get_voices(self):
        """
        Get list of available voices

        Returns:
            List of voice dictionaries
        """
        return self.voices

    def _test_voice(self, voice):
        """
        Test a voice by playing sample text

        Args:
            voice: Voice dictionary
        """
        print(f"\nTesting voice: {voice['name']}")

        voiceName = voice['name'].split('(')[0].strip()  # Remove quality suffix
        testText = f"Hi, my name is {voiceName}, and I am a piper text to speech voice. Do you like the way I sound?"

        try:
            tts = TtsEngine(voice['path'])
            player = MpvPlayer()

            print("Generating speech...")
            wavData = tts.text_to_wav_data(testText)

            if wavData:
                print("Playing...")
                player.play_wav_data(wavData)
                # Wait for playback to finish
                import time
                while player.is_playing():
                    time.sleep(0.1)

            player.cleanup()

        except Exception as e:
            print(f"Error testing voice: {e}")

    def find_voice_by_name(self, name):
        """
        Find voice by name (case-insensitive partial match)

        Args:
            name: Voice name to search for

        Returns:
            Voice path or None if not found
        """
        name = name.lower()

        for voice in self.voices:
            if name in voice['name'].lower():
                return voice['path']

        return None
