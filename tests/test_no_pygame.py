import ast
import pathlib
import unittest


class TestNoPygame(unittest.TestCase):
    def test_runtime_python_has_no_pygame_imports(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        offenders: list[str] = []
        banned = {"pygame", "pygame_ce"}
        for path in sorted(root.rglob("*.py")):
            if "venv" in path.parts or path.parts[-2:] == ("tests", path.name):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
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
