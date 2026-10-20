import ast,pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class LightweightDiagnosticTests(unittest.TestCase):
 def test_diagnostic_uses_pdal_info_not_probe_copc(self):
  source=(ROOT/'algorithms.py').read_text(encoding='utf-8')
  start=source.index('def _diagnose_sources');end=source.index('def processAlgorithm',start);block=source[start:end]
  self.assertIn("[pdal,'info','--metadata',url]",block)
  self.assertIn('run_command_timeout',block)
  self.assertNotIn("'_probe_",block)
  self.assertNotIn('run_pipeline',block)
 def test_interface_file_is_unchanged_by_046(self):
  source=(ROOT/'algorithms.py').read_text(encoding='utf-8')
  for label in ('Emprise','Éditions à produire','Éditions sélectionnées','Dossier de destination','Préfixe des fichiers','Résolution','Accès aux COPC','Diagnostiquer chaque source avant la fusion','Arrêter une source sans croissance après','Charger les COPC produits dans QGIS'):
   self.assertIn(label,source)
