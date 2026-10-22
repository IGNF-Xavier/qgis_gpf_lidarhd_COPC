"""Garde-fous statiques du panneau 3D : comportements qui ne se testent pas sans QGIS graphique."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class PanelStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = (ROOT / 'views3d.py').read_text(encoding='utf-8')
        cls.algo = (ROOT / 'algorithms.py').read_text(encoding='utf-8')

    def test_scenes_are_restored_when_2d_layers_change(self):
        self.assertIn('mapCanvas().layersChanged.connect(self._reassert_soon)', self.panel)
        self.assertIn('def _reassert_layers', self.panel)
        self.assertIn('def refresh_views', self.panel)

    def test_editions_are_listed_and_passed_to_the_algorithm(self):
        for text in ('def search_editions', "'EDITION_MODE'", "'EDITIONS': edition", 'Chercher les éditions'):
            self.assertIn(text, self.panel)

    def test_extracted_copc_gets_explicit_2d_renderer(self):
        self.assertIn('apply_default_renderer(layer)', self.algo)
        self.assertIn("'copc'", self.algo)

    def test_measure_dialog_is_never_touched(self):
        self.assertIn("className() == 'QDialog'", self.panel)

    def test_unique_canvas_names(self):
        self.assertIn('#{self._counter}', self.panel)


if __name__ == '__main__':
    unittest.main()
