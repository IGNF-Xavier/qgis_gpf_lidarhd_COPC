import pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class ProxyEnvironmentTests(unittest.TestCase):
 def test_proxy_is_forwarded_without_credentials_in_log(self):
  proxy=(ROOT/'pdal_support.py').read_text(encoding='utf-8');alg=(ROOT/'algorithms.py').read_text(encoding='utf-8');proc=(ROOT/'process_utils.py').read_text(encoding='utf-8')
  for key in ('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy'):self.assertIn(key,proxy)
  self.assertIn('build_pdal_environment(pdal)',alg)
  self.assertIn('env=pdal_env',alg)
  self.assertIn('env=None',proc)
  self.assertNotIn("proxy_info['password']",alg)
 def test_generated_out_dir_is_collapsed_to_qgis_temp(self):
  alg=(ROOT/'algorithms.py').read_text(encoding='utf-8')
  self.assertIn("os.path.basename(str(raw)).upper()=='OUT_DIR'",alg)
  self.assertIn('c.temporaryFolder()',alg)
 def test_same_environment_gets_pdal_pretest_and_pipeline(self):
  alg=(ROOT/'algorithms.py').read_text(encoding='utf-8')
  self.assertIn("run_command_timeout([pdal,'info','--metadata',effective_urls[0]]",alg)
  self.assertIn('env=pdal_env',alg)
  self.assertIn("run_pipeline([pdal,'pipeline',pipeline]",alg)
