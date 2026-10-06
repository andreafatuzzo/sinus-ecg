import ast
import tomllib
from pathlib import Path

import sinus_dsp

DSP_DIR = Path(__file__).resolve().parents[2]


def test_package_imports() -> None:
    assert sinus_dsp.__version__


def test_version_is_a_literal_equal_to_the_version_of_pyproject() -> None:
    """The version is written in two places, always equal (architecture §8.14)."""
    project = tomllib.loads((DSP_DIR / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    tree = ast.parse((DSP_DIR / "sinus_dsp" / "__init__.py").read_text(encoding="utf-8"))
    literals = [
        statement.value.value
        for statement in tree.body
        if isinstance(statement, ast.Assign)
        and [target.id for target in statement.targets if isinstance(target, ast.Name)]
        == ["__version__"]
        and isinstance(statement.value, ast.Constant)
    ]
    assert literals == [project["version"]]
    assert sinus_dsp.__version__ == project["version"]
    assert "version" not in project.get("dynamic", [])
