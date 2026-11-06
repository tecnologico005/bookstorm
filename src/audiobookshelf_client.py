#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Audiobookshelf API Client

Handles communication with Audiobookshelf for browsing, playback,
downloads, and progress synchronization.
"""

from urllib.parse import urljoin
from typing import Optional, Dict, List

import requests


class AudiobookshelfClient:
    """Client for the Audiobookshelf API"""

    def __init__(self, serverUrl: str, configManager=None):
        """
        Initialize Audiobookshelf client.

        Args:
            serverUrl: Base server URL
            configManager: Optional ConfigManager for token persistence
        """
        self.serverUrl = serverUrl.rstrip('/')
        self.configManager = configManager
        self.authToken = None
        self.httpSession = requests.Session()
        self.defaultTimeout = 30
        self.deviceInfo = {
            'deviceId': 'bookstorm',
            'clientName': 'BookStorm',
            'platform': 'linux'
        }

        if configManager:
            savedToken = configManager.get_abs_auth_token()
            if savedToken:
                self.authToken = savedToken

    def _clear_auth_token(self):
        """Clear the saved authentication token."""
        self.authToken = None
        if self.configManager:
            self.configManager.set_abs_auth_token('')

    def _build_headers(self, headers=None) -> Dict:
        """Build request headers."""
        requestHeaders = {}
        if headers:
            requestHeaders.update(headers)
        if self.authToken:
            requestHeaders['Authorization'] = f'Bearer {self.authToken}'
        return requestHeaders

    def _short_response_text(self, response: requests.Response) -> str:
        """Return a short, printable response summary."""
        try:
            text = response.text.strip()
        except Exception:
            text = ''
        if len(text) > 300:
            text = f"{text[:297]}..."
        return text

    def _make_request(self, method: str, endpoint: str, expectedStatus=(200,), **kwargs) -> Optional[requests.Response]:
        """
        Make an authenticated request.

        Args:
            method: HTTP method
            endpoint: Relative or absolute URL
            expectedStatus: Acceptable HTTP status codes
            **kwargs: Passed to requests

        Returns:
            Response on success, else None
        """
        if endpoint.startswith('http://') or endpoint.startswith('https://'):
            requestUrl = endpoint
        else:
            requestUrl = f"{self.serverUrl}{endpoint}"

        timeout = kwargs.pop('timeout', self.defaultTimeout)
        headers = self._build_headers(kwargs.pop('headers', None))

        try:
            response = self.httpSession.request(
                method=method,
                url=requestUrl,
                headers=headers,
                timeout=timeout,
                **kwargs
            )
        except requests.exceptions.RequestException as error:
            print(f"Audiobookshelf request error for {method} {requestUrl}: {error}")
            return None

        statusCode = getattr(response, 'status_code', None)

        if statusCode == 401:
            print("Audiobookshelf authentication failed. Token may be expired.")
            self._clear_auth_token()
            return None

        if statusCode not in expectedStatus:
            responseText = self._short_response_text(response)
            print(f"Audiobookshelf API error for {method} {requestUrl}: {statusCode}")
            if responseText:
                print(f"Response: {responseText}")
            return None

        return response

    def _request_json(self, method: str, endpoint: str, expectedStatus=(200,), **kwargs):
        """Make a request and decode JSON."""
        response = self._make_request(method, endpoint, expectedStatus=expectedStatus, **kwargs)
        if not response:
            return None

        statusCode = getattr(response, 'status_code', None)
        if statusCode == 204:
            return {}

        try:
            return response.json()
        except ValueError as error:
            print(f"Invalid JSON from Audiobookshelf endpoint {endpoint}: {error}")
            return None

    def _coerce_float(self, value, default: float = 0.0) -> float:
        """Safely convert a value to float."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _extract_list(self, data, preferredKeys: List[str]) -> List[Dict]:
        """Extract a list from variable API response shapes."""
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []

        for key in preferredKeys:
            value = data.get(key)
            if isinstance(value, list):
                return value

        return []

    def _has_more_pages(self, data: Dict, page: int, pageSize: int, collectedCount: int) -> bool:
        """Infer whether a paginated API response has more pages."""
        totalPages = data.get('totalPages') or data.get('numPages') or data.get('pages')
        if isinstance(totalPages, int):
            return page + 1 < totalPages

        totalItems = data.get('total')
        if isinstance(totalItems, int) and pageSize > 0:
            return collectedCount < totalItems

        return False

    def _normalize_url(self, url: str) -> str:
        """Make a possibly relative URL absolute."""
        if not url:
            return ''
        return urljoin(f"{self.serverUrl}/", url)

    def _extract_stream_urls(self, playData: Dict) -> List[str]:
        """Extract one or more playback URLs from a /play response."""
        streamUrls = []

        for key in ['streamUrl', 'contentUrl', 'url']:
            candidateUrl = playData.get(key)
            if candidateUrl:
                normalizedUrl = self._normalize_url(candidateUrl)
                if normalizedUrl not in streamUrls:
                    streamUrls.append(normalizedUrl)

        audioTracks = playData.get('audioTracks')
        if isinstance(audioTracks, list):
            for audioTrack in audioTracks:
                if not isinstance(audioTrack, dict):
                    continue
                contentUrl = audioTrack.get('contentUrl') or audioTrack.get('url')
                if contentUrl:
                    normalizedUrl = self._normalize_url(contentUrl)
                    if normalizedUrl not in streamUrls:
                        streamUrls.append(normalizedUrl)

        return streamUrls

    def is_authenticated(self) -> bool:
        """Check whether a token is available."""
        return bool(self.authToken)

    def login(self, username: str, password: str) -> bool:
        """Authenticate against Audiobookshelf."""
        responseData = self._request_json(
            'POST',
            '/login',
            expectedStatus=(200,),
            headers={'Content-Type': 'application/json'},
            json={
                'username': username,
                'password': password
            },
            timeout=10
        )

        if not isinstance(responseData, dict):
            return False

        userData = responseData.get('user', {})
        token = userData.get('token')
        if not token:
            print("Audiobookshelf login succeeded but no token was returned.")
            return False

        self.authToken = token
        if self.configManager:
            self.configManager.set_abs_auth_token(token)
            self.configManager.set_abs_username(username)
        return True

    def test_connection(self) -> bool:
        """Verify that the current token still works."""
        response = self._make_request('GET', '/api/me', expectedStatus=(200,), timeout=10)
        return response is not None

    def get_current_user(self) -> Optional[Dict]:
        """Get the current user profile including bookmarks."""
        responseData = self._request_json('GET', '/api/me', expectedStatus=(200,), timeout=10)
        if not isinstance(responseData, dict):
            return None
        return responseData

    def get_libraries(self) -> Optional[List[Dict]]:
        """Get available libraries."""
        responseData = self._request_json('GET', '/api/libraries', expectedStatus=(200,), timeout=10)
        if responseData is None:
            return None

        libraries = self._extract_list(responseData, ['libraries', 'results'])
        return libraries if libraries else None

    def get_library_items(self, libraryId: str, limit: int = 0, page: int = 0) -> Optional[List[Dict]]:
        """
        Get items in a library.

        Fetches all pages when limit is 0 so large libraries are fully browsable.
        """
        if not libraryId:
            return None

        items = []
        currentPage = max(0, int(page))
        remainingLimit = max(0, int(limit))

        while True:
            params = {'page': currentPage}
            if remainingLimit > 0:
                params['limit'] = remainingLimit

            responseData = self._request_json(
                'GET',
                f"/api/libraries/{libraryId}/items",
                expectedStatus=(200,),
                params=params,
                timeout=30
            )
            if responseData is None:
                return None if not items else items

            pageItems = self._extract_list(responseData, ['results', 'libraryItems', 'items'])
            if not pageItems and isinstance(responseData, list):
                pageItems = responseData

            items.extend(pageItems)

            if remainingLimit > 0:
                return items[:remainingLimit]

            pageSize = len(pageItems)
            if pageSize == 0:
                break

            if not isinstance(responseData, dict):
                break

            if not self._has_more_pages(responseData, currentPage, pageSize, len(items)):
                break

            currentPage += 1

        return items

    def get_library_item_details(self, itemId: str) -> Optional[Dict]:
        """Get detailed item metadata."""
        for endpoint in [f"/api/items/{itemId}", f"/api/library-items/{itemId}"]:
            response = self._make_request('GET', endpoint, expectedStatus=(200, 404), timeout=15)
            statusCode = getattr(response, 'status_code', None) if response else None
            if not response or statusCode == 404:
                continue
            try:
                responseData = response.json()
            except ValueError as error:
                print(f"Invalid item details response from Audiobookshelf: {error}")
                return None
            if isinstance(responseData, dict):
                return responseData.get('libraryItem') if isinstance(responseData.get('libraryItem'), dict) else responseData
        return None

    def download_audio_file(self, itemId: str, outputPath: str, progressCallback=None) -> bool:
        """Download an audiobook file."""
        response = self._make_request(
            'GET',
            f"/api/items/{itemId}/file",
            expectedStatus=(200,),
            stream=True,
            timeout=30
        )
        if not response:
            return False

        try:
            totalSize = int(response.headers.get('content-length', 0))
            downloaded = 0
            with open(outputPath, 'wb') as outputFile:
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    outputFile.write(chunk)
                    downloaded += len(chunk)
                    if progressCallback and totalSize > 0:
                        percent = int((downloaded / totalSize) * 100)
                        progressCallback(percent)
        except IOError as error:
            print(f"File write error while downloading Audiobookshelf item: {error}")
            return False
        finally:
            response.close()

        print(f"Download complete: {outputPath}")
        return True

    def get_stream_url(self, itemId: str, itemDetails: Optional[Dict] = None) -> Optional[Dict]:
        """
        Start playback via /play and return stream/session details.
        """
        payload = {
            'deviceInfo': self.deviceInfo,
            'mediaPlayer': 'BookStorm',
            'forceDirectPlay': False,
            'forceTranscode': False,
            'supportedMimeTypes': [
                'audio/aac',
                'audio/flac',
                'audio/mp4',
                'audio/mpeg',
                'audio/ogg',
                'audio/opus',
                'audio/webm'
            ]
        }

        playData = self._request_json(
            'POST',
            f"/api/items/{itemId}/play",
            expectedStatus=(200,),
            headers={'Content-Type': 'application/json'},
            json=payload,
            timeout=15
        )
        if not isinstance(playData, dict):
            return None

        streamUrls = self._extract_stream_urls(playData)
        if not streamUrls:
            print("Audiobookshelf play response did not include a playable stream URL.")
            return None

        duration = self._coerce_float(playData.get('duration'))
        if duration <= 0 and isinstance(itemDetails, dict):
            duration = self._coerce_float(itemDetails.get('media', {}).get('duration'))

        return {
            'streamUrl': streamUrls[0],
            'streamUrls': streamUrls,
            'sessionId': playData.get('id'),
            'currentTime': self._coerce_float(playData.get('currentTime')),
            'duration': duration,
            'playData': playData
        }

    def get_item_chapters(self, itemId: str) -> Optional[List[Dict]]:
        """Get chapters for an item."""
        itemDetails = self.get_library_item_details(itemId)
        if not itemDetails:
            return None
        chapters = itemDetails.get('media', {}).get('chapters', [])
        return chapters if chapters else None

    def update_progress(self, itemId: str, currentTime: float, duration: float, progress: float = None,
                        isFinished: bool = None) -> bool:
        """Update persisted media progress."""
        currentTime = max(0.0, self._coerce_float(currentTime))
        duration = max(0.0, self._coerce_float(duration))
        if progress is None:
            progress = min(currentTime / duration, 1.0) if duration > 0 else 0.0
        if isFinished is None:
            isFinished = progress >= 0.99 and duration > 0

        response = self._make_request(
            'PATCH',
            f"/api/me/progress/{itemId}",
            expectedStatus=(200, 204),
            headers={'Content-Type': 'application/json'},
            json={
                'currentTime': currentTime,
                'duration': duration,
                'progress': progress,
                'isFinished': bool(isFinished)
            },
            timeout=10
        )
        return response is not None

    def get_progress(self, itemId: str) -> Optional[Dict]:
        """Get saved media progress for an item."""
        response = self._make_request('GET', f"/api/me/progress/{itemId}", expectedStatus=(200, 404), timeout=10)
        statusCode = getattr(response, 'status_code', None) if response else None
        if not response or statusCode == 404:
            return None

        try:
            return response.json()
        except ValueError as error:
            print(f"Invalid progress response from Audiobookshelf: {error}")
            return None

    def get_bookmarks(self, itemId: str = None) -> Optional[List[Dict]]:
        """
        Get bookmarks for the current user, optionally filtered by item ID.
        """
        userData = self.get_current_user()
        if not userData:
            return None

        bookmarks = userData.get('bookmarks', [])
        if not isinstance(bookmarks, list):
            return None

        if not itemId:
            return bookmarks

        return [
            bookmark for bookmark in bookmarks
            if isinstance(bookmark, dict) and bookmark.get('libraryItemId') == itemId
        ]

    def create_bookmark(self, itemId: str, bookmarkTime: int, title: str) -> Optional[Dict]:
        """Create a named bookmark for an item."""
        responseData = self._request_json(
            'POST',
            f"/api/me/item/{itemId}/bookmark",
            expectedStatus=(200,),
            headers={'Content-Type': 'application/json'},
            json={
                'time': int(bookmarkTime),
                'title': title
            },
            timeout=10
        )
        return responseData if isinstance(responseData, dict) else None

    def update_bookmark(self, itemId: str, bookmarkTime: int, title: str) -> Optional[Dict]:
        """Update an existing bookmark title/time for an item."""
        responseData = self._request_json(
            'PATCH',
            f"/api/me/item/{itemId}/bookmark",
            expectedStatus=(200,),
            headers={'Content-Type': 'application/json'},
            json={
                'time': int(bookmarkTime),
                'title': title
            },
            timeout=10
        )
        return responseData if isinstance(responseData, dict) else None

    def save_bookmark(self, itemId: str, bookmarkTime: int, title: str) -> Optional[Dict]:
        """
        Create or update a bookmark on Audiobookshelf.

        Returns:
            Bookmark dictionary on success, None on failure
        """
        bookmarkData = self.create_bookmark(itemId, bookmarkTime, title)
        if bookmarkData:
            return bookmarkData

        bookmarkData = self.update_bookmark(itemId, bookmarkTime, title)
        if bookmarkData:
            return bookmarkData

        existingBookmarks = self.get_bookmarks(itemId)
        if existingBookmarks is None:
            return None

        for bookmark in existingBookmarks:
            if not isinstance(bookmark, dict):
                continue
            if int(bookmark.get('time', -1)) == int(bookmarkTime):
                return bookmark

        return None

    def delete_bookmark(self, itemId: str, bookmarkTime: int) -> bool:
        """Delete a bookmark for an item."""
        response = self._make_request(
            'DELETE',
            f"/api/me/item/{itemId}/bookmark/{int(bookmarkTime)}",
            expectedStatus=(200, 204),
            timeout=10
        )
        return response is not None

    def create_session(self, itemId: str) -> Optional[str]:
        """
        Compatibility helper for older call sites.

        Streaming should normally use /api/items/{id}/play instead.
        """
        responseData = self._request_json(
            'POST',
            '/api/session/local',
            expectedStatus=(200,),
            headers={'Content-Type': 'application/json'},
            json={
                'libraryItemId': itemId,
                'mediaPlayer': 'BookStorm',
                'deviceInfo': self.deviceInfo
            },
            timeout=10
        )
        if not isinstance(responseData, dict):
            return None
        return responseData.get('id')

    def sync_session(self, sessionId: str, currentTime: float, duration: float, progress: float = None,
                     timeListened: float = 0.0) -> bool:
        """Sync an active playback session."""
        currentTime = max(0.0, self._coerce_float(currentTime))
        duration = max(0.0, self._coerce_float(duration))
        timeListened = max(0.0, self._coerce_float(timeListened))
        if progress is None:
            progress = min(currentTime / duration, 1.0) if duration > 0 else 0.0

        response = self._make_request(
            'POST',
            f"/api/session/{sessionId}/sync",
            expectedStatus=(200, 204),
            headers={'Content-Type': 'application/json'},
            json={
                'currentTime': currentTime,
                'duration': duration,
                'progress': progress,
                'timeListened': timeListened
            },
            timeout=10
        )
        return response is not None

    def close_session(self, sessionId: str, currentTime: float = 0.0, duration: float = 0.0,
                      progress: float = None, timeListened: float = 0.0) -> bool:
        """Close an active playback session with final timing data."""
        currentTime = max(0.0, self._coerce_float(currentTime))
        duration = max(0.0, self._coerce_float(duration))
        timeListened = max(0.0, self._coerce_float(timeListened))
        if progress is None:
            progress = min(currentTime / duration, 1.0) if duration > 0 else 0.0

        response = self._make_request(
            'POST',
            f"/api/session/{sessionId}/close",
            expectedStatus=(200, 204),
            headers={'Content-Type': 'application/json'},
            json={
                'currentTime': currentTime,
                'duration': duration,
                'progress': progress,
                'timeListened': timeListened
            },
            timeout=10
        )
        return response is not None

    def get_library_series(self, libraryId: str) -> Optional[List[Dict]]:
        """Get series in a library."""
        responseData = self._request_json('GET', f"/api/libraries/{libraryId}/series", expectedStatus=(200,), timeout=15)
        if responseData is None:
            return None
        seriesList = self._extract_list(responseData, ['series', 'results', 'items'])
        return seriesList if seriesList else None

    def get_library_collections(self, libraryId: str) -> Optional[List[Dict]]:
        """Get collections in a library."""
        responseData = self._request_json('GET', f"/api/libraries/{libraryId}/collections", expectedStatus=(200,), timeout=15)
        if responseData is None:
            return None
        collectionsList = self._extract_list(responseData, ['collections', 'results', 'items'])
        return collectionsList if collectionsList else None
