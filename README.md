# Receipty

A local web app that uses AI to preview and apply clean, consistent receipt filenames.

**Before:** `IMG_4821.JPG`  
**After:** `10_6_24_Dinner_Mildreds_53.43.JPG`

### Format
```
DAY_MONTH_YEAR_What_Business_Cost.ext
```
- Date is British format (day/month/year), no leading zeros, 2-digit year
- Foreign currencies get a suffix — no suffix means GBP
- Examples:
  - `10_6_24_Dinner_Mildreds_53.43.JPG`
  - `3_7_24_Server_Boosts_Discord_54.89_USD.pdf`

---

## Requirements

- macOS
- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/settings/keys) (~£0.01 per receipt)

---

## Setup

**1. Clone the repo**
```bash
git clone https://github.com/YOUR_USERNAME/receipty.git
cd receipty
```

**2. Create a virtual environment and install dependencies**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**3. Set your Anthropic API key**

Get a key at https://console.anthropic.com/settings/keys, then add it permanently:
```bash
echo 'export ANTHROPIC_API_KEY="your-key-here"' >> ~/.zshrc
source ~/.zshrc
```

---

## Running

### Double-click on macOS

Build the local app once after cloning or moving the project:

```bash
./macos/build_app.sh
```

Then double-click **Receipty.app** in the project folder. It starts the local service
and opens Receipty in your default browser. Keep the app inside the project folder so
it can find the bundled Python environment.

Run the same build command again after changing the launcher or icon:

```bash
./macos/build_app.sh
```

### From Terminal

```bash
source venv/bin/activate
python3 app.py
```

Then open **http://localhost:5001** in your browser.

---

## How to use

1. Click **Browse** next to *Receipt folder* and select the folder containing your receipts
2. Choose **Rename in place** (renames files where they are) or **Copy to folder** (copies renamed files to a new location)
3. If copying, click **Browse** next to *Output folder* to choose the destination
4. Drag and drop your receipt images/PDFs onto the drop zone (or click it to browse)
5. Click **Preview names** and review the proposed filename for every receipt
6. Correct any proposal directly in the filename box, then click **Apply changes**

Receipty verifies that each source file is unchanged between preview and apply. Existing
files are never overwritten; a numeric suffix is added when a filename already exists.

### Optional settings

- Set `RECEIPTY_MODEL` to use a different Anthropic model ID.
- Set `RECEIPTY_PORT` to run the local app on a port other than `5001`.
- Set `FLASK_DEBUG=1` only when developing the app.

### Supported formats
- JPEG, PNG, WEBP, PDF (up to 50 MB each)

---

## Cost

Uses Claude Sonnet via the Anthropic API. Roughly **£0.01 per receipt**. You only pay for what you use — no subscription.
