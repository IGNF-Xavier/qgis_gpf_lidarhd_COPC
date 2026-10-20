import pathlib, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class DefaultDiagnosticTest(unittest.TestCase):
 def test_diagnostic_is_disabled_by_default(self):
  source=(ROOT/'algorithms.py').read_text(encoding='utf-8')
  self.assertIn("QgsProcessingParameterBoolean(self.DIAG,'Diagnostiquer chaque source avant la fusion',False)",source)
  self.assertNotIn("QgsProcessingParameterBoolean(self.DIAG,'Diagnostiquer chaque source avant la fusion',True)",source)
