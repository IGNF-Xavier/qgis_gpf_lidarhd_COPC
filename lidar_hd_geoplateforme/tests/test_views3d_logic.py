import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('views3d_logic', ROOT / 'views3d_logic.py')
v = importlib.util.module_from_spec(spec)
sys.modules['views3d_logic'] = v
spec.loader.exec_module(v)


class FilterTests(unittest.TestCase):
    def test_clauses(self):
        self.assertEqual(v.filter_clause('Classification', '=', 2), 'Classification = 2')
        self.assertEqual(v.filter_clause('Z', 'entre', 125, 120), '(Z >= 120 AND Z <= 125)')
        self.assertEqual(v.filter_clause('Intensity', '≥', 2000), 'Intensity >= 2000')
        self.assertEqual(v.filter_clause('ReturnNumber', '≠', 1), 'ReturnNumber <> 1')
        self.assertEqual(v.filter_clause('', '=', 1), '')

    def test_combined_subset_string(self):
        s = v.ViewSettings(filter_attribute='Z', filter_operator='entre', filter_value=120, filter_value2=125, hidden_values={1, 7})
        self.assertEqual(s.subset_string(), '(Z >= 120 AND Z <= 125) AND Classification <> 1 AND Classification <> 7')
        s.clear_filter()
        self.assertEqual(s.subset_string(), 'Classification <> 1 AND Classification <> 7')
        self.assertEqual(v.ViewSettings().subset_string(), '')


class SettingsTests(unittest.TestCase):
    def test_views_are_independent_and_limited(self):
        a, b = v.ViewSettings(index=1), v.ViewSettings(index=2)
        a.hidden_values.add(5)
        a.point_size = 4
        self.assertEqual(b.hidden_values, set())
        self.assertEqual(b.point_size, 2.0)
        self.assertEqual(v.MAX_VIEWS, 5)

    def test_quality_budgets(self):
        self.assertEqual([v.ViewSettings(quality=q).budget() for q in ('Fluide', 'Équilibrée', 'Fine')], [1_000_000, 2_000_000, 5_000_000])

    def test_changing_field_resets_auto_ranges_and_hidden_values(self):
        s = v.ViewSettings(display_range=(2, 6), saturation=(0, 30), hidden_values={1})
        s.set_color_attribute('Intensity')
        self.assertIsNone(s.display_range)
        self.assertIsNone(s.saturation)
        self.assertEqual(s.hidden_values, set())
        self.assertEqual(s.visible_attribute, 'Intensity')

    def test_range_validity(self):
        self.assertTrue(v.valid_range(0, 1))
        self.assertFalse(v.valid_range(2, 2))
        self.assertFalse(v.valid_range(None, 1))


class HistoSyncTests(unittest.TestCase):
    def test_histogram(self):
        edges, counts = v.histogram([0, 1, 1, 2, 10], bins=5)
        self.assertEqual(sum(counts), 5)
        self.assertEqual(len(edges), 6)
        self.assertEqual(counts[-1], 1)

    def test_percentages(self):
        self.assertEqual(v.class_percentages({2: 75, 5: 25}), {2: 75.0, 5: 25.0})

    def test_sync_modes(self):
        src = dict(x=1, y=2, z=3, distance=100, pitch=40, heading=10)
        tgt = dict(x=0, y=0, z=0, distance=5, pitch=70, heading=90)
        self.assertEqual(v.follow_pose(src, tgt, 'Complet'), src)
        r = v.follow_pose(src, tgt, 'Position seule')
        self.assertEqual((r['x'], r['distance'], r['pitch'], r['heading']), (1, 100, 70, 90))

    def test_poses_close(self):
        a = dict(x=1.0, distance=10.0)
        self.assertTrue(v.poses_close(a, dict(a)))
        self.assertFalse(v.poses_close(a, dict(x=1.0, distance=11.0)))


if __name__ == '__main__':
    unittest.main()
