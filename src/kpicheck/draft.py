"""Ask an LLM to draft the monthly commentary from the KPI facts.

The model only sees the facts JSON. Whatever it writes still goes through verify.py:
the draft is a starting point for the analyst, never the final word.
Requires the `anthropic` package and ANTHROPIC_API_KEY; the model is read from
ANTHROPIC_MODEL (check the provider's documentation for current model names).
"""
import json
import os

SYSTEM = (
    "Sos analista de negocio. Escribí el comentario mensual de KPIs en español rioplatense, "
    "en 6 a 9 oraciones cortas. Usá SOLO números que estén en el JSON, redondeados a 1 decimal "
    "(enteros para pedidos, clientes, ticket y CAC), con formato argentino (1.234,5). "
    "Nombrá siempre la métrica y el período de comparación (contra agosto / contra el mismo mes de 2025). "
    "No agregues contexto con cifras externas. Terminá con una línea de próximos pasos sin números."
)


def draft(facts: dict, model: str | None = None) -> str:
    import anthropic  # imported here so the offline demo runs without it

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model or os.environ["ANTHROPIC_MODEL"],
        max_tokens=900,
        system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(facts, ensure_ascii=False, default=float)}],
    )
    return "".join(block.text for block in msg.content if block.type == "text")
