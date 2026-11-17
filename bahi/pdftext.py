"""Read words with positions from PDFs (text layer or OCR) and images."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from . import ocr as ocr_mod


class PasswordRequired(Exception):
    """The PDF is locked and no (or no matching) password was given."""


class WrongPassword(PasswordRequired):
    """A password was given but it did not open the PDF."""


class UnreadableFile(Exception):
    pass


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def h(self) -> float:
        return max(0.1, self.bottom - self.top)


@dataclass
class PageWords:
    number: int
    width: float
    height: float
    words: list[Word] = field(default_factory=list)
    hrules: list[tuple[float, float, float]] = field(default_factory=list)  # (y, x0, x1)
    source: str = "text"  # text | ocr
    ocr_confidence: float | None = None


def _is_password_error(exc: BaseException) -> bool:
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        name = type(exc).__name__
        if "Password" in name or "password" in str(exc).lower():
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def open_pdf(path: Path, password: str | None = None):
    import pdfplumber

    try:
        return pdfplumber.open(str(path), password=password or "")
    except Exception as exc:  # pdfplumber wraps pdfminer errors
        if _is_password_error(exc):
            if password:
                raise WrongPassword("That password didn't open the PDF.") from exc
            raise PasswordRequired("This PDF is password-protected.") from exc
        raise UnreadableFile(f"Couldn't read this PDF: {exc}") from exc


def is_locked(path: Path) -> bool:
    try:
        pdf = open_pdf(path)
    except PasswordRequired:
        return True
    except UnreadableFile:
        return False
    pdf.close()
    return False


def _hrules(page) -> list[tuple[float, float, float]]:
    out = []
    try:
        for ln in page.lines:
            if abs(ln["top"] - ln["bottom"]) < 1.5 and ln["x1"] - ln["x0"] > 40:
                out.append(((ln["top"] + ln["bottom"]) / 2, ln["x0"], ln["x1"]))
        for r in page.rects:
            h = r["bottom"] - r["top"]
            if h < 1.5 and r["x1"] - r["x0"] > 40:
                out.append(((r["top"] + r["bottom"]) / 2, r["x0"], r["x1"]))
    except Exception:
        return []
    return sorted(out)


def read_pdf(path: Path, password: str | None = None, ocr: bool = True, max_pages: int = 300,
             ocr_settings: dict | None = None, progress=None) -> list[PageWords]:
    """Words for every page. Pages with no text layer are OCR'd when possible."""
    pages: list[PageWords] = []
    scanned: list[int] = []
    with open_pdf(path, password) as pdf:
        total = min(len(pdf.pages), max_pages)
        for i, page in enumerate(pdf.pages[:total]):
            raw = page.extract_words(x_tolerance=1.5, y_tolerance=2.5, keep_blank_chars=False,
                                     use_text_flow=False)
            words = [Word(w["text"], float(w["x0"]), float(w["x1"]), float(w["top"]), float(w["bottom"]))
                     for w in raw if w["text"].strip()]
            pw = PageWords(i + 1, float(page.width), float(page.height), words, _hrules(page))
            if len(words) < 8 and (page.images or not words):
                scanned.append(i)
            pages.append(pw)
            if progress:
                progress(i + 1, total, "Reading pages")
    if scanned and ocr:
        engine = ocr_mod.OCR(ocr_settings or {})
        if not engine.available():
            raise ocr_mod.OCRUnavailable(
                "This PDF is scanned (no text inside). Install Tesseract OCR to read it: "
                "on Linux `sudo apt install tesseract-ocr`, on Windows see README."
            )
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(str(path), password=password or None)
        try:
            dpi = int((ocr_settings or {}).get("dpi", 300))
            for n, i in enumerate(scanned):
                page = doc[i]
                img = page.render(scale=dpi / 72).to_pil()
                words, conf = engine.read(img, scale=72 / dpi)
                pages[i].words = words
                pages[i].hrules = []
                pages[i].source = "ocr"
                pages[i].ocr_confidence = conf
                if progress:
                    progress(n + 1, len(scanned), "Reading scanned pages")
        finally:
            doc.close()
    return pages


def read_image(path: Path, ocr_settings: dict | None = None) -> list[PageWords]:
    from PIL import Image, ImageOps

    engine = ocr_mod.OCR(ocr_settings or {})
    if not engine.available():
        raise ocr_mod.OCRUnavailable("Reading photos needs Tesseract OCR. See README.")
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im.load()
        img = im.convert("RGB")
    scale = 1.0
    if img.width < 1800:
        factor = 1800 / img.width
        img = img.resize((int(img.width * factor), int(img.height * factor)))
        scale = 1 / factor
    words, conf = engine.read(img, scale=scale)
    w, h = img.width * scale, img.height * scale
    return [PageWords(1, w, h, words, [], "ocr", conf)]


def read_bytes_pdf(data: bytes, password: str | None = None) -> list[PageWords]:  # pragma: no cover
    tmp = io.BytesIO(data)
    return read_pdf(tmp, password)  # type: ignore[arg-type]
