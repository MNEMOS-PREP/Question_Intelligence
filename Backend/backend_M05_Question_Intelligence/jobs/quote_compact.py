"""Quote the prose fields of a compact bank file, in place.

    python -m backend_M05_Question_Intelligence.jobs.quote_compact bank/*.goal.yaml

Authors write stems and answers as plain text; YAML reads a ": " or " #"
inside plain text as structure. This wraps every `q:`, `a:`, `m:` and `f:`
value in double quotes (escaping what needs it) and leaves everything else
alone, so a file stays easy to write by hand and always parses.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

FIELD = re.compile(r"^(\s+)(q|a|m|f): (.+)$")


def _complete(value: str) -> bool:
    """Is this already one whole quoted or flow scalar YAML can read?"""
    if not value.startswith(('"', "'", "[")):
        return False
    try:
        parsed = yaml.safe_load(f"x: {value}")
    except yaml.YAMLError:
        return False
    return isinstance(parsed, dict) and set(parsed) == {"x"}


def quote(text: str) -> str:
    lines = []
    for line in text.splitlines():
        m = FIELD.match(line)
        if m and not m.group(3).startswith(("|", ">")) and not _complete(m.group(3)):
            value = m.group(3).replace("\\", "\\\\").replace('"', '\\"')
            line = f'{m.group(1)}{m.group(2)}: "{value}"'
        lines.append(line)
    return "\n".join(lines) + "\n"


def main() -> None:
    for name in sys.argv[1:]:
        path = Path(name)
        fixed = quote(path.read_text(encoding="utf-8"))
        yaml.safe_load(fixed)  # raises with a line number if anything else is wrong
        path.write_text(fixed, encoding="utf-8")
        print(f"ok {path.name}")


if __name__ == "__main__":
    main()
