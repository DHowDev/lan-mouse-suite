import ast
import unittest
from pathlib import Path


class CompatibilityTests(unittest.TestCase):
    def test_sources_parse_with_python_39_grammar(self):
        root = Path(__file__).resolve().parents[1]
        sources = list((root / "src").rglob("*.py")) + list((root / "scripts").rglob("*.py"))
        self.assertGreater(len(sources), 5)
        for source in sources:
            with self.subTest(source=str(source.relative_to(root))):
                ast.parse(source.read_text(encoding="utf-8"), filename=str(source), feature_version=(3, 9))


if __name__ == "__main__":
    unittest.main()
