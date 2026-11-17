"""OCR for scanned statements and photos, using the Tesseract program.

Tesseract gives word boxes, which is what the layout engine needs. It is a
free program: `sudo apt install tesseract-ocr` on Linux; on Windows install the
UB Mannheim build and Bahi finds it in Program Files.
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class OCRUnavailable(Exception):
    pass


WINDOWS_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


def find_tesseract(configured: str | None = None) -> str | None:
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("tesseract")
    if found:
        return found
    for p in WINDOWS_PATHS:
        if Path(p).exists():
            return p
    local = os.environ.get("LOCALAPPDATA")
    if local:
        p = Path(local) / "Programs" / "Tesseract-OCR" / "tesseract.exe"
        if p.exists():
            return str(p)
    return None


class OCR:
    def __init__(self, settings: dict):
        self.settings = settings or {}
        self.binary = find_tesseract(self.settings.get("tesseract"))
        self.lang = self.settings.get("lang", "eng")
        self.psm = str(self.settings.get("psm", 6))

    def available(self) -> bool:
        return bool(self.binary) and self.settings.get("enabled", True) is not False

    def version(self) -> str:
        if not self.binary:
            return ""
        try:
            out = subprocess.run([self.binary, "--version"], capture_output=True, text=True, timeout=20)
            return (out.stdout or out.stderr).splitlines()[0].strip()
        except Exception:
            return ""

    def read(self, image, scale: float = 1.0):
        """Return (words, mean confidence) for a PIL image. Coordinates are multiplied by scale."""
        from .pdftext import Word

        if not self.binary:
            raise OCRUnavailable("Tesseract is not installed.")
        img = clean_image(image)
        with tempfile.TemporaryDirectory(prefix="bahi-ocr-") as td:
            src = Path(td) / "page.png"
            img.save(src)
            cmd = [self.binary, str(src), "stdout", "-l", self.lang, "--psm", self.psm,
                   "-c", "preserve_interword_spaces=1", "tsv"]
            env = dict(os.environ)
            env.setdefault("OMP_THREAD_LIMIT", "2")
            proc = subprocess.run(cmd, capture_output=True, timeout=300, env=env)
            if proc.returncode != 0:
                raise OCRUnavailable(f"Tesseract failed: {proc.stderr.decode('utf-8', 'replace')[:300]}")
            text = proc.stdout.decode("utf-8", "replace")
        words, confs = [], []
        for row in csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE):
            t = (row.get("text") or "").strip()
            try:
                conf = float(row.get("conf") or -1)
            except ValueError:
                conf = -1
            if not t or conf < 0:
                continue
            if not any(ch.isalnum() for ch in t) or (conf < 25 and len(t) <= 2):
                continue  # specks and smudges read as punctuation
            left, top = float(row["left"]), float(row["top"])
            w, h = float(row["width"]), float(row["height"])
            words.append(Word(t, left * scale, (left + w) * scale, top * scale, (top + h) * scale))
            confs.append(conf)
        mean = sum(confs) / len(confs) if confs else None
        return words, mean


def estimate_skew(img) -> float:
    """Angle in degrees that straightens the text lines (projection-profile search)."""
    from PIL import Image

    small = img.convert("L")
    if small.width > 1000:
        small = small.resize((1000, int(small.height * 1000 / small.width)))
    ink = small.point(lambda p: 255 if p < 150 else 0)
    best = (0.0, -1.0)

    def score(angle):
        r = ink.rotate(angle, resample=Image.NEAREST, fillcolor=0)
        col = r.resize((1, r.height), resample=Image.BOX)
        vals = list(col.tobytes())
        mean = sum(vals) / len(vals)
        return sum((v - mean) ** 2 for v in vals)

    for a in [x / 2 for x in range(-8, 9)]:
        sc = score(a)
        if sc > best[1]:
            best = (a, sc)
    centre = best[0]
    for a in [centre + x / 20 for x in range(-10, 11)]:
        sc = score(a)
        if sc > best[1]:
            best = (a, sc)
    return best[0]


def clean_image(image):
    """Grey, despeckle, straighten and stretch contrast before OCR."""
    from PIL import Image, ImageFilter, ImageOps

    img = image.convert("L")
    img = img.filter(ImageFilter.MedianFilter(3))
    angle = estimate_skew(img)
    if abs(angle) >= 0.05:
        img = img.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=255)
    return ImageOps.autocontrast(img, cutoff=1)
