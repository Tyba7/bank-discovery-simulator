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
    model = os.environ.get("OPENAI_MODEL", "")
    if not model and sys.stdin.isatty():  # nobody to answer in a script or CI: keep the default
        model = input(f"Model [press Enter for {DEFAULT_MODEL}]: ")
    model = model.strip() or DEFAULT_MODEL
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
    os.chmod(ENV, 0o600)  # readable by this user only (no effect on Windows)
    print(f"Saved. Using OpenAI model {model}.", flush=True)


def check_node() -> str:
    npm, node = shutil.which("npm"), shutil.which("node")
    if not npm or not node:
        sys.exit("Node.js is missing. Install the LTS version from https://nodejs.org, reopen the terminal, run again.")
    version = subprocess.run(
        [node, "--version"], check=False, capture_output=True, text=True
    ).stdout.strip()  # e.g. v22.12.0
    major = int(version.lstrip("v").split(".")[0]) if version[1:2].isdigit() else 0
    if major < 22:
        sys.exit(f"Node.js {version or '(unknown)'} is too old. Install version 22 or newer from https://nodejs.org.")
    return npm


def newest(*paths: Path) -> float:
    return max(
        (f.stat().st_mtime for p in paths if p.exists() for f in ([p] if p.is_file() else p.rglob("*"))), default=0
    )


def build_frontend(npm: str) -> None:
    """Install when the lockfile changed, build when the sources changed: a git pull never leaves an old UI."""
    front = ROOT / "frontend"
    lock, installed, built = front / "package-lock.json", front / "node_modules" / ".package-lock.json", front / "dist"
    if not installed.exists() or lock.stat().st_mtime > installed.stat().st_mtime:
        print("Installing the web interface's packages (first run, a minute or two)...", flush=True)
        subprocess.run([npm, "--prefix", "frontend", "ci", "--no-audit", "--no-fund"], cwd=ROOT, check=True)
    sources = newest(front / "src", front / "index.html", front / "vite.config.ts", lock)
    if not (built / "index.html").exists() or sources > newest(built / "index.html"):
        print("Building the web interface...", flush=True)
        subprocess.run([npm, "--prefix", "frontend", "run", "build"], cwd=ROOT, check=True)


def main() -> None:
    npm = check_node()
    if ENV.exists():
        print("Using the settings in backend/.env (delete that file to enter a new key or model).")
    else:
        write_settings()
    build_frontend(npm)
    port = os.environ.get("PORT", "8000")
    if not port.isdigit():
        sys.exit(f"PORT must be a number, not {port!r}.")
    print(f"Starting. When you see 'Application startup complete', open http://localhost:{port}", flush=True)
    print("To stop the app, press Ctrl+C in this window.", flush=True)
    uv = shutil.which("uv") or "uv"
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}  # this script's own env is not the backend's
    subprocess.run(
        [uv, "--directory", "backend", "run", "uvicorn", "app.main:app", "--port", port], check=False, cwd=ROOT, env=env
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
    except subprocess.CalledProcessError as e:
        sys.exit(f"A setup step failed ({' '.join(map(str, e.cmd[1:3]))}). See the messages above.")
