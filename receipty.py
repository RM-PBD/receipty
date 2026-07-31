import base64
import hashlib
import io
import json
import os
import re
import shutil
import threading
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import anthropic
import fitz  # PyMuPDF
from PIL import Image, ImageOps


MODEL = os.environ.get("RECEIPTY_MODEL", "claude-sonnet-4-20250514")
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
MAX_IMAGE_EDGE = 3200
FILE_OPERATION_LOCK = threading.Lock()

EXTRACTION_PROMPT = """Extract the purchase details from this receipt or invoice.

Return these fields:
1. date: The transaction or invoice date as D/M/YY (British order, no leading zeros).
2. what: A concise description of what was purchased in Title_Case, using underscores.
3. business: The commonly known seller name, without legal suffixes such as Ltd or Inc.
4. total: The final amount actually paid, with exactly two decimal places. Do not use a
   subtotal, tax amount, account balance, or converted card amount.
5. currency: The ISO 4217 three-letter currency code for the total.

Use all supplied pages. Do not infer unreadable values. If a field cannot be read with
confidence, set it to null. Return only one JSON object with exactly these keys:
{"date": "...", "what": "...", "business": "...", "total": "...", "currency": "..."}"""


class ReceiptValidationError(ValueError):
    """Raised when receipt data or a requested file operation is unsafe."""


def _encode_image(image: Image.Image) -> tuple[str, str]:
    """Orient, resize, and encode an image for reliable vision processing."""
    image = ImageOps.exif_transpose(image)
    image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)

    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))
        image = background
    else:
        image = image.convert("RGB")

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=92, optimize=True)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return "image/jpeg", encoded


def image_to_base64(file_bytes: bytes) -> tuple[str, str]:
    """Prepare an uploaded image and return its API media type and base64 data."""
    try:
        with Image.open(io.BytesIO(file_bytes)) as image:
            return _encode_image(image)
    except (OSError, ValueError) as exc:
        raise ReceiptValidationError("The image could not be opened") from exc


def pdf_to_images(pdf_bytes: bytes, max_pages: int = 4) -> list[tuple[str, str]]:
    """Convert the most useful PDF pages to compact images for vision processing."""
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            if document.needs_pass:
                raise ReceiptValidationError("Password-protected PDFs are not supported")
            if document.page_count == 0:
                raise ReceiptValidationError("The PDF has no pages")

            if document.page_count <= max_pages:
                page_numbers = list(range(document.page_count))
            else:
                # Totals and payment details are often on the final page.
                page_numbers = list(range(max_pages - 1)) + [document.page_count - 1]

            images = []
            for page_number in page_numbers:
                page = document[page_number]
                pixmap = page.get_pixmap(dpi=180, alpha=False)
                with Image.open(io.BytesIO(pixmap.tobytes("png"))) as image:
                    images.append(_encode_image(image))
            return images
    except ReceiptValidationError:
        raise
    except (fitz.FileDataError, RuntimeError, ValueError) as exc:
        raise ReceiptValidationError("The PDF could not be opened") from exc


