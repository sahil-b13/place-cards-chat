import io
import os
import sys

# Tests always run in mock mode, regardless of any local backend/.env.
os.environ["MOCK_MODE"] = "true"
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from PIL import Image

from app.services.cache import TTLCache
from app.services.places import MockPlaces
from app.services.resolver import Resolver
from app.services.vision import MockVision
from app.main import FIXTURES_DIR


def make_jpeg(size=(32, 32), color=(200, 100, 50), exif=None) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", size, color)
    if exif is not None:
        img.save(buf, "JPEG", exif=exif)
    else:
        img.save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def jpeg():
    return make_jpeg()


@pytest.fixture
def resolver():
    return Resolver(MockPlaces(FIXTURES_DIR), MockVision(FIXTURES_DIR), TTLCache(3600))
