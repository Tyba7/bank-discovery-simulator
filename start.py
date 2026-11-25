# /// script
# requires-python = ">=3.11"
# ///
"""Start the app with one command, on macOS, Linux or Windows:

    uv run start.py

The first time, it asks for an OpenAI API key and a model name, writes backend/.env with the preset settings,
installs and builds the web interface, and starts the server. Later runs just start it. Developers can edit
backend/.env (see .env.example) for another provider or a local model.
"""

import getpass
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV = ROOT / "backend" / ".env"
EXAMPLE = ROOT / "backend" / ".env.example"
DEFAULT_MODEL = "gpt-4.1-mini"


def write_settings() -> None:
    key = (os.environ.get("OPENAI_API_KEY") or getpass.getpass("OpenAI API key (hidden while you paste): ")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        sys.exit("That does not look like an OpenAI API key. Run this again and paste the key.")
    model = (os.environ.get("OPENAI_MODEL") or input(f"Model [press Enter for {DEFAULT_MODEL}]: ")).strip()
    model = model or DEFAULT_MODEL
    if not re.fullmatch(r"[A-Za-z0-9._:/-]+", model):
        sys.exit("That does not look like a model name.")
    preset = {
        "LLM_BASE_URL": "https://api.openai.com/v1",
        "LLM_API_KEY": key,
        "LLM_MODEL": model,
        "LLM_EXTRA_BODY": "",
    }
    text = EXAMPLE.read_text()
    for name, value in preset.items():
        text = re.sub(rf"^{name}=.*$", f"{name}={value}", text, flags=re.MULTILINE)
    ENV.write_text(text)  # git ignores backend/.env, so the key stays on this computer
    print(f"Saved. Using OpenAI model {model}.")


def main() -> None:
    npm = shutil.which("npm")
    if not npm:
        sys.exit("Node.js is missing. Install the LTS version from https://nodejs.org, reopen the terminal, run again.")
    if ENV.exists():
        print("Using the settings in backend/.env (delete that file to enter a new key or model).")
    else:
        write_settings()
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        print("Installing and building the web interface (first run only, a minute or two)...")
        subprocess.run([npm, "--prefix", "frontend", "ci", "--no-audit", "--no-fund"], cwd=ROOT, check=True)
        subprocess.run([npm, "--prefix", "frontend", "run", "build"], cwd=ROOT, check=True)
    port = os.environ.get("PORT", "8000")
    print(f"Starting. When you see 'Application startup complete', open http://localhost:{port}")
    print("To stop the app, press Ctrl+C in this window.")
    uv = shutil.which("uv") or "uv"
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}  # this script's own env is not the backend's
    subprocess.run([uv, "--directory", "backend", "run", "uvicorn", "app.main:app", "--port", port], cwd=ROOT, env=env)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
    except subprocess.CalledProcessError as e:
        sys.exit(f"A setup step failed ({' '.join(map(str, e.cmd[1:3]))}). See the messages above.")
