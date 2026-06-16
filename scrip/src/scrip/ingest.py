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


def fetch(source: str) -> tuple[bytes, str, str | None]:
    """Return ``(bytes, kind, charset)`` for ``source``. URLs hit the network and
    surface their HTTP ``Content-Type`` charset (which the HTML5 encoding spec
    ranks above any in-document ``<meta charset>``); local files have no header
    charset (``None``) and rely on in-document detection. ``kind`` ∈ {md, txt,
    html, pdf}. Fetch/read failures surface as ``UsageError`` (exit 2)."""
    if source.startswith(("http://", "https://")):
        return _fetch_url(source)
    p = Path(source).expanduser()
    if not p.is_file():
        raise UsageError(f"no such file: {source}")
    try:
        return p.read_bytes(), _kind_from_suffix(p.suffix), None
    except OSError as e:
        raise UsageError(f"could not read {source}: {e}") from e


def _fetch_url(url: str) -> tuple[bytes, str, str | None]:  # network — not in tests
    req = urllib.request.Request(url, headers={"User-Agent": "scrip-ingest/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (http(s) only)
            data = resp.read()
            ctype = resp.headers.get_content_type()
            charset = resp.headers.get_content_charset()
    except urllib.error.HTTPError as e:
        raise UsageError(f"could not fetch {url}: HTTP {e.code} {e.reason}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise UsageError(f"could not fetch {url}: {reason}") from e
    return data, _kind_from_content_type(ctype, url), charset


def _canonical(text: str) -> str:
    """Normalize line endings to LF and guarantee exactly one trailing newline."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip("\n") + "\n" if text.strip() else ""


# The complete WHATWG Encoding Standard label set for windows-1252. HTML parsing
# decodes all of these as windows-1252; Python's iso-8859-1 codec is *true*
# Latin-1, which would turn CP1252 punctuation bytes (smart quotes/dashes,
# 0x80–0x9F) into C1 controls. Match WHATWG: trim + lowercase, then exact-match.
_CP1252_ALIASES = frozenset(
    {
        "ansi_x3.4-1968",
        "ascii",
        "cp1252",
        "cp819",
        "csisolatin1",
        "ibm819",
        "iso-8859-1",
        "iso-ir-100",
        "iso8859-1",
        "iso88591",
        "iso_8859-1",
        "iso_8859-1:1987",
        "l1",
        "latin1",
        "us-ascii",
        "windows-1252",
        "x-cp1252",
    }
)


def _resolve_charset(label: str) -> str:
    label = label.strip().lower()
    return "cp1252" if label in _CP1252_ALIASES else label


def _decode(data: bytes, charset: str | None) -> str:
    """Decode bytes with a WHATWG-normalized charset, falling back to UTF-8 on an
    unknown codec name (``LookupError``); bad bytes are always replaced."""
    enc = _resolve_charset(charset) if charset else "utf-8"
    try:
        return data.decode(enc, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def extract_text(data: bytes, kind: str, charset: str | None = None) -> str:
    """Extract canonical text from ``data`` according to ``kind``. ``charset``, if
    given (an HTTP header charset), is used to decode rather than guessing."""
    if kind in ("md", "txt"):
        return _canonical(_decode(data, charset))
    if kind == "html":
        return _canonical(_extract_html(data, charset))
    if kind == "pdf":
        return _canonical(_extract_pdf(data))
    raise UsageError(f"unsupported source kind: {kind}")


def _html_for_trafilatura(data: bytes, charset: str | None):
    """A header-declared charset wins (HTML5 ranks it above any in-document
    <meta charset>), so decode with it (WHATWG-normalized); otherwise hand
    trafilatura the raw bytes and let it detect the in-document charset."""
    if not charset:
        return data
    try:
        return data.decode(_resolve_charset(charset), errors="replace")
    except LookupError:  # unknown charset name → fall back to byte detection
        return data


def _extract_html(data: bytes, charset: str | None = None) -> str:
    trafilatura = _import("trafilatura")
    if trafilatura is None:
        raise UsageError(
            "HTML ingest needs the [ingest] extra: "
            "uv tool install 'scriptoria[ingest]'  (or: pip install 'scriptoria[ingest]')"
        )
    # Markdown output keeps headings (feeds block-precise dependencies).
    text = trafilatura.extract(
        _html_for_trafilatura(data, charset),
        output_format="markdown",
        include_comments=False,
    )
    if not text:
        raise DataError("could not extract article text from the HTML")
    return text


def _extract_pdf(data: bytes) -> str:
    pypdf = _import("pypdf")
    if pypdf is None:
        raise UsageError(
            "PDF ingest needs the [ingest] extra: "
            "uv tool install 'scriptoria[ingest]'  (or: pip install 'scriptoria[ingest]')"
        )
    import io

    reader = pypdf.PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    if not text:
        raise DataError("could not extract any text from the PDF (is it scanned?)")
    return text


def extract_metadata(data: bytes, kind: str, charset: str | None = None) -> dict:
    """Best-effort bibliographic metadata from the source itself (HTML only).
    Defensive: any failure yields ``{}``. Explicit ``--title``/``--author`` win."""
    if kind != "html":
        return {}
    trafilatura = _import("trafilatura")
    if trafilatura is None:
        return {}
    try:
        doc = trafilatura.extract_metadata(_html_for_trafilatura(data, charset))
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
