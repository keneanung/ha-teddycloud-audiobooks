"""Native forms for connection settings, books, and ordered TAF segments."""
from copy import deepcopy
from pathlib import PurePosixPath
import re

import aiohttp
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from . import DOMAIN, validate_settings


def connection_schema(settings):
    return vol.Schema({
        vol.Required('url', default=settings.get('url', 'http://')): str,
        vol.Required('topic', default=settings.get('topic', 'teddyCloud')): str,
        vol.Required('boxes', default='\n'.join(settings.get('boxes', []))): selector.TextSelector({'multiline': True}),
        vol.Required('threshold_seconds', default=settings.get('threshold_seconds', 600)): selector.NumberSelector({'min': 1, 'max': 86400, 'step': 1, 'mode': 'box'}),
        vol.Optional('username', default=settings.get('username', '')): str,
        vol.Optional('password'): selector.TextSelector({'type': 'password'}),
    })


def connection_settings(settings, user_input):
    result = deepcopy(settings)
    result.update({k: user_input[k] for k in ('url', 'topic')})
    result['boxes'] = list(dict.fromkeys(b.strip() for b in user_input['boxes'].splitlines() if b.strip()))
    result['threshold_seconds'] = int(user_input['threshold_seconds'])
    if user_input.get('username'):
        result['username'] = user_input['username']
        if user_input.get('password'):
            result['password'] = user_input['password']
    else:
        result.pop('username', None)
        result.pop('password', None)
    # Reuse the runtime schema even before the first book is added.
    check = deepcopy(result)
    if not check.get('books'):
        check['books'] = {'0000000000000001': {'name': 'Validation', 'segments': [{'title':'Validation', 'source':'lib://validation.taf', 'audio_id':1}]}}
    validate_settings(check)
    if not result['topic'] or any(c in result['topic'] for c in '#+'):
        raise vol.Invalid('Invalid topic prefix')
    return result


async def library_files(hass, settings, folder):
    """Use the verified TeddyCloud file index and its actual TAF header IDs."""
    folder = folder.strip().removeprefix('lib://').strip('/')
    if '..' in PurePosixPath(folder).parts:
        raise ValueError('Invalid library folder')
    auth = aiohttp.BasicAuth(settings['username'], settings.get('password', '')) if settings.get('username') else None
    session = async_get_clientsession(hass)
    async with session.get(settings['url'].rstrip('/') + '/api/fileIndex',
                           params={'special':'library', 'path':'/' + folder},
                           auth=auth, timeout=aiohttp.ClientTimeout(total=10)) as response:
        response.raise_for_status()
        data = await response.json(content_type=None)
    files = {}
    for item in data['files']:
        name, desc = item.get('name', ''), item.get('desc', '')
        if item.get('isDirectory') or not name.lower().endswith('.taf') or not desc.startswith('TAF:'):
            continue
        if '/' in name or '\\' in name:
            continue
        source = 'lib://' + (folder + '/' if folder else '') + name
        files[source] = {'title': name[:-4].replace('_', ' '), 'source':source, 'audio_id':int(desc.split(':')[1], 16)}
    return dict(sorted(files.items()))


class Editor:
    """Shared catalog forms; all edits stay staged until the final save."""
    async def async_step_folder(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                self.files = await library_files(self.hass, self.settings, user_input['folder'])
                if not self.files:
                    errors['base'] = 'no_tafs'
                else:
                    return await self.async_step_files()
            except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError):
                errors['base'] = 'cannot_connect'
        book = self.settings['books'].get(self.uid, {})
        segments = book.get('segments', [])
        folder = str(PurePosixPath(segments[0]['source'][6:]).parent) if segments else ''
        if folder == '.':
            folder = ''
        return self.async_show_form(step_id='folder', data_schema=vol.Schema({vol.Required('folder', default=folder): str}), errors=errors)

    async def async_step_files(self, user_input=None):
        if user_input is not None and user_input.get('files'):
            selected = user_input['files']
            if not all(source in self.files for source in selected):
                return self.async_abort(reason='invalid_config')
            old = {s['source']:s for s in self.settings['books'][self.uid].get('segments', [])}
            self.settings['books'][self.uid]['segments'] = [
                {**self.files[source], 'title':old.get(source, {}).get('title', self.files[source]['title'])}
                for source in sorted(selected)]
            return await self.finish()
        old_sources = [s['source'] for s in self.settings['books'][self.uid].get('segments', [])]
        default = [s for s in old_sources if s in self.files] or list(self.files)
        return self.async_show_form(step_id='files', data_schema=vol.Schema({
            vol.Required('files', default=default): selector.SelectSelector({
                'options':[{'value':source, 'label':PurePosixPath(source).name} for source in self.files],
                'multiple':True, 'mode':'list'})}), errors={'base':'select_files'} if user_input is not None else {})

    async def async_step_book(self, user_input=None):
        errors = {}
        if user_input is not None:
            uid = user_input['uid'].replace(':', '').replace(' ', '').upper()
            if not re.fullmatch('[0-9A-F]{16}', uid):
                errors['uid'] = 'invalid_uid'
            elif uid in self.settings['books']:
                errors['uid'] = 'duplicate_uid'
            elif not user_input['name'].strip():
                errors['name'] = 'invalid_config'
            else:
                self.uid = uid
                self.settings['books'][uid] = {'name':user_input['name'].strip(), 'segments':[]}
                return await self.async_step_folder()
        return self.async_show_form(step_id='book', data_schema=vol.Schema({vol.Required('name'):str, vol.Required('uid'):str}), errors=errors)


