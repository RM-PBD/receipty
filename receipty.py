import anthropic
import base64
import json
import re
import shutil
import fitz  # PyMuPDF
from pathlib import Path

MODEL = "claude-sonnet-4-20250514"

EXTRACTION_PROMPT = """Extract the following from this receipt image:
1. date: Transaction date as D/M/YY (British format: day/month/year, no leading zeros, 2-digit year). Example: 10/6/24 means 10th June 2024
2. what: One concise word or short underscore-joined phrase for what was purchased. Title_Case. Examples: Dinner, Coffee, Groceries, Server_Boosts, Train_Ticket
3. business: Simplified business name. No apostrophes, no Ltd/Inc/Restaurant suffixes. Use the commonly known name. No special characters. Examples: Mildreds, Pret, Tesco, Discord
4. total: Final total amount paid, exactly 2 decimal places. Example: 53.43
5. currency: ISO 4217 3-letter code. Example: GBP, USD, EUR

If you cannot confidently read a field, set it to null.
Return ONLY a JSON object: {"date": "...", "what": "...", "business": "...", "total": "...", "currency": "..."}"""


def pdf_to_images(pdf_bytes: bytes, max_pages: int = 2) -> list[tuple[str, str]]:
    """Convert PDF pages to base64 PNG images."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    for i in range(min(len(doc), max_pages)):
        page = doc[i]
        pix = page.get_pixmap(dpi=200)
        png_bytes = pix.tobytes("png")
        b64 = base64.b64encode(png_bytes).decode("ascii")
        images.append(("image/png", b64))
    doc.close()
    return images


def analyze_receipt(file_bytes: bytes, filename: str) -> dict:
    """Send receipt to Claude vision API and extract structured data."""
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        images = pdf_to_images(file_bytes)
    else:
        media_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }.get(ext, "image/jpeg")
        b64 = base64.b64encode(file_bytes).decode("ascii")
        images = [(media_type, b64)]

    content = []
    for media_type, b64_data in images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": b64_data,
            },
        })
    content.append({"type": "text", "text": EXTRACTION_PROMPT})

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": content}],
    )

    raw = response.content[0].text
    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())

    data = json.loads(raw)

    # Validate required fields
    for field in ("date", "what", "business", "total", "currency"):
        if not data.get(field):
            raise ValueError(f"Could not read '{field}' from receipt")

    return data


def build_filename(data: dict, original_ext: str) -> str:
    """Build the standardized filename from extracted receipt data."""
    date_parts = data["date"].split("/")
    day, month, year = date_parts[0], date_parts[1], date_parts[2]

    what = data["what"].replace(" ", "_").replace("'", "")
    business = data["business"].replace(" ", "_").replace("'", "")
    total = data["total"]
    currency = data["currency"].upper().strip()

    base = f"{day}_{month}_{year}_{what}_{business}_{total}"

    if currency != "GBP":
        base += f"_{currency}"

    return base + original_ext


def safe_path(directory: Path, filename: str) -> Path:
    """Return a path that doesn't collide with existing files."""
    target = directory / filename
    if not target.exists():
        return target
    stem = Path(filename).stem
    ext = Path(filename).suffix
    counter = 2
    while True:
        candidate = directory / f"{stem}_{counter}{ext}"
        if not candidate.exists():
            return candidate
        counter += 1


def process_receipt(
    file_bytes: bytes,
    filename: str,
    source_dir: str,
    mode: str,
    output_dir: str | None = None,
) -> dict:
    """Full pipeline: analyze receipt, build filename, rename/copy."""
    try:
        data = analyze_receipt(file_bytes, filename)
        original_ext = Path(filename).suffix  # preserve original case
        new_name = build_filename(data, original_ext)

        source_path = Path(source_dir) / filename

        if mode == "copy":
            if not output_dir:
                raise ValueError("Output directory required for copy mode")
            out_dir = Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            target = safe_path(out_dir, new_name)
            shutil.copy2(source_path, target)
        else:  # rename
            target = safe_path(source_path.parent, new_name)
            source_path.rename(target)

        return {
            "original_name": filename,
            "new_name": target.name,
            "status": "success",
        }

    except Exception as e:
        return {
            "original_name": filename,
            "new_name": None,
            "status": "error",
            "error": str(e),
        }
