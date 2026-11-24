"""Builds Itamar Haim's landing page (Hebrew + English) from content.json.

Usage: python build.py --mode demo|preview|publish
"""
import argparse
import copy
import json
import re
import shutil
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
DEMO_DIR = ROOT.parent / "תמונות" / "להדגמה בלבד — לא לפרסום"
DEMO_OUT = ROOT.parent / "תצוגה מקומית"
MODES = ("demo", "preview", "publish")
FONTS_URL = ("https://fonts.googleapis.com/css2?family=Noto+Sans+Hebrew:wght@200;300;400;500;600"
             "&amp;family=Barlow:wght@200;300;400;500;600&amp;display=swap")


def load_content(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _t(text: str, lang: str) -> str:
    """Escape text; inside the Hebrew page wrap Latin runs in lang=en so they keep their order."""
    if lang != "he":
        return escape(text, quote=False)
    # Wrap Latin runs first, on the raw text, then escape each piece, so entities are never split.
    parts = re.split(r"([A-Za-z][A-Za-z .&'-]*[A-Za-z]|[A-Za-z])", text)
    return "".join(f'<span lang="en" dir="ltr">{escape(p, quote=False)}</span>' if i % 2
                   else escape(p, quote=False) for i, p in enumerate(parts))


class PublishBlocked(Exception):
    """Publish mode refuses to build while something the spec leaves open is still open."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def _wa_digits(content: dict) -> str:
    return re.sub(r"\D", "", (content.get("contact") or {}).get("whatsapp") or "")


def publish_problems(content: dict) -> list[str]:
    problems = []
    url = content.get("site_url")
    if not url:
        problems.append("site_url חסר")
    elif not url.startswith("https://"):
        problems.append("site_url חייב להתחיל ב־https://")
    contact = content.get("contact") or {}
    if not (contact.get("whatsapp") or contact.get("email")):
        problems.append("אין ערוץ קשר")
    if contact.get("whatsapp") and not re.fullmatch(r"972\d{8,9}", _wa_digits(content)):
        problems.append("מספר וואטסאפ לא תקין: צריך להתחיל ב־972")
    return problems


def _base(content: dict) -> str | None:
    url = content.get("site_url")
    return url if not url or url.endswith("/") else url + "/"


def _alternates(content: dict, lang: str) -> str:
    base = _base(content)
    if base:
        he, en = base, base + "en/"
    else:
        he, en = ("./", "en/") if lang == "he" else ("../", "./")
    return "\n".join(f'<link rel="alternate" hreflang="{h}" href="{u}">'
                     for h, u in (("he", he), ("en", en), ("x-default", he)))


def _head_meta(content: dict, lang: str, mode: str, prefix: str) -> str:
    c, base = content[lang], _base(content)
    lines = []
    if mode != "publish":
        lines.append('<meta name="robots" content="noindex, nofollow">')
    if base:
        lines.append(f'<link rel="canonical" href="{base if lang == "he" else base + "en/"}">')
    lines += [f'<meta property="og:type" content="website">',
              f'<meta property="og:locale" content="{"he_IL" if lang == "he" else "en_US"}">',
              f'<meta property="og:title" content="{escape(c["title"])}">',
              f'<meta property="og:description" content="{escape(c["description"])}">']
    # Share cards need an absolute image URL: the real site when publishing, the draft address before.
    og_base = base if mode == "publish" else content.get("preview_url")
    if og_base:
        og_base = og_base if og_base.endswith("/") else og_base + "/"
        lines.append(f'<meta property="og:image" content="{og_base}assets/img/og.jpg">')
    return "\n".join(lines)


def _cta_href(content: dict) -> str:
    contact = content.get("contact") or {}
    if contact.get("whatsapp"):
        return f'https://wa.me/{_wa_digits(content)}'
    if contact.get("email"):
        return f'mailto:{contact["email"]}'
    return "#contact"


def _contacts(content: dict) -> str:
    contact = content.get("contact") or {}
    items = []
    if contact.get("whatsapp"):
        n = _wa_digits(content)
        items.append(f'<li><a href="https://wa.me/{n}" aria-label="WhatsApp"><span dir="ltr">+{n}</span></a></li>')
    if contact.get("email"):
        e = escape(contact["email"])
        items.append(f'<li><a href="mailto:{e}"><span lang="en" dir="ltr">{e}</span></a></li>')
    if contact.get("linkedin"):
        items.append(f'<li><a href="{escape(contact["linkedin"])}"><span lang="en" dir="ltr">LinkedIn</span></a></li>')
    return f'\n  <ul class="contacts">{"".join(items)}</ul>' if items else ""


def _tile(p: dict, lang: str, prefix: str) -> str:
    c = p[lang]
    img = p.get("image")
    if img:
        visual = (f'<div class="img"><img src="{prefix}assets/img/{p["id"]}.jpg" '
                  f'alt="{escape(img["alt_" + lang])}" loading="lazy"></div>')
    elif p["field_kind"] == "num":
        num = escape(c["field"])
        if lang == "he":
            num = f'<span lang="en" dir="ltr">{num}</span>'
        visual = f'<div class="img field"><p class="num">{num}</p></div>'
    else:
        visual = f'<div class="img field"><p class="big">{_t(c["field"], lang)}</p></div>'
    return (f'<article class="tile tile--{p["status_key"]}">{visual}'
            f'<div class="cap"><div><h3 class="t">{_t(c["title"], lang)}</h3>'
            f'<p class="d">{_t(c["desc"], lang)}</p></div>'
            f'<span class="s">{_t(c["status"], lang)}</span></div></article>')


def render_page(content: dict, lang: str, mode: str) -> str:
    if lang not in ("he", "en") or mode not in MODES:
        raise ValueError(f"bad lang/mode: {lang}/{mode}")
    c = content[lang]
    d = "rtl" if lang == "he" else "ltr"
    cta = _cta_href(content)
    other = "en/" if lang == "he" else "../"
    other_lang = "en" if lang == "he" else "he"
    arrow = "←" if lang == "he" else "→"
    prefix = "" if lang == "he" else "../"
    tiles = "\n".join(_tile(p, lang, prefix) for p in content["projects"])
    credits = [p["image"]["credit_" + lang] for p in content["projects"] if p.get("image")]
    credit = (f'\n  <p class="credit">{" · ".join(_t(x, lang) for x in credits)}</p>'
              if credits else "")
    return f"""<!doctype html>
<html lang="{lang}" dir="{d}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(c["title"])}</title>
<meta name="description" content="{escape(c["description"])}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS_URL}">
<link rel="stylesheet" href="{prefix}assets/site.css">
{_alternates(content, lang)}
{_head_meta(content, lang, mode, prefix)}
</head>
<body>
<header class="bar">
  <a class="nm" href="./">{_t(c["name"], lang)}</a>
  <nav class="lnk">
    <a href="#projects">{_t(c["nav_projects"], lang)}</a>
    <a href="{other}" lang="{other_lang}" hreflang="{other_lang}">{escape(c["nav_lang"])}</a>
    <a class="lnk-cta" href="{cta}">{_t(c["cta"], lang)}</a>
  </nav>
</header>
<main>
  <section class="hero">
    <div class="txt">
      <p class="eyebrow"><i aria-hidden="true"></i>{_t(c["eyebrow"], lang)}</p>
      <h1><span class="l1">{_t(c["h1_line1"], lang)}</span> <span class="l2">{_t(c["h1_line2"], lang)}<span class="dot">.</span></span></h1>
      <p class="lead">{_t(c["lead"], lang)}</p>
      <a class="cta" href="{cta}">{_t(c["cta"], lang)} <span aria-hidden="true">{arrow}</span></a>
    </div>
    <div class="por"><img src="{prefix}assets/img/portrait.jpg" alt="{escape(c["name"])}" width="900" height="1205"></div>
  </section>
  <section id="projects" class="projects">
    <div class="sech"><h2>{_t(c["projects_label"], lang)}</h2><span class="aside" lang="en">{escape(c["projects_aside"])}</span></div>
    <div class="grid">
{tiles}
    </div>
  </section>{credit}
</main>
<footer id="contact" class="foot"><div class="foot-in">
  <p class="fl">{_t(c["footer_line"], lang)}</p>
  <a class="cta" href="{cta}">{_t(c["cta"], lang)} <span aria-hidden="true">{arrow}</span></a>{_contacts(content)}
</div></footer>
</body>
</html>
"""


class MissingImage(Exception):
    """An image named in content.json (or the demo map) is not on disk."""


def _with_demo_images(content: dict, demo_dir: Path) -> dict:
    """Demo mode only: fill projects that have no approved image from the local demo map."""
    content = copy.deepcopy(content)
    mapping = json.loads((demo_dir / "demo_images.json").read_text(encoding="utf-8"))
    for p in content["projects"]:
        if not p.get("image") and p["id"] in mapping:
            m = dict(mapping[p["id"]])
            m["file"] = str(demo_dir / m["file"])
            p["image"] = m
    return content


def prepare_images(content: dict, mode: str, out_dir: Path, demo_dir: Path | None) -> None:
    img_out = Path(out_dir) / "assets" / "img"
    img_out.mkdir(parents=True, exist_ok=True)
    for old in img_out.iterdir():  # nothing withdrawn or left over from another mode survives a build
        if old.is_file():          # (files only: OneDrive locks the folder itself)
            old.unlink()
    portrait = Image.open(ROOT / "img-src" / "portrait.jpg").convert("RGB")
    w = 900
    portrait.resize((w, round(portrait.height * w / portrait.width)), Image.LANCZOS).save(
        img_out / "portrait.jpg", quality=85)
    _make_og(portrait).save(img_out / "og.jpg", quality=85)
    for p in content["projects"]:
        img = p.get("image")
        if not img:
            continue
        src = Path(img["file"])
        if not src.is_absolute():
            src = ROOT / "img-src" / src
        if not src.is_file():
            raise MissingImage(src)
        im = Image.open(src).convert("RGB")
        im.thumbnail((1600, 1600))
        im.save(img_out / f'{p["id"]}.jpg', quality=85)


def _make_og(portrait: "Image.Image") -> "Image.Image":
    """1200x630 share image: plaster ground, whole portrait, thin yellow frame offset behind it."""
    og = Image.new("RGB", (1200, 630), "#ECEAE4")
    h = 540
    p = portrait.resize((round(portrait.width * h / portrait.height), h), Image.LANCZOS)
    x, y = (1200 - p.width) // 2 - 11, 90
    draw = ImageDraw.Draw(og)
    draw.rectangle([x + 22, y - 22, x + p.width + 22, y + h - 22], outline="#F1B71C", width=3)
    og.paste(p, (x, y))
    return og


def build(mode: str, out_dir: Path, demo_dir: Path | None = None) -> list[Path]:
    content = load_content(ROOT / "content.json")
    if mode == "publish" and publish_problems(content):
        raise PublishBlocked(publish_problems(content))
    out_dir = Path(out_dir)
    if mode == "demo":
        if out_dir.resolve().is_relative_to(ROOT):
            raise ValueError(f"demo output must stay outside the public repo: {out_dir}")
        content = _with_demo_images(content, Path(demo_dir or DEMO_DIR))
    out_dir.mkdir(parents=True, exist_ok=True)
    prepare_images(content, mode, out_dir, demo_dir)
    he = out_dir / "index.html"
    he.write_text(render_page(content, "he", mode), encoding="utf-8")
    en = out_dir / "en" / "index.html"
    en.parent.mkdir(parents=True, exist_ok=True)
    en.write_text(render_page(content, "en", mode), encoding="utf-8")
    css = out_dir / "assets" / "site.css"
    css.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "assets" / "site.css", css)
    return [he, en, css]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=MODES, required=True)
    args = ap.parse_args()
    out = DEMO_OUT if args.mode == "demo" else ROOT / "docs"
    for p in build(args.mode, out):
        print(p)


if __name__ == "__main__":
    main()
