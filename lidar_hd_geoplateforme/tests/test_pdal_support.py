"""Tests comportementaux (sans QGIS) de pdal_support : stratégies, repli, environnement, pipeline, journaux."""
import importlib.util
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pdal_support', ROOT / 'pdal_support.py')
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)

URL = 'https://data.geopf.fr/telechargement/download/LiDARHD-NUALID/X/LHD_FXX_0653_6860_PTS_LAMB93_IGN69.copc.laz'


class StrategyTests(unittest.TestCase):
    def test_chunk_is_primary_original_is_fallback(self):
        sets = ps.url_sets([URL], 0)
        self.assertEqual([label for label, _ in sets], ['URL chunk', 'URL WFS originale'])
        self.assertIn('/chunk/telechargement/download/', sets[0][1][0])
        self.assertEqual(sets[1][1], [URL])

    def test_forced_modes(self):
        self.assertEqual([l for l, _ in ps.url_sets([URL], 1)], ['URL WFS originale'])
        self.assertEqual([l for l, _ in ps.url_sets([URL], 2)], ['URL chunk'])

    def test_chunk_is_idempotent(self):
        self.assertEqual(ps.chunk_url(ps.chunk_url(URL)), ps.chunk_url(URL))

    def test_failed_chunk_attempt_is_followed_by_original_pipeline(self):
        strategies = ps.url_sets([URL], 0)
        plan = ps.attempt_plan(strategies[0][1], strategies)
        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[1][1], [URL])

    def test_no_duplicate_attempt_when_preflight_already_chose_original(self):
        strategies = ps.url_sets([URL], 0)
        plan = ps.attempt_plan([URL], strategies)
        self.assertEqual([urls for _, urls in plan], [[URL], [ps.chunk_url(URL)]])


class PipelineTests(unittest.TestCase):
    def test_pipeline_matches_tutorial_with_merge_and_absolute_writer(self):
        stages = ps.pipeline_stages([('u1', ps.bounds_string(1, 2, 3, 4)), ('u2', ps.bounds_string(1, 2, 3, 4))], 'out.copc.laz', 0.5)
        self.assertEqual([s['type'] for s in stages], ['readers.copc', 'readers.copc', 'filters.merge', 'writers.copc'])
        self.assertEqual(stages[0]['bounds'], '([1,2],[3,4])')
        self.assertEqual(stages[0]['resolution'], 0.5)
        self.assertEqual(stages[-1]['forward'], 'all')
        self.assertTrue(pathlib.Path(stages[-1]['filename']).is_absolute())
        json.dumps(stages)

    def test_native_resolution_omits_key_and_single_reader_has_no_merge(self):
        stages = ps.pipeline_stages([('u1', '([0,1],[0,1])')], 'o.laz', 0)
        self.assertNotIn('resolution', stages[0])
        self.assertEqual([s['type'] for s in stages], ['readers.copc', 'writers.copc'])


class EnvironmentTests(unittest.TestCase):
    def test_ca_bundle_found_from_env_then_next_to_pdal(self):
        exists = lambda p: p in ('/a/bundle.pem', '/q/bin/curl-ca-bundle.crt')
        self.assertEqual(ps.find_ca_bundle({'SSL_CERT_FILE': '/a/bundle.pem'}, None, exists), ('/a/bundle.pem', 'SSL_CERT_FILE'))
        path, source = ps.find_ca_bundle({}, '/q/bin/pdal.exe', lambda p: p.replace(chr(92), '/').endswith('/q/bin/curl-ca-bundle.crt'))
        self.assertTrue(path.replace(chr(92), '/').endswith('curl-ca-bundle.crt'))
        self.assertEqual(ps.find_ca_bundle({}, None, lambda p: False), (None, None))

    def test_environment_gets_proxy_and_arbiter_ca(self):
        env = {}
        ps.apply_network_environment(env, 'http://proxy:3128', 'localhost', '/ca.pem')
        for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'NO_PROXY', 'ARBITER_CA_INFO', 'SSL_CERT_FILE'):
            self.assertIn(key, env)
        self.assertEqual(env['ARBITER_CA_INFO'], '/ca.pem')


class LogTests(unittest.TestCase):
    def test_tls_failure_is_explained(self):
        log = "*   no trust anchors configured\nCurl failure: SSL peer certificate or SSH remote key was not OK"
        self.assertTrue(any('ARBITER_CA_INFO' in h for h in ps.classify_pdal_log(log)))
        self.assertTrue(ps.key_network_lines(log))

    def test_progress_never_calls_missing_file_a_stall(self):
        msg = ps.progress_message(15, False, 0, 0, 15)
        self.assertIn('non encore créé', msg)
        self.assertNotIn('bloqu', msg)
        msg = ps.progress_message(75, True, 124 * 1048576, 100 * 1048576, 0)
        self.assertIn('COPC local : 124.0 Mio', msg)
        self.assertIn('croissance depuis le dernier contrôle : 24.0 Mio', msg)


if __name__ == '__main__':
    unittest.main()
