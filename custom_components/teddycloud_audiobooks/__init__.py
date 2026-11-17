"""YAML-configured audiobook progress using the existing HA MQTT connection."""
import asyncio
from datetime import timedelta
import logging
from urllib.parse import urlsplit

import aiohttp
from homeassistant.components import mqtt
from homeassistant.components.mqtt.const import MQTT_CONNECTION_STATE
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv, discovery
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
import voluptuous as vol

from .engine import Engine

DOMAIN = "teddycloud_audiobooks"
_LOGGER = logging.getLogger(__name__)
SEGMENT = vol.Schema({vol.Required("title"): cv.string,
                      vol.Required("source"): vol.All(cv.string, vol.Match(r"^lib://[^?\x00]+\.taf$"), vol.Length(max=240)),
                      vol.Required("audio_id"): vol.All(vol.Coerce(int), vol.Range(min=1, max=4294967295))})
BOOK = vol.Schema({vol.Required("name"): cv.string,
                   vol.Required("segments"): vol.All([SEGMENT], vol.Length(min=1))})
CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({
    vol.Required("url"): cv.url,
    vol.Optional("username"): cv.string,
    vol.Optional("password"): cv.string,
    vol.Optional("topic", default="teddyCloud"): cv.string,
    vol.Required("boxes"): vol.All([vol.All(cv.string, vol.Match(r"^[A-Za-z0-9_-]+$"))], vol.Length(min=1)),
    vol.Optional("threshold_seconds", default=600): vol.All(vol.Coerce(int), vol.Range(min=1)),
    vol.Required("books"): vol.All({vol.All(cv.string, vol.Match(r"^[0-9A-F]{16}$")): BOOK}, vol.Length(min=1)),
})}, extra=vol.ALLOW_EXTRA)


async def async_setup(hass, config):
    cfg = config[DOMAIN]
    if urlsplit(cfg["url"]).query or urlsplit(cfg["url"]).fragment:
        raise vol.Invalid("TeddyCloud URL must not contain a query or fragment")
    for book in cfg["books"].values():
        ids = [s["audio_id"] for s in book["segments"]]
        if len(ids) != len(set(ids)):
            raise vol.Invalid("Each segment needs a distinct TAF audio ID")
    manager = Manager(hass, cfg)
    await manager.load()
    hass.data[DOMAIN] = manager
    await discovery.async_load_platform(hass, "select", DOMAIN, {}, config)
    await manager.start()
    return True


