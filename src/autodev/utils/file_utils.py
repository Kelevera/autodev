"""File helpers: atomic writes, markdown-fence stripping, module-name mapping."""

from __future__ import annotations

import os
import re
from pathlib import Path

_FULL_FENCE = re.compile(r"^```[\w-]*\s*\n(.*?)\n?```\s*$", re.DOTALL)
_ANY_FENCE = re.compile(r"```[\w-]*\s*\n(.*?)```", re.DOTALL)


def atomic_write(path: str | Path, content: str) -> None:
    """Write content to path atomically (tmp file + os.replace)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, target)


def strip_code_fences(text: str) -> str:
    """Extract raw code from an LLM response that may be wrapped in fences.

    Handles a response that is exactly one fenced block, a response with
    surrounding prose (largest fenced block wins), or plain code (returned
    as-is). Always ends with a newline.
    """
    stripped = text.strip()
    match = _FULL_FENCE.match(stripped)
    if match:
        return match.group(1).strip() + "\n"
    blocks = _ANY_FENCE.findall(stripped)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    return stripped + "\n"


def module_name_for(path: str | Path) -> str:
    """Map a source path to its importable module name.

    Uses the path segments after a `src` directory when present
    (src/autodev/core/scanner.py -> autodev.core.scanner), otherwise the stem.
    """
    parts = Path(path).with_suffix("").parts
    if "src" in parts:
        return ".".join(parts[parts.index("src") + 1 :])
    return parts[-1]
