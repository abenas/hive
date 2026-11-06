# FinOps: quanto custa manter e operar a Hive

> Valores em USD, região us-east-1, preços públicos de referência de out/2026.
> São **estimativas de ordem de grandeza**. Valide na [AWS Pricing Calculator](https://calculator.aws/) e na
> [página de preços do Bedrock](https://aws.amazon.com/bedrock/pricing/) antes de orçar.

O custo tem três camadas. Cada uma é medida de um jeito:

| Camada | O que é | Como a Hive mede |
|---|---|---|
| 1. Plataforma (fixo) | Infraestrutura que fica de pé 24/7 | Tags `Project=hive` + AWS Cost Explorer |
| 2. Produção (variável por missão) | Tokens de LLM gastos pelos agentes | Tabela `llm_calls`, com custo por agente, modelo e missão |
| 3. Operação da entrega (por cliente) | Hospedagem do que foi implantado | Agente Cloud estima; tag `CostCenter=sites` |

## 1. Plataforma (custo fixo mensal)

| Componente | MVP enxuto | Produção (multi-AZ) |
|---|---|---|
| API + workers (ECS Fargate, 0,25 vCPU/0,5 GB → 2×0,5 vCPU/1 GB) | ~US$ 9 | ~US$ 36 |
| Application Load Balancer (necessário para SSE) | ~US$ 18 | ~US$ 22 |
| Banco (RDS PostgreSQL t4g.micro → Aurora Serverless v2) | ~US$ 15 | ~US$ 60–90 |
| Console web (S3 + CloudFront) | ~US$ 1 | ~US$ 2 |
| Fila/orquestração (SQS + Step Functions) | < US$ 1 | ~US$ 2 |
| Logs e métricas (CloudWatch, ~3 GB/mês) | ~US$ 3 | ~US$ 10 |
| Secrets Manager (4 segredos), Route 53, ECR | ~US$ 3 | ~US$ 4 |
| **Total aproximado** | **~US$ 50/mês** | **~US$ 140–180/mês** |

**Armadilhas a evitar:**

- **NAT Gateway** custa ~US$ 33/mês mais tráfego. Use subnets públicas com security groups restritos, ou VPC endpoints.
- **Logs sem retenção** crescem para sempre. Configure 14–30 dias.
- **Aurora com mínimo alto**: o Serverless v2 permite pausar em 0 ACU; use em ambientes que não são de produção.

## 2. Produção: custo por missão (LLM)

Medição real de uma missão no modo mock: 10 chamadas, ~15 mil tokens de entrada e ~6,7 mil de saída. Com modelos reais, conte com **3–5× mais tokens**, porque entram os prompts de sistema completos, o raciocínio adaptativo (cobrado como saída) e o HTML gerado pelo LLM.

| Roteamento | Preço (in/out por 1M) | Custo estimado por missão |
|---|---|---|
| Opus 5.5 no orquestrador + Sonnet 5.5 nos especialistas (**padrão**) | $4/$20 · $2/$10 | **US$ 0,25 – 0,60** |
| Tudo em Opus 5.5 | $4/$20 | US$ 0,50 – 1,20 |
| Opus 5.5 no orquestrador + Haiku 5.5 nos especialistas | $4/$20 · $0,10/$0,50 | US$ 0,06 – 0,15 |
| Tudo local (gpt-oss:20b na RX 9070 XT) | energia | < US$ 0,01 (mais latência e retrabalho) |
| Híbrido: orquestrador no Claude, resto local | — | US$ 0,03 – 0,10 |

Em 1.000 missões por mês, o roteamento padrão fica entre ~US$ 250 e 600; com Haiku, entre ~US$ 60 e 150. **Em escala, o LLM domina o custo, e a infraestrutura vira detalhe.**

Alavancas, em ordem de impacto:

1. **Prompt caching** nos prompts de sistema e nos insumos repetidos. Leitura de cache sai a 5–10% do preço de entrada.
2. **Roteamento por papel**: modelo forte só onde há julgamento (plano, código); o resto vai para Haiku ou modelo local.
3. **Esforço (`effort`) por papel**: já configurado; FinOps usa `low` e o desenvolvedor usa `high`.
4. **QA determinístico**: o agente de QA não usa LLM, então custa zero e é reprodutível.
5. **Orçamento por missão** (`HIVE_MISSION_BUDGET_USD`): a missão é interrompida antes de estourar, e a interrupção fica registrada na trilha.
6. **Batch API** (−50%) para trabalhos que não precisam de resposta interativa.

## 3. Operação da entrega (por site publicado)

Estimativa do agente Cloud para um site de ~7 KB com 10 mil visitas/mês: **~US$ 0,55/mês** pela tabela, ou ~US$ 0,50 com o free tier perpétuo do CloudFront (1 TB e 10 milhões de requisições por mês). Na prática, o custo é a zona do Route 53. Com isso, fica fácil precificar o produto: o custo marginal de hospedagem é quase zero, então a margem está no valor da produção.

## Visão consolidada (exemplo: 300 missões/mês, roteamento padrão)

| Item | US$/mês |
|---|---|
| Plataforma (MVP) | ~50 |
| LLM (300 × ~US$ 0,40) | ~120 |
| Hospedagem de 300 sites | ~150 (dominado por Route 53; zonas compartilhadas reduzem) |
| **Total** | **~320** · ~US$ 1,07 por site entregue/mês |

## Onde ver isso na plataforma

- **Console → missão → aba FinOps**: custo por agente e por modelo, e o consumo do orçamento.
- **Console → FinOps**: consolidado por agente, modelo e status de missão.
- **Artefato `finops-report.md`** de cada missão, escrito pelo agente FinOps (Fábio).
- **API**: `GET /api/finops/summary` e `GET /api/missions/{id}/audit`.
