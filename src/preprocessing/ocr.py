"""Local OCR with Tesseract for printed documents (photos or scans)."""
import io
import re
from dataclasses import dataclass
from typing import Union

from PIL import Image, ImageOps

import pytesseract

# Tesseract reads printed text best at roughly 300 dpi: upscale small photos
MIN_WIDTH = 1600
MAX_WIDTH = 3500


@dataclass
class OCRResult:
    text: str
    confidence: float  # mean word confidence, 0-100
    words: int


def tesseract_available() -> bool:
    """Whether the tesseract binary and the Spanish model are installed."""
    try:
        return "spa" in pytesseract.get_languages()
    except (pytesseract.TesseractNotFoundError, OSError):
        return False


def _prepare(image: Image.Image) -> Image.Image:
    """Fix phone rotation, convert to grayscale, normalize contrast and size."""
    image = ImageOps.exif_transpose(image)
    image = ImageOps.grayscale(image)
    image = ImageOps.autocontrast(image, cutoff=1)
    if image.width < MIN_WIDTH or image.width > MAX_WIDTH:
        target = MIN_WIDTH if image.width < MIN_WIDTH else MAX_WIDTH
        ratio = target / image.width
        image = image.resize((target, int(image.height * ratio)), Image.LANCZOS)
    return image


def _clean(text: str) -> str:
    """Join hyphenated line breaks and collapse blank lines left by OCR."""
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def ocr_image(source: Union[str, bytes, Image.Image], lang: str = "spa") -> OCRResult:
    """Extract text from an image of a printed document.

    Args:
        source: Path to the image, raw image bytes, or a PIL image
        lang: Tesseract language code

    Returns:
        OCRResult with the text and Tesseract's mean word confidence
    """
    if isinstance(source, bytes):
        image = Image.open(io.BytesIO(source))
    elif isinstance(source, Image.Image):
        image = source
    else:
        image = Image.open(source)

    image = _prepare(image)
    data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
    confidences = [float(c) for c, w in zip(data["conf"], data["text"]) if float(c) >= 0 and w.strip()]
    text = pytesseract.image_to_string(image, lang=lang)

    return OCRResult(
        text=_clean(text),
        confidence=sum(confidences) / len(confidences) if confidences else 0.0,
        words=len(confidences),
    )


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}
# Pages below this mean confidence are reported so they can be retaken or fixed by hand
LOW_CONFIDENCE = 60
# A PDF page with at least this many characters of real text is not OCR'd
MIN_TEXT_LAYER = 200
# Render scale for PDF pages (1 = 72 dpi); ocr_image resizes the result anyway
PDF_RENDER_SCALE = 3


def ocr_pdf(path, log=print) -> OCRResult:
    """OCR a PDF made of images (scans, screenshots), page by page.

    Pages that already have a text layer use it directly. Pages are separated
    by "--- Página N ---" markers so the text can be checked against the PDF.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    pages, confidences, words, low_pages = [], [], 0, []
    try:
        for n in range(len(pdf)):
            page = pdf[n]
            text_layer = page.get_textpage().get_text_range().strip()
            if len(text_layer) >= MIN_TEXT_LAYER:
                pages.append(f"--- Página {n + 1} ---\n{_clean(text_layer)}")
                continue

            result = ocr_image(page.render(scale=PDF_RENDER_SCALE).to_pil())
            pages.append(f"--- Página {n + 1} ---\n{result.text}")
            if result.words:
                confidences.append(result.confidence * result.words)
                words += result.words
                if result.confidence < LOW_CONFIDENCE:
                    low_pages.append(n + 1)
            if (n + 1) % 10 == 0:
                log(f"  {path.name}: {n + 1}/{len(pdf)} páginas")
    finally:
        pdf.close()

    if low_pages:
        log(f"  {path.name}: confianza baja en las páginas {', '.join(map(str, low_pages))}")
    # Pages read from the text layer count as fully reliable
    return OCRResult(
        text="\n\n".join(pages),
        confidence=sum(confidences) / words if words else 100.0,
        words=words,
    )


def extract_folder(src_dir: str = "ocr", dst_dir: str = "manuales", force: bool = False, log=print) -> int:
    """OCR every photo and image PDF in src_dir into dst_dir/<file name>.txt.

    Files that already have their .txt are skipped (unless force), so text
    corrected by hand is never overwritten. A PDF produces a single .txt.

    Returns:
        Number of files processed
    """
    from pathlib import Path

    src, dst = Path(src_dir), Path(dst_dir)
    valid = IMAGE_EXTENSIONS | {".pdf"}
    files = sorted(p for p in src.glob("*") if p.is_file() and p.suffix.lower() in valid) if src.exists() else []
    pending = [p for p in files if force or not (dst / f"{p.stem}.txt").exists()]
    if not pending:
        return 0
    if not tesseract_available():
        raise RuntimeError("Tesseract no está instalado. Instálelo con: sudo apt install tesseract-ocr tesseract-ocr-spa")

    dst.mkdir(parents=True, exist_ok=True)
    for source in pending:
        result = ocr_pdf(source, log=log) if source.suffix.lower() == ".pdf" else ocr_image(source)
        out = dst / f"{source.stem}.txt"
        out.write_text(result.text + "\n", encoding="utf-8")
        warning = f"  ← confianza baja, revise {out}" if result.confidence < LOW_CONFIDENCE else ""
        log(f"OCR {source.name} -> {out} ({result.words} palabras, confianza {result.confidence:.0f}%){warning}")
    return len(pending)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extrae con OCR el texto de las fotos y PDFs escaneados de ocr/ a manuales/")
    parser.add_argument("--src", default="ocr", help="Carpeta con las fotos o PDFs. Default: ocr")
    parser.add_argument("--dst", default="manuales", help="Carpeta donde guardar los .txt. Default: manuales")
    parser.add_argument("--force", action="store_true", help="Rehacer también los que ya tienen .txt")
    args = parser.parse_args()
    n = extract_folder(args.src, args.dst, args.force)
    print(f"{n} archivos procesados" if n else f"Nada nuevo que procesar en {args.src}/")
