from hive.agents.site_builder import autofix, css_hooks, dedupe_css

# Padrão real observado com qwen3:14b: o mesmo bloco repetido até esgotar os tokens.
LOOPING_CSS = """:root { --accent: #0ff; }

/* Estilo para o WhatsApp e Instagram no rodapé */

footer a {
  color: var(--accent);
}

/* Estilo para o WhatsApp e Instagram no rodapé */

footer a {
  color: var(--accent);
}

@media (max-width: 600px) { footer a { margin: 0; } }

/* Estilo para o WhatsApp e Instagram no rodapé */

footer a {
  color: var(--accent);
}
"""


def test_dedupe_css_drops_repeated_blocks_and_keeps_nested_rules():
    css, removed = dedupe_css(LOOPING_CSS)
    assert removed == 2
    assert css.count("footer a {\n  color") == 1
    assert "@media (max-width: 600px) { footer a { margin: 0; } }" in css


def test_dedupe_css_drops_unterminated_tail_from_truncated_output():
    css, removed = dedupe_css(":root { --a: 1; }\nbody { color: red; }\nfooter a {\n  color: var(--a")
    assert removed == 0
    assert "footer a" not in css and "body { color: red; }" in css


def test_css_hooks_lists_what_the_stylesheet_must_cover():
    html = '<html><head><title>x</title></head><body><section id="produtos" class="grid card"><h2 class="title">P</h2></section></body></html>'
    hooks = css_hooks(html)
    assert hooks == {"classes": ["card", "grid", "title"], "ids": ["produtos"], "tags": ["body", "h2", "section"]}


def test_autofix_repairs_mechanical_qa_failures_without_an_llm_round():
    html = ('<html><head><title>Sabor da Vila</title></head><body><nav><ul><li><a href="#a">A</a></li></ul></nav>'
            '<img src="img-hero.svg"><img src="logo.svg" alt="Logo"></body></html>')
    fixed_html, fixed_css, fixes = autofix(html, "body { color: #fff; }", "Pães artesanais & café", {"img-hero.svg": "Pão neon"})
    assert '<html lang="pt-BR"' in fixed_html and 'name="viewport"' in fixed_html
    assert 'content="Pães artesanais &amp; café"' in fixed_html and 'href="styles.css"' in fixed_html
    assert '<img alt="Pão neon" src="img-hero.svg">' in fixed_html and 'alt="Logo"' in fixed_html
    assert "list-style: none" in fixed_css
    assert len(fixes) == 6

    again_html, again_css, again = autofix(fixed_html, fixed_css, "x", {})
    assert again == [] and again_html == fixed_html  # idempotente
