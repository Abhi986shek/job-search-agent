"""CV layout and rendering: one structure, three outputs (HTML preview, DOCX, PDF) with the same styling.

Layout follows the owner's CV: blue name and accents, a circular photo at the top right, contact details, a
two-column body (experience and education on the left; skills, projects, certificates, languages and interests on
the right), dark markers beside each entry, and skills shown as chips. Content comes only from the structure that
the service builds from the approved profile, plus the header details kept in cv_extras.json.
"""

from __future__ import annotations

import base64
import html
import json
import re
from datetime import datetime
from pathlib import Path

from config import DATA_DIR, UPLOADS_DIR

PRIMARY = "2F6DB5"     # name, rules and accents
DARK = "1F2A3A"        # headings, entry markers
CHIP_BG = "A9C9EE"     # skill and interest chips
CHIP_TEXT = "0F2742"
MUTED = "5B6B7F"

LEFT_SECTIONS = ("experience", "education")
RIGHT_SECTIONS = ("certificates", "skills", "projects", "other projects", "languages", "interests")
# Skills and technologies that do not fit the current role. Kept out of the CV.
CV_SKILL_EXCLUDE = {"java", "spring boot", "hibernate"}

# Projects shown in full (up to FEATURED_MAX). Matched by part of the project name, in this order.
# Override with "featured_projects" in data/cv_extras.json.
FEATURED_PROJECT_KEYS = ["CyberSphere", "Festival greetings", "Real-time voice assistant",
                         "Customer support AI agent", "Conversational AI agent backend"]
FEATURED_MAX = 5
# Not work projects, so never on the CV (a learning repo and a profile page).
EXCLUDED_PROJECT_KEYS = ["GitHub profile README", "Python interview roadmap"]
HEADER_SECTIONS = ("summary",)
EXTRAS_FILE = DATA_DIR / "cv_extras.json"
ASSETS_DIR = DATA_DIR / "cv_assets"

DEFAULT_EXTRAS = {
    "contact": {
        "email": "abhishekmitra986@gmail.com",
        "phone": "7001829418",
        "location": "Bengaluru, Karnataka, India",
        "linkedin": "linkedin.com/in/abhishek-mitra-588710161",
    },
    "languages": [
        {"name": "Bengali", "level": "Native or bilingual proficiency"},
        {"name": "Hindi", "level": "Full professional proficiency"},
        {"name": "English", "level": "Full professional proficiency"},
    ],
    "interests": ["Martial Arts (Taekwondo)", "Calisthenics"],
}


# ── Header details (contact, languages, interests) ─────────────────────────────

def load_extras() -> dict:
    if EXTRAS_FILE.is_file():
        try:
            data = json.loads(EXTRAS_FILE.read_text(encoding="utf-8"))
            return {**DEFAULT_EXTRAS, **data, "contact": {**DEFAULT_EXTRAS["contact"], **(data.get("contact") or {})}}
        except (ValueError, OSError):
            pass
    return json.loads(json.dumps(DEFAULT_EXTRAS))


def save_extras(data: dict) -> dict:
    clean = {
        "contact": {k: str(v).strip() for k, v in (data.get("contact") or {}).items() if str(v).strip()},
        "languages": [{"name": str(x.get("name", "")).strip(), "level": str(x.get("level", "")).strip()}
                      for x in data.get("languages") or [] if str(x.get("name", "")).strip()],
        "interests": [str(x).strip() for x in data.get("interests") or [] if str(x).strip()],
    }
    EXTRAS_FILE.parent.mkdir(parents=True, exist_ok=True)
    EXTRAS_FILE.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    return clean


# ── Structure built from the profile ───────────────────────────────────────────

