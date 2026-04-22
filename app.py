import subprocess
from flask import Flask, render_template, request, jsonify
from receipty import process_receipt

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB max


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/process", methods=["POST"])
def process():
    file = request.files.get("file")
    if not file:
        return jsonify({"status": "error", "error": "No file provided"}), 400

    source_dir = request.form.get("source_dir", "").strip()
    mode = request.form.get("mode", "rename")
    output_dir = request.form.get("output_dir", "").strip() or None

    if not source_dir:
        return jsonify({"status": "error", "error": "Source directory required"}), 400

    file_bytes = file.read()
    filename = file.filename

    result = process_receipt(file_bytes, filename, source_dir, mode, output_dir)
    return jsonify(result)


@app.route("/api/pick-folder", methods=["POST"])
def pick_folder():
    prompt = request.json.get("prompt", "Select a folder")
    result = subprocess.run(
        [
            "osascript", "-e",
            f'POSIX path of (choose folder with prompt "{prompt}")',
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        return jsonify({"path": None})
    return jsonify({"path": result.stdout.strip()})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
