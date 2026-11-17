"""Run in an HA Python environment; no live MQTT, API writes or HA restart."""
import asyncio
import importlib.util
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

if importlib.util.find_spec("homeassistant") is not None:
    from custom_components.teddycloud_audiobooks import CONFIG_SCHEMA, DOMAIN, Manager
    import voluptuous as vol
else:
    Manager = None

UID = 'E00403500ECCB59F'
CFG = {'url': 'http://example.invalid', 'boxes': ['48CA4351C694'], 'topic': 'teddyCloud',
       'threshold_seconds': 10, 'books': {UID: {'name': 'Test', 'segments': [
           {'title': 'One', 'source': 'lib://one.taf', 'audio_id': 11},
           {'title': 'Two', 'source': 'lib://two.taf', 'audio_id': 12}]}}}


@unittest.skipIf(Manager is None, 'Requires the Home Assistant runtime')
class Persistence(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = SimpleNamespace(loop=asyncio.get_running_loop())
        with patch('custom_components.teddycloud_audiobooks.Store') as store:
            store.return_value.async_load = AsyncMock(return_value=None)
            store.return_value.async_save = AsyncMock()
            self.manager = Manager(self.hass, deepcopy(CFG))
        await self.manager.load()
        self.manager.reconcile = AsyncMock()

    async def test_manual_durable_before_api_and_restart(self):
        seen = []
        self.manager.store.async_save.side_effect = lambda data: seen.append(deepcopy(data))
        await self.manager.choose_segment(1)
        self.assertEqual(seen[-1]['indices'][UID], 1)
        self.manager.reconcile.assert_awaited_once_with(UID)
        self.manager.store.async_load.return_value = seen[-1]
        await self.manager.load()
        self.assertEqual(self.manager.engine.indices[UID], 1)
        self.assertFalse(self.manager.engine.sessions)

    async def test_failed_storage_prevents_api_write(self):
        self.manager.store.async_save.side_effect = OSError('disk full')
        with self.assertRaises(OSError):
            await self.manager.choose_segment(1)
        self.manager.reconcile.assert_not_awaited()
        self.assertEqual(self.manager.engine.indices[UID], 0)

    async def test_retained_event_ignored(self):
        self.manager.connected = True
        self.manager.engine.armed.add('48CA4351C694')
        await self.manager.message(SimpleNamespace(retain=True, topic='teddyCloud/box/48CA4351C694/TagValid', payload=UID))
        self.assertFalse(self.manager.engine.sessions)

    async def test_catalog_change_rejected(self):
        self.manager.store.async_load.return_value = {'indices': {UID: 0}, 'catalog': {UID: [['lib://wrong.taf', 99]]}}
        with self.assertRaises(vol.Invalid):
            await self.manager.load()

    async def test_timer_persists_before_reconciliation(self):
        self.manager.connected = True
        self.manager.hass.loop = SimpleNamespace(time=lambda: 11)
        for kind, payload in [('TagValid', ''), ('TagValid', UID), ('Playback', 'ON'), ('ContentAudioId', '11')]:
            self.manager.engine.event('box', kind, payload, 0)
        seen = []
        self.manager.store.async_save.side_effect = lambda data: seen.append(deepcopy(data))
        self.manager.reconcile.side_effect = lambda uid: self.assertEqual(seen[-1]['indices'][uid], 1)
        await self.manager.tick(None)
        self.assertEqual(self.manager.engine.indices[UID], 1)
        self.manager.reconcile.assert_awaited_once_with(UID)

    async def test_timer_storage_failure_never_writes_api(self):
        self.manager.connected = True
        self.manager.hass.loop = SimpleNamespace(time=lambda: 11)
        for kind, payload in [('TagValid', ''), ('TagValid', UID), ('Playback', 'ON'), ('ContentAudioId', '11')]:
            self.manager.engine.event('box', kind, payload, 0)
        self.manager.store.async_save.side_effect = OSError('disk full')
        await self.manager.tick(None)
        self.manager.reconcile.assert_not_awaited()
        self.assertEqual(self.manager.engine.indices[UID], 0)

    async def test_idle_tick_does_not_report_entities(self):
        from unittest.mock import Mock
        listener = Mock()
        self.manager.listeners.append(listener)
        self.manager.retry_at = self.manager.hass.loop.time() + 60
        await self.manager.tick(None)
        listener.assert_not_called()

    async def test_schema(self):
        self.assertEqual(CONFIG_SCHEMA({DOMAIN: CFG})[DOMAIN]['threshold_seconds'], 10)


class Response:
    def __init__(self, data=None, error=None):
        self.data, self.error = data, error

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    async def json(self, **kwargs):
        return self.data


@unittest.skipIf(Manager is None, 'Requires the Home Assistant runtime')
class Api(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await Persistence.asyncSetUp(self)
        # Use the implementation rather than the persistence-test stub.
        self.manager.reconcile = Manager.reconcile.__get__(self.manager)
        from unittest.mock import Mock
        self.http = Mock()
        self.desired = {'source': 'lib://one.taf', 'live': False, 'nocloud': True}

    async def test_no_unnecessary_write(self):
        self.http.get.return_value = Response(self.desired)
        with patch('custom_components.teddycloud_audiobooks.async_get_clientsession', return_value=self.http):
            await self.manager.reconcile(UID)
        self.http.post.assert_not_called()
        self.assertNotIn(UID, self.manager.pending)

    async def test_form_and_reversed_uid(self):
        self.http.get.side_effect = [Response({'source': 'old'}), Response(self.desired)]
        self.http.post.return_value = Response()
        with patch('custom_components.teddycloud_audiobooks.async_get_clientsession', return_value=self.http):
            await self.manager.reconcile(UID)
        self.http.post.assert_called_once_with(
            'http://example.invalid/content/json/set/9fb5cc0e500304e0', auth=None,
            data={'source': 'lib://one.taf', 'live': 'false', 'nocloud': 'true'})
        self.assertNotIn(UID, self.manager.pending)

    async def test_unavailable_then_retry(self):
        self.http.get.return_value = Response(error=TimeoutError())
        with patch('custom_components.teddycloud_audiobooks.async_get_clientsession', return_value=self.http):
            await self.manager.reconcile(UID)
            self.assertIn(UID, self.manager.pending)
            self.http.get.return_value = Response(self.desired)
            await self.manager.reconcile(UID)
        self.assertNotIn(UID, self.manager.pending)
        self.assertNotIn(UID, self.manager.errors)

    async def test_readback_mismatch_remains_pending(self):
        self.http.get.return_value = Response({'source': 'wrong'})
        self.http.post.return_value = Response()
        with patch('custom_components.teddycloud_audiobooks.async_get_clientsession', return_value=self.http):
            await self.manager.reconcile(UID)
        self.assertIn(UID, self.manager.pending)


if __name__ == '__main__':
    unittest.main()
