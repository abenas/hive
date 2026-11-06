"""Gerador determinístico de site (template) usado pelo agente desenvolvedor no modo mock
e como referência de estrutura para modelos de LLM."""

import re
from html import escape

from hive.agents.schemas import DesignSystem, SiteContent


def css_hooks(html: str) -> dict[str, list[str]]:
    """Classes, ids e tags usados no HTML: é o que o CSS precisa cobrir (sem mandar o HTML inteiro)."""
    classes = sorted({c for attr in re.findall(r'class="([^"]+)"', html) for c in attr.split()})
    ids = sorted(set(re.findall(r'id="([^"]+)"', html)))
    tags = sorted(set(re.findall(r"<([a-z][a-z0-9]*)\b", html)) - {"html", "head", "meta", "title", "link"})
    return {"classes": classes, "ids": ids, "tags": tags}


def dedupe_css(css: str) -> tuple[str, int]:
    """Remove blocos de nível superior idênticos (sintoma de modelo local em repetição).

    Devolve (css, quantidade removida). Comentários colados a um bloco viajam com ele.
    """
    blocks, depth, start = [], 0, 0
    for i, ch in enumerate(css):
        if ch == "{":
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                blocks.append(css[start : i + 1])
                start = i + 1
    tail = css[start:].strip()
    seen, kept = set(), []
    for block in blocks:
        key = re.sub(r"\s+", " ", block).strip()
        if key not in seen:
            seen.add(key)
            kept.append(block.strip())
    return "\n\n".join(kept) + (f"\n{tail}" if tail and depth == 0 else "") + "\n", len(blocks) - len(kept)


NAV_RESET = "nav ul { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 16px; }"


def autofix(html: str, css: str, description: str, alts: dict[str, str]) -> tuple[str, str, list[str]]:
    """Corrige de forma determinística os erros mecânicos que o QA reprovaria.

    Evita uma rodada inteira de retrabalho (LLM + QA) por um atributo esquecido. Só mexe no que tem
    resposta certa e única; o resto continua com o QA. Devolve (html, css, correções aplicadas).
    """
    fixes: list[str] = []
    if re.search(r"<html(?![^>]*\blang=)", html, re.I):
        html = re.sub(r"<html\b", '<html lang="pt-BR"', html, count=1, flags=re.I)
        fixes.append("idioma do documento (lang=pt-BR)")
    if "<head" in html and not re.search(r'<meta[^>]+name="viewport"', html, re.I):
        html = re.sub(r"(<head[^>]*>)", r'\1\n<meta name="viewport" content="width=device-width, initial-scale=1">',
                      html, count=1, flags=re.I)
        fixes.append("meta viewport")
    if "<head" in html and not re.search(r'<meta[^>]+name="description"', html, re.I) and description:
        html = re.sub(r"(<head[^>]*>)", lambda m: f'{m.group(1)}\n<meta name="description" content="{escape(description)}">',
                      html, count=1, flags=re.I)
        fixes.append("meta description a partir do conteúdo aprovado")
    if "<head" in html and not re.search(r'<link[^>]+rel="stylesheet"', html, re.I):
        html = re.sub(r"(</head>)", r'<link rel="stylesheet" href="styles.css">\n\1', html, count=1, flags=re.I)
        fixes.append("vínculo com styles.css")

    def add_alt(m: re.Match) -> str:
        tag = m.group(0)
        if re.search(r'\balt="[^"]+"', tag):
            return tag
        src = (re.search(r'\bsrc="([^"]+)"', tag) or [None, ""])[1]
        alt = alts.get(src, "Ilustração")
        fixes.append(f"texto alternativo de {src or 'imagem'}")
        return re.sub(r'\s*\balt="[^"]*"', "", tag).replace("<img", f'<img alt="{escape(alt)}"', 1)

    html = re.sub(r"<img\b[^>]*>", add_alt, html, flags=re.I)
    if re.search(r"<nav\b[^>]*>.*?<ul\b", html, re.S | re.I) and not re.search(r"list-style(?:-type)?\s*:\s*none", css):
        css = f"{css.rstrip()}\n\n{NAV_RESET}\n"
        fixes.append("estilo do menu (lista sem marcadores)")
    return html, css, fixes


def initials(name: str) -> str:
    words = [w for w in name.split() if w[:1].isalnum()]
    return "".join(w[0] for w in words[:2]).upper() or "H"


def logo_svg(name: str, design: DesignSystem) -> str:
    p = design.palette
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img">'
        f"<title>{escape(name)}</title>"
        f'<rect width="64" height="64" rx="16" fill="{p.primary}"/>'
        f'<text x="32" y="41" text-anchor="middle" font-family="sans-serif" font-size="24" '
        f'font-weight="700" fill="{p.on_primary}">{escape(initials(name))}</text></svg>'
    )


