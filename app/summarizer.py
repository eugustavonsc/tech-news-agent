from openai import OpenAI

from app import config

client = OpenAI(
    api_key=config.OPENCODER_API_KEY,
    base_url=config.OPENCODER_BASE_URL,
)

IRRELEVANT_MARKER = "IRRELEVANTE"

SYSTEM_PROMPT = (
    "Você é um curador de notícias de tecnologia. "
    "Se o texto recebido NÃO for genuinamente sobre tecnologia "
    "(ex: só cita a palavra 'tecnologia' de passagem, mas é sobre "
    "economia, esporte, política, acidentes, agropecuária etc.), "
    f"responda apenas com a palavra '{IRRELEVANT_MARKER}', sem mais nada.\n\n"
    "Caso contrário, resuma o texto de forma concisa em português para o Telegram. "
    "Use o seguinte formato:\n"
    "📰 **[Título da Notícia]**\n"
    "- Resumo em 2 frases.\n"
    "- **Por que importa:** breve contexto.\n"
    "🔗 Fonte: [Link]"
)


def format_news_with_llm(raw_text):
    """Retorna o resumo formatado, ou IRRELEVANT_MARKER se o texto não for
    realmente sobre tecnologia (ex: apenas cita a palavra de passagem)."""
    response = client.chat.completions.create(
        model=config.SUMMARIZER_MODEL_ID,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": raw_text},
        ],
        temperature=0.3,
    )
    return (response.choices[0].message.content or "").strip()
