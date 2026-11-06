#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bookmark Manager

Manages reading positions for books using SQLite for persistence.
Tracks chapter, paragraph, and sentence positions.
"""

import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime


class BookmarkManager:
    """Manages bookmarks for books"""

    def __init__(self, dbPath=None):
        """
        Initialize bookmark manager

        Args:
            dbPath: Path to SQLite database (default: ~/.bookstorm/bookmarks.db)
        """
        if dbPath is None:
            homePath = Path.home()
            bookstormDir = homePath / ".bookstorm"
            bookstormDir.mkdir(exist_ok=True)
            dbPath = bookstormDir / "bookmarks.db"

        self.dbPath = dbPath
        self._init_db()

    def _init_db(self):
        """Initialize database schema"""
        with sqlite3.connect(self.dbPath) as conn:
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bookmarks (
                    book_id TEXT PRIMARY KEY,
                    book_path TEXT NOT NULL,
                    book_title TEXT,
                    chapter_index INTEGER NOT NULL DEFAULT 0,
                    paragraph_index INTEGER NOT NULL DEFAULT 0,
                    sentence_index INTEGER NOT NULL DEFAULT 0,
                    last_accessed TEXT,
                    created_at TEXT
                )
            ''')

            # Add audio_position column if it doesn't exist (migration for existing databases)
            try:
                cursor.execute('ALTER TABLE bookmarks ADD COLUMN audio_position REAL DEFAULT 0.0')
            except sqlite3.OperationalError:
                # Column already exists
                pass

            # Create named_bookmarks table for multiple bookmarks per book
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS named_bookmarks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    chapter_index INTEGER NOT NULL DEFAULT 0,
                    paragraph_index INTEGER NOT NULL DEFAULT 0,
                    audio_position REAL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    server_library_item_id TEXT,
                    server_time INTEGER,
                    server_created_at INTEGER,
                    UNIQUE(book_id, name)
                )
            ''')

            for columnName, columnType in [
                ('server_library_item_id', 'TEXT'),
                ('server_time', 'INTEGER'),
                ('server_created_at', 'INTEGER')
            ]:
                try:
                    cursor.execute(f'ALTER TABLE named_bookmarks ADD COLUMN {columnName} {columnType}')
                except sqlite3.OperationalError:
                    pass

            conn.commit()

    def _get_book_id(self, bookPath):
        """Generate unique book ID from file path"""
        bookPath = str(Path(bookPath).resolve())
        return hashlib.sha256(bookPath.encode()).hexdigest()[:16]

    def _get_unique_named_bookmark_name(self, cursor, bookId, baseName):
        """Return an unused bookmark name for a given book."""
        candidateName = baseName
        suffixIndex = 2
        while True:
            cursor.execute('''
                SELECT 1 FROM named_bookmarks
                WHERE book_id = ? AND name = ?
            ''', (bookId, candidateName))
            if cursor.fetchone() is None:
                return candidateName
            candidateName = f"{baseName} ({suffixIndex})"
            suffixIndex += 1

    def save_bookmark(self, bookPath, bookTitle, chapterIndex, paragraphIndex, sentenceIndex=0, audioPosition=0.0):
        """
        Save bookmark for a book

        Args:
            bookPath: Path to book file
            bookTitle: Title of the book
            chapterIndex: Current chapter index
            paragraphIndex: Current paragraph index
            sentenceIndex: Current sentence index (default: 0)
            audioPosition: Audio playback position in seconds (default: 0.0)
        """
        bookId = self._get_book_id(bookPath)
        timestamp = datetime.now().isoformat()

        with sqlite3.connect(self.dbPath) as conn:
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR REPLACE INTO bookmarks
                (book_id, book_path, book_title, chapter_index, paragraph_index,
                 sentence_index, audio_position, last_accessed, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                        COALESCE((SELECT created_at FROM bookmarks WHERE book_id = ?), ?))
            ''', (bookId, str(bookPath), bookTitle, chapterIndex, paragraphIndex,
                  sentenceIndex, audioPosition, timestamp, bookId, timestamp))

            conn.commit()

    def get_bookmark(self, bookPath):
        """
        Get bookmark for a book

        Args:
            bookPath: Path to book file

        Returns:
            Dictionary with bookmark data or None if not found
        """
        bookId = self._get_book_id(bookPath)

        with sqlite3.connect(self.dbPath) as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT chapter_index, paragraph_index, sentence_index,
                       book_title, last_accessed, audio_position
                FROM bookmarks
                WHERE book_id = ?
            ''', (bookId,))

            row = cursor.fetchone()

        if row:
            return {
                'chapterIndex': row[0],
                'paragraphIndex': row[1],
                'sentenceIndex': row[2],
                'bookTitle': row[3],
                'lastAccessed': row[4],
                'audioPosition': row[5] if row[5] is not None else 0.0
            }

        return None

    def delete_bookmark(self, bookPath):
        """
        Delete bookmark for a book

        Args:
            bookPath: Path to book file
        """
        bookId = self._get_book_id(bookPath)

        with sqlite3.connect(self.dbPath) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM bookmarks WHERE book_id = ?', (bookId,))
            conn.commit()

    def list_bookmarks(self):
        """
        List all bookmarks

        Returns:
            List of dictionaries with bookmark data
        """
        with sqlite3.connect(self.dbPath) as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT book_path, book_title, chapter_index, paragraph_index,
                       sentence_index, last_accessed
                FROM bookmarks
                ORDER BY last_accessed DESC
            ''')

            rows = cursor.fetchall()

        bookmarks = []
        for row in rows:
            bookmarks.append({
                'bookPath': row[0],
                'bookTitle': row[1],
                'chapterIndex': row[2],
                'paragraphIndex': row[3],
                'sentenceIndex': row[4],
                'lastAccessed': row[5]
            })

        return bookmarks

    def create_named_bookmark(self, bookPath, name, chapterIndex, paragraphIndex, audioPosition=0.0,
                              serverLibraryItemId=None, serverTime=None, serverCreatedAt=None):
        """
        Create a named bookmark for a book

        Args:
            bookPath: Path to book file
            name: Bookmark name
            chapterIndex: Chapter index
            paragraphIndex: Paragraph index
            audioPosition: Audio position in seconds (default: 0.0)

        Returns:
            Bookmark ID if created successfully, None if name already exists
        """
        bookId = self._get_book_id(bookPath)
        timestamp = datetime.now().isoformat()

        try:
            with sqlite3.connect(self.dbPath) as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    INSERT INTO named_bookmarks
                    (book_id, name, chapter_index, paragraph_index, audio_position, created_at,
                     server_library_item_id, server_time, server_created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (bookId, name, chapterIndex, paragraphIndex, audioPosition, timestamp,
                      serverLibraryItemId, serverTime, serverCreatedAt))

                conn.commit()
                return cursor.lastrowid

        except sqlite3.IntegrityError:
            # Bookmark with this name already exists
            return None

    def get_named_bookmarks(self, bookPath):
        """
        Get all named bookmarks for a book

        Args:
            bookPath: Path to book file

        Returns:
            List of named bookmark dictionaries
        """
        bookId = self._get_book_id(bookPath)

        with sqlite3.connect(self.dbPath) as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT id, name, chapter_index, paragraph_index, audio_position, created_at,
                       server_library_item_id, server_time, server_created_at
                FROM named_bookmarks
                WHERE book_id = ?
                ORDER BY created_at DESC
            ''', (bookId,))

            rows = cursor.fetchall()

        bookmarks = []
        for row in rows:
            bookmarks.append({
                'id': row[0],
                'name': row[1],
                'chapterIndex': row[2],
                'paragraphIndex': row[3],
                'audioPosition': row[4],
                'createdAt': row[5],
                'serverLibraryItemId': row[6],
                'serverTime': row[7],
                'serverCreatedAt': row[8]
            })

        return bookmarks

    def update_named_bookmark_server_data(self, bookmarkId, serverLibraryItemId=None, serverTime=None,
                                          serverCreatedAt=None):
        """
        Update server metadata for an existing named bookmark.

        Args:
            bookmarkId: Local bookmark ID
            serverLibraryItemId: Linked Audiobookshelf item ID
            serverTime: Server bookmark time in seconds
            serverCreatedAt: Server bookmark created timestamp
        """
        with sqlite3.connect(self.dbPath) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE named_bookmarks
                SET server_library_item_id = ?, server_time = ?, server_created_at = ?
                WHERE id = ?
            ''', (serverLibraryItemId, serverTime, serverCreatedAt, bookmarkId))
            conn.commit()

    def upsert_named_bookmark_from_server(self, bookPath, name, chapterIndex, paragraphIndex, audioPosition=0.0,
                                          serverLibraryItemId=None, serverTime=None, serverCreatedAt=None):
        """
        Insert or update a local bookmark from Audiobookshelf server data.

        Returns:
            Local bookmark ID
        """
        bookId = self._get_book_id(bookPath)
        timestamp = datetime.now().isoformat()

        with sqlite3.connect(self.dbPath) as conn:
            cursor = conn.cursor()

            if serverLibraryItemId and serverTime is not None:
                cursor.execute('''
                    SELECT id FROM named_bookmarks
                    WHERE book_id = ? AND server_library_item_id = ? AND server_time = ?
                ''', (bookId, serverLibraryItemId, serverTime))
                row = cursor.fetchone()
                if row:
                    bookmarkId = row[0]
                    try:
                        cursor.execute('''
                            UPDATE named_bookmarks
                            SET name = ?, chapter_index = ?, paragraph_index = ?, audio_position = ?,
                                "server_created_at" = ?, created_at = ?
                            WHERE id = ?
                        ''', (name, chapterIndex, paragraphIndex, audioPosition,
                              serverCreatedAt, timestamp, bookmarkId))
                    except sqlite3.IntegrityError:
                        # Keep the existing local name if requested server name collides.
                        cursor.execute('''
                            UPDATE named_bookmarks
                            SET chapter_index = ?, paragraph_index = ?, audio_position = ?,
                                "server_created_at" = ?, created_at = ?
                            WHERE id = ?
                        ''', (chapterIndex, paragraphIndex, audioPosition,
                              serverCreatedAt, timestamp, bookmarkId))
                    conn.commit()
                    return bookmarkId

            cursor.execute('''
                INSERT OR IGNORE INTO named_bookmarks
                (book_id, name, chapter_index, paragraph_index, audio_position, created_at,
                 server_library_item_id, server_time, server_created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (bookId, name, chapterIndex, paragraphIndex, audioPosition, timestamp,
                  serverLibraryItemId, serverTime, serverCreatedAt))

            if cursor.lastrowid:
                conn.commit()
                return cursor.lastrowid

            cursor.execute('''
                SELECT id, server_library_item_id, server_time FROM named_bookmarks
                WHERE book_id = ? AND name = ?
            ''', (bookId, name))
            row = cursor.fetchone()
            bookmarkId = row[0] if row else None
            existingServerItemId = row[1] if row else None
            existingServerTime = row[2] if row else None

            hasServerIdentity = serverLibraryItemId is not None and serverTime is not None
            if bookmarkId and hasServerIdentity:
                sameServerBookmark = (
                    existingServerItemId == serverLibraryItemId and
                    existingServerTime == serverTime
                )
                if not sameServerBookmark:
                    uniqueName = self._get_unique_named_bookmark_name(cursor, bookId, name)
                    cursor.execute('''
                        INSERT INTO named_bookmarks
                        (book_id, name, chapter_index, paragraph_index, audio_position, created_at,
                         server_library_item_id, server_time, server_created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (bookId, uniqueName, chapterIndex, paragraphIndex, audioPosition, timestamp,
                          serverLibraryItemId, serverTime, serverCreatedAt))
                    conn.commit()
                    return cursor.lastrowid

            if bookmarkId:
                cursor.execute('''
                    UPDATE named_bookmarks
                    SET chapter_index = ?, paragraph_index = ?, audio_position = ?,
                        "server_library_item_id" = ?, "server_time" = ?, "server_created_at" = ?
                    WHERE id = ?
                ''', (chapterIndex, paragraphIndex, audioPosition,
                      serverLibraryItemId, serverTime, serverCreatedAt, bookmarkId))
                conn.commit()
            return bookmarkId

    def delete_named_bookmark(self, bookmarkId):
        """
        Delete a named bookmark by ID

        Args:
            bookmarkId: Bookmark ID
        """
        with sqlite3.connect(self.dbPath) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM named_bookmarks WHERE id = ?', (bookmarkId,))
            conn.commit()

    def delete_all_named_bookmarks(self, bookPath):
        """
        Delete all named bookmarks for a specific book

        Args:
            bookPath: Path to book file
        """
        bookId = self._get_book_id(bookPath)

        with sqlite3.connect(self.dbPath) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM named_bookmarks WHERE book_id = ?', (bookId,))
            conn.commit()

    def get_named_bookmark_by_id(self, bookmarkId):
        """
        Get a named bookmark by ID

        Args:
            bookmarkId: Bookmark ID

        Returns:
            Bookmark dictionary or None if not found
        """
        with sqlite3.connect(self.dbPath) as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT name, chapter_index, paragraph_index, audio_position,
                       server_library_item_id, server_time, server_created_at
                FROM named_bookmarks
                WHERE id = ?
            ''', (bookmarkId,))

            row = cursor.fetchone()

        if row:
            return {
                'name': row[0],
                'chapterIndex': row[1],
                'paragraphIndex': row[2],
                'audioPosition': row[3],
                'serverLibraryItemId': row[4],
                'serverTime': row[5],
                'serverCreatedAt': row[6]
            }

        return None