def render_css(design: DesignSystem) -> str:
    p = design.palette
    return f""":root {{
  --primary: {p.primary}; --on-primary: {p.on_primary}; --secondary: {p.secondary};
  --accent: {p.accent}; --bg: {p.background}; --surface: {p.surface};
  --text: {p.text}; --muted: {p.muted}; --radius: {design.radius_px}px;
  --font-heading: {design.font_heading}, system-ui, sans-serif;
  --font-body: {design.font_body}, system-ui, sans-serif;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{ margin: 0; font-family: var(--font-body); color: var(--text); background: var(--bg); line-height: 1.6; }}
h1, h2, h3 {{ font-family: var(--font-heading); line-height: 1.2; }}
a {{ color: var(--primary); }}
.container {{ width: min(1120px, 100% - 32px); margin-inline: auto; }}
.site-header {{ position: sticky; top: 0; background: var(--bg); border-bottom: 1px solid var(--surface); z-index: 10; }}
.site-header .container {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-block: 12px; }}
.brand {{ display: flex; align-items: center; gap: 10px; font-weight: 700; color: var(--text); text-decoration: none; }}
.brand img {{ width: 36px; height: 36px; }}
nav ul {{ display: flex; flex-wrap: wrap; gap: 16px; list-style: none; margin: 0; padding: 0; }}
nav a {{ color: var(--text); text-decoration: none; font-size: .95rem; }}
.hero {{ background: linear-gradient(135deg, var(--primary), var(--secondary)); color: var(--on-primary); padding: 96px 0; }}
.hero h1 {{ font-size: clamp(2rem, 5vw, 3.25rem); margin: 0 0 16px; max-width: 18ch; }}
.hero p {{ font-size: 1.2rem; max-width: 60ch; opacity: .95; }}
.btn {{ display: inline-block; background: var(--accent); color: var(--text); padding: 14px 24px; border-radius: var(--radius); font-weight: 700; text-decoration: none; margin-top: 16px; }}
section {{ padding: 72px 0; }}
section:nth-of-type(even) {{ background: var(--surface); }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 20px; margin-top: 24px; }}
.card {{ background: var(--bg); border: 1px solid var(--surface); border-radius: var(--radius); padding: 20px; }}
.card h3 {{ margin-top: 0; color: var(--primary); }}
.muted {{ color: var(--muted); }}
.hero-art, .section-art {{ display: block; width: 100%; height: auto; border-radius: var(--radius); margin-top: 24px; }}
.hero-art {{ max-width: 720px; box-shadow: 0 0 40px color-mix(in srgb, var(--accent) 35%, transparent); }}
.site-footer {{ padding: 32px 0; background: var(--text); color: var(--bg); font-size: .9rem; }}
@media (max-width: 640px) {{ nav ul {{ display: none; }} .hero {{ padding: 64px 0; }} }}
"""


def render_html(content: SiteContent, company: str, *, defect: bool = False,
                images: dict[str, tuple[str, str]] | None = None) -> str:
    """`defect=True` reproduz um erro comum (título SEO longo demais, que as correções automáticas não
    resolvem porque exige reescrever o texto) para
    demonstrar o ciclo QA → retrabalho no modo de simulação.
    `images` mapeia section_id ("hero" ou id do sitemap) -> (arquivo, texto alternativo)."""
    images = images or {}

    def figure(key: str, cls: str) -> str:
        if key not in images:
            return ""
        src, alt = images[key]
        return f'<img class="{cls}" src="{escape(src)}" alt="{escape(alt)}" width="800" height="500" loading="lazy">'

    nav = "".join(f'<li><a href="#{escape(s.id)}">{escape(s.title)}</a></li>' for s in content.sections)
    blocks = []
    for s in content.sections:
        items = "".join(
            f'<article class="card"><h3>{escape(i.title)}</h3><p>{escape(i.text)}</p></article>'
            for i in s.items
        )
        grid = f'<div class="grid">{items}</div>' if items else ""
        blocks.append(
            f'<section id="{escape(s.id)}"><div class="container"><h2>{escape(s.title)}</h2>'
            f"<p>{escape(s.body)}</p>{figure(s.id, 'section-art')}{grid}</div></section>"
        )
    c = content.contact
    channels = "".join(f"<li>{escape(ch)}</li>" for ch in c.channels)
    meta_desc = f'<meta name="description" content="{escape(content.seo.description)}">\n'
    alt = f' alt="Logotipo {escape(company)}"'
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(content.seo.title + (" | " + content.hero.subheadline if defect else ""))}</title>
{meta_desc}<meta name="keywords" content="{escape(", ".join(content.seo.keywords))}">
<link rel="icon" href="logo.svg">
<link rel="stylesheet" href="styles.css">
</head>
<body>
<header class="site-header"><div class="container">
<a class="brand" href="#"><img src="logo.svg"{alt} width="36" height="36">{escape(company)}</a>
<nav aria-label="Principal"><ul>{nav}<li><a href="#contato">Contato</a></li></ul></nav>
</div></header>
<main>
<div class="hero"><div class="container">
<h1>{escape(content.hero.headline)}</h1>
<p>{escape(content.hero.subheadline)}</p>
<a class="btn" href="#contato">{escape(content.hero.cta)}</a>
{figure("hero", "hero-art")}
</div></div>
{"".join(blocks)}
<section id="contato"><div class="container">
<h2>{escape(c.headline)}</h2><p>{escape(c.text)}</p><ul>{channels}</ul>
<a class="btn" href="#contato">{escape(content.hero.cta)}</a>
</div></section>
</main>
<footer class="site-footer"><div class="container">{escape(content.footer)}</div></footer>
</body>
</html>
"""
