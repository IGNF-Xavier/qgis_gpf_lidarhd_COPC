import pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class IndeterminateThenExtractionTests(unittest.TestCase):
 def test_timeout_is_not_a_preflight_hole(self):
  s=(ROOT/'algorithms.py').read_text(encoding='utf-8');a=s.index('def _diagnose_sources');b=s.index('def processAlgorithm',a);block=s[a:b]
  self.assertIn("source_result['status']='indeterminate'",block)
  self.assertIn('Validation reportée à l’extraction réelle',block)
  self.assertIn('conservée pour l’extraction complète',block)
 def test_real_extraction_remains_strict(self):
  s=(ROOT/'algorithms.py').read_text(encoding='utf-8')
  self.assertIn('TROU DE COUVERTURE CONFIRMÉ PAR L’EXTRACTION RÉELLE',s)
  self.assertIn('Aucun COPC incomplet ne sera produit.',s)
 def test_stall_does_not_kill_before_output_exists(self):
  s=(ROOT/'process_utils.py').read_text(encoding='utf-8')
  self.assertIn('stall_seconds and exists and now-last_growth>=stall_seconds',s)
