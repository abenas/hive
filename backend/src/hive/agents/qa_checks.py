"""Verificações determinísticas de QA (sem LLM: custo zero e resultado reprodutível)."""

import re
from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass
class Check:
    id: str
    title: str
    passed: bool
    detail: str
    critical: bool = True


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: list[tuple[str, dict]] = []
        self.ids: set[str] = set()
        self.text_in: dict[str, str] = {}
        self._stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if "id" in a:
            self.ids.add(a["id"])
        self._stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self._stack:
            while self._stack and self._stack.pop() != tag:
                pass

    def handle_data(self, data):
        if self._stack and self._stack[-1] == "title":
            self.text_in["title"] = self.text_in.get("title", "") + data


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    rgb = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(fg: str, bg: str) -> float:
    try:
        a, b = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    except (ValueError, IndexError):
        return 0.0
    return round((a + 0.05) / (b + 0.05), 2)


def run_checks(html: str, css: str, section_ids: list[str], palette: dict) -> list[Check]:
    p = _Collector()
    p.feed(html)
    tags = p.tags
    find = lambda name: [a for t, a in tags if t == name]  # noqa: E731
    metas = find("meta")
    meta_names = {m.get("name") for m in metas}
    imgs = find("img")
    h1s = find("h1")
    title = p.text_in.get("title", "").strip()
    desc = next((m.get("content", "") for m in metas if m.get("name") == "description"), "")
    anchors = [a.get("href", "")[1:] for a in find("a") if a.get("href", "").startswith("#") and len(a.get("href")) > 1]
    broken = sorted({x for x in anchors if x not in p.ids})
    missing_sections = [s for s in section_ids if s not in p.ids]
    nav_list = re.search(r"<nav\b[^>]*>.*?<ul\b", html, re.S | re.I)
    nav_styled = not nav_list or re.search(r"list-style(?:-type)?\s*:\s*none", css)
    size_kb = round((len(html.encode()) + len(css.encode())) / 1024, 1)
    text_contrast = contrast_ratio(palette.get("text", "#000"), palette.get("background", "#fff"))
    hero_contrast = contrast_ratio(palette.get("on_primary", "#fff"), palette.get("primary", "#000"))

    return [
        Check("html-lang", "Idioma do documento declarado", bool(find("html") and find("html")[0].get("lang")),
              f"lang={find('html')[0].get('lang') if find('html') else None}"),
        Check("viewport", "Meta viewport (responsividade)", "viewport" in meta_names, ""),
        Check("seo-title", "Título SEO entre 10 e 60 caracteres", 10 <= len(title) <= 60, f"{len(title)} caracteres"),
        Check("seo-description", "Meta description entre 50 e 160 caracteres", 50 <= len(desc) <= 160,
              f"{len(desc)} caracteres" if desc else "ausente"),
        Check("single-h1", "Exatamente uma <h1>", len(h1s) == 1, f"{len(h1s)} encontrada(s)"),
        Check("img-alt", "Todas as imagens com texto alternativo", all(i.get("alt") for i in imgs),
              f"{sum(1 for i in imgs if not i.get('alt'))} de {len(imgs)} sem alt"),
        Check("sections", "Todas as seções do mapa do site presentes", not missing_sections,
              "faltando: " + ", ".join(missing_sections) if missing_sections else f"{len(section_ids)} seções"),
        Check("anchors", "Links internos apontam para âncoras existentes", not broken,
              "quebrados: " + ", ".join(broken) if broken else f"{len(anchors)} links"),
        Check("contrast-text", "Contraste texto/fundo ≥ 4.5:1 (WCAG AA)", text_contrast >= 4.5, f"{text_contrast}:1"),
        Check("contrast-hero", "Contraste no destaque ≥ 3:1 (texto grande)", hero_contrast >= 3.0, f"{hero_contrast}:1"),
        Check("nav-style", "Menu de navegação estilizado (sem marcadores de lista)", bool(nav_styled),
              "" if nav_styled else "o <ul> do <nav> não tem list-style: none no CSS"),
        Check("stylesheet", "Folha de estilos vinculada", any(l.get("rel") == "stylesheet" for l in find("link")), ""),
        Check("weight", "Peso HTML+CSS ≤ 100 KB", size_kb <= 100, f"{size_kb} KB", critical=False),
        Check("no-inline-js", "Sem scripts inline (CSP estrita)", not re.search(r"<script(?![^>]*\bsrc=)", html),
              "", critical=False),
    ]
