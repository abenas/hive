"""Ilustrações em SVG: validação/higienização do que o LLM produz e arte procedural de fallback."""

import hashlib
import math
import re
import xml.etree.ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
FORBIDDEN_TAGS = {"script", "foreignObject", "iframe", "object", "embed", "audio", "video"}
MAX_BYTES = 60_000


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def sanitize_svg(svg: str) -> tuple[str | None, str]:
    """Devolve (svg_seguro, motivo). svg_seguro=None quando o documento é inválido ou inseguro.

    Regras: XML bem formado, raiz <svg> com viewBox, sem scripts/objetos embutidos, sem
    atributos de evento (on*) e sem referências externas (http/https/data em href).
    """
    svg = svg.strip()
    svg = re.sub(r"^```(?:svg|xml)?\s*|\s*```$", "", svg)  # modelos às vezes cercam com markdown
    if len(svg.encode()) > MAX_BYTES:
        return None, f"SVG muito grande ({len(svg.encode())} bytes)"
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as e:
        return None, f"XML inválido: {e}"
    if _local(root.tag) != "svg":
        return None, "raiz não é <svg>"
    if "viewBox" not in root.attrib:
        root.set("viewBox", "0 0 800 500")
    for el in root.iter():
        if _local(el.tag) in FORBIDDEN_TAGS:
            return None, f"elemento proibido <{_local(el.tag)}>"
        for attr, value in el.attrib.items():
            name = _local(attr).lower()
            if name.startswith("on"):
                return None, f"atributo de evento proibido ({name})"
            if name == "href" and not value.startswith("#"):
                return None, "referência externa em href"
            if any(not ref.strip(" '\"").startswith("#") for ref in re.findall(r"url\(([^)]*)\)", value)):
                return None, "url() externa"
    elements = sum(1 for _ in root.iter())
    if elements < 4:
        return None, "SVG praticamente vazio"
    ET.register_namespace("", SVG_NS)
    return ET.tostring(root, encoding="unicode"), f"{elements} elementos"


def neon_art(seed: str, palette: dict, label: str = "") -> str:
    """Arte procedural estilo synthwave/cyberpunk: horizonte em grade, sol e silhueta urbana em neon."""
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    rnd = lambda i, lo, hi: lo + (h >> (i * 7)) % (hi - lo + 1)  # noqa: E731 — pseudo-aleatório determinístico
    bg = palette.get("background", "#0b0b16")
    c1 = palette.get("primary", "#ff2bd6")
    c2 = palette.get("secondary", "#00e5ff")
    c3 = palette.get("accent", "#f9f871")
    grid = "".join(f'<line x1="{400 + (i - 10) * 12}" y1="300" x2="{400 + (i - 10) * 90}" y2="500"/>' for i in range(21))
    grid += "".join(f'<line x1="0" y1="{300 + 200 * (k / 8) ** 1.8:.1f}" x2="800" y2="{300 + 200 * (k / 8) ** 1.8:.1f}"/>'
                    for k in range(1, 9))
    buildings, x = [], 0
    for i in range(18):
        w, top = rnd(i, 30, 70), rnd(i + 3, 150, 260)
        buildings.append(f'<rect x="{x}" y="{top}" width="{w}" height="{300 - top}"/>')
        x += w + rnd(i + 5, 2, 10)
        if x > 800:
            break
    windows = "".join(f'<rect x="{rnd(i, 0, 780)}" y="{rnd(i + 9, 170, 290)}" width="4" height="6"/>' for i in range(40))
    sun_r = rnd(1, 70, 100)
    stripes = "".join(f'<rect x="{400 - sun_r}" y="{205 - sun_r + 12 * k + 40}" width="{2 * sun_r}" height="{2 + k}" fill="{bg}"/>'
                      for k in range(1, 6))
    stars = "".join(f'<circle cx="{rnd(i, 0, 800)}" cy="{rnd(i + 11, 0, 150)}" r="{rnd(i + 2, 1, 2) / 2}"/>' for i in range(30))
    angle = rnd(4, 0, 360)
    ring = f'<ellipse cx="{400 + 160 * math.cos(math.radians(angle)):.0f}" cy="90" rx="38" ry="10" fill="none" stroke="{c3}" stroke-width="2" opacity=".7"/>'
    return f"""<svg xmlns="{SVG_NS}" viewBox="0 0 800 500" role="img"><title>{label}</title>
<defs>
<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{bg}"/><stop offset="1" stop-color="{c1}" stop-opacity=".35"/></linearGradient>
<linearGradient id="sun" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{c3}"/><stop offset="1" stop-color="{c1}"/></linearGradient>
<filter id="glow"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs>
<rect width="800" height="500" fill="{bg}"/><rect width="800" height="300" fill="url(#sky)"/>
<g fill="#ffffff" opacity=".7">{stars}</g>{ring}
<circle cx="400" cy="205" r="{sun_r}" fill="url(#sun)" filter="url(#glow)"/>{stripes}
<g fill="{bg}" stroke="{c2}" stroke-width="1.5" filter="url(#glow)">{"".join(buildings)}</g>
<g fill="{c3}" opacity=".8">{windows}</g>
<rect y="300" width="800" height="200" fill="{bg}"/>
<g stroke="{c1}" stroke-width="1.2" opacity=".8" filter="url(#glow)">{grid}</g>
</svg>"""
