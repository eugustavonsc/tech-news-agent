"""Curadoria do lote de notícias antes de resumir e enviar ao Telegram.

Por que existe: o fetcher entrega ~400 notícias por dia (o job roda a cada ~10
minutos), e o filtro de palavras-chave do fetcher junto com o gate IRRELEVANTE
do summarizer deixam passar muito ruído. Numa amostra de 25 notícias enviadas:
metade não era tecnologia (reembolso de aéreas, política internacional, futebol,
saúde bucal), havia publieditorial e listicle de afiliado, e um único teste do
Starship apareceu 6 vezes vindo de 6 veículos diferentes.

A curadoria roda ANTES de `format_news_with_llm`, usando só título e descrição do
fetcher. Isso é deliberado: resumir uma notícia que vai ser descartada é pagar
por trabalho jogado no lixo. Uma chamada de curadoria por execução substitui
dezenas de chamadas de resumo.

Duplicata de assunto exige julgamento semântico: "SpaceX lança Starship com
sucesso" e "Foguete gigante pousa no mar após teste" são a mesma notícia com
títulos pouco parecidos, então o dedupe por similaridade de string do fetcher
não pega.
"""

import json
import logging

from openai import OpenAI

from app import config

logger = logging.getLogger(__name__)

client = OpenAI(
    api_key=config.OPENCODER_API_KEY,
    base_url=config.OPENCODER_BASE_URL,
)

DESCRIPTION_PREVIEW_CHARS = 300

SYSTEM_PROMPT = """Você é o editor de um canal brasileiro de notícias de tecnologia no Telegram. Recebe uma lista numerada de notícias candidatas e decide quais merecem ser enviadas aos inscritos.

Seja EXIGENTE: é melhor enviar 1 boa notícia que 10 medíocres. Os inscritos recebem poucas mensagens por dia e cada uma precisa valer a interrupção.

REJEITE uma candidata se ela:
- não for genuinamente sobre tecnologia (economia, política, esporte, saúde, turismo, curiosidades e notícia local aparecem na lista por engano do filtro de palavras-chave);
- for publieditorial, propaganda, cupom, lista de ofertas ou review de afiliado ("separamos uma seleção", "bom e barato", "confira os descontos");
- for opinião, coluna, entrevista ou análise em vez de fato novo;
- for nicho corporativo sem interesse para o público geral (resultado financeiro, fusão, mudança de executivo);
- for vaga ou sem fato concreto (só faz sentido para quem abrir o link);
- tratar do MESMO assunto de outra candidata da lista (mantenha apenas a de melhor fonte e texto mais completo);
- tratar do MESMO assunto de uma notícia já enviada recentemente (lista fornecida). Assunto repetido com título diferente ainda é repetição.

APROVE apenas fato novo e concreto sobre tecnologia, com impacto real para quem usa tecnologia no Brasil. Priorize IA, segurança e vazamentos, golpes, lançamentos de produto, plataformas usadas por muita gente (WhatsApp, Android, iOS, Google, streaming), espaço e ciência aplicada.

Aprove no MÁXIMO {max_aprovadas} candidatas. Se nenhuma prestar, devolva uma lista vazia — isso é um resultado legítimo e esperado em muitas execuções.

Responda APENAS com JSON, sem cercas de código e sem texto em volta:
{{"aprovadas": [<ids aprovados>], "motivo": "<uma frase curta sobre o critério aplicado>"}}"""


def _build_user_prompt(candidates, recent_titles):
    blocks = []
    for i, article in enumerate(candidates):
        description = (article.get("description") or "").strip()
        if len(description) > DESCRIPTION_PREVIEW_CHARS:
            description = description[:DESCRIPTION_PREVIEW_CHARS] + "..."
        blocks.append(
            f"id: {i}\n"
            f"título: {article.get('title')}\n"
            f"fonte: {article.get('source') or 'desconhecida'}\n"
            f"descrição: {description or '(sem descrição)'}"
        )

    prompt = "CANDIDATAS:\n\n" + "\n\n---\n\n".join(blocks)

    if recent_titles:
        enviadas = "\n".join(f"- {t}" for t in recent_titles)
        prompt += (
            "\n\n=====\n\nJÁ ENVIADAS RECENTEMENTE "
            f"(não repita o assunto):\n{enviadas}"
        )
    else:
        prompt += "\n\n=====\n\nNada foi enviado recentemente."

    return prompt


def _parse_response(raw):
    """Extrai o JSON da resposta, tolerando cercas de código."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    return json.loads(text.strip())


def select(candidates, recent_titles=()):
    """Decide quais candidatas enviar.

    Retorna (aprovadas, rejeitadas, motivo) — duas listas de artigos e a frase
    do editor. Em caso de falha do LLM, retorna ([], [], motivo): nada é enviado
    e nada é descartado, então as notícias voltam a ser avaliadas na próxima
    execução (~10 min depois), sem perda.
    """
    if not candidates:
        return [], [], "nenhuma candidata"

    system = SYSTEM_PROMPT.format(max_aprovadas=config.MAX_APPROVED_PER_RUN)

    try:
        response = client.chat.completions.create(
            model=config.MODEL_ID,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": _build_user_prompt(candidates, recent_titles)},
            ],
            temperature=0.2,
        )
        raw = (response.choices[0].message.content or "").strip()
    except Exception:
        logger.exception("Curadoria falhou na chamada ao LLM; nada será enviado nesta execução")
        return [], [], "erro ao chamar o LLM"

    try:
        decision = _parse_response(raw)
    except (ValueError, IndexError):
        logger.error("Curadoria devolveu resposta não-JSON: %r", raw[:300])
        return [], [], "resposta do LLM ilegível"

    motivo = str(decision.get("motivo") or "sem motivo informado")

    raw_ids = decision.get("aprovadas")
    if not isinstance(raw_ids, list):
        logger.error("Curadoria devolveu 'aprovadas' inválido: %r", raw_ids)
        return [], [], "campo 'aprovadas' inválido"

    approved_idx = []
    for value in raw_ids:
        try:
            idx = int(value)
        except (TypeError, ValueError):
            logger.warning("Curadoria devolveu id não numérico: %r", value)
            continue
        if 0 <= idx < len(candidates) and idx not in approved_idx:
            approved_idx.append(idx)
        else:
            logger.warning("Curadoria devolveu id fora do lote: %r", value)

    approved_idx = approved_idx[: config.MAX_APPROVED_PER_RUN]

    approved = [candidates[i] for i in approved_idx]
    rejected = [a for i, a in enumerate(candidates) if i not in set(approved_idx)]
    return approved, rejected, motivo
