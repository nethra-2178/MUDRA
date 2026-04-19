"""app.py — MUDRA Flask backend"""

import os, uuid
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, abort, render_template
from flask_cors import CORS
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
CORS(app)

BASE_DIR   = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
OUTPUT_DIR = BASE_DIR / "static" / "outputs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

from engine.ela            import run_ela
from engine.ocr            import run_ocr_check
from engine.metadata       import run_metadata_check
from engine.scorer         import compute_score
from engine.explainer      import explain
from certificate.generator import generate_certificate


@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")


@app.route("/result", methods=["GET"])
def result():
    return render_template("result.html")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "MUDRA backend is running.", "version": "1.0.0"})


@app.route("/analyse", methods=["POST"])
def analyse():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"error": "Empty filename."}), 400

    ext = Path(uploaded.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Unsupported file type '{ext}'."}), 400

    doc_type  = request.form.get("doc_type", "generic").strip().lower()
    safe_stem = secure_filename(Path(uploaded.filename).stem)
    unique_id = uuid.uuid4().hex[:8]
    save_name = f"{safe_stem}_{unique_id}{ext}"
    save_path = str(UPLOAD_DIR / save_name)
    uploaded.save(save_path)

    try:
        base_name = f"{safe_stem}_{unique_id}"

        # ── Pass save_path to every engine — each handles PDF/image itself ──
        app.logger.warning(f"STARTING ANALYSIS: {save_path}")
        ela_result   = run_ela(save_path, base_name)
        ocr_result   = run_ocr_check(save_path, doc_type)
        app.logger.warning(f"OCR RESULT: {ocr_result}")
        meta_result  = run_metadata_check(save_path)

        # FIX: pass doc_type so scorer can apply type-specific evidence checks
        # (previously doc_type was never forwarded, disabling blank-doc detection)
        score_result = compute_score(ela_result, ocr_result, meta_result, doc_type)

        explanation  = explain(score_result, doc_type)
        cert_info    = generate_certificate(
            original_filename=uploaded.filename,
            doc_type=doc_type,
            score_result=score_result,
            explanation=explanation,
        )
    except Exception as e:
        app.logger.exception("Analysis pipeline error")
        return jsonify({"error": f"Analysis failed: {str(e)}"}), 500

    # Build metadata dict for frontend
    raw_meta = meta_result.get("metadata", {})
    meta_display = {
        "filename":  uploaded.filename,
        "filetype":  ext.lstrip(".").upper(),
        "filesize":  f"{round(os.path.getsize(save_path)/1024, 1)} KB",
    }
    for key in ("Software", "DateTime", "DateTimeOriginal", "Make", "Model"):
        if key in raw_meta:
            meta_display[key.lower()] = raw_meta[key]

    heatmap_path = (
        f"/static/outputs/{ela_result['heatmap_filename']}"
        if ela_result.get("heatmap_filename") else None
    )

    return jsonify({
        "verdict":         score_result["verdict"],
        "score":           score_result["score"],
        "checks":          score_result["checks"],
        "anomalies":       score_result["anomalies"],
        "explanation": {
            "en": explanation.get("english", ""),
            "ta": explanation.get("tamil",   ""),
        },
        "ela_heatmap_url": heatmap_path,
        "metadata":        meta_display,
        "cert_id":         cert_info["cert_id"],
        "cert_hash":       cert_info["cert_id"],
        "assets": {
            "certificate_url": f"/download/{cert_info['cert_id']}",
        },
    }), 200


@app.route("/download/<cert_id>", methods=["GET"])
def download_certificate(cert_id: str):
    filename  = f"MUDRA_{cert_id.upper()}.pdf"
    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        abort(404)
    return send_from_directory(str(OUTPUT_DIR), filename, as_attachment=True)


@app.route("/heatmap/<filename>", methods=["GET"])
def serve_heatmap(filename: str):
    safe = secure_filename(filename)
    if not (OUTPUT_DIR / safe).exists():
        abort(404)
    return send_from_directory(str(OUTPUT_DIR), safe)


if __name__ == "__main__":
    port  = int(os.getenv("PORT", 8500))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
