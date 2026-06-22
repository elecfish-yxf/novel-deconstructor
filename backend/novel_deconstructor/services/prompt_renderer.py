from pathlib import Path
import re


VARIABLE_RE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


class PromptRenderer:
    def __init__(self, prompt_dir: Path | None = None):
        self.prompt_dir = prompt_dir or Path(__file__).resolve().parents[1] / "prompts"

    def load_builtin(self, mode: str) -> str:
        path = self.prompt_dir / f"{mode}.md"
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {mode}")
        return path.read_text(encoding="utf-8")

    def render(self, template: str, context: dict[str, object]) -> str:
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            value = context.get(key, "")
            return "" if value is None else str(value)

        return VARIABLE_RE.sub(replace, template)

    def render_builtin(self, mode: str, context: dict[str, object]) -> str:
        return self.render(self.load_builtin(mode), context)
