import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

import build

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content.json"

# The "not for publication" list lives OUTSIDE this public repo on purpose (final review, 24.11.2026).
FORBIDDEN_FILE = ROOT.parent / "קבצי עבודה" / "forbidden_terms.json"
if not FORBIDDEN_FILE.is_file():
    raise RuntimeError(f"missing {FORBIDDEN_FILE}: the do-not-publish list is required to run the tests")
_F = __import__("json").loads(FORBIDDEN_FILE.read_text(encoding="utf-8"))
FORBIDDEN_TERMS, FORBIDDEN_NUMBERS = _F["terms"], _F["numbers"]


def forbidden_hits(text: str) -> list[str]:
    """Scans raw text (whole HTML incl. <head> and attributes, or a source file)."""
    hits = []
    for term in FORBIDDEN_TERMS:
        if re.search(r"[A-Za-z]", term):
            if re.search(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", text, flags=re.I):
                hits.append(term)
        elif term in text:
            hits.append(term)
    return hits


def forbidden_number_hits(text: str) -> list[str]:
    return [n for n in FORBIDDEN_NUMBERS if re.search(rf"(?<!\d){n}(?!\d)", text)]


class _Text(HTMLParser):
    """Collects visible text nodes with the nearest lang attribute in effect."""

    VOID = {"meta", "link", "img", "br", "hr", "input", "source"}

    def __init__(self):
        super().__init__()
        self.stack = []  # (tag, lang)
        self.chunks = []  # (text, lang)
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        a = dict(attrs)
        lang = a.get("lang") or (self.stack[-1][1] if self.stack else None)
        self.stack.append((tag, lang))
        if tag in ("script", "style", "head"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        while self.stack:
            t, _ = self.stack.pop()
            if t in ("script", "style", "head"):
                self.skip -= 1
            if t == tag:
                break

    def handle_data(self, data):
        if self.skip or not data.strip():
            return
        self.chunks.append((data, self.stack[-1][1] if self.stack else None))


def text_nodes(html):
    p = _Text()
    p.feed(html)
    return p.chunks


def visible_text(html):
    return " ".join(t for t, _ in text_nodes(html))


@pytest.fixture(scope="module")
def content():
    return build.load_content(CONTENT)


@pytest.fixture(scope="module")
def he_html(content):
    return build.render_page(content, "he", "preview")


def test_he_page_basics(he_html):
    assert '<html lang="he" dir="rtl">' in he_html
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", he_html, flags=re.S).group(1)
    assert "מהתכנון" in h1 and "ועד הביצוע" in h1
    assert "יזם ומנהל נכסים · תל אביב" in visible_text(he_html)


def test_projects_in_order(he_html):
    tiles = re.findall(r'<article class="tile[^"]*".*?</article>', he_html, flags=re.S)
    assert len(tiles) == 4
    titles = ["מלון פבריק, נחלת בנימין 28", "דירות יוקרה, רחוב נס ציונה",
              "מלון, רוטשילד פינת נחלת בנימין", "אלנבי 87 ולינקולן"]
    statuses = ["הושלם", "הושלם", "לקראת ביצוע", "בתכנון"]
    for tile, title, status in zip(tiles, titles, statuses):
        text = re.sub(r"\s+", " ", visible_text(tile))
        assert title in text
        assert status in text


def _complete(content):
    import copy
    c = copy.deepcopy(content)
    c["site_url"] = "https://example.com/"
    c["contact"] = {"whatsapp": "972501234567", "email": "x@example.com", "linkedin": None}
    return c


def test_forbidden_terms_absent(content):
    """Raw HTML, incl. <head> and attributes, in every mode, plus the built docs/ files."""
    pages = [build.render_page(c, lang, mode) for c in (content, _complete(content))
             for lang in ("he", "en") for mode in ("preview", "publish")]
    pages += [p.read_text(encoding="utf-8") for p in (ROOT / "docs").rglob("*.html")]
    for html in pages:
        assert forbidden_hits(html) == []
        assert forbidden_number_hits(visible_text(html) + " " + " ".join(
            re.findall(r'(?:content|alt|title)="([^"]*)"', html))) == []


def test_forbidden_scan_sees_head_and_attributes(content):
    """Review finding #2: the old check skipped <head> and alt text."""
    import copy
    probe = next(t for t in FORBIDDEN_TERMS if t.isascii() and " " not in t)
    c = copy.deepcopy(content)
    c["he"]["description"] = probe
    assert forbidden_hits(build.render_page(c, "he", "preview")) == [probe]


def test_forbidden_list_not_in_repo():
    """Review finding #1: the repo is public, so the list itself must not be in it."""
    for p in ROOT.rglob("*"):
        if p.is_file() and not {".git", ".superpowers", "__pycache__"} & set(p.parts):
            if p.suffix.lower() in {".py", ".json", ".html", ".css", ".md", ".ini", ".txt"}:
                assert forbidden_hits(p.read_text(encoding="utf-8")) == [], p


def test_latin_wrapped(he_html):
    for text, lang in text_nodes(he_html):
        if re.search(r"[A-Za-z]", text):
            assert lang == "en", f"Latin outside lang=en: {text!r}"


def test_cta_count(he_html):
    assert visible_text(he_html).count("שליחת הודעה") == 3


CSS = ROOT / "assets" / "site.css"
TOKENS = {"--paper": "#ECEAE4", "--stone": "#DEDAD1", "--ink": "#2E2E2E", "--soft": "#5F5E5A",
          "--blue": "#1F3FA8", "--yellow": "#F1B71C", "--red": "#D2382B"}
ITB_FORBIDDEN = _F["itb"]


def contrast(a: str, b: str) -> float:
    def lum(h):
        h = h.lstrip("#")
        rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted([lum(a), lum(b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def css_rule(css: str, selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"no rule for {selector}"
    return m.group(1)


def test_tokens_exact():
    root = css_rule(CSS.read_text(encoding="utf-8"), ":root")
    for name, value in TOKENS.items():
        assert re.search(rf"{name}\s*:\s*{value}\s*;", root, flags=re.I), name


def test_no_itb_brand(content):
    sources = [CSS.read_text(encoding="utf-8"), (ROOT / "build.py").read_text(encoding="utf-8"),
               build.render_page(content, "he", "preview"), build.render_page(content, "en", "preview")]
    for src in sources:
        for bad in ITB_FORBIDDEN:
            assert bad.lower() not in src.lower(), bad


def test_contrast_aa():
    t = TOKENS
    for fg, bg in [("--ink", "--paper"), ("--soft", "--paper"), ("--blue", "--paper"),
                   ("--ink", "--stone"), ("--soft", "--stone")]:
        assert contrast(t[fg], t[bg]) >= 4.5, (fg, bg)


def test_type_and_buttons():
    css = CSS.read_text(encoding="utf-8")
    assert "clamp(" in css_rule(css, "h1")
    cta = css_rule(css, ".cta")
    assert re.search(r"border:\s*1px solid var\(--blue\)", cta)
    assert re.search(r"background:\s*transparent", cta)
    assert re.search(r"border:\s*3px solid var\(--yellow\)", css_rule(css, ".por::before"))


def test_hover_stays_delicate():
    """Galia asked for thin, delicate buttons; a solid blue hover fill brings the filled button back."""
    css = CSS.read_text(encoding="utf-8")
    hover = re.search(r"@media \(hover: hover\)\s*\{\s*\.cta:hover\s*\{([^}]*)\}", css)
    assert hover, ".cta:hover must live inside @media (hover: hover)"
    assert "var(--blue)" not in hover.group(1).split("background")[-1].split(";")[0]
    assert not re.search(r"^\.cta:hover", css, flags=re.M)


def test_fonts_link(he_html):
    assert "Noto+Sans+Hebrew:wght@200;300;400;500;600" in he_html
    assert "Barlow:wght@200;300;400;500;600" in he_html
    assert 'href="assets/site.css"' in he_html


def test_build_copies_css(tmp_path):
    build.build("preview", tmp_path)
    assert (tmp_path / "assets" / "site.css").read_text(encoding="utf-8") == CSS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def en_html(content):
    return build.render_page(content, "en", "preview")


def test_en_page_basics(en_html):
    assert '<html lang="en" dir="ltr">' in en_html
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", en_html, flags=re.S).group(1)
    assert "From planning" in h1 and "through construction" in h1
    tiles = re.findall(r'<article class="tile[^"]*".*?</article>', en_html, flags=re.S)
    titles = ["Fabric Hotel, 28 Nahalat Binyamin", "Luxury apartments, Ness Ziona Street",
              "Hotel, Rothschild Boulevard at Nahalat Binyamin", "87 Allenby and Lincoln Street"]
    statuses = ["Completed", "Completed", "Pre-construction", "In planning"]
    assert len(tiles) == 4
    for tile, title, status in zip(tiles, titles, statuses):
        text = visible_text(tile)
        assert title in text and status in text
    assert 'href="../assets/site.css"' in en_html


def test_hreflang_pair(he_html, en_html):
    for html in (he_html, en_html):
        assert re.search(r'<link rel="alternate" hreflang="he" href="[^"]+">', html)
        assert re.search(r'<link rel="alternate" hreflang="en" href="[^"]+">', html)
        assert re.search(r'<link rel="alternate" hreflang="x-default" href="[^"]+">', html)
    assert '<link rel="alternate" hreflang="en" href="en/">' in he_html
    assert '<link rel="alternate" hreflang="he" href="../">' in en_html


def test_lang_switch_links(he_html, en_html):
    assert re.search(r'<a href="en/" lang="en"[^>]*>EN</a>', he_html)
    assert re.search(r'<a href="\.\./" lang="he"[^>]*>עב</a>', en_html)


def test_en_hebrew_wrapped(en_html):
    for text, lang in text_nodes(en_html):
        if re.search(r"[֐-׿]", text):
            assert lang == "he", f"Hebrew outside lang=he: {text!r}"


def test_build_writes_en_page(tmp_path):
    written = build.build("preview", tmp_path)
    assert tmp_path / "en" / "index.html" in written


DEMO_DIR = ROOT.parent / "תמונות" / "להדגמה בלבד — לא לפרסום"


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_portrait_full_alt(tmp_path, he_html, en_html):
    from PIL import Image
    assert re.search(r'<img src="assets/img/portrait\.jpg" alt="איתמר חיים"', he_html)
    assert re.search(r'<img src="\.\./assets/img/portrait\.jpg" alt="Itamar Haim"', en_html)
    build.build("preview", tmp_path)
    assert Image.open(tmp_path / "assets" / "img" / "portrait.jpg").width == 900


def test_og_image(tmp_path, content, he_html, en_html):
    """Review finding #4: LinkedIn needs an absolute og:image, also on the preview link Galia sends."""
    from PIL import Image
    build.build("preview", tmp_path)
    assert Image.open(tmp_path / "assets" / "img" / "og.jpg").size == (1200, 630)
    expected = content["preview_url"] + "assets/img/og.jpg"
    assert expected.startswith("https://")
    for html in (he_html, en_html):
        assert f'<meta property="og:image" content="{expected}">' in html
        assert 'rel="canonical"' not in html


def test_publish_requires_https_site_url(content):
    c = _complete(content)
    c["site_url"] = "itamarhaim.co.il"
    assert build.publish_problems(c) == ["site_url חייב להתחיל ב־https://"]


def test_whatsapp_number_normalized(content):
    """Review finding #5: wa.me wants digits only; '+972-50-…' or '054-…' broke the only action."""
    c = _complete(content)
    c["contact"]["whatsapp"] = "+972-50-123-4567"
    html = build.render_page(c, "he", "publish")
    assert 'href="https://wa.me/972501234567"' in html
    assert "++" not in visible_text(html)
    assert build.publish_problems(c) == []
    c["contact"]["whatsapp"] = "054-1234567"
    assert build.publish_problems(c) == ["מספר וואטסאפ לא תקין: צריך להתחיל ב־972"]


def test_preview_clears_stale_images(tmp_path):
    """Review finding #3: an image withdrawn from content.json must not linger in the output."""
    build.build("preview", tmp_path)
    (tmp_path / "assets" / "img" / "fabric.jpg").write_bytes(b"stale")
    build.build("preview", tmp_path)
    assert sorted(p.name for p in (tmp_path / "assets" / "img").iterdir()) == ["og.jpg", "portrait.jpg"]


def test_demo_refuses_repo_paths():
    with pytest.raises(ValueError):
        build.build("demo", ROOT / "docs", DEMO_DIR)


def test_committed_docs_images(content):
    approved = {f'{p["id"]}.jpg' for p in content["projects"] if p.get("image")}
    names = {p.name for p in (ROOT / "docs" / "assets" / "img").iterdir()}
    assert names == {"og.jpg", "portrait.jpg"} | approved


def test_missing_image_fails(tmp_path, content):
    import copy
    bad = copy.deepcopy(content)
    bad["projects"][0]["image"] = {"file": "nope.jpg", "alt_he": "x", "alt_en": "x",
                                   "credit_he": "x", "credit_en": "x"}
    with pytest.raises(build.MissingImage):
        build.prepare_images(bad, "preview", tmp_path, None)


def test_no_demo_images_in_repo():
    demo = {_sha(p) for p in DEMO_DIR.rglob("*") if p.is_file()}
    for p in ROOT.rglob("*"):
        if p.is_file() and ".git" not in p.parts and ".superpowers" not in p.parts:
            assert _sha(p) not in demo, p


def test_preview_images_are_only_approved(tmp_path):
    build.build("preview", tmp_path)
    names = sorted(p.name for p in (tmp_path / "assets" / "img").iterdir())
    assert names == ["og.jpg", "portrait.jpg"]


def test_demo_mode_local_only(tmp_path):
    demo_out = tmp_path / "demo"
    build.build("demo", demo_out, DEMO_DIR)
    html = (demo_out / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<img src="assets/img/fabric\.jpg" alt="[^"]+"', html)
    assert "עמית גושר" in html
    assert (demo_out / "assets" / "img" / "fabric.jpg").exists()
    prev_out = tmp_path / "preview"
    build.build("preview", prev_out)
    prev = (prev_out / "index.html").read_text(encoding="utf-8")
    assert "עמית גושר" not in prev
    fabric_tile = re.findall(r'<article class="tile[^"]*".*?</article>', prev, flags=re.S)[0]
    assert 'class="img field"' in fabric_tile


def test_field_tiles(he_html):
    allenby = re.findall(r'<article class="tile[^"]*".*?</article>', he_html, flags=re.S)[3]
    assert 'class="img field"' in allenby
    assert re.search(r'<span lang="en" dir="ltr">87</span>', allenby)


ROBOTS = '<meta name="robots" content="noindex, nofollow">'


def _with(content, **over):
    import copy
    c = copy.deepcopy(content)
    for k, v in over.items():
        c[k] = v
    return c


def test_noindex_until_publish(content):
    for mode in ("demo", "preview"):
        assert ROBOTS in build.render_page(content, "he", mode)
    assert ROBOTS not in build.render_page(content, "he", "publish")
    assert ROBOTS not in build.render_page(content, "en", "publish")


def test_publish_blocked_lists_all(content, tmp_path):
    assert build.publish_problems(content) == ["site_url חסר", "אין ערוץ קשר"]
    with pytest.raises(build.PublishBlocked):
        build.build("publish", tmp_path)


def test_publish_ok_when_complete(content):
    full = _with(content, site_url="https://example.com/",
                 contact={"whatsapp": "972500000000", "email": None, "linkedin": None})
    assert build.publish_problems(full) == []


def test_contact_rendering(content):
    full = _with(content, contact={"whatsapp": "972500000000", "email": "x@example.com", "linkedin": None})
    he = build.render_page(full, "he", "preview")
    assert he.count('href="https://wa.me/972500000000"') == 4  # bar, hero, footer CTA + footer list
    assert 'href="mailto:x@example.com"' in he
    text = visible_text(he)
    assert "+972500000000" in text and "x@example.com" in text
    assert 'href="#contact"' not in he


def test_meta_tags(content, he_html):
    assert "<title>איתמר חיים · יזם ומנהל נכסים</title>" in he_html
    for tag in ('name="description"', 'property="og:title"', 'property="og:description"'):
        assert tag in he_html
    assert 'rel="canonical"' not in he_html
    full = _with(content, site_url="https://example.com/")
    he = build.render_page(full, "he", "publish")
    en = build.render_page(full, "en", "publish")
    assert '<link rel="canonical" href="https://example.com/">' in he
    assert '<link rel="canonical" href="https://example.com/en/">' in en
    assert '<meta property="og:image" content="https://example.com/assets/img/og.jpg">' in he
    assert '<link rel="alternate" hreflang="en" href="https://example.com/en/">' in he


def test_quotes_and_entities_survive(he_html, en_html):
    """Found in the visual pass: 'נדל"ן' came out as 'נדל&<span>quot</span>;ן'."""
    he = visible_text(he_html)
    assert 'פיתוח נדל"ן מלונאי ומגורים בתל אביב.' in he
    assert "quot" not in he
    assert "Real Estate Developer & Asset Manager · Tel Aviv" in visible_text(en_html)


def test_portrait_keeps_its_ratio():
    """Found in the visual pass: the height="1205" attribute beat aspect-ratio and stretched the photo."""
    rule = css_rule(CSS.read_text(encoding="utf-8"), ".por img")
    assert re.search(r"height:\s*auto", rule)


def test_h1_reads_as_words(he_html, en_html):
    """Found by the spell check: the two block lines joined into 'מהתכנוןועד' for screen readers."""
    for html, expected in ((he_html, "מהתכנון ועד הביצוע."), (en_html, "From planning through construction.")):
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.S).group(1)
        assert re.sub(r"<[^>]+>", "", h1) == expected


def test_build_writes_he_page(tmp_path):
    written = build.build("preview", tmp_path)
    assert tmp_path / "index.html" in written
    assert (tmp_path / "index.html").read_text(encoding="utf-8").startswith("<!doctype html>")
