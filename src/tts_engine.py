#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TTS Engine Wrapper

Wrapper for piper-tts to generate speech from text.
Handles streaming audio generation for real-time playback.
"""

import subprocess
import wave
import io
import struct
import shutil

from .text_validator import is_valid_text


class TtsEngine:
    """Text-to-speech engine using piper-tts"""

    @staticmethod
    def is_available():
        """
        Check if piper-tts is available on the system

        Returns:
            bool: True if piper-tts is installed, False otherwise
        """
        return shutil.which('piper-tts') is not None

    def __init__(self, modelPath="/usr/share/piper-voices/en/en_US/hfc_male/medium/en_US-hfc_male-medium.onnx"):
        """
        Initialize TTS engine

        Args:
            modelPath: Path to piper-tts voice model
        """
        self.modelPath = modelPath
        self.sampleRate = 22050
        self.sampleWidth = 2  # 16-bit
        self.channels = 1

    def text_to_wav_data(self, text):
        """
        Convert text to WAV audio data

        Args:
            text: Text to convert to speech

        Returns:
            Bytes containing WAV audio data

        Raises:
            RuntimeError: If piper-tts fails
        """
        if not is_valid_text(text):
            return None

        # Safety: Limit text size to prevent excessive memory usage
        # ~10,000 chars = ~10-15 minutes of audio at normal reading speed
        # Reduced to 5000 to lower memory usage per paragraph
        MAX_TEXT_LENGTH = 5000
        if len(text) > MAX_TEXT_LENGTH:
            print(f"Warning: Paragraph too long ({len(text)} chars), truncating to {MAX_TEXT_LENGTH}")
            text = text[:MAX_TEXT_LENGTH] + "..."

        process = None
        try:
            # Run piper-tts with raw output
            process = subprocess.Popen(
                [
                    'piper-tts',
                    '--model', self.modelPath,
                    '--output-raw'
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            # Send text and get raw audio with timeout (60 seconds max)
            # This prevents hanging if piper-tts gets stuck
            rawAudio = None
            stderr = None
            try:
                rawAudio, stderr = process.communicate(
                    input=text.encode('utf-8'),
                    timeout=60
                )
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()  # Clean up
                raise RuntimeError("piper-tts timed out (>60s)")

            if process.returncode != 0:
                errorMsg = stderr.decode('utf-8', errors='ignore')
                del stderr  # Free stderr buffer immediately
                stderr = None
                raise RuntimeError(f"piper-tts failed: {errorMsg}")

            # Free stderr buffer immediately (can be large if piper-tts is verbose)
            if stderr:
                del stderr
                stderr = None

            # Convert raw PCM to WAV format
            wavData = self._raw_to_wav(rawAudio)

            # CRITICAL: Delete rawAudio immediately after conversion
            # This is a huge uncompressed buffer (~1-2MB per paragraph)
            if rawAudio:
                del rawAudio
                rawAudio = None

            # Ensure process is fully terminated and cleaned up
            if process:
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass

            return wavData

        except FileNotFoundError:
            raise RuntimeError("piper-tts not found. Please install piper-tts.")
        except Exception as e:
            # Clean up buffers on error
            if rawAudio:
                del rawAudio
            if stderr:
                del stderr
            # Ensure subprocess is terminated if something goes wrong
            if process and process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass  # Process is truly stuck, nothing we can do
            raise RuntimeError(f"TTS generation failed: {str(e)}")

    def _raw_to_wav(self, rawData):
        """
        Convert raw PCM data to WAV format

        Args:
            rawData: Raw PCM audio bytes

        Returns:
            WAV formatted bytes
        """
        wavBuffer = io.BytesIO()

        try:
            with wave.open(wavBuffer, 'wb') as wavFile:
                wavFile.setnchannels(self.channels)
                wavFile.setsampwidth(self.sampleWidth)
                wavFile.setframerate(self.sampleRate)
                wavFile.writeframes(rawData)

            wavBuffer.seek(0)
            result = wavBuffer.read()
        finally:
            # Explicitly close BytesIO to free memory
            wavBuffer.close()

        return result

    def get_audio_params(self):
        """
        Get audio parameters for playback

        Returns:
            Dictionary with sampleRate, sampleWidth, channels
        """
        return {
            'sampleRate': self.sampleRate,
            'sampleWidth': self.sampleWidth,
            'channels': self.channels
        }
