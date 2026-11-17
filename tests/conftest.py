import json
import shutil
from pathlib import Path

import pytest

from bahi import config, db, tallymock

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


def expected(name: str) -> dict:
    return json.loads((SAMPLES / "expected" / f"{name}.json").read_text())


def has_tesseract() -> bool:
    return shutil.which("tesseract") is not None


@pytest.fixture
def cfg(tmp_path):
    home = tmp_path / "home"
    config.init_home(home)
    c = config.load(home)
    c.lab["corpus"] = str(SAMPLES)
    c.ensure_dirs()
    return c


@pytest.fixture
def conn(cfg):
    c = db.connect(cfg.db_path)
    yield c
    c.close()


@pytest.fixture
def tally(cfg):
    """A running Tally simulator; cfg points at it."""
    server, mock = tallymock.start_background()
    cfg.tally["host"] = "127.0.0.1"
    cfg.tally["port"] = server.server_address[1]
    yield mock
    server.shutdown()
    server.server_close()
