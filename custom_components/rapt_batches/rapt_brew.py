"""Pull recordings from the RAPT Brew website (brew.rapt.io).

The new RAPT site has no export button. Its charts are fed by Next.js "server
actions", and this module replays those calls with the user's own logged-in
session cookie. The cookie is used for the requests of one call and is never
stored or logged. Only brew.rapt.io is ever contacted.

Derived from the standalone rapt_pull.py script, trimmed to what the importer
needs: readings in the library's own (key, ts, value) shape, no files.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.util import dt as dt_util

from .importers import ImportResult, build_result

_LOGGER = logging.getLogger(__name__)

BASE = "https://brew.rapt.io"
HOST = "brew.rapt.io"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
TIMEOUT = aiohttp.ClientTimeout(total=60)
WINDOW_MS = 14 * 86_400_000  # telemetry is requested in slices this long
MAX_SLICES = 40  # about 18 months; a guard against a bad start or end time

DATA_POINTS = [
    "timestamp",
    "temperature",
    "targetTemperature",
    "gravity",
    "gravityVelocity",
    "battery",
    "rssi",
]
ACTION_TELEMETRY = "fetchDeviceTelemetryAction"
ACTION_RECORDINGS = "fetchDeviceChartRecordingsAction"
NEEDED_ACTIONS = (ACTION_TELEMETRY, ACTION_RECORDINGS)

_ACTION_RE = re.compile(
    r'createServerReference\)?\(\s*"([0-9a-f]{40,})"\s*,[\w$.]+,\s*void 0\s*,'
    r'[\w$.]+,\s*"(\w+)"\s*\)'
)
_CHUNK_RE = re.compile(r'/_next/static/[^"\'\s\\<>]+?\.js')
_LOGIN_RE = re.compile(r"^/(login|signin|sign-in|auth)\b")
_ID_RE = re.compile(r"/batch/rec/(\d+)|^\s*(\d+)\s*$")
_FLIGHT_RE = re.compile(r"^[0-9a-f]+:(\{.*)$")

NOT_LOGGED_IN = "Not logged in: the cookie is wrong or has expired. Copy a fresh one."


def parse_recording_id(text: str) -> int:
    """Accept the bare number or the whole chart-page address."""
    m = _ID_RE.search(text or "")
    if not m:
        raise HomeAssistantError(
            "Could not find a recording number. Paste the chart page address "
            "(it contains /batch/rec/<number>/chart) or just the number."
        )
    return int(m.group(1) or m.group(2))


def clean_cookie(text: str) -> str:
    """The Cookie header value, with an optional leading 'Cookie:' removed."""
    cookie = re.sub(r"^\s*cookie:\s*", "", text or "", flags=re.I).strip()
    if "=" not in cookie or "\n" in cookie or "\r" in cookie:
        raise HomeAssistantError(
            "The cookie must be the whole Cookie header on one line (name=value; name=value ...)."
        )
    return cookie


def parse_flight(text: str) -> dict[str, Any]:
    """The action's result object from an RSC 'flight' response (the JSON with an "ok" key)."""
    for line in text.splitlines():
        m = _FLIGHT_RE.match(line)
        if not m:
            continue
        try:
            obj = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(obj, dict) and "ok" in obj:
            return obj
    raise HomeAssistantError("Unexpected reply from the RAPT site (it may have changed).")


def to_sg(value: float | None) -> float | None:
    """RAPT sends gravity as SG * 1000 (1029.5); convert to SG (1.0295)."""
    if value is None:
        return None
    return round(value / 1000.0, 5) if value >= 100 else round(float(value), 5)


def _iso_to_ts(value: str | None) -> float | None:
    parsed = dt_util.parse_datetime(re.sub(r"(\.\d{6})\d+", r"\1", value)) if value else None
    return parsed.timestamp() if parsed else None


