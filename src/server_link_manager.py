#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Server Link Manager

Manages sidecar files that link local books to Audiobookshelf server books.
Enables progress sync and prevents duplicate downloads.
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict


class ServerLinkManager:
    """Manages server link metadata for local books"""

    def __init__(self):
        """Initialize server link manager"""
        # Create sidecar directory
        homePath = Path.home()
        self.sidecarDir = homePath / ".bookstorm" / "server_links"
        self.sidecarDir.mkdir(parents=True, exist_ok=True)

    def _get_book_hash(self, bookPath: str) -> str:
        """Generate hash from book path for sidecar filename"""
        pathStr = str(Path(bookPath).resolve())
        return hashlib.sha256(pathStr.encode()).hexdigest()[:16]

    def create_link(self, bookPath: str, serverUrl: str, serverId: str, libraryId: str,
                   title: str = "", author: str = "", duration: float = 0.0,
                   chapters: int = 0, manualOverride: bool = False, sessionId: str = None,
                   serverBook: Dict = None):
        """
        Create server link for a local book

        Args:
            bookPath: Path to local book file
            serverUrl: Audiobookshelf server URL
            serverId: Server's library item ID
            libraryId: Server's library ID
            title: Book title
            author: Author name
            duration: Audio duration in seconds
            chapters: Number of chapters
            manualOverride: True if user manually linked despite mismatch
            sessionId: Active listening session ID (for streaming)
            serverBook: Full server book metadata (for streaming)
        """
        bookHash = self._get_book_hash(bookPath)
        sidecarPath = self.sidecarDir / f"{bookHash}.json"

        linkData = {
            'server_url': serverUrl,
            'server_id': serverId,
            'library_id': libraryId,
            'local_path': str(Path(bookPath).resolve()),
            'linked_at': datetime.now().isoformat(),
            'validation': {
                'duration': duration,
                'chapters': chapters,
                'title': title,
                'author': author
            },
            'manual_override': manualOverride,
            'session_id': sessionId,
            'server_book': serverBook
        }

        with open(sidecarPath, 'w') as f:
            json.dump(linkData, f, indent=2)

        print(f"Created server link: {sidecarPath}")

    def get_link(self, bookPath: str) -> Optional[Dict]:
        """
        Get server link for a local book

        Args:
            bookPath: Path to local book file

        Returns:
            Link data dictionary, or None if no link exists
        """
        bookHash = self._get_book_hash(bookPath)
        sidecarPath = self.sidecarDir / f"{bookHash}.json"

        if not sidecarPath.exists():
            return None

        try:
            with open(sidecarPath, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error reading server link: {e}")
            return None

    def has_link(self, bookPath: str) -> bool:
        """Check if book has server link"""
        return self.get_link(bookPath) is not None

    def find_by_server_id(self, serverId: str) -> Optional[str]:
        """
        Find local book path by server ID

        Args:
            serverId: Server's library item ID

        Returns:
            Local book path if found, None otherwise
        """
        # Search all sidecar files
        for sidecarPath in self.sidecarDir.glob("*.json"):
            try:
                with open(sidecarPath, 'r') as f:
                    linkData = json.load(f)
                    if linkData.get('server_id') == serverId:
                        localPath = linkData.get('local_path')
                        # Verify file still exists
                        if localPath and Path(localPath).exists():
                            return localPath
            except (json.JSONDecodeError, IOError):
                continue

        return None

    def delete_link(self, bookPath: str):
        """Delete server link for a book"""
        bookHash = self._get_book_hash(bookPath)
        sidecarPath = self.sidecarDir / f"{bookHash}.json"

        if sidecarPath.exists():
            sidecarPath.unlink()
            print(f"Deleted server link: {sidecarPath}")

    def update_session(self, bookPath: str, sessionId: str):
        """
        Update session ID for an existing link

        Args:
            bookPath: Path to book file (or stream URL)
            sessionId: New session ID
        """
        linkData = self.get_link(bookPath)
        if not linkData:
            return

        linkData['session_id'] = sessionId
        bookHash = self._get_book_hash(bookPath)
        sidecarPath = self.sidecarDir / f"{bookHash}.json"

        with open(sidecarPath, 'w') as f:
            json.dump(linkData, f, indent=2)

    def clear_session(self, bookPath: str):
        """
        Clear session ID from link (when session closed)

        Args:
            bookPath: Path to book file (or stream URL)
        """
        linkData = self.get_link(bookPath)
        if not linkData:
            return

        linkData['session_id'] = None
        bookHash = self._get_book_hash(bookPath)
        sidecarPath = self.sidecarDir / f"{bookHash}.json"

        with open(sidecarPath, 'w') as f:
            json.dump(linkData, f, indent=2)

