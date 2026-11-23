import hashlib
import json
from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
VARIANTS_DIR = PROMPTS_DIR / "variants"


class Prompt:
    """A versioned prompt file. A variant (prompts/variants/<name>/<prompt>.md) overrides the default when present."""

    def __init__(self, name: str, variant: str | None = None):
        path = VARIANTS_DIR / variant / f"{name}.md" if variant else None
        if path is None or not path.exists():
            path = PROMPTS_DIR / f"{name}.md"
        self.name = name
        self.text = path.read_text()
        self.version = hashlib.sha256(self.text.encode()).hexdigest()[:12]  # recorded in every trace

    def render(self, **values: str) -> str:
        return Template(self.text).substitute(values)  # $placeholders, so JSON braces in prompts are safe


def variant_options(variant: str | None) -> dict:
    """Code switches that belong to a variant (prompts/variants/<name>/variant.json); none for the default."""
    if not variant:
        return {}
    folder = VARIANTS_DIR / variant
    if not folder.is_dir():
        raise ValueError(f"Unknown prompt variant '{variant}': no folder {folder}")
    options = folder / "variant.json"
    return json.loads(options.read_text()) if options.exists() else {}
