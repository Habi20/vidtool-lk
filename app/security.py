"""Pure validation helpers. No I/O, no framework imports, so they are trivial to unit test."""
import re
from pathlib import Path

from .config import ALLOWED_EXT

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_BAD_NAME_CHARS = re.compile(r"[^\w.\- ()]+")


def validate_ext(filename: str) -> str:
    """Return the lowercase extension if allowed, else raise ValueError."""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValueError(f"Unsupported file type '{ext or 'none'}'")
    return ext


def display_name(filename: str) -> str:
    """Name for the UI only. Never used to build a filesystem path."""
    base = Path(filename or "video").name
    return _BAD_NAME_CHARS.sub("_", base)[:120] or "video"


def parse_id(value: str) -> str:
    """IDs are uuid4().hex. Anything else (../, wildcards, SQL) is rejected."""
    if not isinstance(value, str) or not _HEX32.match(value):
        raise ValueError("Invalid id")
    return value


def is_within(base: Path, target: Path) -> bool:
    """Defense in depth against path traversal."""
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def host_only(host_header: str) -> str:
    """'127.0.0.1:8765' -> '127.0.0.1'."""
    return (host_header or "").rsplit(":", 1)[0] if ":" in (host_header or "") else (host_header or "")


def deduplicate_names(names: list[str]) -> list[str]:
    """Ensure filenames are unique case-insensitively for safe extraction across platforms."""
    seen: dict[str, int] = {}
    result: list[str] = []
    for name in names:
        p = Path(name)
        stem, ext = p.stem, p.suffix
        lower_key = name.lower()
        if lower_key not in seen:
            seen[lower_key] = 1
            result.append(name)
        else:
            count = 2
            candidate = f"{stem} ({count}){ext}"
            while candidate.lower() in seen:
                count += 1
                candidate = f"{stem} ({count}){ext}"
            seen[candidate.lower()] = 1
            result.append(candidate)
    return result
