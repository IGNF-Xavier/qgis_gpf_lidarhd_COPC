import pathlib
import unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class StrictCoverageHoleTests(unittest.TestCase):
    def test_strict_hole_is_detailed_and_aborts(self):
        source=(ROOT/'algorithms.py').read_text(encoding='utf-8')
        start=source.index('def _diagnose_sources');end=source.index('def processAlgorithm',start);block=source[start:end]
        for text in ('TROU DE COUVERTURE CONFIRMÉ AVANT EXTRACTION — MODE STRICT','Dalle :','métadonnée :','catalogue :','ressource :','Aucun COPC incomplet ne sera produit.'):
            self.assertIn(text,block)
        self.assertIn('raise QgsProcessingException',block)
