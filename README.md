# AI Survey App

A lightweight Flask web app to run human evaluations of AI‑generated images. Participants view images in parts (A/B), answer short questions, and submit feedback that is saved locally. Designed for rapid studies comparing multiple image models.

> Repo: https://github.com/ukhalilov/ai-survey-app

## Features
- Simple, mobile‑friendly pages with Jinja templates (`templates/`)
- Two survey flows (Part A & Part B) with a final “Thanks” screen
- Config‑driven storage paths via `config.yaml`
- Reads pre‑generated images and optional `manifest.csv` files
- Saves responses to disk (CSV/JSON) for later analysis
- Ready for local dev and Render.com deployment (`render.yaml`)

## Project Structure (high‑level)
```
ai-survey-app/
├─ app.py                # Flask app entrypoint & routes
├─ config.yaml           # Paths & app options
├─ requirements.txt      # Python dependencies
├─ render.yaml           # Render.com service definition (optional)
├─ static/               # CSS/JS/assets
└─ templates/            # Jinja templates (index, onboarding, no_data, thanks, etc.)
```
Templates commonly used: `index.html`, `onboarding.html`, `no_data.html`, `thanks.html`.

## Prerequisites
- Python 3.10+ recommended
- Git
- (Optional) A folder with images and an optional `manifest.csv` (see “Data layout”)

## Installation (Local)
```bash
git clone https://github.com/ukhalilov/ai-survey-app.git
cd ai-survey-app
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

If `requirements.txt` is empty or missing items, install your needs manually, then export:
```bash
pip install flask pyyaml pandas
pip freeze > requirements.txt
```

## Configuration
Edit `config.yaml`. Minimal example:
```yaml
storage:
  root: "/data/storage"          # where responses & runtime files are written
  fallback_root: "/data/storage" # used if root is not writable
data:
  images_root: "/var/data/research/images"   # where your survey images live
  manifests_root: "/var/data/research/manifests" # where manifest.csv lives
app:
  title: "AI Survey"
  debug: true
```

You can also override common paths with environment variables:
- `SURVEY_STORAGE` – preferred writable folder for outputs (e.g., `/data/storage`)
- `SURVEY_STORAGE_FALLBACK` – fallback writable folder

The app will try `SURVEY_STORAGE` first; if not writable, it falls back to `SURVEY_STORAGE_FALLBACK` or the values in `config.yaml`.

## Data layout
You can point the app to your dataset using `config.yaml`. A typical layout:
```
/var/data/research/
├─ images/
│  ├─ modelA/...
│  ├─ modelB/...
│  └─ ...
└─ manifests/
   └─ run-YYYYMMDD_HHMMSS/
      └─ manifest.csv
```
- `manifest.csv` can include columns like: `image_path`, `prompt`, `model`, `seed`, etc.
- If no data is found, the app renders a friendly “No data” page.

## Run (Local)
```bash
# In the project root (after activating the venv)
export FLASK_ENV=development      # Windows: set FLASK_ENV=development
python app.py
# App starts on http://127.0.0.1:5000 (or the PORT env if set)
```
Environment variables:
- `PORT` – override port if your host requires it (e.g., Render sets `PORT`)
- `FLASK_ENV=development` – dev mode with hot‑reload

## Deploy to Render.com
1. Push this repo to GitHub (already done).
2. In Render, create a **Web Service** from the repo.
3. Use a **persistent disk** for survey outputs and datasets.
   - Common mount: `/data/storage` for responses; `/var/data/research` for images/manifests.
4. Confirm `render.yaml` or set:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python app.py`
5. Set Environment:
   - `SURVEY_STORAGE=/data/storage`
   - `SURVEY_STORAGE_FALLBACK=/data/storage`
   - (Optionally) `FLASK_ENV=production`
6. Upload/copy your image dataset & manifests to the mounted path.

> Note: Render containers don’t provide `sudo` in the shell. Prefer app‑level Python tools or pre‑build steps.

## Routes (typical)
- `/` – Landing or Part selection
- `/part-a` – Part A flow
- `/part-b` – Part B flow
- `/thanks` – Final page after submit

## Saving responses
By default, responses are written to the storage root in subfolders like:
```
/data/storage/
└─ responses/
   ├─ part_a.csv
   ├─ part_b.csv
   └─ logs/*.json
```
Adjust paths in `config.yaml` as needed.

## Troubleshooting
- **“No data” page shows** → Check `images_root` and/or `manifests_root` in `config.yaml`. Make sure the mounted disk paths exist in the container and are readable.
- **Can’t write responses** → Ensure `SURVEY_STORAGE` is a mounted, writable path. On Render attach a persistent disk and point to it.
- **`pip freeze` empty** → Your venv may be inactive or you installed into the system interpreter. Activate venv and reinstall, then run `pip freeze > requirements.txt`.
- **`sudo: command not found` on Render shell** → Expected. Use app dependencies via `pip`, or rebuild the service with updated `requirements.txt`.

## License
MIT (or your preferred license).

## Acknowledgements
Built by Ulugbek Khalilov for evaluating image‑generation models with structured human feedback.