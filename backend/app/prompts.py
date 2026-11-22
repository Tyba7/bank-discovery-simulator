import hashlib
from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


class Prompt:
    def __init__(self, name: str):
        self.name = name
        self.text = (PROMPTS_DIR / f"{name}.md").read_text()
        self.version = hashlib.sha256(self.text.encode()).hexdigest()[:12]  # recorded in every trace

    def render(self, **values: str) -> str:
        return Template(self.text).substitute(values)  # $placeholders, so JSON braces in prompts are safe
