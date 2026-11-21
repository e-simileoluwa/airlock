"""Issue #96 / task 9.71: a relative link in the root docs has to resolve.

`AGENTS.md` gives a read order and `CONTRIBUTING.md` repeats four of those links in one sentence,
so the first paths a contributor follows are Markdown, and nothing read them. `tests/unit/
test_site.py` resolves internal links for the generated pages only; pytest does not parse Markdown
and ruff does not check links, so a renamed file leaves a dead path in the documents a reader
starts from and every gate stays green.

This walks the root `*.md` files and `docs/**/*.md`, finds inline links with a small regex, and
resolves each relative target against the directory of the file that holds it. Standard library
only, per `AGENTS.md` 4: no Markdown parser and no link checker.

What is skipped, and why:

- A target that starts with `#` is an anchor in the same document. Anchors are a heading
  question, and `tests/unit/test_site.py` already owns ids for the pages it parses.
- A target that starts with `http://`, `https://` or `mailto:` leaves the repository, and the
  suite never opens a socket (`AGENTS.md` 5), so the check is that the target is spelled as an
  absolute address, not that it answers.
- An image source (`![alt](path)`) is fetched by a browser from the published page, not read as a
  document path, and the site test already resolves the assets that page references.
- A fenced code block is a command or a sample, not prose, so a path inside one is not a link.
  Inline code spans are masked for the same reason before the link regex runs.
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: A floor on the number of resolved links, so a moved glob that matches less than it should
#: cannot pass by finding nothing. The tree held well over this many when the test was written.
MINIMUM_LINKS = 30

#: Inline link with an optional image bang, an optional title, and an angle-bracketed target.
_LINK = re.compile(
    r"(?P<image>!?)\[(?P<text>[^\]]*)\]"
    r"\((?P<target><[^>]*>|[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)
_FENCE = re.compile(r"^\s*(?:```|~~~)")
_INLINE_CODE = re.compile(r"`[^`]*`")

#: Prefixes that address something outside the repository.
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:")


def documents(root: Path) -> list[Path]:
    """Every Markdown document this test owns, in a stable order."""
    return sorted(root.glob("*.md")) + sorted((root / "docs").rglob("*.md"))


def links(text: str) -> list[tuple[int, str]]:
    """Every inline link target in one document as (one-based line, raw target)."""
    found: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        masked = _INLINE_CODE.sub(lambda match: " " * len(match.group(0)), line)
        for match in _LINK.finditer(masked):
            if match.group("image"):
                continue
            found.append((number, match.group("target")))
    return found


def relative_path(target: str) -> str | None:
    """The repository-relative part of a link, or None when there is nothing to resolve."""
    raw = target.strip().strip("<>")
    # A same-document anchor names a heading, not a path.
    if raw.startswith("#"):
        return None
    # An absolute address leaves the repository; the suite does not dial it.
    if raw.startswith(EXTERNAL_PREFIXES):
        return None
    path = urllib.parse.unquote(raw.split("#", 1)[0].split("?", 1)[0])
    return path or None


def broken_links(sources: Iterable[Path], root: Path) -> tuple[int, list[str]]:
    """Return (resolved count, failures as `source:line -> target`)."""
    resolved = 0
    broken: list[str] = []
    for source in sources:
        for number, target in links(source.read_text(encoding="utf-8")):
            path = relative_path(target)
            if path is None:
                continue
            base = root if path.startswith("/") else source.parent
            destination = (base / path.lstrip("/")).resolve()
            label = f"{source.relative_to(root).as_posix()}:{number} -> {target}"
            if not destination.is_relative_to(root):
                broken.append(f"{label} (escapes the repository)")
                continue
            if destination.exists():
                resolved += 1
            else:
                broken.append(label)
    return resolved, broken


def test_every_relative_link_resolves() -> None:
    resolved, broken = broken_links(documents(REPO_ROOT), REPO_ROOT)

    assert broken == [], "\n".join(broken)
    assert resolved >= MINIMUM_LINKS, f"only {resolved} links resolved, floor is {MINIMUM_LINKS}"


def test_a_missing_target_is_reported(tmp_path: Path) -> None:
    """The resolver reports the source and line, so a broken link is not a silent skip."""
    page = tmp_path / "page.md"
    page.write_text("fine [here](target.md) and broken [there](missing.md)\n", encoding="utf-8")
    (tmp_path / "target.md").write_text("# Target\n", encoding="utf-8")

    resolved, broken = broken_links([page], tmp_path)

    assert resolved == 1
    assert broken == ["page.md:1 -> missing.md"]