def _fmt_date(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.lower() in ("present", "current", "now"):
        return "Present"
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(value[:10] if fmt == "%Y-%m-%d" else value[:7], fmt).strftime("%b %Y")
        except ValueError:
            continue
    return value


def _short_description(text: str, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = ""
    for s in sentences:
        if out and len(out) + len(s) > limit:
            break
        out = f"{out} {s}".strip()
    return out[:limit]


# Client and company wording stays out of project names and descriptions.
_CLIENT_PARENS = re.compile(r"\s*\([^()]*\b(?:client|company)\b[^()]*\)", re.I)
_CLIENT_PHRASE = re.compile(r"\s+for an? [A-Za-z\- ]*?(?:client|company)\b", re.I)
_COPY_PHRASE = re.compile(r",?\s*company-account copy", re.I)
_SENTENCE_DROP = re.compile(r"client|company|shellkode|commit", re.I)


def _clean_name(name: str) -> str:
    text = _CLIENT_PARENS.sub("", name or "")
    text = _CLIENT_PHRASE.sub("", text)
    text = re.sub(r"^TagNPin:\s*", "", _COPY_PHRASE.sub("", text))
    return re.sub(r"\s+", " ", text).strip(" -:,")


def _clean_description(text: str) -> str:
    """Keep the sentences that describe the work. Drops anything naming a client or company, and commit counts."""
    sentences = re.split(r"(?<=[.!?])\s+", text or "")
    kept = [s for s in sentences if s.strip() and not _SENTENCE_DROP.search(s)]
    return _short_description(" ".join(kept))


def _project_url(pr: dict) -> str:
    """Link to the project: its own URL, or the GitHub repo it came from."""
    if pr.get("url"):
        return pr["url"]
    source = pr.get("source") or ""
    if source.startswith("github:"):
        return "https://github.com/" + source[len("github:"):]
    return ""


def _tech(pr: dict) -> list[str]:
    return [t for t in pr.get("technologies") or [] if t.lower() not in CV_SKILL_EXCLUDE]


def _one_line(text: str, limit: int = 130) -> str:
    """The first sentence that describes the work, for a one-line description."""
    for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
        if sentence.strip() and not _SENTENCE_DROP.search(sentence):
            return sentence.strip()[:limit]
    return ""


def _edu_sort_key(entry: dict) -> int:
    years = [int(y) for y in re.findall(r"(\d{4})", entry.get("year") or "")]
    return max(years) if years else 0


def _split_projects(profile: dict, extras: dict) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]]]:
    """(featured, rest): featured projects in full, the rest as a short list. Excluded ones are left out."""
    excluded = [k.lower() for k in EXCLUDED_PROJECT_KEYS]
    keys = [k.lower() for k in (extras.get("featured_projects") or FEATURED_PROJECT_KEYS)]
    items = []
    for pr in profile.get("projects") or []:
        name = _clean_name(pr.get("name") or "")
        if name and not any(k in name.lower() for k in excluded):
            items.append((name, pr))
    used: set[int] = set()
    featured: list[tuple[str, dict]] = []
    for key in keys:
        if len(featured) >= FEATURED_MAX:
            break
        for idx, (name, pr) in enumerate(items):
            if idx not in used and key in name.lower():
                used.add(idx)
                featured.append((name, pr))
                break
    rest = [item for idx, item in enumerate(items) if idx not in used]
    return featured, rest


