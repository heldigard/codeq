from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Generator

import pytest

from .fixtures import write_fixtures, write_java_fixtures, write_typescript_fixtures


@pytest.fixture
def fixture_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp) / "project"
        fixture.mkdir()
        write_fixtures(fixture)
        write_java_fixtures(fixture)
        write_typescript_fixtures(fixture)
        yield fixture
