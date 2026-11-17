import importlib.util
from pathlib import Path
import sys
import unittest

path = Path(__file__).parents[1] / 'custom_components/teddycloud_audiobooks/engine.py'
spec = importlib.util.spec_from_file_location('audiobook_engine', path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
UID = 'E00403500ECCB59F'
OTHER = 'E004035000000001'
BOOK = {'name': 'Test', 'segments': [{'audio_id': 11}, {'audio_id': 12}, {'audio_id': 13}]}


class Sessions(unittest.TestCase):
    def setUp(self):
        self.e = module.Engine({UID: BOOK, OTHER: BOOK}, 10)

    def start(self, box='a', uid=UID, audio='11', at=0):
        for kind, payload in [('TagValid', '-' + uid), ('TagValid', uid),
                              ('Playback', 'ON'), ('ContentAudioId', audio)]:
            self.e.event(box, kind, payload, at)

    def test_threshold_duplicate_final(self):
        self.start()
        self.assertEqual(self.e.due(9.99), [])
        self.e.event('a', 'TagValid', UID, 9)
        self.e.event('a', 'Playback', 'ON', 9)
        self.assertEqual(self.e.due(10), [UID])
        self.assertEqual(self.e.due(100), [])
        self.start(audio='12', at=100)
        self.assertEqual(self.e.due(110), [UID])
        self.start(audio='13', at=120)
        self.assertEqual(self.e.due(130), [])
        self.assertEqual(self.e.indices[UID], 2)

    def test_early_removal_and_stop(self):
        for kind, payload in [('TagValid', '-' + UID), ('TagValid', ''), ('Playback', 'OFF')]:
            self.start()
            self.e.event('a', kind, payload, 9)
            self.assertEqual(self.e.due(11), [])

    def test_cache_mismatch_does_not_advance(self):
        self.e.manual(UID, 1)
        self.start(audio='11')
        self.assertEqual(self.e.due(100), [])

    def test_manual_invalidates_old_timer_even_same_index(self):
        self.start()
        self.e.manual(UID, 0)
        self.assertEqual(self.e.due(100), [])

    def test_two_boxes_one_tag_and_two_books(self):
        self.start('a')
        self.start('b')
        self.start('c', OTHER)
        self.assertEqual(set(self.e.due(10)), {UID, OTHER})
        self.assertEqual(self.e.indices[UID], 1)

    def test_reconnect_requires_boundary(self):
        self.start()
        self.e.reset()
        for kind, payload in [('TagValid', UID), ('Playback', 'ON'), ('ContentAudioId', '11')]:
            self.e.event('a', kind, payload, 5)
        self.assertEqual(self.e.due(100), [])
        self.start(at=100)
        self.assertEqual(self.e.due(110), [UID])

    def test_unrelated_tag_and_event_order(self):
        self.start()
        self.e.event('a', 'TagValid', 'UNMANAGED', 5)
        self.assertEqual(self.e.due(100), [])
        self.e.event('a', 'TagValid', UID, 100)
        self.e.event('a', 'ContentAudioId', '11', 100)
        self.e.event('a', 'Playback', 'ON', 100)
        self.assertEqual(self.e.due(110), [UID])

    def test_restored_indices(self):
        restored = module.Engine({UID: BOOK}, 10, {UID: 1})
        self.assertEqual(restored.indices[UID], 1)
        self.assertEqual(restored.sessions, {})


if __name__ == '__main__':
    unittest.main()
