"""Tests statiques de non-régression de l'interface Processing complète."""
import ast
import configparser
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ALGORITHMS = ROOT / 'algorithms.py'

class InterfaceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ALGORITHMS.read_text(encoding='utf-8')
        cls.tree = ast.parse(cls.source)
        cls.extract_class = next(
            node for node in cls.tree.body
            if isinstance(node, ast.ClassDef) and node.name == 'ExtractEditionsAlgorithm'
        )

    def test_plugin_version(self):
        parser = configparser.ConfigParser()
        parser.read(ROOT / 'metadata.txt', encoding='utf-8')
        self.assertEqual(parser['general']['version'], '0.5.0')

    def test_complete_processing_parameters_are_preserved(self):
        required_constants = {
            'MODE', 'SEL', 'PREFIX', 'R', 'URL_MODE',
            'DIAG', 'STALL', 'L', 'M', 'OUT'
        }
        assigned = set()
        for statement in self.extract_class.body:
            if isinstance(statement, ast.Assign):
                assigned.update(
                    target.id for target in statement.targets
                    if isinstance(target, ast.Name)
                )
        self.assertTrue(required_constants.issubset(assigned),
                        required_constants - assigned)
        base_class = next(node for node in self.tree.body
                          if isinstance(node, ast.ClassDef) and node.name == 'Base')
        base_source = ast.get_source_segment(self.source, base_class)
        for inherited in ("E='EXTENT'", "C='CRS'", "D='OUT_DIR'", "'Emprise'", "'SCR de repli'"):
            self.assertIn(inherited, base_source)

    def test_interface_does_not_revert_to_pipeline_json_form(self):
        forbidden_labels = ('Pipeline JSON à exécuter', 'Méthode de sélection')
        for label in forbidden_labels:
            self.assertNotIn(label, self.source)
        required_labels = (
            'Emprise', 'Éditions à produire', 'Éditions sélectionnées',
            'Dossier de destination', 'Préfixe des fichiers',
            'Résolution', 'Accès aux COPC',
            'Diagnostiquer chaque source avant la fusion',
            'Arrêter une source sans croissance après',
            'Charger les COPC produits dans QGIS'
        )
        for label in required_labels:
            self.assertIn(label, self.source)

    def test_two_processing_algorithms_remain_registered(self):
        provider = (ROOT / 'provider.py').read_text(encoding='utf-8')
        self.assertIn('ListEditionsAlgorithm', provider)
        self.assertIn('ExtractEditionsAlgorithm', provider)
        self.assertGreaterEqual(provider.count('addAlgorithm'), 2)

    def test_diagnostic_signature_and_calls_are_consistent(self):
        self.assertIn('stall,selection_method,pdal_env,feedback', self.source)
        self.assertIn('stall,selection_method,pdal_env,f)', self.source)
        diagnostic_start = self.source.index('def _diagnose_sources')
        process_start = self.source.index('def processAlgorithm', diagnostic_start)
        diagnostic = self.source[diagnostic_start:process_start]
        self.assertIn("'selection_method':selection_method", diagnostic)
        self.assertIn('probe_url(url,feedback)', diagnostic)
        self.assertIn("[pdal,'info','--metadata',url]", diagnostic)
        self.assertNotIn('_probe_', diagnostic)
