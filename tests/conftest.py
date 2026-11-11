"""Shared fixtures. Puts the project root on sys.path so `geoquiz` imports."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Pixels per degree of the whole-world view on a full-HD screen.
DEFAULT_PX_PER_DEG = 1920 / 360


@pytest.fixture(scope="session")
def world():
    """The real bundled map; loading takes ~0.3 s so it is shared."""
    from geoquiz.mapdata import WorldMap

    return WorldMap.load()


@pytest.fixture(scope="session")
def px():
    return DEFAULT_PX_PER_DEG
