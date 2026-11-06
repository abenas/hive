# LLM local na Radeon RX 9070 XT (16 GB)

**Resumo: dá para usar, e o caminho recomendado é o Ollama rodando no Windows (backend Vulkan), acessado de dentro do WSL.**

## Por que o Ollama no Windows e não no WSL

- No WSL2 não existe `/dev/kfd`, então o ROCm nativo não enxerga a GPU AMD. Relatos de compilar o Ollama com HIP dentro do WSL existem, mas são instáveis e acabam com metade do modelo na CPU.
- O Ollama traz o backend **Vulkan** habilitado por padrão no Windows e no Linux, e ele funciona com a RDNA4 (gfx1201) sem gambiarra. Em geração de texto, o Vulkan costuma empatar com o ROCm ou ficar à frente.
- Alternativa equivalente: **LM Studio** no Windows (llama.cpp com Vulkan ou ROCm). Ele expõe um servidor local, mas a Hive usa a API nativa do Ollama (`/api/chat` com `format` = JSON Schema). Para usar o LM Studio, seria preciso escrever um provedor novo.

> **Verificado nesta máquina (29/10/2026):** um Ollama instalado *dentro* do WSL (`~/.local/bin/ollama`)
> responde normalmente, mas carrega o modelo com `size_vram: 0`, ou seja, 100% na CPU. O WSL só expõe a GPU
> via `/dev/dxg` (D3D12) e nenhum driver Vulkan AMD a enxerga. Resultado com `qwen2.5-coder:14b`: ~4 tokens/s
> e ~12 GB de RAM do WSL ocupados. Confira sempre com `curl localhost:11434/api/ps` (campo `size_vram`).

### Medido com Ollama no Windows (RX 9070 XT, `qwen2.5-coder:14b`, 29/10/2026)

- Modelo 100% na VRAM (9,5 GB), **~48 tokens/s**, ou seja, ~12× mais rápido que a CPU no WSL.
- Missão completa (site de padaria): **~5 min**, 9 chamadas, ~17 mil tokens de entrada e ~8,5 mil de saída,
  **US$ 0,005 de energia**, QA aprovado na 1ª tentativa. O desenvolvedor é a etapa mais longa (~2 min, ~2,7 mil tokens).
- Rede: WSL com `networkingMode=mirrored` em `%UserProfile%\.wslconfig`, então o Ollama escuta só em `127.0.0.1`.

### `qwen3:14b` em todos os papéis (31/10/2026)

- O desenvolvedor gerava HTML+CSS numa única resposta JSON. Em pedidos ricos (ex.: cyberpunk) o CSS crescia além de
  8 mil tokens e terminava em **repetição em loop** do mesmo bloco; sem teto, o *context shift* do Ollama deixava a
  geração seguir sem fim. Correção na plataforma: HTML e CSS em duas chamadas, teto de saída calculado pelo espaço livre
  no contexto e remoção determinística de blocos de CSS repetidos.
- Com isso, a missão cyberpunk (7 seções, 5 ilustrações SVG) concluiu em **~5 min**, 12 chamadas, QA aprovado de primeira.

### Acelerando a produção (03/11/2026, missão cyberpunk, `qwen3:14b`)

| Rodada | Tempo | O que mudou |
|---|---|---|
| Antes | 515 s | — |
| Lote 1 | 501 s | Paralelismo real (`OLLAMA_NUM_PARALLEL=2`), ilustradora ∥ desenvolvedor, autorrevisão só do SEO |
| Lote 1 + menos retrabalho | **319 s** | Vera lista só o que não tem fonte; correções automáticas no desenvolvedor |

- **Paralelismo real:** defina a variável de usuário `OLLAMA_NUM_PARALLEL=2` no Windows, reinicie o Ollama e use
  `HIVE_OLLAMA_MAX_PARALLEL=2` no `.env`. Com 16k de contexto, o `qwen3:14b` passa de 11,8 para 14,4 GB, ainda todo na VRAM.
  Duas chamadas curtas juntas somaram ~72 tokens/s, contra ~52 de uma sozinha (~1,4×). Com prompts longos (~6,6 mil tokens)
  o ganho sumiu.
- **O que mais pesa é o retrabalho:** cada volta custa de 60 a 100 s. Correções determinísticas, como estilo do menu,
  meta tags, `alt` e ano de copyright, saem mais baratas que uma rodada de QA.

## Modelos que cabem em 16 GB de VRAM

| Modelo | VRAM aprox. | Uso sugerido na Hive | Observação |
|---|---|---|---|
| `gpt-oss:20b` (MXFP4) | ~13–14 GB | **padrão**: todos os papéis | Bom em raciocínio e JSON estruturado; ~90 tok/s relatados nessa placa |
| `qwen3:14b` (Q4_K_M) | ~9–10 GB | redator, PO, FinOps | Mais leve, deixa sobra para contexto maior (~50 tok/s) |
| `qwen3-coder:30b` / `qwen3:30b-a3b` (MoE, Q4) | ~18 GB | desenvolvedor | Não cabe inteiro: parte vai para a RAM. Por ser MoE, continua usável |
| `gemma3:12b` | ~8 GB | redator | Bom em português |

> Os números de VRAM e velocidade vêm de benchmarks da comunidade; confirme com `ollama ps` na sua máquina.
> Contexto maior consome VRAM extra (KV cache). A Hive usa `num_ctx=16384` por padrão (`HIVE_OLLAMA_NUM_CTX`).

## Passo a passo

1. **Windows**: instale o Ollama e rode `ollama pull gpt-oss:20b`.
2. Libere acesso a partir do WSL: defina a variável de ambiente do Windows `OLLAMA_HOST=0.0.0.0:11434` e reinicie o Ollama. Pode ser preciso liberar a porta 11434 no firewall para a rede do WSL.
3. **WSL**: descubra o IP do host com `ip route | awk '/default/ {print $3}'` (nesta máquina é `192.168.80.1`). Com o WSL em modo de rede *mirrored*, basta usar `localhost`.
4. Configure o `backend/.env`:

   ```env
   HIVE_LLM_PROVIDER=ollama
   HIVE_OLLAMA_URL=http://192.168.80.1:11434
   HIVE_OLLAMA_MODEL=gpt-oss:20b
   ```

5. Teste com `curl $HIVE_OLLAMA_URL/api/tags`.

## Modo híbrido (recomendado para qualidade × custo)

O roteamento é por papel. Por exemplo, o orquestrador (planejamento crítico) fica no Claude e o trabalho braçal vai para a GPU local:

```env
HIVE_LLM_PROVIDER=ollama
HIVE_ROUTING={"orchestrator": "anthropic:claude-opus-5-5", "developer": "anthropic:claude-sonnet-5-5"}
```

## FinOps do modelo local

O custo do LLM local não é zero: a conta é **energia × tempo de inferência**. A Hive calcula assim:

```
custo = segundos × HIVE_LOCAL_GPU_WATTS (304 W, TBP da 9070 XT) / 3.600.000 × HIVE_ENERGY_PRICE_PER_KWH_USD
```

Exemplo: uma missão com ~10 chamadas de ~30 s dá ~0,025 kWh, ou seja, menos de US$ 0,01. O custo real do caminho local está em **qualidade** (mais retrabalho do QA, saídas JSON inválidas que precisam de nova tentativa) e em **latência**. As duas coisas aparecem na trilha de auditoria (`llm.call`, `task.rework`), o que permite comparar os provedores com dados.
