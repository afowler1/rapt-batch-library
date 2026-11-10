"""Tests for the RAPT Brew importer.

Home Assistant is not needed: the few HA modules the importer touches are stubbed,
and the website is replaced by a fake that speaks the same server-action protocol.

Run from the repo root:  python -m unittest discover -s tests -v
"""
import asyncio
import importlib
import json
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _stub_homeassistant():
    """Minimal stand-ins for the HA modules rapt_brew and importers import."""

    class HomeAssistantError(Exception):
        pass

    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m

    from datetime import datetime, timezone

    mod("homeassistant")
    mod("homeassistant.core", HomeAssistant=object)
    mod("homeassistant.exceptions", HomeAssistantError=HomeAssistantError)
    mod("homeassistant.helpers")
    mod("homeassistant.helpers.aiohttp_client", async_create_clientsession=lambda hass, **kw: FakeSession())
    mod("homeassistant.util")
    mod(
        "homeassistant.util.dt",
        parse_datetime=lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")),
    )
    sys.modules["homeassistant"].exceptions = sys.modules["homeassistant.exceptions"]
    return HomeAssistantError


class FakeSession:
    async def close(self):
        pass


HAError = _stub_homeassistant()
try:
    import aiohttp  # noqa: F401
except ImportError:  # only DummyCookieJar and the exception types are used
    aio = types.ModuleType("aiohttp")
    aio.ClientError = type("ClientError", (Exception,), {})
    aio.ClientTimeout = lambda **kw: None
    aio.DummyCookieJar = lambda: None
    sys.modules["aiohttp"] = aio

pkg = types.ModuleType("rapt_batches")
pkg.__path__ = [str(ROOT / "custom_components" / "rapt_batches")]
sys.modules["rapt_batches"] = pkg
importers = importlib.import_module("rapt_batches.importers")
brew = importlib.import_module("rapt_batches.rapt_brew")

START = 1791611925193  # ms
STEP = 45 * 60 * 1000


def flight(obj):
    return f"0:{{}}\n1:{json.dumps(obj)}\n"


class FakeSite:
    """Answers the three kinds of request RaptBrewClient makes."""

    def __init__(self, entries, control, fid=42, active=False):
        self.entries, self.control, self.fid = entries, control, fid
        self.active = active
        self.telemetry_calls = 0
        self.cookies_seen = set()

    def install(self, client):
        client._http = self.http

    async def http(self, method, path, body=None, headers=None):
        if path.endswith("/chart") and method == "GET":
            end = "null" if self.active else str(START + 10 * 86_400_000)
            page = (
                '<script src="/_next/static/chunks/app.js"></script>'
                '{\\"mac\\":\\"aa-bb\\",\\"frontendId\\":%d,\\"deviceName\\":\\"Fat Controller\\",'
                '\\"startMs\\":%d,\\"endMs\\":%s}' % (self.fid, START, end)
            )
            return 200, page
        if path.startswith("/_next/static"):
            return 200, (
                'createServerReference)("%s",a.callServer,void 0,a.findSourceMapURL,"fetchDeviceTelemetryAction")'
                'createServerReference)("%s",a.callServer,void 0,a.findSourceMapURL,"fetchDeviceChartRecordingsAction")'
            ) % ("a" * 42, "b" * 42)
        args = json.loads(body)
        action = (headers or {})["Next-Action"]
        if action == "b" * 42:
            return 200, flight(
                {
                    "ok": True,
                    "items": [
                        {"frontendId": self.fid, "title": "10/10 - Fat Controller", "status": "ACTIVE" if self.active else "ENDED",
                         "startTime": "2026-10-10T06:00:25.1930000Z", "endTime": None if self.active else "2026-10-20T06:00:25Z"},
                        {"frontendId": 7, "title": "Older", "status": "ENDED",
                         "startTime": "2026-01-01T00:00:00Z", "endTime": "2026-01-10T00:00:00Z"},
                    ],
                }
            )
        self.telemetry_calls += 1
        lo, hi = args[0]["customStartMs"], args[0]["customEndMs"]
        pick = lambda rows: [r for r in rows if lo <= r["t"] < hi]
        return 200, flight(
            {"ok": True, "items": [{"deviceType": "TemperatureController", "entries": pick(self.entries), "controlEntries": pick(self.control)}]}
        )


def run(coro):
    return asyncio.run(coro)


def make_control(n=300, junk=True):
    rows = []
    for k in range(n):
        r = {"t": START + k * STEP, "temperature": 20 + k % 5, "gravity": 1040 - k * 0.1, "battery": 70, "rssi": -60}
        if k % 3 == 0:
            r["gravityVelocity"] = -1.5
        rows.append(r)
    if junk:
        rows.append({"t": START + n * STEP, "temperature": 21, "gravity": 1256.4})  # Pill out of the fermenter
    return rows


