import ast
import pathlib
import unittest

_SOURCE_DIRS = ("pathwise", "map_generation", "analytics")
_SOURCE_FILES = ("main.py",)


class TestNoPygame(unittest.TestCase):
    def test_runtime_python_has_no_pygame_imports(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        offenders: list[str] = []
        banned = {"pygame", "pygame_ce"}
        paths = [root / name for name in _SOURCE_FILES if (root / name).is_file()]
        for folder in _SOURCE_DIRS:
            base = root / folder
            if base.is_dir():
                paths.extend(base.rglob("*.py"))
        for path in sorted(paths):
            if "venv" in path.parts or "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        base = alias.name.split(".")[0]
                        if base in banned:
                            offenders.append(f"{path}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    base = node.module.split(".")[0]
                    if base in banned:
                        offenders.append(f"{path}: from {node.module}")

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
