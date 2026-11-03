"""Serve the frontend files from a URL that changes whenever a file changes.

Phones and the Companion app cache scripts aggressively, and the card and panel
modules import each other by relative path, so a changed file kept being served
from the old copy. Putting a hash of the files into the URL path means every
module is fetched fresh after an update (relative imports inherit the new path),
and lets us mark the files as safe to cache for a year.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import STATIC_URL

FRONTEND_DIR = Path(__file__).parent / "frontend"
CONTENT_TYPES = {".js": "text/javascript", ".css": "text/css"}


def _index() -> tuple[dict[str, Path], str]:
    """Map file names to paths and hash their contents (runs in an executor)."""
    files = {p.name: p for p in sorted(FRONTEND_DIR.iterdir()) if p.is_file()}
    digest = hashlib.sha256()
    for name, path in files.items():
        digest.update(name.encode())
        digest.update(path.read_bytes())
    return files, digest.hexdigest()[:10]


class FrontendView(HomeAssistantView):
    """Serves /rapt_batches_static/<hash>/<file>, and the old unversioned path."""

    requires_auth = False  # public static assets, like HA's own
    name = "api:rapt_batches:frontend"
    url = STATIC_URL + "/{version}/{filename}"
    extra_urls = [STATIC_URL + "/{filename}"]

    def __init__(self, files: dict[str, Path], version: str) -> None:
        self._files = files  # only these names can be served: no path traversal
        self._version = version

    async def get(self, request: web.Request, filename: str, version: str | None = None) -> web.StreamResponse:
        path = self._files.get(filename)
        if path is None:
            raise web.HTTPNotFound()
        # The current hash can be cached for good; anything else must be rechecked.
        cache = "public, max-age=31536000, immutable" if version == self._version else "no-cache"
        response = web.FileResponse(path, headers={"Cache-Control": cache})
        content_type = CONTENT_TYPES.get(path.suffix)
        if content_type:
            response.content_type = content_type
        return response


async def async_register_frontend(hass: HomeAssistant) -> str:
    """Register the view and return the hash that goes in the URLs."""
    files, version = await hass.async_add_executor_job(_index)
    hass.http.register_view(FrontendView(files, version))
    return version