def structure_from_profile(profile: dict, extras: dict) -> dict:
    """Map the approved profile to CV sections. Nothing is invented: every line comes from the profile or extras."""
    p = profile or {}
    sections: list[dict] = []
    if p.get("summary"):
        sections.append({"title": "Summary", "items": [{"heading": p["summary"], "subheading": "", "dates": "",
                                                        "bullets": []}]})
    exp_items = []
    for e in sorted(p.get("experience") or [], key=lambda e: e.get("start") or "", reverse=True):
        dates = " - ".join(x for x in (_fmt_date(e.get("start")), _fmt_date(e.get("end"))) if x)
        exp_items.append({"heading": e.get("employer") or "", "subheading": e.get("title") or "", "dates": dates,
                          "location": e.get("location") or "", "bullets": list(e.get("highlights") or [])})
    if exp_items:
        sections.append({"title": "Experience", "items": exp_items})
    edu_items = [{"heading": x.get("institution") or "", "subheading": x.get("degree") or "",
                  "dates": x.get("year") or "", "bullets": []} for x in sorted(p.get("education") or [], key=_edu_sort_key, reverse=True)]
    if edu_items:
        sections.append({"title": "Education", "items": edu_items})
    if p.get("skills"):
        sections.append({"title": "Skills", "items": [{"heading": "", "subheading": "", "dates": "",
                                                       "bullets": [s for s in p["skills"] if s.lower() not in CV_SKILL_EXCLUDE]}]})
    featured, rest = _split_projects(p, extras)
    if featured:
        sections.append({"title": "Projects", "items": [
            {"heading": name, "subheading": ", ".join(_tech(pr)), "dates": "", "url": _project_url(pr),
             "bullets": [d] if (d := _clean_description(pr.get("description") or "")) else []}
            for name, pr in featured]})
    if rest:
        sections.append({"title": "Other projects", "items": [
            {"heading": name, "subheading": _one_line(pr.get("description") or ""), "dates": "",
             "url": _project_url(pr), "bullets": []}
            for name, pr in rest]})
    if p.get("certifications"):
        sections.append({"title": "Certificates", "items": [{"heading": "", "subheading": "", "dates": "",
                                                             "bullets": list(p["certifications"])}]})
    langs = [f"{x['name']} ({x['level']})" if x.get("level") else x["name"] for x in extras.get("languages") or []]
    if langs:
        sections.append({"title": "Languages", "items": [{"heading": "", "subheading": "", "dates": "",
                                                          "bullets": langs}]})
    if extras.get("interests"):
        sections.append({"title": "Interests", "items": [{"heading": "", "subheading": "", "dates": "",
                                                          "bullets": list(extras["interests"])}]})
    return {"name": p.get("full_name") or "", "headline": p.get("current_title") or p.get("headline") or "",
            "contact": [], "sections": sections}


# ── Photo (circle, same file for every output) ─────────────────────────────────

def _initials(name: str) -> str:
    parts = [x for x in re.split(r"\s+", name or "") if x]
    return "".join(x[0] for x in parts[:2]).upper() or "CV"


