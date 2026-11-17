"""Native configuration forms and safe progress migration, using HA's runtime."""
import importlib.util
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import test_manager as manager_tests
CFG, UID = manager_tests.CFG, manager_tests.UID

if importlib.util.find_spec('homeassistant') is not None:
    from custom_components.teddycloud_audiobooks.config_flow import (
        ConfigFlow, OptionsFlow, connection_settings, library_files)
    import voluptuous as vol
else:
    ConfigFlow = None


@unittest.skipIf(ConfigFlow is None, 'Requires the Home Assistant runtime')
class Forms(unittest.IsolatedAsyncioTestCase):
    def setup_flow(self):
        flow = ConfigFlow()
        flow.hass = SimpleNamespace()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = Mock()
        return flow

    async def options_flow(self):
        entry = SimpleNamespace(data=deepcopy(CFG), options={})
        flow = OptionsFlow()
        flow.handler = 'entry'
        flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_known_entry=lambda _:entry))
        await flow.async_step_init()
        return flow, entry

    async def test_import_preserves_catalog(self):
        result = await self.setup_flow().async_step_import(CFG)
        self.assertEqual(result['type'], 'create_entry')
        self.assertEqual(result['data']['books'], CFG['books'])

    async def test_setup_wizard_uses_discovered_ids(self):
        flow = self.setup_flow()
        form = await flow.async_step_user()
        self.assertEqual(form['step_id'], 'user')
        with patch('custom_components.teddycloud_audiobooks.config_flow.library_files', new=AsyncMock(return_value={'lib://one.taf':CFG['books'][UID]['segments'][0]})):
            result = await flow.async_step_user({'url':CFG['url'],'topic':'teddyCloud','boxes':'48CA4351C694','threshold_seconds':600})
            self.assertEqual(result['step_id'], 'book')
            result = await flow.async_step_book({'name':'Test', 'uid':'e0:04:03:50:0e:cc:b5:9f'})
            self.assertEqual(result['step_id'], 'folder')
            result = await flow.async_step_folder({'folder':'Books'})
            self.assertEqual(result['step_id'], 'files')
            result = await flow.async_step_files({'files':['lib://one.taf']})
        self.assertEqual(result['type'], 'create_entry')
        self.assertEqual(result['data']['books'][UID]['segments'][0]['audio_id'], 11)

    async def test_box_list_and_credentials(self):
        cfg = deepcopy(CFG)
        cfg.update(username='user',password='private')
        inp = {'url':CFG['url'],'topic':'teddyCloud','boxes':'box1\nbox2\nbox1','threshold_seconds':600,'username':'user'}
        result = connection_settings(cfg, inp)
        self.assertEqual(result['boxes'], ['box1','box2'])
        self.assertEqual(result['password'], 'private')
        inp['username'] = ''
        self.assertNotIn('password', connection_settings(cfg, inp))
        inp['topic'] = 'bad/#'
        with self.assertRaises(vol.Invalid):
            connection_settings(cfg, inp)

    async def test_segment_move_is_staged_until_confirm(self):
        flow, entry = await self.options_flow()
        flow.uid, flow.segment_index = UID, 0
        result = await flow.async_step_segment_edit({'title':'Renamed', 'position':2, 'remove':False})
        self.assertEqual(result['step_id'], 'confirm')
        self.assertEqual(entry.data, CFG)
        result = await flow.async_step_confirm({})
        self.assertEqual(result['data']['books'][UID]['segments'][1]['title'], 'Renamed')
        self.assertEqual(result['data']['reset_progress'], [])

    async def test_removal_requires_explicit_reset_confirmation(self):
        flow, _ = await self.options_flow()
        flow.uid, flow.segment_index = UID, 0
        await flow.async_step_segment_edit({'title':'One', 'position':1, 'remove':True})
        result = await flow.async_step_confirm({'allow_reset':False})
        self.assertEqual(result['errors']['base'], 'confirm_reset')
        result = await flow.async_step_confirm({'allow_reset':True})
        self.assertEqual(result['data']['reset_progress'], [UID])

    async def test_last_book_and_segment_are_protected(self):
        flow, _ = await self.options_flow()
        self.assertEqual((await flow.async_step_remove_book())['reason'], 'last_book')
        flow.uid, flow.segment_index = UID, 0
        flow.settings['books'][UID]['segments'] = flow.settings['books'][UID]['segments'][:1]
        result = await flow.async_step_segment_edit({'title':'One', 'position':1, 'remove':True})
        self.assertEqual(result['errors']['base'], 'last_segment')

    async def test_library_reads_actual_header_ids(self):
        from test_manager import Response
        http = Mock()
        http.get.return_value = Response({'files':[
            {'name':'02.taf','desc':'TAF:0000000C:hash:123:1','isDirectory':False},
            {'name':'song.m4b','desc':'','isDirectory':False},
            {'name':'invalid.taf','desc':'','isDirectory':False}]})
        with patch('custom_components.teddycloud_audiobooks.config_flow.async_get_clientsession', return_value=http):
            result = await library_files(None, CFG, 'Books')
        self.assertEqual(result['lib://Books/02.taf']['audio_id'], 12)
        self.assertEqual(len(result), 1)
        self.assertEqual(http.get.call_args.kwargs['params'], {'special':'library','path':'/Books'})


