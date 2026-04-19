"""engine/ela.py — Error Level Analysis for forgery detection.

Accepts either a file path (str/Path) or a PIL.Image.
For PDFs, analyses the FIRST page (ELA is a single-image operation).
"""

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageEnhance

try:
    from pdf2image import convert_from_path
    _PDF2IMAGE_OK = True
except ImportError:
    _PDF2IMAGE_OK = False

OUTPUT_DIR = Path(__file__).parent.parent / "static" / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ELA_QUALITY = 90
AMPLIFY     = 10


def _load_first_image(source) -> Image.Image:
    """Load the first page/frame of any file as a PIL RGB image."""
    if isinstance(source, Image.Image):
        return source.convert("RGB")

    path   = Path(source)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        if not _PDF2IMAGE_OK:
            raise RuntimeError(
                "pdf2image not installed. Run: pip install pdf2image && "
                "sudo apt install poppler-utils"
            )
        pages = convert_from_path(str(path), dpi=200, first_page=1, last_page=1)
        if not pages:
            raise RuntimeError(f"Could not convert PDF to image: {path}")
        return pages[0].convert("RGB")

    return Image.open(str(path)).convert("RGB")


def run_ela(source, base_name: str) -> dict:
    """
    Run Error Level Analysis on a document.

    Parameters
    ----------
    source    : str | Path | PIL.Image
                File path (PDF/JPG/PNG/…) or already-loaded PIL Image.
                For PDFs, only the first page is analysed.
    base_name : str  — used to name the saved heatmap file.

    Returns
    -------
    dict: score, heatmap_filename, high_ela_regions
    """
    try:
        img = _load_first_image(source)
    except Exception as e:
        # Return a neutral result so the rest of the pipeline still runs
        return {
            "score":            0.0,
            "heatmap_filename": None,
            "high_ela_regions": False,
            "error":            str(e),
        }

    # Re-save at lower quality and compute pixel difference
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=ELA_QUALITY)
    buf.seek(0)
    resaved = Image.open(buf).convert("RGB")

    diff      = ImageChops.difference(img, resaved)
    amplified = ImageEnhance.Brightness(diff).enhance(AMPLIFY)

    # Save heatmap
    heatmap_filename = f"{base_name}_ela.png"
    amplified.save(str(OUTPUT_DIR / heatmap_filename))

    arr   = np.array(diff).astype(float)
    score = float(np.mean(arr))

    return {
        "score":            score,
        "heatmap_filename": heatmap_filename,
        "high_ela_regions": score > 5.0,
    }