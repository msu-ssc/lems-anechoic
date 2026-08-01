import ast
from pathlib import Path

from msu_anechoic import experiment
from msu_anechoic import spec_an


def test_spec_an_owns_its_config_model():
    assert spec_an.SpecAnConfig.__module__ == "msu_anechoic.spec_an"
    assert experiment.SpecAnConfig is spec_an.SpecAnConfig


def test_spec_an_package_does_not_import_the_root_project():
    source_path = Path(__file__).parents[1] / "packages" / "spec-an" / "msu_anechoic" / "spec_an.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    assert not any(module == "msu_anechoic" or module.startswith("msu_anechoic.") for module in imported_modules)
