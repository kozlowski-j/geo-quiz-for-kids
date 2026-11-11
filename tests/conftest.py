"""Shared fixtures. Puts the project root on sys.path so `geoquiz` imports."""
import math
import os
import sys
from pathlib import Path

import pytest

# The UI tests open the real game without a screen or a sound card.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Pixels per degree of the whole-world view on a full-HD screen.
DEFAULT_PX_PER_DEG = 1920 / 360


def haversine_km(lon1, lat1, lon2, lat2):
    """Great-circle distance: the reference the game's faster maths is checked against."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))


@pytest.fixture(scope="session")
def world():
    """The real bundled map; loading takes ~0.3 s so it is shared."""
    from geoquiz.mapdata import WorldMap

    return WorldMap.load()


@pytest.fixture(scope="session")
def px():
    return DEFAULT_PX_PER_DEG