def _parse_json_object(raw: str) -> dict:
    """Read one JSON object even if the model wrapped it in a code fence."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ReceiptValidationError("The AI returned an unreadable response") from None
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ReceiptValidationError("The AI returned invalid receipt data") from exc

    if not isinstance(value, dict):
        raise ReceiptValidationError("The AI did not return a receipt object")
    return value


def _filename_component(value: object, field: str, max_length: int = 80) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReceiptValidationError(f"Could not read '{field}' from receipt")

    normalized = unicodedata.normalize("NFKD", value.strip()).encode("ascii", "ignore").decode()
    normalized = normalized.replace("&", " and ").replace("'", "")
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", normalized).strip("_")
    normalized = re.sub(r"_+", "_", normalized)[:max_length].rstrip("_")
    if not normalized:
        raise ReceiptValidationError(f"Could not create a safe '{field}' value")
    return normalized


def validate_receipt_data(data: dict) -> dict:
    """Validate and normalize model output before it can become a filename."""
    if not isinstance(data, dict):
        raise ReceiptValidationError("Receipt data must be an object")

    date_value = data.get("date")
    if not isinstance(date_value, str) or not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2}", date_value.strip()):
        raise ReceiptValidationError("Could not read a valid receipt date")
    try:
        parsed_date = datetime.strptime(date_value.strip(), "%d/%m/%y")
    except ValueError as exc:
        raise ReceiptValidationError("Could not read a valid receipt date") from exc

    raw_total = data.get("total")
    if raw_total is None:
        raise ReceiptValidationError("Could not read 'total' from receipt")
    total_text = str(raw_total).strip().replace(",", "")
    total_text = re.sub(r"^[£$€]\s*", "", total_text)
    try:
        total_value = Decimal(total_text)
    except InvalidOperation as exc:
        raise ReceiptValidationError("Could not read a valid total") from exc
    if not total_value.is_finite() or total_value < 0 or total_value >= Decimal("100000000"):
        raise ReceiptValidationError("Could not read a valid total")

    currency = data.get("currency")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Za-z]{3}", currency.strip()):
        raise ReceiptValidationError("Could not read a valid currency")

    return {
        "date": f"{parsed_date.day}/{parsed_date.month}/{parsed_date:%y}",
        "what": _filename_component(data.get("what"), "what"),
        "business": _filename_component(data.get("business"), "business"),
        "total": format(total_value.quantize(Decimal("0.01")), ".2f"),
        "currency": currency.upper().strip(),
    }


def analyze_receipt(file_bytes: bytes, filename: str) -> dict:
    """Send a receipt to Claude vision and return validated structured data."""
    if not file_bytes:
        raise ReceiptValidationError("The receipt file is empty")

    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ReceiptValidationError(f"Unsupported file type: {extension or 'unknown'}")

    images = pdf_to_images(file_bytes) if extension == ".pdf" else [image_to_base64(file_bytes)]
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": encoded,
            },
        }
        for media_type, encoded in images
    ]
    content.append({"type": "text", "text": EXTRACTION_PROMPT})

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        temperature=0,
        messages=[{"role": "user", "content": content}],
    )
    raw = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    return validate_receipt_data(_parse_json_object(raw))


def build_filename(data: dict, original_ext: str) -> str:
    """Build a standardized filename from validated receipt data."""
    normalized = validate_receipt_data(data)
    day, month, year = normalized["date"].split("/")
    base = (
        f"{day}_{month}_{year}_{normalized['what']}_{normalized['business']}_"
        f"{normalized['total']}"
    )
    if normalized["currency"] != "GBP":
        base += f"_{normalized['currency']}"

    extension = original_ext if original_ext.startswith(".") else f".{original_ext}"
    if extension.lower() not in SUPPORTED_EXTENSIONS:
        raise ReceiptValidationError("The output file type is not supported")
    return base + extension


def validate_proposed_filename(filename: str, original_ext: str) -> str:
    """Validate a reviewed filename supplied by the local web interface."""
    if not isinstance(filename, str) or filename != Path(filename).name or len(filename) > 255:
        raise ReceiptValidationError("The proposed filename is invalid")
    if Path(filename).suffix.lower() != original_ext.lower():
        raise ReceiptValidationError("The file extension cannot be changed")

    pattern = re.compile(
        r"^(\d{1,2})_(\d{1,2})_(\d{2})_"
        r"[A-Za-z0-9][A-Za-z0-9_-]*_\d+(?:\.\d{2})(?:_[A-Z]{3})?\.[A-Za-z0-9]+$"
    )
    match = pattern.fullmatch(filename)
    if not match:
        raise ReceiptValidationError("Use DAY_MONTH_YEAR_What_Business_0.00.ext")
    try:
        datetime.strptime("/".join(match.groups()), "%d/%m/%y")
    except ValueError as exc:
        raise ReceiptValidationError("The proposed filename has an invalid date") from exc
    return filename


def safe_path(directory: Path, filename: str) -> Path:
    """Return a path that does not collide with an existing file."""
    target = directory / filename
    if not target.exists():
        return target
    stem = Path(filename).stem
    extension = Path(filename).suffix
    counter = 2
    while True:
        candidate = directory / f"{stem}_{counter}{extension}"
        if not candidate.exists():
            return candidate
        counter += 1


def file_fingerprint(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def _source_path(source_dir: str, filename: str) -> Path:
    if not source_dir:
        raise ReceiptValidationError("Source directory required")
    if not filename or filename != Path(filename).name:
        raise ReceiptValidationError("The source filename is invalid")

    directory = Path(source_dir).expanduser().resolve()
    source = (directory / filename).resolve()
    if source.parent != directory:
        raise ReceiptValidationError("The source filename is invalid")
    if not source.is_file():
        raise ReceiptValidationError(f"Source file not found: {filename}")
    if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ReceiptValidationError("The source file type is not supported")
    return source


def preview_receipt(file_bytes: bytes, filename: str) -> dict:
    """Analyze without changing files, returning a reviewable proposal."""
    try:
        data = analyze_receipt(file_bytes, filename)
        return {
            "original_name": Path(filename).name,
            "new_name": build_filename(data, Path(filename).suffix),
            "data": data,
            "fingerprint": file_fingerprint(file_bytes),
            "status": "success",
            "action": "preview",
        }
    except Exception as exc:
        return {
            "original_name": Path(filename).name,
            "new_name": None,
            "status": "error",
            "error": str(exc),
        }


def commit_receipt(
    filename: str,
    new_name: str,
    source_dir: str,
    mode: str,
    output_dir: str | None = None,
    expected_fingerprint: str | None = None,
) -> dict:
    """Apply a reviewed rename or copy after re-checking the source file."""
    try:
        if mode not in {"rename", "copy"}:
            raise ReceiptValidationError("Mode must be 'rename' or 'copy'")
        source = _source_path(source_dir, filename)
        reviewed_name = validate_proposed_filename(new_name, source.suffix)

        if expected_fingerprint:
            current_fingerprint = file_fingerprint(source.read_bytes())
            if current_fingerprint != expected_fingerprint:
                raise ReceiptValidationError("The source file changed after preview; preview it again")

        with FILE_OPERATION_LOCK:
            if mode == "copy":
                if not output_dir:
                    raise ReceiptValidationError("Output directory required for copy mode")
                destination = Path(output_dir).expanduser().resolve()
                destination.mkdir(parents=True, exist_ok=True)
                target = destination / reviewed_name
                if target.resolve() == source:
                    return {
                        "original_name": filename,
                        "new_name": source.name,
                        "status": "success",
                        "action": "unchanged",
                    }
                target = safe_path(destination, reviewed_name)
                shutil.copy2(source, target)
                action = "copied"
            else:
                if source.name == reviewed_name:
                    return {
                        "original_name": filename,
                        "new_name": source.name,
                        "status": "success",
                        "action": "unchanged",
                    }
                target = safe_path(source.parent, reviewed_name)
                source.rename(target)
                action = "renamed"

        return {
            "original_name": filename,
            "new_name": target.name,
            "status": "success",
            "action": action,
        }
    except Exception as exc:
        return {
            "original_name": Path(filename).name,
            "new_name": None,
            "status": "error",
            "error": str(exc),
        }


def process_receipt(
    file_bytes: bytes,
    filename: str,
    source_dir: str,
    mode: str,
    output_dir: str | None = None,
) -> dict:
    """Backward-compatible one-step pipeline for API clients."""
    preview = preview_receipt(file_bytes, filename)
    if preview["status"] == "error":
        return preview
    return commit_receipt(
        filename=filename,
        new_name=preview["new_name"],
        source_dir=source_dir,
        mode=mode,
        output_dir=output_dir,
        expected_fingerprint=preview["fingerprint"],
    )
