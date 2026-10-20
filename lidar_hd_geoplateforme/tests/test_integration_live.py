"""Test d'intégration réel (réseau Géoplateforme + pdal.exe) : readers.copc distants → COPC local valide.

Désactivé par défaut. Activer avec LIDARHD_LIVE=1 ; PDAL via LIDARHD_PDAL (sinon `pdal` du PATH).
Reproduit l'environnement du plugin (bundle CA via ARBITER_CA_INFO, proxy via HTTPS_PROXY si défini).
"""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pdal_support', ROOT / 'pdal_support.py')
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)

PDAL = os.environ.get('LIDARHD_PDAL') or shutil.which('pdal')
BASE = 'https://data.geopf.fr/telechargement/download/LiDARHD-NUALID/NUALHD_1-0__LAZ_LAMB93_KE_2025-06-06/LHD_FXX_%s_PTS_LAMB93_IGN69.copc.laz'


@unittest.skipUnless(os.environ.get('LIDARHD_LIVE') == '1' and PDAL, 'LIDARHD_LIVE=1 et pdal requis')
class LiveExtractionTests(unittest.TestCase):
    def run_pdal(self, args, env):
        return subprocess.run([PDAL] + args, capture_output=True, text=True, timeout=240, env=env)

    def test_two_tiles_chunk_urls_to_local_valid_copc(self):
        env = os.environ.copy()
        bundle, _ = ps.find_ca_bundle(env, PDAL)
        ps.apply_network_environment(env, None, None, bundle)
        bounds = ps.bounds_string(652950, 653050, 6859400, 6859500)
        urls = [ps.chunk_url(BASE % '0652_6860'), ps.chunk_url(BASE % '0653_6860')]
        with tempfile.TemporaryDirectory() as folder:
            out = os.path.join(folder, 'live.copc.laz')
            pipeline = os.path.join(folder, 'p.json')
            stages = ps.pipeline_stages([(u, bounds) for u in urls], out, 0.5)
            with open(pipeline, 'w', encoding='utf-8') as stream:
                json.dump({'pipeline': stages}, stream)
            result = self.run_pdal(['pipeline', pipeline], env)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(os.path.isfile(out))
            info = self.run_pdal(['info', '--summary', out], env)
            count = json.loads(info.stdout)['summary']['num_points']
            self.assertGreater(count, 100000)  # deux dalles ; ~75 000 si filters.merge était omis
            header = open(out, 'rb').read(4)
            self.assertEqual(header, b'LASF')


if __name__ == '__main__':
    unittest.main()
