"""
Prompt library — loads system prompts from .txt files at call time.

Prompts live in src/prompts/*.txt so they can be iterated and diff-reviewed
independently of the Python code that calls them.
"""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """
    Load a prompt template from the prompts directory.

    Args:
        name: Filename stem (e.g. "bull_analyst" loads "bull_analyst.txt").

    Returns:
        The prompt text with leading/trailing whitespace stripped.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    path = PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {name}.txt (looked in {PROMPTS_DIR})")
    return path.read_text(encoding="utf-8").strip()
