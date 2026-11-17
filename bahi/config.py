"""Settings in bahi.toml, and where Bahi keeps its data.

Everything lives under one folder (BAHI_HOME): settings, the database, the
original statements, exports and backups. On a CA firm's PC that folder is
the Bahi folder itself, so the whole install can be copied or backed up.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore

DEFAULT_TOML = """\
# Bahi settings. Restart Bahi after changing this file.

[server]
host = "127.0.0.1"      # 127.0.0.1 = this computer only. Use "0.0.0.0" to open it on your network.
port = 8765
password = ""           # required when host is not 127.0.0.1 (user name: admin)
open_browser = true

[tally]
host = "localhost"      # the PC running TallyPrime
port = 9000             # TallyPrime: F1 Help > Settings > Connectivity
edu_mode = false        # TEST ONLY: move voucher dates to the 1st/2nd/31st for TallyPrime Educational mode

[ocr]
enabled = true          # read scanned statements and photos with Tesseract
tesseract = ""          # full path to tesseract(.exe) if it isn't found automatically
lang = "eng"
psm = 6
dpi = 300

[watch]
enabled = false         # process files dropped into inbox/<client name>/ automatically
folder = "inbox"
interval_seconds = 20

[lab]
corpus = "samples"      # statements with known answers, checked by `bahi lab`

[backup]
keep = 14               # how many daily database backups to keep
"""


@dataclass
class Config:
    home: Path
    server: dict = field(default_factory=dict)
    tally: dict = field(default_factory=dict)
    ocr: dict = field(default_factory=dict)
    watch: dict = field(default_factory=dict)
    lab: dict = field(default_factory=dict)
    backup: dict = field(default_factory=dict)

    @property
    def data_dir(self) -> Path:
        return self.home / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bahi.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def inbox_dir(self) -> Path:
        p = Path(self.watch.get("folder", "inbox"))
        return p if p.is_absolute() else self.home / p

    @property
    def corpus_dir(self) -> Path:
        p = Path(self.lab.get("corpus", "samples"))
        if p.is_absolute():
            return p
        if (self.home / p).exists():
            return self.home / p
        return Path(__file__).resolve().parents[1] / p

    def ensure_dirs(self):
        for d in (self.data_dir, self.uploads_dir, self.exports_dir, self.backups_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


def default_home() -> Path:
    env = os.environ.get("BAHI_HOME")
    if env:
        return Path(env).expanduser()
    cwd = Path.cwd()
    if (cwd / "bahi.toml").exists():
        return cwd
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "Bahi"
    return Path.home() / "bahi-data"


def init_home(home: Path) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    toml = home / "bahi.toml"
    if not toml.exists():
        toml.write_text(DEFAULT_TOML, encoding="utf-8")
    return toml


def load(home: Path | None = None) -> Config:
    home = Path(home) if home else default_home()
    toml = home / "bahi.toml"
    data = tomllib.loads(DEFAULT_TOML)
    if toml.exists():
        user = tomllib.loads(toml.read_text(encoding="utf-8"))
        for section, values in user.items():
            if isinstance(values, dict):
                data.setdefault(section, {}).update(values)
    cfg = Config(home=home, **{k: data.get(k, {}) for k in ("server", "tally", "ocr", "watch", "lab", "backup")})
    if os.environ.get("BAHI_PASSWORD"):
        cfg.server["password"] = os.environ["BAHI_PASSWORD"]
    return cfg