class Manager:
    def __init__(self, hass, cfg):
        self.hass, self.cfg = hass, cfg
        self.store = Store(hass, 1, DOMAIN)
        self.lock = asyncio.Lock()
        self.listeners = []
        self.pending = set()
        self.errors = {}
        self.connected = False
        self.retry_at = 0
        self.unsubs = []

    async def load(self):
        data = await self.store.async_load() or {}
        indices = data.get("indices", {})
        self.catalog = {uid: [[s["source"], s["audio_id"]] for s in book["segments"]]
                        for uid, book in self.cfg["books"].items()}
        saved_catalog = data.get("catalog", {})
        for uid, entries in self.catalog.items():
            if uid in saved_catalog and saved_catalog[uid] != entries:
                raise vol.Invalid(f"Segment catalog changed for {uid}; migrate saved progress explicitly")
        for uid, book in self.cfg["books"].items():
            index = indices.get(uid, 0)
            if type(index) is not int or not 0 <= index < len(book["segments"]):
                raise vol.Invalid(f"Saved index for {uid} no longer fits configuration; restore segment ordering")
        self.engine = Engine(self.cfg["books"], self.cfg["threshold_seconds"], indices)
        self.selected = data.get("selected")
        if self.selected not in self.engine.books:
            self.selected = next(iter(self.engine.books))
        await self.save()
        # Reconcile idempotently at startup, including uncertain writes before a crash.
        self.pending = set(self.engine.books)

    async def save(self):
        await self.store.async_save({"indices": self.engine.indices, "selected": self.selected, "catalog": self.catalog})

    @callback
    def notify(self):
        for listener in self.listeners:
            listener()

    @callback
    def connection(self, connected):
        self.connected = connected
        self.engine.reset()

    async def start(self):
        self.unsubs.append(async_dispatcher_connect(self.hass, MQTT_CONNECTION_STATE, self.connection))
        self.connected = mqtt.is_connected(self.hass)
        for box in self.cfg["boxes"]:
            for kind in ("TagValid", "Playback", "ContentAudioId"):
                topic = f'{self.cfg["topic"]}/box/{box}/{kind}'
                self.unsubs.append(await mqtt.async_subscribe(self.hass, topic, self.message, qos=0))
        self.unsubs.append(await mqtt.async_subscribe(self.hass, f'{self.cfg["topic"]}/status', self.status, qos=0))
        self.unsubs.append(async_track_time_interval(self.hass, self.tick, timedelta(seconds=1)))
        self.hass.bus.async_listen_once("homeassistant_stop", self.stop)

    @callback
    def stop(self, event):
        for unsub in self.unsubs:
            unsub()
        self.engine.reset()

    @callback
    def status(self, msg):
        # A TeddyCloud reconnect also invalidates any incomplete observation.
        self.engine.reset()

    async def message(self, msg):
        if msg.retain or not self.connected:
            return
        _, box, kind = msg.topic.rsplit("/", 2)
        async with self.lock:
            self.engine.event(box, kind, msg.payload, self.hass.loop.time())

    async def choose_book(self, uid):
        async with self.lock:
            self.selected = uid
            await self.save()
            self.notify()

    async def choose_segment(self, index):
        async with self.lock:
            uid = self.selected
            old = self.engine.indices[uid]
            self.engine.manual(uid, index)
            try:
                await self.save()  # Durable intent always precedes the external write.
            except Exception:
                self.engine.indices[uid] = old
                raise
            self.pending.add(uid)
            _LOGGER.info("Manual segment selection for %s: %s", uid, index + 1)
            await self.reconcile(uid)
            self.notify()

    async def tick(self, now):
        async with self.lock:
            old = dict(self.engine.indices)
            changed = self.engine.due(self.hass.loop.time()) if self.connected else []
            if changed:
                try:
                    await self.save()
                except Exception:
                    self.engine.indices = old
                    _LOGGER.exception("Progress persistence failed; suppressed session advancement")
                    return
                self.pending.update(changed)
                for uid in changed:
                    _LOGGER.info("Prepared next segment for %s: %s", uid, self.engine.indices[uid] + 1)
            dirty = bool(changed)
            # Retry at most once per minute, including on API failure.
            if self.hass.loop.time() >= self.retry_at or changed:
                self.retry_at = self.hass.loop.time() + 60
                before = (set(self.pending), dict(self.errors))
                for uid in list(self.pending):
                    await self.reconcile(uid)
                dirty = dirty or before != (self.pending, self.errors)
            if dirty:
                self.notify()

    async def reconcile(self, uid):
        segment = self.engine.books[uid]["segments"][self.engine.indices[uid]]
        ruid = bytes.fromhex(uid)[::-1].hex()
        base = self.cfg["url"].rstrip("/") + "/content/json/"
        auth = aiohttp.BasicAuth(self.cfg["username"], self.cfg.get("password", "")) if "username" in self.cfg else None
        session = async_get_clientsession(self.hass)
        desired = {"source": segment["source"], "live": False, "nocloud": True}
        try:
            async with asyncio.timeout(10):
                async with session.get(base + "get/" + ruid, auth=auth) as response:
                    response.raise_for_status()
                    current = await response.json(content_type=None)
                if any(current.get(k) != v for k, v in desired.items()):
                    async with session.post(base + "set/" + ruid, auth=auth,
                                            data={k: str(v).lower() if isinstance(v, bool) else v for k, v in desired.items()}) as response:
                        response.raise_for_status()
                    async with session.get(base + "get/" + ruid, auth=auth) as response:
                        response.raise_for_status()
                        updated = await response.json(content_type=None)
                    if any(updated.get(k) != v for k, v in desired.items()):
                        raise ValueError("Assignment read-back did not match")
            self.pending.discard(uid)
            self.errors.pop(uid, None)
        except (aiohttp.ClientError, TimeoutError, ValueError):
            self.errors[uid] = "Assignment pending; check TeddyCloud connectivity and tag metadata"
            _LOGGER.warning("TeddyCloud assignment pending for %s; retrying in 60 seconds", uid)