class RaptBrewClient:
    """One logged-in session against brew.rapt.io. Use as an async context manager."""

    def __init__(self, hass: HomeAssistant, cookie: str, action_cache: dict[str, str]) -> None:
        self._cookie = clean_cookie(cookie)
        self._cache = action_cache  # action ids, kept between calls in hass.data
        # Own session with no cookie jar: the cookie is only ever the header we set.
        self._session = async_create_clientsession(hass, cookie_jar=aiohttp.DummyCookieJar())

    async def __aenter__(self) -> "RaptBrewClient":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self._session.close()

    # ---- http ----------------------------------------------------------

    async def _http(
        self, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None
    ) -> tuple[int, str]:
        """Returns (status, text). Follows same-host redirects; a login redirect means not logged in."""
        url = BASE + path
        h = {"User-Agent": UA, "Cookie": self._cookie, "Accept-Language": "en", **(headers or {})}
        for _hop in range(4):
            try:
                async with self._session.request(
                    method, url, data=body, headers=h, timeout=TIMEOUT, allow_redirects=False
                ) as resp:
                    if resp.status in (301, 302, 303, 307, 308):
                        target = urlparse(resp.headers.get("Location", ""))
                        if target.netloc not in ("", HOST) or _LOGIN_RE.match(target.path or ""):
                            raise HomeAssistantError(NOT_LOGGED_IN)
                        path = (target.path or "/") + (f"?{target.query}" if target.query else "")
                        url = BASE + path
                        if resp.status in (301, 302, 303):
                            method, body = "GET", None
                        continue
                    if resp.status in (401, 403):
                        raise HomeAssistantError(NOT_LOGGED_IN)
                    return resp.status, await resp.text()
            except (aiohttp.ClientError, TimeoutError) as err:
                raise HomeAssistantError(f"Could not reach the RAPT site: {err}") from err
        raise HomeAssistantError("The RAPT site redirected too many times.")

    # ---- page and actions ------------------------------------------------

    async def page_meta(self, fid: int) -> dict[str, Any]:
        path = f"/batch/rec/{fid}/chart"
        status, html = await self._http("GET", path)
        if status != 200:
            raise HomeAssistantError(f"The RAPT site answered HTTP {status} for that recording.")
        h = html.replace('\\"', '"')
        blob = next(
            (
                h[m.start() : m.start() + 900]
                for m in re.finditer(r'"mac":"', h)
                if f'"frontendId":{fid}' in h[m.start() : m.start() + 900]
            ),
            None,
        )
        if blob is None:
            raise HomeAssistantError(
                f"Recording {fid} was not found. Check the number, and that the cookie is from the account that owns it."
            )

        def g(pat: str) -> str | None:
            m = re.search(pat, blob)
            return m.group(1) if m and m.group(1) != "null" else None

        mac = g(r'"mac":"([^"]+)"')
        if not mac:
            raise HomeAssistantError("Could not read the device from the chart page (the site may have changed).")
        start, end = g(r'"startMs":(\d+)'), g(r'"endMs":(\d+)')
        return {
            "fid": fid,
            "mac": mac,
            "device_name": g(r'"deviceName":"([^"]*)"'),
            "start_ms": int(start) if start else None,
            "end_ms": int(end) if end else None,
            "_html": html,
        }

    async def _action_ids(self, html: str, refresh: bool = False) -> dict[str, str]:
        if not refresh and all(n in self._cache for n in NEEDED_ACTIONS):
            return self._cache
        found: dict[str, str] = {}
        for url in sorted(set(_CHUNK_RE.findall(html.replace("\\/", "/")))):
            status, js = await self._http("GET", url)
            if status != 200:
                continue
            found.update({m.group(2): m.group(1) for m in _ACTION_RE.finditer(js)})
            if all(n in found for n in NEEDED_ACTIONS):
                break
        if not all(n in found for n in NEEDED_ACTIONS):
            raise HomeAssistantError("Could not find the RAPT site's data calls (the site may have changed).")
        self._cache.update(found)
        return self._cache

    async def _action(self, name: str, args: list[Any], meta: dict[str, Any]) -> dict[str, Any]:
        path = f"/batch/rec/{meta['fid']}/chart"
        status = 0
        for attempt in (0, 1):  # second attempt re-reads the action ids in case they changed
            ids = await self._action_ids(meta["_html"], refresh=attempt == 1)
            status, text = await self._http(
                "POST",
                path,
                json.dumps(args).encode(),
                {
                    "Accept": "text/x-component",
                    "Next-Action": ids[name],
                    "Content-Type": "text/plain;charset=UTF-8",
                },
            )
            if status == 200:
                try:
                    return parse_flight(text)
                except HomeAssistantError:
                    pass
        raise HomeAssistantError(f"The RAPT site did not return data (HTTP {status}).")

    async def recordings(self, meta: dict[str, Any]) -> list[dict[str, Any]]:
        res = await self._action(ACTION_RECORDINGS, [meta["mac"]], meta)
        if not res.get("ok"):
            raise HomeAssistantError(f"Could not list recordings: {res.get('message') or 'unknown error'}")
        return res.get("items", [])

    async def telemetry(
        self, meta: dict[str, Any], start_ms: int, end_ms: int
    ) -> dict[str, dict[int, dict[str, Any]]]:
        """Merged readings: {"entries": {t: {...}}, "control": {t: {...}}}.

        A Temperature Controller reports the Pill's readings as "control" entries and
        its own probe as "entries"; a bare Pill only has "entries".
        """
        if (end_ms - start_ms) / WINDOW_MS > MAX_SLICES:
            raise HomeAssistantError("That recording is too long to pull.")
        merged: dict[str, dict[int, dict[str, Any]]] = {"entries": {}, "control": {}}
        cur = start_ms
        while cur < end_ms:
            nxt = min(cur + WINDOW_MS, end_ms)
            args = [
                {
                    "macAddresses": [meta["mac"]],
                    "preset": "custom",
                    "dataPoints": DATA_POINTS,
                    "customStartMs": cur,
                    "customEndMs": nxt,
                }
            ]
            res = await self._action(ACTION_TELEMETRY, args, meta)
            if not res.get("ok"):
                raise HomeAssistantError(f"Could not read the readings: {res.get('message') or 'unknown error'}")
            for item in res.get("items", []):
                for e in item.get("entries") or []:
                    merged["entries"].setdefault(e["t"], {}).update(e)
                for e in item.get("controlEntries") or []:
                    merged["control"].setdefault(e["t"], {}).update(e)
            cur = nxt
        return merged


