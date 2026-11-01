"""Constants for RAPT Batches."""
from __future__ import annotations

DOMAIN = "rapt_batches"
VERSION = "0.3.0"
DB_NAME = "rapt_batches.db"
PLATFORMS = ["sensor"]

PANEL_URL = "rapt-batches"
CONF_PANEL_TITLE = "panel_title"
CONF_PANEL_ICON = "panel_icon"
DEFAULT_PANEL_TITLE = "Brewing Library"
DEFAULT_PANEL_ICON = "mdi:beer-outline"
STATIC_URL = "/rapt_batches_static"

# Measurement keys recorded for each batch
KEYS = ("sg", "temp", "battery", "velocity")

CONF_NAME = "name"
CONF_DEVICE = "device_id"
CONF_OG = "og"
CONF_FG = "fg"
CONF_START = "start"
CONF_END = "end"
CONF_STATUS = "status"
CONF_FINISH = "finish"
CONF_REOPEN = "reopen"
CONF_ARCHIVE = "archive"

# Stored values. "completed" is shown as "Finished" in the UI.
STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"
STATUS_ARCHIVED = "archived"

ABV_FACTOR = 131.25


def entity_key(key: str) -> str:
    """Config-data key holding the entity id for a measurement key."""
    return f"{key}_entity"


def signal(subentry_id: str) -> str:
    """Dispatcher signal fired when a batch receives new data."""
    return f"{DOMAIN}_update_{subentry_id}"
