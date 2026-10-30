"""Finding reference photos on the internet."""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from easy_photo import APP_NAME, APP_VERSION


class WebSearchError(Exception):
    """Raised when a search or a download fails."""


@dataclass(frozen=True)
class FoundImage:
    """A photo found on the internet."""

    title: str
    image_url: str
    """Address of the picture file itself."""

    page_url: str
    """Address of the page that describes the picture and its license."""


class WebSearch(ABC):
    """Finds photos on the internet for a search phrase, and downloads them."""

    USER_AGENT = f"{APP_NAME}/{APP_VERSION} (https://github.com/alfa-yohannis/easy-photo)"
    TIMEOUT_SECONDS = 30

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the service, shown in the window."""

    @abstractmethod
    def find_images(self, query: str, limit: int) -> list[FoundImage]:
        """Search for photos.

        Args:
            query: What to look for, such as "Mount Fuji autumn".
            limit: Most photos to return.

        Returns:
            The photos found, best match first.

        Raises:
            WebSearchError: When the search fails.
        """

    def download(self, image: FoundImage, folder: Path) -> Path:
        """Download a found photo into a folder, unless it is already there.

        Args:
            image: The photo.
            folder: Where to put it.

        Returns:
            The downloaded file.

        Raises:
            WebSearchError: When the download fails.
        """
        address_bytes = image.image_url.encode("utf-8")
        digest = hashlib.sha1(address_bytes, usedforsecurity=False).hexdigest()
        target = folder / f"{digest[:20]}.jpg"
        if target.exists():
            return target
        folder.mkdir(parents=True, exist_ok=True)
        data = self._get(image.image_url)
        target.write_bytes(data)
        return target

    def _get(self, url: str) -> bytes:
        """Fetch an address with the app's user agent.

        Args:
            url: The address.

        Returns:
            The data.

        Raises:
            WebSearchError: When the request fails.
        """
        headers = {"User-Agent": self.USER_AGENT}
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.TIMEOUT_SECONDS) as response:
                return response.read()
        except OSError as error:
            raise WebSearchError(f"Could not reach {url}: {error}") from error


class WikimediaSearch(WebSearch):
    """Searches Wikimedia Commons, a free library of photos that needs no account or key.

    Only JPEG photos are used, as copies 1024 pixels wide. The photos are only
    measured on this computer, never shared.
    """

    API_URL = "https://commons.wikimedia.org/w/api.php"
    WIDTH = 1024

    @property
    def name(self) -> str:
        """Name of the service."""
        return "Wikimedia Commons"

    def find_images(self, query: str, limit: int) -> list[FoundImage]:
        """Search Wikimedia Commons for photos.

        Args:
            query: What to look for.
            limit: Most photos to return.

        Returns:
            The JPEG photos found, best match first.

        Raises:
            WebSearchError: When the search fails or the answer cannot be read.
        """
        parameters = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"{query} filetype:bitmap",
            "gsrnamespace": "6",
            "gsrlimit": str(limit * 2),
            "prop": "imageinfo",
            "iiprop": "url|mime",
            "iiurlwidth": str(self.WIDTH),
        }
        query_text = urllib.parse.urlencode(parameters)
        data = self._get(f"{self.API_URL}?{query_text}")
        try:
            answer = json.loads(data)
        except json.JSONDecodeError as error:
            raise WebSearchError("Wikimedia Commons sent an answer that could not be read.") from error
        query_part = answer.get("query", {})
        pages = query_part.get("pages", {})
        page_list = pages.values()
        ordered = sorted(page_list, key=self._search_rank)
        found: list[FoundImage] = []
        for page in ordered:
            image = self._image_from(page)
            if image is not None:
                found.append(image)
            if len(found) >= limit:
                break
        return found

    def _search_rank(self, page: dict) -> int:
        """Sort key: the place of a page in the search results.

        Args:
            page: One page of the answer.

        Returns:
            Its rank, best first.
        """
        return page.get("index", 0)

    def _image_from(self, page: dict) -> FoundImage | None:
        """Read one search result.

        Args:
            page: One page of the answer.

        Returns:
            The photo, or None when it is not a JPEG photo.
        """
        infos = page.get("imageinfo", [])
        if not infos:
            return None
        info = infos[0]
        if info.get("mime") != "image/jpeg":
            return None
        image_url = info.get("thumburl") or info.get("url")
        if not image_url:
            return None
        title = page.get("title", "")
        page_url = info.get("descriptionurl", "")
        return FoundImage(title, image_url, page_url)
