"""`scrip ingest` — bring a source into vault/raw/.

Hermetic by construction: the network *fetch* is separate from the pure
*extract + write*, which is what these tests exercise (local bytes only). HTML/PDF
extraction needs the optional [ingest] extra, so those tests skip when it is
absent; the "extra missing" path is tested by monkeypatching the importer.
"""

import importlib.util

import pytest
import yaml

from scrip import cli, errors, ingest, lock_path, raw_dir

needs_trafilatura = pytest.mark.skipif(
    importlib.util.find_spec("trafilatura") is None, reason="needs the [ingest] extra"
)
needs_pypdf = pytest.mark.skipif(
    importlib.util.find_spec("pypdf") is None, reason="needs the [ingest] extra"
)

def _make_pdf(text: str) -> bytes:
    """Build a valid one-page PDF whose content stream draws ``text`` (with a
    correct xref table + startxref, which pypdf requires)."""
    stream = b"BT /F1 24 Tf 20 60 Td (" + text.encode("latin-1") + b") Tj ET"
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer<</Size %d/Root 1 0 R>>\n" % (len(objs) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % xref_pos
    return bytes(out)


# --- pure helpers -----------------------------------------------------------
def test_slugify_from_url():
    assert ingest.default_slug("https://example.com/blog/My-Post.html") == "my-post"


def test_slugify_from_path():
    assert ingest.default_slug("/tmp/Some Notes.md") == "some-notes"


def test_extract_md_passthrough():
    assert ingest.extract_text(b"# Title\n\nBody.\n", "md") == "# Title\n\nBody.\n"


def test_extract_txt_normalizes_crlf_and_trailing_newline():
    assert ingest.extract_text(b"a\r\nb", "txt") == "a\nb\n"


# --- CLI: local file ingest (no extractor needed) ---------------------------
def test_ingest_local_md_writes_raw_and_meta(kb, tmp_path):
    src = tmp_path / "note.md"
    src.write_text("# Note\n\nKeep this verbatim.\n", encoding="utf-8")
    assert cli.main(["ingest", str(src), "--root", str(kb.root)]) == 0
    assert (raw_dir(kb.root) / "note.md").read_text() == "# Note\n\nKeep this verbatim.\n"
    meta = yaml.safe_load((raw_dir(kb.root) / "note.meta.yaml").read_text())
    assert "retrieved" in meta


def test_ingest_custom_slug_and_title(kb, tmp_path):
    src = tmp_path / "x.md"
    src.write_text("text\n")
    cli.main(
        ["ingest", str(src), "--slug", "my-src", "--title", "My Source", "--root", str(kb.root)]
    )
    meta = yaml.safe_load((raw_dir(kb.root) / "my-src.meta.yaml").read_text())
    assert meta["title"] == "My Source"
    assert (raw_dir(kb.root) / "my-src.md").exists()


def test_ingest_refuses_overwrite_without_reingest(kb, tmp_path):
    src = tmp_path / "n.md"
    src.write_text("v1\n")
    assert cli.main(["ingest", str(src), "--slug", "s", "--root", str(kb.root)]) == 0
    src.write_text("v2\n")
    assert cli.main(["ingest", str(src), "--slug", "s", "--root", str(kb.root)]) == 2
    assert (raw_dir(kb.root) / "s.md").read_text() == "v1\n"  # immutable


def test_ingest_reingest_overwrites(kb, tmp_path):
    src = tmp_path / "n.md"
    src.write_text("v1\n")
    cli.main(["ingest", str(src), "--slug", "s", "--root", str(kb.root)])
    src.write_text("v2 changed\n")
    assert cli.main(["ingest", str(src), "--slug", "s", "--reingest", "--root", str(kb.root)]) == 0
    assert (raw_dir(kb.root) / "s.md").read_text() == "v2 changed\n"


def test_ingest_releases_lock(kb, tmp_path):
    src = tmp_path / "n.md"
    src.write_text("x\n")
    cli.main(["ingest", str(src), "--slug", "s", "--root", str(kb.root)])
    assert not lock_path(kb.root).exists()


def test_ingest_unsafe_slug_exit_2(kb, tmp_path):
    src = tmp_path / "n.md"
    src.write_text("x\n")
    assert cli.main(["ingest", str(src), "--slug", "../evil", "--root", str(kb.root)]) == 2


def test_ingest_missing_file_exit_2(kb):
    assert cli.main(["ingest", "/no/such/file.md", "--root", str(kb.root)]) == 2


