"""engine/metadata.py — EXIF / file metadata anomaly checks.

Handles PDFs gracefully — PIL cannot read EXIF from PDFs, so for PDF
files we skip EXIF extraction and report "No EXIF (PDF)" instead of
crashing with "cannot identify image file".
"""

from pathlib import Path
from PIL import Image
import PIL.ExifTags as ExifTags

try:
    import pypdf                        # pypdf (preferred) or PyPDF2
    _PYPDF_OK = True
except ImportError:
    try:
        import PyPDF2 as pypdf          # fallback
        _PYPDF_OK = True
    except ImportError:
        _PYPDF_OK = False


def _check_pdf_metadata(file_path: str) -> tuple[dict, list]:
    """Extract metadata from a PDF file. Returns (meta_dict, anomalies)."""
    meta      = {}
    anomalies = []

    if not _PYPDF_OK:
        # No PDF library — just note it's a PDF, no EXIF
        anomalies.append("No EXIF metadata found — normal for PDF documents")
        return meta, anomalies

    try:
        with open(file_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            info   = reader.metadata  # returns a DocumentInformation object or None

        if info:
            field_map = {
                "/Producer":  "Producer",
                "/Creator":   "Creator",
                "/Author":    "Author",
                "/CreationDate": "CreationDate",
                "/ModDate":   "ModDate",
                "/Title":     "Title",
            }
            for pdf_key, display_key in field_map.items():
                val = info.get(pdf_key, "")
                if val:
                    meta[display_key] = str(val)[:200]

            # Suspicious: created in an image editor
            creator  = meta.get("Creator",  "").lower()
            producer = meta.get("Producer", "").lower()
            combined = creator + " " + producer
            if any(s in combined for s in ["photoshop", "gimp", "affinity", "paint.net", "inkscape"]):
                anomalies.append(
                    f"Document created/edited with image editing software: "
                    f"{meta.get('Creator') or meta.get('Producer')}"
                )

            # Suspicious: ModDate differs from CreationDate
            cdate = meta.get("CreationDate", "")
            mdate = meta.get("ModDate", "")
            if cdate and mdate and cdate != mdate:
                anomalies.append(
                    f"PDF modification date differs from creation date "
                    f"(Created: {cdate[:16]}, Modified: {mdate[:16]})"
                )
        else:
            # No metadata at all in PDF — normal for scanned docs
            anomalies.append("No metadata found in PDF — normal for scanned documents")

    except Exception as e:
        anomalies.append(f"Could not read PDF metadata: {str(e)}")

    return meta, anomalies


def _check_image_metadata(file_path: str) -> tuple[dict, list]:
    """Extract EXIF metadata from an image file. Returns (meta_dict, anomalies)."""
    meta      = {}
    anomalies = []

    try:
        img  = Image.open(file_path)
        exif = img._getexif()

        if exif:
            for tag_id, value in exif.items():
                tag = ExifTags.TAGS.get(tag_id, str(tag_id))
                meta[tag] = str(value)[:200]

            software = meta.get("Software", "").lower()
            if any(s in software for s in ["photoshop", "gimp", "affinity", "paint"]):
                anomalies.append(f"Edited with: {meta['Software']}")

            if "GPSInfo" in meta:
                anomalies.append("Unexpected GPS metadata in document")

            orig = meta.get("DateTimeOriginal", "")
            mod  = meta.get("DateTime", "")
            if orig and mod and orig != mod:
                anomalies.append("Modification timestamp differs from capture time")
        else:
            anomalies.append("No EXIF metadata found (possible stripped/edited file)")

    except Exception as e:
        anomalies.append(f"Metadata read error: {str(e)}")

    return meta, anomalies


def run_metadata_check(file_path: str) -> dict:
    """
    Check file metadata for anomalies.

    Automatically routes to PDF or image metadata extraction
    based on file extension — never crashes on PDFs.
    """
    suffix = Path(file_path).suffix.lower()

    if suffix == ".pdf":
        meta, anomalies = _check_pdf_metadata(file_path)
    else:
        meta, anomalies = _check_image_metadata(file_path)

    return {
        "metadata":  meta,
        "anomalies": anomalies,
    }