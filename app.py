import os
import subprocess

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

from receipty import commit_receipt, preview_receipt, process_receipt


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


@app.errorhandler(RequestEntityTooLarge)
def file_too_large(_error):
    return jsonify({"status": "error", "error": "Receipt exceeds the 50 MB upload limit"}), 413


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify({"status": "error", "error": "No file provided"}), 400
    return jsonify(preview_receipt(uploaded.read(), uploaded.filename))


@app.route("/api/apply", methods=["POST"])
def apply_change():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "error": "Invalid request"}), 400

    required = ("filename", "new_name", "source_dir", "mode", "fingerprint")
    missing = next((field for field in required if not payload.get(field)), None)
    if missing:
        return jsonify({"status": "error", "error": f"Missing field: {missing}"}), 400

    result = commit_receipt(
        filename=payload["filename"],
        new_name=payload["new_name"],
        source_dir=payload["source_dir"],
        mode=payload["mode"],
        output_dir=payload.get("output_dir") or None,
        expected_fingerprint=payload["fingerprint"],
    )
    return jsonify(result)


@app.route("/api/process", methods=["POST"])
def process():
    """Compatibility endpoint for older clients; new clients preview first."""
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify({"status": "error", "error": "No file provided"}), 400

    source_dir = request.form.get("source_dir", "").strip()
    mode = request.form.get("mode", "rename")
    output_dir = request.form.get("output_dir", "").strip() or None
    if not source_dir:
        return jsonify({"status": "error", "error": "Source directory required"}), 400

    result = process_receipt(uploaded.read(), uploaded.filename, source_dir, mode, output_dir)
    return jsonify(result)


@app.route("/api/pick-folder", methods=["POST"])
def pick_folder():
    payload = request.get_json(silent=True) or {}
    prompt = payload.get("prompt", "Select a folder")
    if not isinstance(prompt, str) or len(prompt) > 120:
        return jsonify({"path": None, "error": "Invalid folder prompt"}), 400

    try:
        result = subprocess.run(
            [
                "osascript",
                "-e", "on run argv",
                "-e", "POSIX path of (choose folder with prompt (item 1 of argv))",
                "-e", "end run",
                "--", prompt,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return jsonify({"path": None})

    if result.returncode != 0:
        return jsonify({"path": None})
    return jsonify({"path": result.stdout.strip()})


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("RECEIPTY_PORT", "5001")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
