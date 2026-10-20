import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]

class Qgis340HeaderCompatibilityTests(unittest.TestCase):
    def test_qgis340_header_api_is_used(self):
        source=(ROOT/'network.py').read_text(encoding='utf-8')
        self.assertNotIn('rawHeaderPairs',source)
        self.assertIn('reply.rawHeaderList()',source)
        self.assertIn('reply.rawHeader(key)',source)
        self.assertIn("name=bytes(key).decode('latin1').lower()",source)
        self.assertIn("bytes(reply.rawHeader(key)).decode('latin1')",source)