def photo_png(name: str) -> Path:
    """A circular PNG: the photo from data/uploads/profile_photo.* if present, otherwise the initials."""
    from PIL import Image, ImageDraw, ImageFont

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    out = ASSETS_DIR / "photo_circle.png"
    size = 400
    src = next((p for p in sorted(UPLOADS_DIR.glob("profile_photo.*"))
                if p.suffix.lower() in (".jpg", ".jpeg", ".png")), None)
    if src:
        img = Image.open(src).convert("RGB")
        w, h = img.size
        side = min(w, h)
        img = img.crop(((w - side) // 2, (h - side) // 2, (w - side) // 2 + side, (h - side) // 2 + side))
        img = img.resize((size, size))
    else:
        img = Image.new("RGB", (size, size), tuple(int(PRIMARY[i:i + 2], 16) for i in (0, 2, 4)))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 150)
        except OSError:
            font = ImageFont.load_default(size=150)
        draw.text((size // 2, size // 2), _initials(name), anchor="mm", fill="white", font=font)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    rgba = img.convert("RGBA")
    rgba.putalpha(mask)
    rgba.save(out)
    return out


PHOTO_EXTS = (".jpg", ".jpeg", ".png")
PHOTO_MAX_BYTES = 5 * 1024 * 1024


def current_photo() -> Path | None:
    return next((p for p in sorted(UPLOADS_DIR.glob("profile_photo.*")) if p.suffix.lower() in PHOTO_EXTS), None)


def save_photo(data: bytes, filename: str) -> Path:
    """Store the CV photo in data/uploads. Only one photo is kept; a new upload replaces the old one."""
    import io

    from PIL import Image

    suffix = Path(filename or "").suffix.lower()
    if suffix not in PHOTO_EXTS:
        raise ValueError("Use a JPG or PNG photo")
    if len(data) > PHOTO_MAX_BYTES:
        raise ValueError("The photo is larger than 5 MB")
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception as exc:  # noqa: BLE001
        raise ValueError("That file is not a valid image") from exc
    delete_photo()
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOADS_DIR / f"profile_photo{suffix}"
    target.write_bytes(data)
    return target


def delete_photo() -> bool:
    removed = False
    for old in UPLOADS_DIR.glob("profile_photo.*"):
        old.unlink()
        removed = True
    return removed


def photo_data_uri(name: str) -> str:
    return "data:image/png;base64," + base64.b64encode(photo_png(name).read_bytes()).decode()


# ── Structure helpers ──────────────────────────────────────────────────────────

def _sections_by_key(cv: dict) -> dict[str, dict]:
    return {(s.get("title") or "").strip().lower(): s for s in cv.get("sections") or []}


def _other_sections(cv: dict) -> list[dict]:
    known = set(LEFT_SECTIONS + RIGHT_SECTIONS + HEADER_SECTIONS)
    return [s for s in cv.get("sections") or [] if (s.get("title") or "").strip().lower() not in known]


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _link_html(item: dict) -> str:
    """The item heading as a link to its GitHub repo when it has one."""
    text = _esc(item.get("heading"))
    url = item.get("url")
    return f'<a href="{_esc(url)}" target="_blank" style="color:#{PRIMARY};text-decoration:none">{text}</a>' if url else text


# ── HTML preview ───────────────────────────────────────────────────────────────

_CSS = f"""
@page {{ size: A4; margin: 0; }}
body {{ font-family: Arial, Helvetica, sans-serif; color: #{DARK}; font-size: 10pt; margin: 0; background: #f2f4f7; }}
.cv {{ width: 186mm; min-height: 273mm; margin: 6mm auto; padding: 10mm 12mm; background: #fff; box-sizing: border-box; }}
header {{ display: flex; justify-content: space-between; gap: 6mm; border-bottom: 1.5px solid #{PRIMARY}; padding-bottom: 4mm; }}
.name {{ font-size: 26pt; color: #{PRIMARY}; font-weight: 700; margin: 0; line-height: 1.1; }}
.headline {{ font-size: 12pt; margin: 1.5mm 0 3mm; }}
.summary {{ font-size: 9.5pt; line-height: 1.45; color: #333; margin: 0; }}
.head-right {{ width: 56mm; text-align: right; }}
.photo {{ width: 30mm; height: 30mm; border-radius: 50%; margin-left: auto; display: block; }}
.contact {{ list-style: none; padding: 0; margin: 3mm 0 0; font-size: 8.8pt; line-height: 1.5; }}
.cols {{ display: flex; gap: 7mm; margin-top: 5mm; }}
.left {{ width: 110mm; }}
.right {{ width: 69mm; }}
h2 {{ font-size: 10.5pt; letter-spacing: .08em; text-transform: uppercase; color: #{DARK};
     border-bottom: 1.5px solid #{PRIMARY}; padding-bottom: 1mm; margin: 0 0 3mm; }}
section {{ margin-bottom: 5mm; }}
.entry {{ display: flex; gap: 3mm; margin-bottom: 3.5mm; }}
.marker {{ width: 3.2mm; min-width: 3.2mm; height: 3.2mm; background: #{DARK}; margin-top: 1mm; }}
.entry-body {{ flex: 1; }}
.entry-head {{ font-weight: 700; font-size: 10pt; }}
.entry-sub {{ font-size: 9.5pt; }}
.dates {{ font-size: 8.5pt; color: #{MUTED}; font-style: italic; }}
ul.bullets {{ margin: 1mm 0 0 4mm; padding: 0; font-size: 9pt; line-height: 1.4; }}
.chips span {{ display: inline-block; background: #{CHIP_BG}; color: #{CHIP_TEXT}; border-radius: 3px;
              padding: 1mm 2.2mm; margin: .8mm; font-size: 8.5pt; }}
.plain {{ font-size: 9pt; line-height: 1.4; margin: 0; }}
"""


def html_document(cv: dict, extras: dict, photo_src: str | None = None) -> str:
    sections = _sections_by_key(cv)
    summary = ""
    if "summary" in sections and sections["summary"].get("items"):
        summary = sections["summary"]["items"][0].get("heading") or ""
    contact = extras.get("contact") or {}
    contact_lines = [v for v in (contact.get("email"), contact.get("phone"), contact.get("location"),
                                 contact.get("linkedin")) if v]
    header = f"""<header>
  <div class="head-left">
    <p class="name">{_esc(cv.get('name'))}</p>
    <p class="headline">{_esc(cv.get('headline'))}</p>
    <p class="summary">{_esc(summary)}</p>
  </div>
  <div class="head-right">
    <img class="photo" src="{photo_src or ''}" alt="" />
    <ul class="contact">{''.join(f'<li>{_esc(x)}</li>' for x in contact_lines)}</ul>
  </div>
</header>"""

    def entries_html(section: dict) -> str:
        out = []
        for it in section.get("items") or []:
            bullets = "".join(f"<li>{_esc(b)}</li>" for b in it.get("bullets") or [])
            loc = f" | {_esc(it.get('location'))}" if it.get("location") else ""
            out.append(f"""<div class="entry"><span class="marker"></span><div class="entry-body">
  <div class="entry-head">{_link_html(it)}</div>
  <div class="entry-sub">{_esc(it.get('subheading'))}</div>
  <div class="dates">{_esc(it.get('dates'))}{loc}</div>
  {f'<ul class="bullets">{bullets}</ul>' if bullets else ''}
</div></div>""")
        return "".join(out)

    def section_html(title: str, section: dict) -> str:
        return f"<section><h2>{_esc(title)}</h2>{entries_html(section)}</section>"

    def chips_html(section: dict) -> str:
        items = [b for it in section.get("items") or [] for b in it.get("bullets") or []]
        return f'<section><h2>{_esc(section["title"])}</h2><div class="chips">' + "".join(
            f"<span>{_esc(x)}</span>" for x in items) + "</div></section>"

    def compact_html(section: dict) -> str:
        lines = []
        for it in section.get("items") or []:
            desc = f'<div class="dates">{_esc(it.get("subheading"))}</div>' if it.get("subheading") else ""
            lines.append(f'<div class="plain" style="margin-bottom:2mm"><b>{_link_html(it)}</b>{desc}</div>')
        return f'<section><h2>{_esc(section["title"])}</h2>{"".join(lines)}</section>'

    def plain_html(section: dict) -> str:
        items = [b for it in section.get("items") or [] for b in it.get("bullets") or []]
        return (f'<section><h2>{_esc(section["title"])}</h2>'
                + "".join(f'<p class="plain">{_esc(x)}</p>' for x in items) + "</section>")

    left, right = [], []
    for key in LEFT_SECTIONS:
        if key in sections and sections[key].get("items"):
            left.append(section_html(sections[key]["title"], sections[key]))
    for key in RIGHT_SECTIONS:
        s = sections.get(key)
        if s and s.get("items"):
            if key in ("skills", "interests"):
                right.append(chips_html(s))
            elif key == "projects":
                right.append(section_html(s["title"], s))
            elif key == "other projects":
                right.append(compact_html(s))
            else:
                right.append(plain_html(s))
    for s in _other_sections(cv):
        right.append(section_html(s.get("title") or "", s))

    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{_esc(cv.get('name'))} - CV</title>
<style>{_CSS}</style></head><body><div class="cv">{header}
<div class="cols"><div class="left">{''.join(left)}</div><div class="right">{''.join(right)}</div></div>
</div></body></html>"""


# ── DOCX ───────────────────────────────────────────────────────────────────────

def render_docx(cv: dict, extras: dict, path: Path) -> None:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    def rgb(hex_: str) -> RGBColor:
        return RGBColor.from_string(hex_)

    def shade(cell, hex_: str) -> None:
        tc_pr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hex_)
        tc_pr.append(shd)

    def border(paragraph, hex_: str) -> None:
        p_pr = paragraph._p.get_or_add_pPr()
        p_bdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        for k, v in (("w:val", "single"), ("w:sz", "10"), ("w:space", "1"), ("w:color", hex_)):
            bottom.set(qn(k), v)
        p_bdr.append(bottom)
        p_pr.append(p_bdr)

    def para(container, text="", size=9.5, bold=False, italic=False, color=DARK, space_after=2, align=None):
        p = container.add_paragraph()
        p.paragraph_format.space_after = Pt(space_after)
        p.paragraph_format.space_before = Pt(0)
        if align is not None:
            p.alignment = align
        run = p.add_run(text)
        run.font.size, run.font.bold, run.font.italic = Pt(size), bold, italic
        run.font.color.rgb = rgb(color)
        return p

    def link_para(container, text: str, url: str, size: float, bold: bool) -> None:
        from docx.opc.constants import RELATIONSHIP_TYPE

        p = container.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        r_id = p.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
        hyperlink = OxmlElement("w:hyperlink")
        hyperlink.set(qn("r:id"), r_id)
        run = OxmlElement("w:r")
        run_pr = OxmlElement("w:rPr")
        if bold:
            run_pr.append(OxmlElement("w:b"))
        color = OxmlElement("w:color")
        color.set(qn("w:val"), PRIMARY)
        run_pr.append(color)
        underline = OxmlElement("w:u")
        underline.set(qn("w:val"), "single")
        run_pr.append(underline)
        size_el = OxmlElement("w:sz")
        size_el.set(qn("w:val"), str(int(size * 2)))
        run_pr.append(size_el)
        run.append(run_pr)
        text_el = OxmlElement("w:t")
        text_el.text = text
        run.append(text_el)
        hyperlink.append(run)
        p._p.append(hyperlink)

    def section_title(container, title: str) -> None:
        p = para(container, title.upper(), size=10.5, bold=True, space_after=4)
        border(p, PRIMARY)

    def entries(container, section: dict) -> None:
        for it in section.get("items") or []:
            if it.get("url"):
                link_para(container, it.get("heading") or "", it["url"], 10, True)
            else:
                para(container, it.get("heading") or "", size=10, bold=True, space_after=0)
            if it.get("subheading"):
                para(container, it["subheading"], size=9.5, space_after=0)
            meta = " | ".join(x for x in (it.get("dates"), it.get("location")) if x)
            if meta:
                para(container, meta, size=8.5, italic=True, color=MUTED, space_after=1)
            for b in it.get("bullets") or []:
                bp = para(container, "\u2022  " + b, size=9, space_after=1)
                bp.paragraph_format.left_indent = Mm(4)
            container.add_paragraph().paragraph_format.space_after = Pt(2)

    def chips(container, items: list[str]) -> None:
        cols = 3
        rows = max(1, (len(items) + cols - 1) // cols)
        table = container.add_table(rows=rows, cols=cols)
        for i, text in enumerate(items):
            cell = table.cell(i // cols, i % cols)
            shade(cell, CHIP_BG)
            cell.paragraphs[0].add_run(text).font.size = Pt(8.5)
            cell.paragraphs[0].runs[0].font.color.rgb = rgb(CHIP_TEXT)
        container.add_paragraph().paragraph_format.space_after = Pt(2)

    sections = _sections_by_key(cv)
    doc = Document()
    for s in doc.sections:
        s.top_margin = s.bottom_margin = Mm(12)
        s.left_margin = s.right_margin = Mm(12)
    doc.styles["Normal"].font.name = "Arial"

    summary = sections["summary"]["items"][0].get("heading") if "summary" in sections and sections["summary"].get("items") else ""
    head = doc.add_table(rows=1, cols=2)
    head.autofit = False
    left_cell, right_cell = head.cell(0, 0), head.cell(0, 1)
    left_cell.width, right_cell.width = Mm(120), Mm(66)
    left_cell.paragraphs[0].add_run(cv.get("name") or "").font.size = Pt(24)
    left_cell.paragraphs[0].runs[0].font.bold = True
    left_cell.paragraphs[0].runs[0].font.color.rgb = rgb(PRIMARY)
    para(left_cell, cv.get("headline") or "", size=11, space_after=3)
    para(left_cell, summary or "", size=9.5, space_after=0)
    photo = photo_png(cv.get("name") or "")
    pp = right_cell.paragraphs[0]
    pp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    pp.add_run().add_picture(str(photo), width=Mm(28))
    contact = extras.get("contact") or {}
    for value in (contact.get("email"), contact.get("phone"), contact.get("location"), contact.get("linkedin")):
        if value:
            para(right_cell, value, size=8.8, space_after=1, align=WD_ALIGN_PARAGRAPH.RIGHT)
    border(left_cell.paragraphs[-1], PRIMARY)

    body = doc.add_table(rows=1, cols=2)
    body.autofit = False
    lc, rc = body.cell(0, 0), body.cell(0, 1)
    lc.width, rc.width = Mm(110), Mm(76)
    lc.paragraphs[0].text = ""
    rc.paragraphs[0].text = ""
    for key in LEFT_SECTIONS:
        if key in sections and sections[key].get("items"):
            section_title(lc, sections[key]["title"])
            entries(lc, sections[key])
    for key in RIGHT_SECTIONS:
        s = sections.get(key)
        if not s or not s.get("items"):
            continue
        section_title(rc, s["title"])
        items = [b for it in s["items"] for b in it.get("bullets") or []]
        if key in ("skills", "interests"):
            chips(rc, items)
        elif key == "projects":
            entries(rc, s)
        elif key == "other projects":
            for it in s["items"]:
                if it.get("url"):
                    link_para(rc, it.get("heading") or "", it["url"], 9, True)
                else:
                    para(rc, it.get("heading") or "", size=9, bold=True, space_after=0)
                if it.get("subheading"):
                    para(rc, it["subheading"], size=8.5, color=MUTED, space_after=3)
            rc.add_paragraph().paragraph_format.space_after = Pt(2)
        else:
            for x in items:
                para(rc, x, size=9, space_after=1)
            rc.add_paragraph().paragraph_format.space_after = Pt(2)
    for s in _other_sections(cv):
        section_title(rc, s.get("title") or "")
        entries(rc, s)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


# ── PDF ────────────────────────────────────────────────────────────────────────

def render_pdf(cv: dict, extras: dict, path: Path) -> None:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (BaseDocTemplate, Frame, FrameBreak, HRFlowable, Image, NextPageTemplate,
                                    PageTemplate, Paragraph, Spacer, Table, TableStyle)

    from documents import _pdf_font

    font, font_bold = _pdf_font()
    c_primary, c_dark = colors.HexColor("#" + PRIMARY), colors.HexColor("#" + DARK)
    c_muted, c_chip, c_chip_text = colors.HexColor("#" + MUTED), colors.HexColor("#" + CHIP_BG), colors.HexColor("#" + CHIP_TEXT)
    st = {
        "name": ParagraphStyle("name", fontName=font_bold, fontSize=24, leading=28, textColor=c_primary),
        "headline": ParagraphStyle("headline", fontName=font, fontSize=11, leading=14, textColor=c_dark, spaceAfter=3),
        "summary": ParagraphStyle("summary", fontName=font, fontSize=9.5, leading=13.5, textColor=colors.HexColor("#333333")),
        "contact": ParagraphStyle("contact", fontName=font, fontSize=8.8, leading=12, alignment=TA_RIGHT),
        "h2": ParagraphStyle("h2", fontName=font_bold, fontSize=10.5, leading=13, textColor=c_dark, spaceAfter=2),
        "head": ParagraphStyle("head", fontName=font_bold, fontSize=10, leading=12.5, textColor=c_dark),
        "sub": ParagraphStyle("sub", fontName=font, fontSize=9.5, leading=12, textColor=c_dark),
        "dates": ParagraphStyle("dates", fontName=font, fontSize=8.5, leading=11, textColor=c_muted),
        "bullet": ParagraphStyle("bullet", fontName=font, fontSize=9, leading=12.2, textColor=c_dark, leftIndent=8,
                                 bulletIndent=0),
        "plain": ParagraphStyle("plain", fontName=font, fontSize=9, leading=12, textColor=c_dark),
        "chip": ParagraphStyle("chip", fontName=font, fontSize=8.5, leading=10.5, textColor=c_chip_text),
    }

    def _link(item: dict) -> str:
        text = escape(item.get("heading") or "")
        if item.get("url"):
            return f'<a href="{escape(item["url"])}" color="#{PRIMARY}">{text}</a>'
        return text

    def rule() -> HRFlowable:
        return HRFlowable(width="100%", thickness=1.2, color=c_primary, spaceBefore=1, spaceAfter=3)

    def heading(title: str) -> list:
        return [Paragraph(escape(title.upper()), st["h2"]), rule()]

    def entries(section: dict) -> list:
        out = []
        for it in section.get("items") or []:
            block = []
            block.append(Paragraph(_link(it), st["head"]))
            if it.get("subheading"):
                block.append(Paragraph(escape(it["subheading"]), st["sub"]))
            meta = " | ".join(x for x in (it.get("dates"), it.get("location")) if x)
            if meta:
                block.append(Paragraph(escape(meta), st["dates"]))
            for b in it.get("bullets") or []:
                block.append(Paragraph(escape(b), st["bullet"], bulletText="\u2022"))
            block.append(Spacer(1, 3 * mm))
            out.extend(block)
        return out

    def chips(items: list[str]) -> list:
        cols = 3
        cells = [Paragraph(escape(x), st["chip"]) for x in items]
        while len(cells) % cols:
            cells.append("")
        rows = [cells[i:i + cols] for i in range(0, len(cells), cols)]
        table = Table(rows, colWidths=[22 * mm] * cols)
        style = [("BACKGROUND", (0, 0), (-1, -1), colors.white), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                 ("LEFTPADDING", (0, 0), (-1, -1), 2.2 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 2.2 * mm),
                 ("TOPPADDING", (0, 0), (-1, -1), 1.2 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2 * mm)]
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                if cell:
                    style.append(("BACKGROUND", (c, r), (c, r), c_chip))
        table.setStyle(TableStyle(style))
        return [table, Spacer(1, 3 * mm)]

    sections = _sections_by_key(cv)
    summary = sections["summary"]["items"][0].get("heading") if "summary" in sections and sections["summary"].get("items") else ""
    photo = Image(str(photo_png(cv.get("name") or "")), width=30 * mm, height=30 * mm)
    contact = extras.get("contact") or {}
    contact_lines = [Paragraph(escape(v), st["contact"]) for v in (contact.get("email"), contact.get("phone"),
                                                                   contact.get("location"), contact.get("linkedin")) if v]
    header_left = [Paragraph(escape(cv.get("name") or ""), st["name"]),
                   Paragraph(escape(cv.get("headline") or ""), st["headline"]),
                   Paragraph(escape(summary or ""), st["summary"])]
    header_right = [photo, Spacer(1, 2 * mm)] + contact_lines
    head = Table([[header_left, header_right]], colWidths=[118 * mm, 68 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    header_rule = HRFlowable(width="100%", thickness=1.5, color=c_primary, spaceBefore=2, spaceAfter=4)

    left, right = [], []
    for key in LEFT_SECTIONS:
        if key in sections and sections[key].get("items"):
            left += heading(sections[key]["title"]) + entries(sections[key])
    for key in RIGHT_SECTIONS:
        s = sections.get(key)
        if not s or not s.get("items"):
            continue
        right += heading(s["title"])
        items = [b for it in s["items"] for b in it.get("bullets") or []]
        if key in ("skills", "interests"):
            right += chips(items)
        elif key == "projects":
            right += entries(s)
        elif key == "other projects":
            for it in s["items"]:
                right.append(Paragraph(_link(it), st["head"]))
                if it.get("subheading"):
                    right.append(Paragraph(escape(it["subheading"]), st["dates"]))
                right.append(Spacer(1, 1.5 * mm))
            right.append(Spacer(1, 2 * mm))
        else:
            right += [Paragraph(escape(x), st["plain"]) for x in items] + [Spacer(1, 3 * mm)]
    for s in _other_sections(cv):
        right += heading(s.get("title") or "") + entries(s)

    # Page 1: a header frame, then a left and a right column. Later pages: two full-height columns.
    # Content flows left column first, then right column, and continues on the next page the same way.
    page_w, page_h = A4
    margin, header_h, gap = 12 * mm, 62 * mm, 6 * mm
    left_w, right_w = 110 * mm, page_w - 2 * margin - 110 * mm - gap
    right_x = margin + left_w + gap
    body_top_first = page_h - margin - header_h - 4 * mm
    frame_kw = dict(leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, showBoundary=0)
    first = PageTemplate(id="First", frames=[
        Frame(margin, page_h - margin - header_h, page_w - 2 * margin, header_h, **frame_kw),
        Frame(margin, margin, left_w, body_top_first - margin, **frame_kw),
        Frame(right_x, margin, right_w, body_top_first - margin, **frame_kw),
    ])
    later = PageTemplate(id="Later", frames=[
        Frame(margin, margin, left_w, page_h - 2 * margin, **frame_kw),
        Frame(right_x, margin, right_w, page_h - 2 * margin, **frame_kw),
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(str(path), pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=margin,
                          bottomMargin=margin, title=f"{cv.get('name') or 'CV'}")
    doc.addPageTemplates([first, later])
    flow = [head, header_rule, NextPageTemplate("Later"), FrameBreak()] + left + [FrameBreak()] + right
    doc.build(flow)
