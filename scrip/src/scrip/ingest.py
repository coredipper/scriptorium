"""`scrip ingest` — bring a source into ``vault/raw/`` (the INGEST step of
AGENT.md), the input side of the answer ladder.

Fetch a URL or read a local file, extract its **canonical text**, and write
``raw/<slug>.md`` + ``raw/<slug>.meta.yaml``. The stored text is what everything
downstream hashes and cites, so extraction quality matters: HTML and PDF go
through the optional ``[ingest]`` extra (trafilatura / pypdf), while ``.md`` /
``.txt`` are passthrough. Without the extra, ``.md`` / ``.txt`` still ingest and
HTML/PDF raise a clear "install the extra" message.

The network *fetch* (``fetch``) is deliberately separate from the pure
*extract + write* (``extract_text`` / ``write_source``) so the latter is
hermetically testable on local bytes with no network and no LLM.
"""

from __future__ import annotations

import importlib
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml

from . import raw_dir
from .errors import DataError, UsageError

_SUFFIX_KIND = {
    ".md": "md",
    ".markdown": "md",
    ".txt": "txt",
    ".text": "txt",
    ".html": "html",
    ".htm": "html",
    ".pdf": "pdf",
}


def _import(name: str):
    """Import an optional backend, or ``None`` if it is not installed. Indirected
    so tests can simulate the missing-extra path."""
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower().strip()).strip("-")
    return s or "source"


def default_slug(source: str) -> str:
    """Derive a vault slug from a URL or path (its basename, slugified)."""
    if source.startswith(("http://", "https://")):
        parsed = urlparse(source)
        stem = Path(parsed.path).stem or parsed.netloc
    else:
        stem = Path(source).stem
    return _slugify(stem)


def _kind_from_suffix(suffix: str) -> str:
    # Unknown extensions are treated as plain text (notes are often extensionless).
    return _SUFFIX_KIND.get(suffix.lower(), "txt")


def _kind_from_content_type(ctype: str, url: str) -> str:
    if "pdf" in ctype:
        return "pdf"
    if "html" in ctype:
        return "html"
    if "markdown" in ctype:
        return "md"
    if ctype.startswith("text/"):
        return "txt"
    # Fall back to the URL path's extension; default HTML for the web.
    suffix = Path(urlparse(url).path).suffix
    return _SUFFIX_KIND.get(suffix.lower(), "html")


def fetch(source: str) -> tuple[bytes, str]:
    """Return ``(bytes, kind)`` for ``source``. URLs hit the network; everything
    else is read from disk. ``kind`` ∈ {md, txt, html, pdf}. Fetch/read failures
    surface as ``UsageError`` (exit 2), not an internal error."""
    if source.startswith(("http://", "https://")):
        return _fetch_url(source)
    p = Path(source).expanduser()
    if not p.is_file():
        raise UsageError(f"no such file: {source}")
    try:
        return p.read_bytes(), _kind_from_suffix(p.suffix)
    except OSError as e:
        raise UsageError(f"could not read {source}: {e}") from e


def _fetch_url(url: str) -> tuple[bytes, str]:  # network — not exercised in tests
    req = urllib.request.Request(url, headers={"User-Agent": "scrip-ingest/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (http(s) only)
            data = resp.read()
            ctype = resp.headers.get_content_type()
    except urllib.error.HTTPError as e:
        raise UsageError(f"could not fetch {url}: HTTP {e.code} {e.reason}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise UsageError(f"could not fetch {url}: {reason}") from e
    return data, _kind_from_content_type(ctype, url)


def _canonical(text: str) -> str:
    """Normalize line endings to LF and guarantee exactly one trailing newline."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip("\n") + "\n" if text.strip() else ""


def extract_text(data: bytes, kind: str) -> str:
    """Extract canonical text from ``data`` according to ``kind``."""
    if kind in ("md", "txt"):
        return _canonical(data.decode("utf-8", errors="replace"))
    if kind == "html":
        return _canonical(_extract_html(data))
    if kind == "pdf":
        return _canonical(_extract_pdf(data))
    raise UsageError(f"unsupported source kind: {kind}")


def _extract_html(data: bytes) -> str:
    trafilatura = _import("trafilatura")
    if trafilatura is None:
        raise UsageError(
            "HTML ingest needs the [ingest] extra: "
            "uv tool install './scrip[ingest]'  (or: pip install 'scrip[ingest]')"
        )
    # Pass the raw bytes so trafilatura detects the declared/actual charset
    # itself; pre-decoding as UTF-8 would corrupt Windows-1252/Latin-1 pages in
    # the canonical raw text. Markdown output keeps headings (feeds block deps).
    text = trafilatura.extract(data, output_format="markdown", include_comments=False)
    if not text:
        raise DataError("could not extract article text from the HTML")
    return text


def _extract_pdf(data: bytes) -> str:
    pypdf = _import("pypdf")
    if pypdf is None:
        raise UsageError(
            "PDF ingest needs the [ingest] extra: "
            "uv tool install './scrip[ingest]'  (or: pip install 'scrip[ingest]')"
        )
    import io

    reader = pypdf.PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    if not text:
        raise DataError("could not extract any text from the PDF (is it scanned?)")
    return text


def extract_metadata(data: bytes, kind: str) -> dict:
    """Best-effort bibliographic metadata from the source itself (HTML only).
    Defensive: any failure yields ``{}``. Explicit ``--title``/``--author`` win."""
    if kind != "html":
        return {}
    trafilatura = _import("trafilatura")
    if trafilatura is None:
        return {}
    try:
        doc = trafilatura.extract_metadata(data)  # bytes — charset handled inside
    except Exception:  # noqa: BLE001 — metadata is best-effort, never fatal
        return {}
    out = {}
    for key in ("title", "author"):
        val = getattr(doc, key, None) if doc is not None else None
        if val:
            out[key] = val
    return out


def build_meta(*, source: str, title: str | None, author: str | None) -> dict:
    """Assemble the bibliographic sidecar. ``retrieved`` is the ingest time;
    ``url`` is set only when the source was fetched from the web. The sidecar is
    metadata — never hashed, never cited (SPEC §2.1)."""
    is_url = source.startswith(("http://", "https://"))
    meta = {
        "title": title,
        "author": author,
        "url": source if is_url else None,
        "retrieved": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return {k: v for k, v in meta.items() if v is not None}


def write_source(root: Path, slug: str, text: str, meta: dict, *, overwrite: bool) -> dict:
    """Write ``raw/<slug>.md`` + ``.meta.yaml``. Refuses to clobber an existing
    source unless ``overwrite`` (the deliberate ``--reingest``). Must be called
    while holding the write lock."""
    rd = raw_dir(root)
    rd.mkdir(parents=True, exist_ok=True)
    md = rd / f"{slug}.md"
    try:
        with md.open("w" if overwrite else "x", encoding="utf-8") as f:
            f.write(text)
    except FileExistsError:
        raise UsageError(
            f"raw/{slug} already exists (raw sources are immutable); "
            f"pass --reingest to replace it as a tracked re-ingest"
        ) from None
    (rd / f"{slug}.meta.yaml").write_text(
        yaml.safe_dump(meta, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return {"id": f"raw/{slug}", "path": str(md.relative_to(root))}
