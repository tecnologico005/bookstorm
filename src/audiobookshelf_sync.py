#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Audiobookshelf Sync Manager

Tracks streaming session lifecycle and persisted progress updates.
"""

import time
from typing import Optional, Dict


class AudiobookshelfSync:
    """Manage Audiobookshelf playback sync for a single active item."""

    def __init__(self, absClient, serverLinkManager):
        """
        Initialize sync manager.

        Args:
            absClient: AudiobookshelfClient instance
            serverLinkManager: ServerLinkManager instance
        """
        self.client = absClient
        self.linkManager = serverLinkManager
        self.sessionId = None
        self.serverId = None
        self.duration = 0.0
        self.bookPath = None
        self.lastSyncPosition = 0.0
        self.lastSyncAt = None

    def _calculate_progress(self, currentTime: float) -> float:
        """Calculate normalized playback progress."""
        if self.duration <= 0:
            return 0.0
        return min(max(currentTime, 0.0) / self.duration, 1.0)

    def _calculate_time_listened(self, currentTime: float) -> float:
        """
        Estimate listening time since the previous session sync.

        Audiobookshelf expects time spent listening, not position delta.
        """
        if self.lastSyncAt is None:
            return 0.0

        wallElapsed = max(0.0, time.monotonic() - self.lastSyncAt)
        positionDelta = max(0.0, currentTime - self.lastSyncPosition)

        if positionDelta > 0:
            return min(wallElapsed, positionDelta + 1.0)
        return min(wallElapsed, 1.0)

    def _update_sync_state(self, currentTime: float):
        """Store the latest synced playback state."""
        self.lastSyncPosition = max(0.0, float(currentTime))
        self.lastSyncAt = time.monotonic()

    def mark_progress_checkpoint(self, currentTime: float):
        """Reset session timing around a seek, pause, or resume."""
        self._update_sync_state(currentTime)

    def start_streaming_session(self, serverBook: Dict) -> Optional[Dict]:
        """
        Start a streaming playback session with /play.

        Returns:
            Dict with stream and session information, or None on error.
        """
        serverId = serverBook.get('id') or serverBook.get('libraryItemId')
        if not serverId:
            print("ERROR: No Audiobookshelf item ID found for stream start.")
            return None

        if not self.client or not self.client.is_authenticated():
            print("ERROR: Not authenticated to Audiobookshelf.")
            return None

        result = self.client.get_stream_url(serverId, itemDetails=serverBook)
        if not result:
            return None

        self.sessionId = result.get('sessionId')
        self.serverId = serverId
        self.duration = max(
            self.client._coerce_float(result.get('duration')),
            self.client._coerce_float(serverBook.get('media', {}).get('duration'))
        )

        startPosition = self.client._coerce_float(result.get('currentTime'))
        self._update_sync_state(startPosition)

        if self.sessionId:
            print(f"Started Audiobookshelf session: {self.sessionId}")
        else:
            print("Audiobookshelf stream started without a session ID. Falling back to direct progress updates.")

        return {
            'streamUrl': result.get('streamUrl'),
            'streamUrls': result.get('streamUrls', []),
            'sessionId': self.sessionId,
            'startPosition': startPosition,
            'playData': result.get('playData', {})
        }

    def set_book_path(self, bookPath: str):
        """Store the path or URL used for this stream."""
        self.bookPath = bookPath

    def sync_progress(self, currentTime: float, updateSession: bool = True, isFinished: bool = None) -> bool:
        """
        Sync current playback position to Audiobookshelf.

        Args:
            currentTime: Current playback position in seconds
            updateSession: Whether to send session heartbeat data
            isFinished: Optional finished flag override
        """
        if not self.serverId or not self.client or not self.client.is_authenticated():
            return False

        currentTime = max(0.0, self.client._coerce_float(currentTime))
        progress = self._calculate_progress(currentTime)
        if isFinished is None:
            isFinished = progress >= 0.999 and self.duration > 0

        progressSaved = self.client.update_progress(
            self.serverId,
            currentTime,
            self.duration,
            progress=progress,
            isFinished=isFinished
        )

        sessionSaved = True
        if self.sessionId and updateSession:
            timeListened = self._calculate_time_listened(currentTime)
            sessionSaved = self.client.sync_session(
                self.sessionId,
                currentTime,
                self.duration,
                progress=progress,
                timeListened=timeListened
            )
            if not sessionSaved:
                print("Audiobookshelf session sync failed. Continuing with direct progress updates.")
                self.sessionId = None

        if progressSaved or sessionSaved:
            self._update_sync_state(currentTime)

        if self.bookPath:
            self.linkManager.update_session(str(self.bookPath), self.sessionId)

        return progressSaved

    def close_session(self, currentTime: float = 0.0, isFinished: bool = None):
        """Close the active playback session and persist final progress."""
        currentTime = max(0.0, self.client._coerce_float(currentTime))
        progress = self._calculate_progress(currentTime)
        if isFinished is None:
            isFinished = progress >= 0.999 and self.duration > 0

        if self.serverId and self.client and self.client.is_authenticated():
            self.client.update_progress(
                self.serverId,
                currentTime,
                self.duration,
                progress=progress,
                isFinished=isFinished
            )

        if self.sessionId and self.client and self.client.is_authenticated():
            timeListened = self._calculate_time_listened(currentTime)
            print(f"Closing Audiobookshelf session: {self.sessionId}")
            self.client.close_session(
                self.sessionId,
                currentTime=currentTime,
                duration=self.duration,
                progress=progress,
                timeListened=timeListened
            )

        if self.bookPath:
            self.linkManager.clear_session(str(self.bookPath))

        self.sessionId = None
        self.lastSyncAt = None

    def get_server_progress(self) -> Optional[Dict]:
        """Fetch persisted progress for the active server item."""
        if not self.serverId or not self.client:
            return None
        return self.client.get_progress(self.serverId)

    def is_active(self) -> bool:
        """Return True when an active server item is being tracked."""
        return self.serverId is not None

    def has_open_session(self) -> bool:
        """Return True when a live Audiobookshelf session is open."""
        return self.sessionId is not None

    def reset(self):
        """Clear sync state for the current item."""
        self.sessionId = None
        self.serverId = None
        self.duration = 0.0
        self.bookPath = None
        self.lastSyncPosition = 0.0
        self.lastSyncAt = None
