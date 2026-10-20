import pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class Tests(unittest.TestCase):
 def test_information_panel(self):
  s=(ROOT/'algorithms.py').read_text(encoding='utf-8')
  for x in ('Emprise et SCR','Éditions','Résolution','0,50 m','Accès aux COPC','Diagnostic individuel','Seuil sans croissance','Sorties locales','Mode strict'):self.assertIn(x,s)
 def test_preflight(self):
  a=(ROOT/'algorithms.py').read_text(encoding='utf-8');n=(ROOT/'network.py').read_text(encoding='utf-8')
  self.assertIn('def _select_effective_urls',a);self.assertIn('effective_urls,range_checks=self._select_effective_urls',a)
  self.assertIn('attempt_plan(effective_urls',a);self.assertIn("response['body'][:4]==b'LASF'",n)
 def test_diagnostic_default_false(self):
  self.assertIn("QgsProcessingParameterBoolean(self.DIAG,'Diagnostiquer chaque source avant la fusion',False)",(ROOT/'algorithms.py').read_text(encoding='utf-8'))
