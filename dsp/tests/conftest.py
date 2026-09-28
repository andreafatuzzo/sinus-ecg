from pathlib import Path

import pytest

MITDB_DIR = Path(__file__).resolve().parents[2] / "data" / "mitdb"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if MITDB_DIR.is_dir() and any(MITDB_DIR.glob("*.hea")):
        return
    skip = pytest.mark.skip(reason=f"MIT-BIH database not found in {MITDB_DIR}")
    for item in items:
        if item.get_closest_marker("needs_data"):
            item.add_marker(skip)
