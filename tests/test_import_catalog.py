import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from import_catalog import merge


class ImportCatalogTests(unittest.TestCase):
    def test_imports_replace_matching_packages_and_preserve_others(self):
        existing = [{'package': '@a/one', 'version': '1'}, {'package': '@b/two', 'version': '1'}]
        imported = [{'package': '@a/one', 'version': '2'}, {'package': '@c/three', 'version': '1'}]
        self.assertEqual(merge(existing, imported), [
            {'package': '@a/one', 'version': '2'},
            {'package': '@b/two', 'version': '1'},
            {'package': '@c/three', 'version': '1'},
        ])


if __name__ == '__main__':
    unittest.main()
