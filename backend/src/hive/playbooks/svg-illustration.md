---
name: svg-illustration
title: Ilustração vetorial em SVG
version: 1.0.0
roles: [illustrator]
---
- Documento completo: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500">`, até ~60 elementos. Nada de `<script>`, `<image>`, `<foreignObject>`, `on*` ou links externos; o SVG é rejeitado e substituído se tiver isso.
- Composição: um assunto central reconhecível ligado ao tema da seção (ex.: pão, xícara, bolo, mapa), um fundo com profundidade (gradiente + formas de horizonte) e no máximo três cores fortes da paleta.
- Brilho neon: defina uma vez `<filter id="glow"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>` e aplique só nos contornos principais (`stroke` com `filter="url(#glow)"`).
- Prefira formas simples e legíveis (`path`, `circle`, `rect`, `polygon`) a detalhes finos. Sem textos longos dentro da imagem.
- `alt` descreve o que a imagem mostra e por que importa para a seção, em uma frase.
