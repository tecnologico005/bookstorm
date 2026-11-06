#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MPV Audio Player

Audio playback using python-mpv for both TTS and audio books.
Supports real-time speed control without re-encoding.
"""

import os
import gc
import time
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor

try:
    import mpv
    HAS_MPV = True
except ImportError:
    HAS_MPV = False


class MpvPlayer:
    """Audio player using mpv for all playback"""

    def __init__(self):
        """Initialize mpv audio player"""
        self.isInitialized = False
        self.player = None
        self.isPaused = False
        self.audioFileLoaded = False  # Track if audio file is loaded
        self.playbackSpeed = 1.0  # Current playback speed
        self.volume = 100  # Current volume level (0-200)
        self.endFileCallback = None  # Callback for when file finishes
        self.playlist = []  # Current playlist (for multi-file audiobooks)
        self.currentPlaylistIndex = 0  # Current file index in playlist
        self.activeTempFiles = []  # Track temp files for cleanup
        self.tempFileLock = threading.Lock()  # Protect temp file list
        # Thread pool for cleanup tasks (prevents daemon thread accumulation)
        self.cleanupExecutor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mpv-cleanup")

        if not HAS_MPV:
            print("Warning: python-mpv not installed. Audio playback will not work.")
            print("Install with: pip install python-mpv")
            return

        try:
            # Initialize mpv player
            # pylint: disable=no-member
            self.player = mpv.MPV(
                input_default_bindings=False,  # Disable default key bindings
                input_vo_keyboard=False,  # Disable keyboard input
                video=False,  # Audio only
                ytdl=False,  # Don't use youtube-dl
                quiet=True,  # Minimal console output
                demuxer_max_bytes='20M',  # Reduced from 50M - limit demuxer cache
                demuxer_max_back_bytes='5M',  # Reduced from 10M - limit backward cache
                cache=False,  # Disable additional caching for local files
                audio_buffer=0.5,  # Reduce audio buffer to 0.5 seconds (default is 2s)
            )

            # Register event handler for cleanup
            @self.player.event_callback('end-file')
            def on_end_file(event):
                """Called when file finishes playing"""
                # Call user callback if set
                if self.endFileCallback:
                    self.endFileCallback()

            self.isInitialized = True

        except Exception as e:
            print(f"Warning: Could not initialize mpv: {e}")
            self.isInitialized = False

    def play_wav_data(self, wavData, playbackSpeed=None):
        """
        Play WAV data directly from memory (for TTS)

        Args:
            wavData: WAV file data as bytes
            playbackSpeed: Playback speed (0.5 to 2.0), uses current speed if None

        Returns:
            True if playback started successfully
        """
        if not self.isInitialized or not self.player:
            return False

        import tempfile
        tempFile = None
        try:
            # Create a temporary file for the WAV data
            # python-mpv needs a file path, it can't play from memory directly
            tempFile = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            tempFile.write(wavData)
            tempFile.close()

            # Use current playback speed if not specified
            if playbackSpeed is None:
                playbackSpeed = self.playbackSpeed

            # Track this temp file for cleanup
            with self.tempFileLock:
                self.activeTempFiles.append(tempFile.name)

            # Load and play the temp file
            success = self.load_audio_file(tempFile.name, playbackSpeed=playbackSpeed)
            if success:
                success = self.play_audio_file()

            # Schedule more aggressive cleanup with memory awareness
            if tempFile:
                import time
                def cleanup_temp_file(filepath, file_size):
                    # Shorter delay for smaller files, longer for larger ones
                    # Small files (<100KB): 0.5s delay
                    # Medium files (100KB-1MB): 1s delay  
                    # Large files (>1MB): 2s delay
                    if file_size < 100 * 1024:
                        delay = 0.5
                    elif file_size < 1024 * 1024:
                        delay = 1.0
                    else:
                        delay = 2.0
                    
                    time.sleep(delay)
                    try:
                        # Force garbage collection after file deletion
                        os.unlink(filepath)
                        import gc
                        gc.collect()  # Help reclaim memory sooner
                    except:
                        pass
                    # Remove from active list
                    with self.tempFileLock:
                        try:
                            # Remove by path if stored as string
                            if filepath in self.activeTempFiles:
                                self.activeTempFiles.remove(filepath)
                            else:
                                # Remove by dict path if stored as dict
                                for item in self.activeTempFiles:
                                    if isinstance(item, dict) and item.get('path') == filepath:
                                        self.activeTempFiles.remove(item)
                                        break
                        except ValueError:
                            pass  # Already removed
                
                # Use thread pool with file size for better memory management
                self.cleanupExecutor.submit(cleanup_temp_file, tempFile.name, len(wavData))

            return success

        except Exception as e:
            print(f"Error playing WAV data: {e}")
            return False


    def pause(self):
        """Pause playback"""
        if self.isInitialized and self.player:
            self.player.pause = True
            self.isPaused = True

    def resume(self):
        """Resume playback"""
        if self.isInitialized and self.player:
            self.player.pause = False
            self.isPaused = False

    def stop(self):
        """Stop playback"""
        if self.isInitialized and self.player:
            self.player.stop()
            self.isPaused = False
            # Immediately clean up any temp files
            self._cleanup_temp_files()

    def is_playing(self):
        """Check if audio is currently playing"""
        if not self.isInitialized or not self.player:
            return False
        try:
            # mpv is playing if not paused and not idle
            # pylint: disable=no-member
            return not self.player.pause and not self.player.idle_active
        except:
            return False

    def is_paused(self):
        """Check if audio is paused"""
        return self.isPaused

    def set_speed(self, speed):
        """
        Set playback speed

        Args:
            speed: Playback speed (0.5 to 2.0)
        """
        if not self.isInitialized or not self.player:
            return

        # Clamp speed to valid range
        speed = max(0.5, min(2.0, float(speed)))
        self.playbackSpeed = speed
        self.player.speed = speed

    def get_speed(self):
        """Get current playback speed"""
        return self.playbackSpeed

    def increase_volume(self, step=5):
        """
        Increase volume by step amount

        Args:
            step: Volume increase amount (default 5)

        Returns:
            Current volume level (0-200, allows software amplification)
        """
        if not self.isInitialized or not self.player:
            return 100

        try:
            # pylint: disable=no-member
            currentVolume = self.player.volume if self.player.volume is not None else 100
            # Allow up to 200% for software amplification (useful for quiet audio)
            newVolume = min(200, currentVolume + step)
            self.volume = newVolume
            self.player.volume = newVolume
            return int(newVolume)
        except Exception as e:
            print(f"Error increasing volume: {e}")
            return 100

    def decrease_volume(self, step=5):
        """
        Decrease volume by step amount

        Args:
            step: Volume decrease amount (default 5)

        Returns:
            Current volume level (0-100)
        """
        if not self.isInitialized or not self.player:
            return 100

        try:
            # pylint: disable=no-member
            currentVolume = self.player.volume if self.player.volume is not None else 100
            newVolume = max(0, currentVolume - step)
            self.volume = newVolume
            self.player.volume = newVolume
            return int(newVolume)
        except Exception as e:
            print(f"Error decreasing volume: {e}")
            return 100

    def get_volume(self):
        """
        Get current volume level

        Returns:
            Current volume (0-200, 100 is normal, >100 is software amplification)
        """
        # Return our tracked volume instead of querying mpv
        # This is more reliable, especially during cleanup
        return self.volume

    def set_volume(self, volume):
        """
        Set volume level

        Args:
            volume: Volume level (0-200, 100 is normal, >100 is software amplification)
        """
        if not self.isInitialized or not self.player:
            # Store it anyway for when player is ready
            self.volume = max(0, min(200, int(volume)))
            return

        try:
            # Clamp to valid range
            volume = max(0, min(200, int(volume)))
            self.volume = volume
            # pylint: disable=no-member
            self.player.volume = volume
        except Exception as e:
            print(f"Error setting volume: {e}")

    def _cleanup_temp_files(self):
        """Immediately clean up all active temp files"""
        import gc
        with self.tempFileLock:
            for tempPath in self.activeTempFiles:
                try:
                    if os.path.exists(tempPath):
                        os.unlink(tempPath)
                except Exception as e:
                    # Ignore errors - file might already be deleted
                    pass
            # Clear the list
            self.activeTempFiles = []
        # CRITICAL: Force FULL garbage collection to free memory from deleted files
        # After 30+ minutes of reading, temp file handles accumulate in older generations
        gc.collect()  # Full collection across all generations

    def _purge_mpv_buffers(self):
        """
        Aggressively purge mpv internal buffers and caches
        Call this between paragraphs to prevent memory accumulation
        """
        if not self.isInitialized or not self.player:
            return

        try:
            # Stop any playback first to release audio buffers
            self.player.stop()

            # Wait a moment for mpv to fully stop and release buffers
            import time
            time.sleep(0.05)

            # Force mpv to clear its internal demuxer cache
            # This releases memory held by the demuxer
            try:
                # Setting these properties forces mpv to flush caches
                # pylint: disable=no-member
                self.player.command('seek', 0, 'absolute')  # Dummy seek to flush
            except:
                pass  # Might fail if nothing is loaded, that's ok

            # Mark as unloaded so next load is clean
            self.audioFileLoaded = False

        except Exception as e:
            # Don't fail if buffer purge fails
            pass

    def cleanup(self):
        """Cleanup resources"""
        if self.isInitialized and self.player:
            try:
                self.player.stop()
            except:
                pass
            try:
                self.player.terminate()
            except:
                pass
            self.isInitialized = False
        # Clean up any remaining temp files
        self._cleanup_temp_files()
        # Shutdown cleanup thread pool (wait for pending tasks to finish)
        try:
            self.cleanupExecutor.shutdown(wait=True, cancel_futures=False)
        except:
            pass

    def is_available(self):
        """Check if mpv is available"""
        return self.isInitialized

    # Audio file playback methods (for audiobooks)

    def load_audio_file(self, audioPath, authToken=None, playbackSpeed=1.0, startPosition=0.0):
        """
        Load an audio file for streaming playback

        Args:
            audioPath: Path to audio file or URL
            authToken: Optional Bearer token for authenticated URLs
            playbackSpeed: Playback speed (0.5 to 2.0, default 1.0)
            startPosition: Start time in seconds (for resuming playback)

        Returns:
            True if loaded successfully
        """
        if not self.isInitialized:
            return False

        try:
            audioPath = str(audioPath)
            self.playbackSpeed = max(0.5, min(2.0, float(playbackSpeed)))

            # Aggressively purge mpv buffers before loading new file
            # This prevents memory accumulation over long reading sessions
            if self.audioFileLoaded:
                self._purge_mpv_buffers()

            # Check if this is a URL (for streaming from Audiobookshelf)
            isUrl = audioPath.startswith('http://') or audioPath.startswith('https://')

            if isUrl and authToken:
                # Load with authentication header
                # pylint: disable=no-member
                self.player.http_header_fields = [f'Authorization: Bearer {authToken}']
            else:
                # Clear any previous headers
                # pylint: disable=no-member
                self.player.http_header_fields = []

            # Set start position before loading (more reliable for streams than seeking after)
            if startPosition > 0:
                self.player.start = startPosition
            else:
                self.player.start = 0

            # Load the file (mpv handles all formats natively)
            self.player.loadfile(audioPath, 'replace')
            self.player.pause = True  # Keep paused until play_audio_file() is called
            self.player.speed = self.playbackSpeed
            # Restore volume setting (important for TTS paragraphs)
            self.player.volume = self.volume
            self.audioFileLoaded = True
            self.playlist = []  # Clear playlist (single file mode)
            self.currentPlaylistIndex = 0
            return True

        except Exception as e:
            print(f"Error loading audio file: {e}")
            self.audioFileLoaded = False
            return False

    def load_audio_playlist(self, audioFiles, authToken=None, playbackSpeed=1.0):
        """
        Load a playlist of audio files (for multi-file audiobooks)

        Args:
            audioFiles: List of audio file paths
            authToken: Optional Bearer token for authenticated URLs
            playbackSpeed: Playback speed (0.5 to 2.0, default 1.0)

        Returns:
            True if loaded successfully
        """
        if not self.isInitialized:
            return False

        if not audioFiles:
            return False

        try:
            self.playlist = [str(path) for path in audioFiles]
            self.currentPlaylistIndex = 0
            self.playbackSpeed = max(0.5, min(2.0, float(playbackSpeed)))

            # Aggressively purge mpv buffers before loading new playlist
            if self.audioFileLoaded:
                self._purge_mpv_buffers()

            # Load first file in playlist
            firstFile = self.playlist[0]

            # Check if this is a URL
            isUrl = firstFile.startswith('http://') or firstFile.startswith('https://')

            if isUrl and authToken:
                # pylint: disable=no-member
                self.player.http_header_fields = [f'Authorization: Bearer {authToken}']
            else:
                # pylint: disable=no-member
                self.player.http_header_fields = []

            # Load first file
            self.player.loadfile(firstFile, 'replace')

            # Add remaining files to mpv playlist
            for audioFile in self.playlist[1:]:
                self.player.loadfile(str(audioFile), 'append')

            self.player.pause = True
            self.player.speed = self.playbackSpeed
            # Restore volume setting (important for playlist/folder audiobooks)
            self.player.volume = self.volume
            self.audioFileLoaded = True
            return True

        except Exception as e:
            print(f"Error loading audio playlist: {e}")
            self.audioFileLoaded = False
            return False

    def play_audio_file(self, startPosition=0.0):
        """
        Play loaded audio file from a specific position

        Args:
            startPosition: Start time in seconds

        Returns:
            True if playback started successfully
        """
        if not self.isInitialized or not self.audioFileLoaded:
            return False

        try:
            # Start playback first (this ensures mpv begins loading/decoding)
            self.player.pause = False
            self.isPaused = False

            # Only seek if we have a non-zero start position
            # Seeking to position 0 immediately after load can fail if file isn't ready
            if startPosition > 0:
                # Wait a moment for file to be ready before seeking
                import time
                time.sleep(0.1)
                self.player.seek(startPosition, reference='absolute')

            return True

        except Exception as e:
            print(f"Error playing audio file: {e}")
            return False

    def pause_audio_file(self):
        """Pause audio file playback"""
        if self.isInitialized and self.audioFileLoaded:
            self.player.pause = True
            self.isPaused = True

    def resume_audio_file(self):
        """Resume audio file playback"""
        if self.isInitialized and self.audioFileLoaded:
            self.player.pause = False
            self.isPaused = False

    def stop_audio_file(self):
        """Stop audio file playback"""
        if self.isInitialized and self.audioFileLoaded:
            try:
                self.player.stop()
            except:
                pass
            self.isPaused = False
            # Clean up temp files when stopping
            self._cleanup_temp_files()

    def is_audio_file_playing(self):
        """Check if audio file is currently playing"""
        if not self.isInitialized or not self.audioFileLoaded:
            return False
        return self.is_playing()

    def get_audio_position(self):
        """
        Get current playback position in seconds

        Returns:
            Position in seconds, or 0.0 if not playing
        """
        if not self.isInitialized or not self.audioFileLoaded:
            return 0.0

        try:
            # pylint: disable=no-member
            pos = self.player.time_pos
            return pos if pos is not None else 0.0
        except:
            return 0.0

    def seek_audio(self, position):
        """
        Seek to a specific position in the audio file

        Args:
            position: Position in seconds

        Returns:
            True if seek successful
        """
        if not self.isInitialized or not self.audioFileLoaded:
            return False

        try:
            # For very small positions (< 1 second), just skip seeking
            # This avoids issues with mpv not being ready yet
            if position < 1.0:
                position = 0.0

            if position > 0:
                # Validate position against file duration
                duration = None
                try:
                    # pylint: disable=no-member
                    duration = self.player.duration

                    if duration is None:
                        # mpv hasn't loaded duration yet - wait a bit
                        import time
                        time.sleep(0.2)
                        duration = self.player.duration

                    if duration and position > duration:
                        position = max(0, duration - 1.0)  # Seek to 1 second before end
                except:
                    # If we can't get duration, DON'T seek - it will likely fail
                    return False

                self.player.seek(position, reference='absolute')

            return True
        except Exception as e:
            print(f"Error seeking audio to {position}s: {e}")
            # Don't fail completely - just start from beginning
            return True

    def unload_audio_file(self):
        """Unload the current audio file"""
        if self.audioFileLoaded:
            self.stop_audio_file()
            self.audioFileLoaded = False

    def is_audio_file_loaded(self):
        """Check if audio file is loaded"""
        return self.audioFileLoaded

    def set_end_file_callback(self, callback):
        """
        Set callback to be called when file finishes playing

        Args:
            callback: Function to call (no arguments)
        """
        self.endFileCallback = callback

    def get_current_playlist_index(self):
        """
        Get current playlist index (for multi-file audiobooks)

        Returns:
            Current file index in playlist (0 if not using playlist)
        """
        if not self.isInitialized or not self.audioFileLoaded:
            return 0

        if not self.playlist:
            return 0

        try:
            # Get current playlist position from mpv
            # pylint: disable=no-member
            playlistPos = self.player.playlist_pos
            if playlistPos is not None and 0 <= playlistPos < len(self.playlist):
                self.currentPlaylistIndex = playlistPos
                return playlistPos
        except:
            pass

        return self.currentPlaylistIndex

    def seek_to_playlist_index(self, index, waitForLoad=True):
        """
        Seek to a specific file in the playlist

        Args:
            index: File index in playlist
            waitForLoad: If True, wait for file to fully load before returning.
                        Set to False if you're immediately calling play_audio_file() after.

        Returns:
            True if seek successful
        """
        if not self.isInitialized or not self.audioFileLoaded:
            print(f"ERROR: Cannot seek - mpv not initialized or no audio loaded")
            return False

        if not self.playlist or index < 0 or index >= len(self.playlist):
            print(f"ERROR: Invalid playlist index: {index} (playlist has {len(self.playlist) if self.playlist else 0} items)")
            return False

        try:
            # Set playlist position
            # pylint: disable=no-member
            currentPos = self.player.playlist_pos

            # If playlist is idle (pos = -1), we need to unpause first to activate it
            if currentPos == -1:
                # Unpause to activate the playlist
                self.player.pause = False
                import time
                time.sleep(0.1)
                # Now pause again so we can seek
                self.player.pause = True
                time.sleep(0.1)

            # Now set the playlist position
            self.player.playlist_pos = index

            # Update our internal tracking
            self.currentPlaylistIndex = index

            # Optionally wait for mpv to load the new file
            # Skip this if caller will immediately play (play_audio_file will trigger load)
            if waitForLoad:
                import time
                maxWait = 2.0  # Maximum 2 seconds
                elapsed = 0.0
                interval = 0.05  # Check every 50ms

                while elapsed < maxWait:
                    time.sleep(interval)
                    elapsed += interval

                    try:
                        # Check if file has loaded by seeing if duration is available
                        duration = self.player.duration
                        if duration is not None:
                            break
                    except:
                        pass

            return True
        except Exception as e:
            print(f"Error seeking to playlist index {index}: {e}")
            return False