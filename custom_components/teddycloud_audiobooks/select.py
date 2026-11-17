"""Two selectors shared by every configured audiobook."""
from homeassistant.components.select import SelectEntity
from . import DOMAIN


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    manager = hass.data[DOMAIN]
    async_add_entities([BookSelect(manager), SegmentSelect(manager)])


class BaseSelect(SelectEntity):
    _attr_should_poll = False

    def __init__(self, manager):
        self.manager = manager

    async def async_added_to_hass(self):
        self.manager.listeners.append(self.async_write_ha_state)
        self.async_on_remove(lambda: self.manager.listeners.remove(self.async_write_ha_state))


class BookSelect(BaseSelect):
    _attr_name = "Audiobook"
    _attr_unique_id = "teddycloud_audiobook"
    _attr_icon = "mdi:book-music"

    @property
    def options(self):
        return [f'{b["name"]} ({uid})' for uid, b in self.manager.engine.books.items()]

    @property
    def current_option(self):
        uid = self.manager.selected
        return f'{self.manager.engine.books[uid]["name"]} ({uid})'

    async def async_select_option(self, option):
        await self.manager.choose_book(option.rsplit("(", 1)[1][:-1])


class SegmentSelect(BaseSelect):
    _attr_name = "Audiobook segment"
    _attr_unique_id = "teddycloud_audiobook_segment"
    _attr_icon = "mdi:playlist-music"

    @property
    def options(self):
        return [f'{i + 1}: {s["title"]}' for i, s in enumerate(self.manager.engine.books[self.manager.selected]["segments"])]

    @property
    def current_option(self):
        return self.options[self.manager.engine.indices[self.manager.selected]]

    @property
    def extra_state_attributes(self):
        uid = self.manager.selected
        return {"tag_uid": uid, "segment_index": self.manager.engine.indices[uid] + 1,
                "assignment_pending": uid in self.manager.pending,
                "assignment_error": self.manager.errors.get(uid)}

    async def async_select_option(self, option):
        await self.manager.choose_segment(self.options.index(option))
