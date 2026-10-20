import pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class LocalOutputAndRangeTests(unittest.TestCase):
 def test_writer_is_local_absolute(self):
  s=(ROOT/'algorithms.py').read_text(encoding='utf-8')
  self.assertIn('folder=c.temporaryFolder() if not raw or is_generated_out_dir else raw',s)
  self.assertIn('folder=os.path.abspath(os.path.normpath(folder))',s)
  self.assertIn("output=os.path.abspath(os.path.join(folder",s)
  self.assertIn("stages=pipeline_stages(readers,output,resolution)",s)
  self.assertIn('COPC local de sortie : ',s)
 def test_range_probe_is_systematic_and_strict(self):
  s=(ROOT/'network.py').read_text(encoding='utf-8')
  self.assertIn("'bytes=0-1023'",s);self.assertIn("'bytes=1024-2047'",s)
  self.assertIn("response['status']==206",s)
  self.assertIn("content_range.lower().startswith",s)
  self.assertIn("'range_compatible':first['compatible'] and second['compatible']",s)
