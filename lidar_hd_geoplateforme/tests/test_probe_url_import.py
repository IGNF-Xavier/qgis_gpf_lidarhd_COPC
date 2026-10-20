import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class ProbeUrlImportRegressionTest(unittest.TestCase):
    def test_probe_url_is_imported_from_network(self):
        source=(ROOT/'algorithms.py').read_text(encoding='utf-8')
        tree=ast.parse(source)
        imports=[]
        for node in tree.body:
            if isinstance(node,ast.ImportFrom) and node.module=='network':
                imports.extend(alias.name for alias in node.names)
        self.assertIn('probe_url',imports)
        self.assertIn('probe_url(url,feedback)',source)
