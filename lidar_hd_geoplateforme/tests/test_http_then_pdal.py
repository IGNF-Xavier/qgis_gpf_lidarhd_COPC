import pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class HttpThenPdalTests(unittest.TestCase):
 def test_http_probe_precedes_pdal(self):
  s=(ROOT/'algorithms.py').read_text(encoding='utf-8');start=s.index('def _diagnose_sources');end=s.index('def processAlgorithm',start);b=s[start:end]
  self.assertLess(b.index('probe_url(url,feedback)'),b.index("[pdal,'info','--metadata',url]"))
  self.assertIn("pdal_timeout=min(stall if stall>0 else 30,30)",b)
  self.assertIn("'pdal_tested':False",b)
 def test_interface_contract_remains(self):
  s=(ROOT/'algorithms.py').read_text(encoding='utf-8')
  for label in ('Emprise','Éditions à produire','Éditions sélectionnées','Dossier de destination','Préfixe des fichiers','Résolution','Accès aux COPC','Diagnostiquer chaque source avant la fusion','Arrêter une source sans croissance après','Charger les COPC produits dans QGIS'):self.assertIn(label,s)