# --- extractors -------------------------------------------------------------
@needs_trafilatura
def test_extract_html_strips_boilerplate():
    html = (
        b"<html><head><title>T</title></head><body>"
        b"<nav>Home About Login</nav>"
        b"<article><h1>Main Heading</h1><p>The important load-bearing sentence.</p></article>"
        b"<footer>Copyright boilerplate 2026</footer></body></html>"
    )
    text = ingest.extract_text(html, "html")
    assert "important load-bearing sentence" in text.lower()
    assert "copyright boilerplate" not in text.lower()


@needs_trafilatura
def test_ingest_html_autofills_title_from_page(kb, tmp_path):
    src = tmp_path / "page.html"
    src.write_text(
        "<html><head><title>Auto-Captured Title</title></head><body><article>"
        "<h1>Auto-Captured Title</h1><p>A sufficiently long article paragraph so the "
        "main-content extractor keeps it as the body of the page rather than "
        "discarding it.</p></article></body></html>",
        encoding="utf-8",
    )
    cli.main(["ingest", str(src), "--slug", "page", "--root", str(kb.root)])
    meta = yaml.safe_load((raw_dir(kb.root) / "page.meta.yaml").read_text())
    assert meta["title"] == "Auto-Captured Title"


@needs_trafilatura
def test_html_respects_declared_charset():
    """A non-UTF-8 page (here Windows-1252) must not be corrupted in the canonical
    raw text — decoding has to honor the declared charset, not assume UTF-8."""
    body = (
        "don’t panic — this windows-1252 article body is long enough that "
        "the main-content extractor keeps it as the page body."
    )
    html = (
        '<html><head><meta charset="windows-1252"><title>Enc</title></head>'
        "<body><article><h1>Enc</h1><p>" + body + "</p></article></body></html>"
    )
    data = html.encode("cp1252")
    text = ingest.extract_text(data, "html")
    assert "’" in text  # curly apostrophe survived
    assert "�" not in text  # not mangled to the replacement char


@needs_trafilatura
def test_html_uses_http_header_charset_when_no_meta():
    """When a page declares its charset only in the HTTP Content-Type header (no
    in-document <meta charset>), that charset must be honored — else header-only
    cp1252/Latin-1 pages corrupt the canonical raw text."""
    body = "résumé — a long enough latin-1/1252 article body for the extractor to keep."
    html = (
        "<html><head><title>Enc</title></head><body><article><h1>Enc</h1><p>"
        + body
        + "</p></article></body></html>"
    )
    data = html.encode("cp1252")  # no <meta charset> in the document
    text = ingest.extract_text(data, "html", charset="windows-1252")
    assert "résumé" in text
    assert "�" not in text


@needs_trafilatura
def test_html_iso_8859_1_label_decoded_as_cp1252():
    """Per WHATWG, an `iso-8859-1` (or latin1/ascii) label decodes as
    windows-1252 when parsing HTML, so CP1252 punctuation bytes become real
    Unicode punctuation rather than C1 control characters."""
    body = "smart “quotes” and an em—dash, with enough body text for the extractor."
    html = (
        "<html><head><title>P</title></head><body><article><h1>P</h1><p>"
        + body
        + "</p></article></body></html>"
    )
    data = html.encode("cp1252")  # 0x93/0x94 quotes, 0x97 em dash
    text = ingest.extract_text(data, "html", charset="iso-8859-1")
    assert "“" in text and "”" in text and "—" in text  # real punctuation
    assert "\x93" not in text and "\x94" not in text and "\x97" not in text  # no C1


def test_text_unknown_charset_falls_back_cleanly():
    """An unknown header charset on a text/markdown response must not raise
    LookupError (an internal exit 4) — fall back to UTF-8."""
    out = ingest.extract_text(b"hello world", "txt", charset="totally-bogus-charset")
    assert "hello world" in out


def test_fetch_url_error_maps_to_exit_2(kb, monkeypatch):
    import urllib.error

    def boom(*a, **k):
        raise urllib.error.URLError("name or service not known")

    monkeypatch.setattr(ingest.urllib.request, "urlopen", boom)
    rc = cli.main(["ingest", "https://nonexistent.invalid/x", "--root", str(kb.root)])
    assert rc == 2  # a clean usage error, not an internal (4)


def test_html_without_extra_gives_helpful_error(monkeypatch):
    monkeypatch.setattr(ingest, "_import", lambda name: None)
    with pytest.raises(errors.UsageError):
        ingest.extract_text(b"<html><body>x</body></html>", "html")


@needs_pypdf
def test_extract_pdf_returns_text():
    text = ingest.extract_text(_make_pdf("Hello PDF"), "pdf")
    assert "Hello" in text