class Helpers(unittest.TestCase):
    def test_recording_id(self):
        self.assertEqual(brew.parse_recording_id("919738"), 919738)
        self.assertEqual(brew.parse_recording_id(" https://brew.rapt.io/batch/rec/919738/chart "), 919738)
        with self.assertRaises(HAError):
            brew.parse_recording_id("hello")

    def test_cookie(self):
        self.assertEqual(brew.clean_cookie("Cookie: a=b; c=d"), "a=b; c=d")
        for bad in ("", "nocookie", "a=b\nX-Evil: 1"):
            with self.assertRaises(HAError):
                brew.clean_cookie(bad)

    def test_sg(self):
        self.assertEqual(brew.to_sg(1029.5), 1.0295)
        self.assertEqual(brew.to_sg(1.0295), 1.0295)
        self.assertIsNone(brew.to_sg(None))

    def test_flight(self):
        self.assertEqual(brew.parse_flight(flight({"ok": True, "items": []}))["ok"], True)
        with self.assertRaises(HAError):
            brew.parse_flight("garbage")


class Conversion(unittest.TestCase):
    def test_pill_readings_preferred_and_junk_removed(self):
        tele = {"entries": {r["t"]: r for r in make_control(50, junk=False)}, "control": {r["t"]: r for r in make_control(300)}}
        res = brew.to_import_result(tele)
        self.assertEqual(res.dropped, 1)  # the 1.2564 reading
        keys = {k for k, _t, _v in res.rows}
        self.assertEqual(keys, {"sg", "temp", "velocity", "battery"})  # rssi is not stored
        self.assertEqual(len([r for r in res.rows if r[0] == "sg"]), 300)

    def test_bare_pill_uses_entries(self):
        tele = {"entries": {r["t"]: r for r in make_control(40, junk=False)}, "control": {}}
        self.assertEqual(len([r for r in brew.to_import_result(tele).rows if r[0] == "sg"]), 40)

    def test_matches_legacy_csv_import(self):
        """The same readings must give the same result as the legacy CSV importer."""
        ctl = make_control(300)
        lines = ["Date,Temperature,Gravity,Gravity Velocity,Signal Strength,Battery"]
        for r in ctl:
            from datetime import datetime, timezone

            d = datetime.fromtimestamp(r["t"] / 1000, timezone.utc).isoformat()
            lines.append(",".join([d, str(r["temperature"]), str(round(r["gravity"] / 1000, 5)),
                                   str(r.get("gravityVelocity", "")), str(r["rssi"]) if "rssi" in r else "", str(r.get("battery", ""))]))
        legacy = importers.parse_legacy_rapt("\n".join(lines))
        new = brew.to_import_result({"entries": {}, "control": {r["t"]: r for r in ctl}})
        self.assertEqual(new.rows, legacy.rows)
        self.assertEqual((new.og_guess, new.fg_guess, new.start_ts, new.end_ts), (legacy.og_guess, legacy.fg_guess, legacy.start_ts, legacy.end_ts))

    def test_no_gravity_is_an_error(self):
        with self.assertRaises(HAError):
            brew.to_import_result({"entries": {1: {"t": 1, "temperature": 20}}, "control": {}})


class Pulling(unittest.TestCase):
    def setUp(self):
        self.ctl = make_control(300)
        self.site = FakeSite([{"t": START + 5, "temperature": 18, "targetTemperature": 19}], self.ctl)
        self.cache = {}

    def client(self, site=None):
        c = brew.RaptBrewClient(None, "session=abc", self.cache)
        (site or self.site).install(c)
        return c

    def test_pull_end_to_end_in_slices(self):
        async def go():
            async with self.client() as c:
                meta = await c.page_meta(42)
                tele = await c.telemetry(meta, START, meta["end_ms"])
            return tele

        tele = run(go())
        self.assertEqual(len(tele["control"]), len(self.ctl))
        self.assertEqual(self.site.telemetry_calls, 1)  # 10 days fits one 14 day slice
        self.assertEqual(set(self.cache), {"fetchDeviceTelemetryAction", "fetchDeviceChartRecordingsAction"})

    def test_long_recording_is_sliced(self):
        async def go():
            async with self.client() as c:
                meta = await c.page_meta(42)
                await c.telemetry(meta, START, START + 30 * 86_400_000)

        run(go())
        self.assertEqual(self.site.telemetry_calls, 3)

    def test_absurd_length_refused(self):
        async def go():
            async with self.client() as c:
                meta = await c.page_meta(42)
                await c.telemetry(meta, 0, START)

        with self.assertRaises(HAError):
            run(go())

    def test_wrong_recording(self):
        async def go():
            async with self.client() as c:
                await c.page_meta(999)

        with self.assertRaises(HAError):
            run(go())

    def test_recordings_listed(self):
        async def go():
            async with self.client() as c:
                return await c.recordings(await c.page_meta(42))

        self.assertEqual([r["frontendId"] for r in run(go())], [42, 7])


if __name__ == "__main__":
    unittest.main()