@unittest.skipIf(ConfigFlow is None, 'Requires the Home Assistant runtime')
class CatalogMigration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await manager_tests.Persistence.asyncSetUp(self)

    async def test_reorder_follows_assigned_segment(self):
        self.manager.store.async_load.return_value = {'indices':{UID:1}, 'catalog':{UID:[['lib://one.taf',11],['lib://two.taf',12]]}}
        self.manager.cfg['books'][UID]['segments'].reverse()
        await self.manager.load()
        self.assertEqual(self.manager.engine.indices[UID], 0)

    async def test_reset_is_explicit_and_idempotent(self):
        self.manager.store.async_load.return_value = {'indices':{UID:0}, 'catalog':{UID:[['lib://removed.taf',99]]}}
        self.manager.cfg['reset_progress'] = [UID]
        await self.manager.load()
        self.assertEqual(self.manager.engine.indices[UID], 0)
        self.manager.store.async_load.return_value = {'indices':{UID:1}, 'catalog':self.manager.catalog}
        await self.manager.load()
        self.assertEqual(self.manager.engine.indices[UID], 1)

    async def test_unloaded_timer_does_nothing(self):
        self.manager.running = False
        await self.manager.tick(None)
        self.manager.reconcile.assert_not_awaited()

    async def test_unloaded_manual_requests_do_not_write(self):
        from homeassistant.exceptions import HomeAssistantError
        self.manager.running = False
        with self.assertRaises(HomeAssistantError):
            await self.manager.choose_segment(1)
        self.manager.reconcile.assert_not_awaited()

    async def test_shutdown_does_not_remove_its_one_time_listener_twice(self):
        listener = Mock()
        self.manager.stop_unsub = listener
        self.manager.stop(SimpleNamespace(event_type='homeassistant_stop'))
        listener.assert_not_called()
        self.assertFalse(self.manager.running)

    async def test_unload_removes_shutdown_listener(self):
        listener = Mock()
        self.manager.stop_unsub = listener
        self.manager.stop(None)
        listener.assert_called_once()
        self.assertIsNone(self.manager.stop_unsub)


@unittest.skipIf(ConfigFlow is None, 'Requires the Home Assistant runtime')
class Lifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_entry_setup_and_unload(self):
        import asyncio
        from custom_components.teddycloud_audiobooks import async_setup_entry, async_unload_entry, DOMAIN
        manager = SimpleNamespace(load=AsyncMock(), start=AsyncMock(), stop=Mock(), lock=asyncio.Lock())
        entries = SimpleNamespace(async_forward_entry_setups=AsyncMock(), async_unload_platforms=AsyncMock(return_value=True))
        hass = SimpleNamespace(data={}, config_entries=entries)
        entry = SimpleNamespace(data=CFG, options={}, async_on_unload=Mock(), add_update_listener=Mock(return_value=lambda:None))
        with patch('custom_components.teddycloud_audiobooks.Manager', return_value=manager):
            self.assertTrue(await async_setup_entry(hass, entry))
        self.assertIs(hass.data[DOMAIN], manager)
        manager.load.assert_awaited_once()
        manager.start.assert_awaited_once()
        self.assertTrue(await async_unload_entry(hass, entry))
        manager.stop.assert_called_once_with(None)
        self.assertNotIn(DOMAIN, hass.data)
