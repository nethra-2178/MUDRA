"""engine/preprocess.py — load & normalise the uploaded file into a PIL Image."""

from pathlib import Path
from PIL import Image
import fitz  # PyMuPDF


def preprocess(file_path: str):
    """
    Returns (PIL.Image, work_path_str).
    PDFs are rasterised to the first page at 150 dpi.
    """
    p   = Path(file_path)
    ext = p.suffix.lower()

    if ext == ".pdf":
        doc     = fitz.open(file_path)
        page    = doc[0]
        mat     = fitz.Matrix(150 / 72, 150 / 72)
        pix     = page.get_pixmap(matrix=mat, alpha=False)
        out     = p.with_suffix(".png")
        pix.save(str(out))
        img     = Image.open(str(out)).convert("RGB")
        return img, str(out)
    else:
        img = Image.open(file_path).convert("RGB")
        return img, file_path