def to_import_result(tele: dict[str, dict[int, dict[str, Any]]]) -> ImportResult:
    """Telemetry to the library's readings: gravity (required), temperature, velocity, battery."""
    data = tele["control"] or tele["entries"]
    records: list[tuple[float, dict[str, float]]] = []
    skipped = 0
    for t in sorted(data):
        e = data[t]
        sg = to_sg(e.get("gravity"))
        if sg is None:
            if e.get("temperature") is not None:
                skipped += 1  # a reading without gravity cannot be used
            continue
        values = {"sg": sg}
        for key, field in (("temp", "temperature"), ("velocity", "gravityVelocity"), ("battery", "battery")):
            if isinstance(e.get(field), (int, float)):
                values[key] = float(e[field])
        records.append((t / 1000.0, values))
    return build_result(records, skipped)


_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')


def parse_recordings_page(html: str) -> list[dict[str, Any]]:
    """The recordings embedded in the /batches page (the site renders them into the HTML)."""
    text = "".join(json.loads(m.group(1)) for m in _PUSH_RE.finditer(html))
    marker = '"recordings":['
    at = text.find(marker)
    if at < 0:
        raise HomeAssistantError("Could not find the recording list (the RAPT site may have changed).")
    try:
        items, _end = json.JSONDecoder().raw_decode(text[at + len(marker) - 1 :])
    except ValueError as err:
        raise HomeAssistantError("Could not read the recording list (the RAPT site may have changed).") from err
    return [r for r in items if isinstance(r, dict) and "frontendId" in r]


async def async_list_recordings(hass: HomeAssistant, cookie: str) -> dict[str, Any]:
    """Every recording on the account, newest first."""
    cache = hass.data.setdefault("rapt_batches_actions", {})
    async with RaptBrewClient(hass, cookie, cache) as client:
        status, html = await client._http("GET", "/batches?view=all")
    if status != 200:
        raise HomeAssistantError(f"The RAPT site answered HTTP {status}.")
    return {
        "recordings": [
            {
                "id": r["frontendId"],
                "title": r.get("title") or str(r["frontendId"]),
                "active": r.get("status") == "ACTIVE",
                "start_ts": _iso_to_ts(r.get("startTime")),
                "end_ts": _iso_to_ts(r.get("endTime")),
            }
            for r in sorted(parse_recordings_page(html), key=lambda r: r.get("startTime") or "", reverse=True)
        ]
    }


async def async_pull(hass: HomeAssistant, cookie: str, recording: str) -> tuple[str, ImportResult]:
    """Download one recording. Returns (its title, the cleaned readings)."""
    fid = parse_recording_id(recording)
    cache = hass.data.setdefault("rapt_batches_actions", {})
    async with RaptBrewClient(hass, cookie, cache) as client:
        meta = await client.page_meta(fid)
        rec = next((r for r in await client.recordings(meta) if r.get("frontendId") == fid), {})
        start_ms = meta["start_ms"] or (
            int(_iso_to_ts(rec.get("startTime")) * 1000) if rec.get("startTime") else None
        )
        end_ms = meta["end_ms"] or (int(_iso_to_ts(rec.get("endTime")) * 1000) if rec.get("endTime") else None)
        if not start_ms or not end_ms:
            raise HomeAssistantError("That recording has no end time yet. Finish it on the RAPT site first.")
        tele = await client.telemetry(meta, start_ms, end_ms)
    result = await hass.async_add_executor_job(to_import_result, tele)
    return rec.get("title") or meta["device_name"] or str(fid), result
