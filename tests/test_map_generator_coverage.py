"""Coverage for pathwise.map_generator re-exports and validation CLI."""

import runpy
import sys
import unittest

from pathwise import map_generator


class TestMapGeneratorModule(unittest.TestCase):
    def test_reexports(self):
        self.assertIn("generate_map_layout", map_generator.__all__)
        layout = map_generator.generate_map_layout(42, difficulty=map_generator.DifficultyProfile.default())
        self.assertIn("roads", layout)

    def test_main_validation_block(self):
        argv = sys.argv
        try:
            sys.argv = ["map_generator", "3"]
            runpy.run_module("pathwise.map_generator", run_name="__main__")
        finally:
            sys.argv = argv


if __name__ == "__main__":
    unittest.main()
