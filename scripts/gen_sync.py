"""Generate sync mirrors of the _async/ trees.

    uv run python scripts/gen_sync.py            # regenerate
    uv run python scripts/gen_sync.py --check    # drift check (exit 1 on diff)

Pipeline: token-rewrite via :class:`_ProseRule` → prepend header →
``ruff format`` (skipped if absent) → write-if-changed or check.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tokenize as std_tokenize
from pathlib import Path

import tokenize_rt
import unasync

ROOT = Path(__file__).resolve().parents[1]

ADDITIONAL_REPLACEMENTS = {
    "AsyncClient": "Client",
    "acreate_client": "create_client",
    "aclose": "close",
    "_async": "_sync",
}

_PROSE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\basync\s+with\b"), "with"),
    (re.compile(r"\basync\s+for\b"), "for"),
    (re.compile(r"\basync\s+def\b"), "def"),
    (re.compile(r"\bawait\s+(?=\S)"), ""),
    (re.compile(r"\bAsyncClient\b"), "Client"),
    (re.compile(r"\bacreate_client\b"), "create_client"),
    (re.compile(r"\basynccontextmanager\b"), "contextmanager"),
    (re.compile(r"\bAsyncIterator\b"), "Iterator"),
    (re.compile(r"\bAsyncIterable\b"), "Iterable"),
    (re.compile(r"\bAsyncGenerator\b"), "Generator"),
    (re.compile(r"\bcoroutines\b"), "functions"),
    (re.compile(r"\bcoroutine\b"), "function"),
    (re.compile(r"\bawaitable\b"), "callable"),
    (re.compile(r"\basynchronously\b"), "synchronously"),
    (re.compile(r"\basynchronous\b"), "synchronous"),
    (re.compile(r"\bAsync\s+"), ""),
    (re.compile(r"\basync\s+"), ""),
)

# Everything between these markers (inclusive) is dropped from the sync mirror.
_SKIP_START = re.compile(r"#\s*gen_sync:\s*skip-block\b")
_SKIP_END = re.compile(r"#\s*gen_sync:\s*end-skip\b")

_HEADER = """\
# DO NOT EDIT — generated from {source} by scripts/gen_sync.py.
# Run `python scripts/gen_sync.py` (or rebuild the package) to regenerate.

"""


def _rewrite_prose(text: str) -> str:
    for pat, repl in _PROSE_PATTERNS:
        text = pat.sub(repl, text)
    return text


class _ProseRule(unasync.Rule):
    """``unasync.Rule`` extended with docstring/comment regex and the
    ``# gen_sync: skip-block`` directive."""

    _PROSE_TOKEN_NAMES = frozenset({"STRING", "COMMENT", "FSTRING_MIDDLE"})

    def _unasync_tokens(self, tokens):
        skip_next = False
        skipping = False
        for token in tokens:
            if token.name == "COMMENT":
                if skipping:
                    if _SKIP_END.search(token.src):
                        skipping = False
                    continue
                if _SKIP_START.search(token.src):
                    skipping = True
                    continue

            if skipping:
                continue

            if skip_next:
                skip_next = False
                continue

            if token.src in ("async", "await"):
                skip_next = True
                continue

            new_src = token.src
            if token.name == "NAME":
                new_src = self._unasync_name(new_src)
            elif token.name == "STRING" and len(new_src) >= 2:
                left, inner, right = new_src[0], new_src[1:-1], new_src[-1]
                new_src = left + self._unasync_name(inner) + right
            if token.name in self._PROSE_TOKEN_NAMES:
                new_src = _rewrite_prose(new_src)
            if new_src != token.src:
                token = token._replace(src=new_src)
            yield token


RULES = (
    _ProseRule(
        fromdir="/src/supabase_orm/_async/",
        todir="/src/supabase_orm/_sync/",
        additional_replacements=ADDITIONAL_REPLACEMENTS,
    ),
    _ProseRule(
        fromdir="/tests/_async/",
        todir="/tests/_sync/",
        additional_replacements=ADDITIONAL_REPLACEMENTS,
    ),
)


def _files_for_rule(rule: _ProseRule) -> list[Path]:
    src_root = ROOT / rule.fromdir.strip("/")
    if not src_root.exists():
        return []
    return sorted(src_root.rglob("*.py"))


def _render_file(rule: _ProseRule, filepath: Path) -> tuple[Path, bytes]:
    """Run ``rule`` over ``filepath`` and return ``(out_path, content_bytes)``."""
    with open(filepath, "rb") as f:
        encoding, _ = std_tokenize.detect_encoding(f.readline)
    with open(filepath, encoding=encoding) as f:
        tokens = tokenize_rt.src_to_tokens(f.read())
        tokens = rule._unasync_tokens(tokens)
        body = tokenize_rt.tokens_to_src(tokens)

    rel_source = filepath.relative_to(ROOT).as_posix()
    out_path = Path(str(filepath).replace(rule.fromdir, rule.todir))
    content = (_HEADER.format(source=rel_source) + body).encode(encoding)
    return out_path, content


def _format_with_ruff(outputs: dict[Path, bytes]) -> dict[Path, bytes]:
    """Pipe each generated file through ``ruff format``. No-op on missing ruff."""
    try:
        subprocess.run(["ruff", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return outputs

    formatted: dict[Path, bytes] = {}
    for path, content in outputs.items():
        try:
            proc = subprocess.run(
                ["ruff", "format", "--stdin-filename", str(path), "-"],
                input=content,
                capture_output=True,
                check=True,
            )
            formatted[path] = proc.stdout
        except subprocess.CalledProcessError as exc:
            sys.stderr.write(f"ruff format failed on {path}:\n{exc.stderr.decode()}\n")
            raise
    return formatted


def _render_all() -> dict[Path, bytes]:
    outputs: dict[Path, bytes] = {}
    for rule in RULES:
        for src in _files_for_rule(rule):
            out_path, content = _render_file(rule, src)
            outputs[out_path] = content
    if not outputs:
        raise SystemExit("gen_sync: no source files found under _async/ dirs.")
    return _format_with_ruff(outputs)


def _write_if_changed(outputs: dict[Path, bytes]) -> list[Path]:
    """Write only files whose content differs. Returns the changed paths."""
    changed: list[Path] = []
    for path, content in outputs.items():
        if path.exists() and path.read_bytes() == content:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        changed.append(path)
    return changed


def _check(outputs: dict[Path, bytes]) -> int:
    """Compare against the committed tree. Returns 0 (clean) or 1 (drift)."""
    drift: list[Path] = []
    for path, content in outputs.items():
        actual = path.read_bytes() if path.exists() else b""
        if actual != content:
            drift.append(path)
    if not drift:
        return 0
    sys.stderr.write(
        "gen_sync: drift detected. The following generated files are stale "
        "(run `python scripts/gen_sync.py` to regenerate):\n"
    )
    for path in drift:
        sys.stderr.write(f"  {path.relative_to(ROOT)}\n")
    return 1


def regenerate() -> list[Path]:
    """Programmatic entry point used by ``hatch_build.py`` — no CLI parsing.
    Returns the files that were written."""
    outputs = _render_all()
    return _write_if_changed(outputs)


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if regenerating would change any file. Doesn't write.",
    )
    args = parser.parse_args(argv)

    outputs = _render_all()
    if args.check:
        return _check(outputs)
    changed = _write_if_changed(outputs)
    if changed:
        sys.stderr.write(f"gen_sync: wrote {len(changed)} file(s).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
