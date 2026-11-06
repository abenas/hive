---
name: web-quality
title: Qualidade web antes da entrega
version: 1.0.0
roles: [developer]
---
Antes de entregar, confira cada item. São exatamente as verificações que o QA executa; acertar aqui evita retrabalho.

- `<html lang="pt-BR">`, `<meta charset="utf-8">` e `<meta name="viewport" content="width=device-width, initial-scale=1">`.
- `<title>` com 10 a 60 caracteres e `<meta name="description">` com 50 a 160 caracteres: copie do content.json, não reescreva.
- Exatamente uma `<h1>` (o título do destaque). Seções usam `<h2>`, itens usam `<h3>`.
- Cada seção do sitemap vira `<section id="...">` com o mesmo id do sitemap. Todo `href="#x"` precisa apontar para um id existente.
- Toda `<img>` tem `alt` descritivo, `width` e `height`. Use os arquivos de images.json na seção indicada por `section_id`.
- `<link rel="stylesheet" href="styles.css">`. Nada de `<script>` nem recursos externos (fontes, CDNs, imagens remotas).
- CSS com as cores do design system em variáveis (`:root { --primary: ... }`), mobile first, `max-width` no conteúdo e `@media (prefers-reduced-motion: reduce)` quando houver animação.