class ConfigFlow(Editor, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.settings = {'books':{}}

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors = {}
        if user_input is not None:
            try:
                self.settings = connection_settings(self.settings, user_input)
                await library_files(self.hass, self.settings, '')
                return await self.async_step_book()
            except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError, vol.Invalid):
                errors['base'] = 'cannot_connect'
        return self.async_show_form(step_id='user', data_schema=connection_schema(self.settings), errors=errors)

    async def async_step_import(self, user_input):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        try:
            settings = validate_settings(deepcopy(user_input))
        except vol.Invalid:
            return self.async_abort(reason='invalid_config')
        return self.async_create_entry(title='TeddyCloud Audiobooks', data=settings)

    async def finish(self):
        try:
            settings = validate_settings(self.settings)
        except vol.Invalid:
            return self.async_abort(reason='invalid_config')
        return self.async_create_entry(title='TeddyCloud Audiobooks', data=settings)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow()


class OptionsFlow(Editor, config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        self.original = deepcopy(dict(self.config_entry.options or self.config_entry.data))
        self.settings = deepcopy(self.original)
        self.settings['reset_progress'] = []
        return self.async_show_menu(step_id='init', menu_options=['connection','edit_book','add_book','remove_book'])

    async def async_step_connection(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                self.settings = connection_settings(self.settings, user_input)
                await library_files(self.hass, self.settings, '')
                return await self.finish()
            except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError, vol.Invalid):
                errors['base'] = 'cannot_connect'
        return self.async_show_form(step_id='connection', data_schema=connection_schema(self.settings), errors=errors)

    async def async_step_add_book(self, user_input=None):
        return await self.async_step_book(user_input)

    def book_schema(self):
        return vol.Schema({vol.Required('uid'):selector.SelectSelector({'options':[
            {'value':uid, 'label':f'{book["name"]} ({uid})'} for uid,book in self.settings['books'].items()]})})

    async def async_step_edit_book(self, user_input=None):
        if user_input is not None:
            if user_input['uid'] not in self.settings['books']:
                return self.async_abort(reason='invalid_config')
            self.uid = user_input['uid']
            return await self.async_step_book_menu()
        return self.async_show_form(step_id='edit_book', data_schema=self.book_schema())

    async def async_step_book_menu(self, user_input=None):
        return self.async_show_menu(step_id='book_menu', menu_options=['rename','folder','segment'])

    async def async_step_rename(self, user_input=None):
        if user_input is not None:
            if user_input['name'].strip():
                self.settings['books'][self.uid]['name'] = user_input['name'].strip()
                return await self.finish()
        return self.async_show_form(step_id='rename', data_schema=vol.Schema({
            vol.Required('name', default=self.settings['books'][self.uid]['name']):str}))

    async def async_step_segment(self, user_input=None):
        segments = self.settings['books'][self.uid]['segments']
        if user_input is not None:
            self.segment_index = int(user_input['segment'])
            if not 0 <= self.segment_index < len(segments):
                return self.async_abort(reason='invalid_config')
            return await self.async_step_segment_edit()
        return self.async_show_form(step_id='segment', data_schema=vol.Schema({
            vol.Required('segment'):selector.SelectSelector({'options':[
                {'value':str(i), 'label':f'{i+1}: {s["title"]}'} for i,s in enumerate(segments)]})}))

    async def async_step_segment_edit(self, user_input=None):
        segments = self.settings['books'][self.uid]['segments']
        segment = segments[self.segment_index]
        errors = {}
        if user_input is not None:
            if user_input.get('remove') and len(segments) == 1:
                errors['base'] = 'last_segment'
            elif not user_input['title'].strip():
                errors['title'] = 'invalid_config'
            else:
                segment = segments.pop(self.segment_index)
                if not user_input.get('remove'):
                    segment['title'] = user_input['title'].strip()
                    position = max(0, min(int(user_input['position'])-1, len(segments)))
                    segments.insert(position, segment)
                return await self.finish()
        return self.async_show_form(step_id='segment_edit', data_schema=vol.Schema({
            vol.Required('title', default=segment['title']):str,
            vol.Required('position', default=self.segment_index+1):selector.NumberSelector({'min':1, 'max':len(segments), 'step':1, 'mode':'box'}),
            vol.Optional('remove', default=False):bool}), errors=errors)

    async def async_step_remove_book(self, user_input=None):
        if len(self.settings['books']) == 1:
            return self.async_abort(reason='last_book')
        if user_input is not None:
            uid = user_input['uid']
            if uid not in self.settings['books']:
                return self.async_abort(reason='invalid_config')
            self.settings['books'].pop(uid)
            return await self.finish()
        return self.async_show_form(step_id='remove_book', data_schema=self.book_schema())

    async def finish(self):
        try:
            self.settings = validate_settings(self.settings)
        except vol.Invalid:
            return self.async_abort(reason='invalid_config')
        removed = []
        for uid, book in self.original['books'].items():
            if uid not in self.settings['books']:
                continue
            new = {(s['source'],s['audio_id']) for s in self.settings['books'][uid]['segments']}
            if any((s['source'],s['audio_id']) not in new for s in book['segments']):
                removed.append(uid)
        self.settings['reset_progress'] = removed
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None):
        reset = self.settings['reset_progress']
        if user_input is not None and (not reset or user_input.get('allow_reset')):
            return self.async_create_entry(title='', data=self.settings)
        schema = vol.Schema({vol.Required('allow_reset', default=False):bool}) if reset else vol.Schema({})
        return self.async_show_form(step_id='confirm', data_schema=schema,
            description_placeholders={'books':str(len(self.settings['books'])),
                                      'segments':str(sum(len(b['segments']) for b in self.settings['books'].values())),
                                      'resets':str(len(reset))},
            errors={'base':'confirm_reset'} if user_input is not None else {})
