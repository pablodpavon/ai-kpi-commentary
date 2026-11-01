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


# ---------------------------------------------------------------- weekly (live pipeline)

WEEKLY_MODEL = "claude-haiku-5-5"
# US$ per million tokens: (input, cache write 5 min, cache read, output).
# Source: Anthropic pricing page (platform.claude.com/docs/en/about-claude/pricing), checked 30-Oct-2026.
PRICES = {"claude-haiku-5-5": (0.10, 0.125, 0.01, 0.50)}
WEEKLY_MAX_TOKENS = 4000   # Haiku 5.5 thinks by default and thinking tokens count here
WEEKLY_EFFORT = "low"


def weekly_system(last_year: int) -> str:
    return (
        "Sos analista de negocio. Escribí el comentario semanal de KPIs de una tienda online, en español rioplatense, "
        "en 5 a 8 oraciones cortas. Usá SOLO números que estén en el JSON, redondeados a 1 decimal "
        "(enteros para pedidos, clientes, ticket y CAC), con formato argentino (1.234,5). "
        "En el JSON, 'mom' y 'prev' son contra la semana anterior; 'yoy' y 'last_year', contra la misma semana del año pasado. "
        "Cada vez que cites una variación, nombrá la métrica y escribí exactamente \"contra la semana anterior\" "
        f"o \"contra la misma semana de {last_year}\". Una métrica con números por oración. "
        "No escribas fechas, números de semana, títulos ni cifras que no estén en el JSON. "
        "Terminá con una línea de próximos pasos sin números."
    )


def load_key(path) -> str:
    """Read ANTHROPIC_API_KEY=... from a local file (chmod 600). The key is never printed or logged."""
    from pathlib import Path

    p = Path(path).expanduser()
    if not p.is_file():
        raise RuntimeError(f"no API key file at {p}; nothing was called and nothing was spent")
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if line.startswith("ANTHROPIC_API_KEY="):
            key = line.split("=", 1)[1].strip().strip("'\"")
            if not key.startswith("sk-ant-"):
                raise RuntimeError(f"the ANTHROPIC_API_KEY line in {p} does not look like an Anthropic key")
            return key
    raise RuntimeError(f"{p} has no ANTHROPIC_API_KEY= line; nothing was called")


def cost_usd(model: str, usage: dict) -> float | None:
    p = PRICES.get(model)
    if p is None:
        return None
    return (usage.get("input_tokens", 0) * p[0] + usage.get("cache_creation_input_tokens", 0) * p[1]
            + usage.get("cache_read_input_tokens", 0) * p[2] + usage.get("output_tokens", 0) * p[3]) / 1e6


def estimate_usd(facts: dict, model: str = WEEKLY_MODEL) -> float:
    """Upper estimate before calling: 3 characters per token in, the full max_tokens out."""
    chars = len(weekly_system(2025)) + len(json.dumps(facts, ensure_ascii=False, default=float))
    return cost_usd(model, {"input_tokens": chars / 3, "output_tokens": WEEKLY_MAX_TOKENS})


class AnthropicDrafter:
    """Callable drafter: facts -> (text, usage dict, model). Built with an explicit key, never from the environment."""

    def __init__(self, key: str, model: str = WEEKLY_MODEL):
        import anthropic

        self.client = anthropic.Anthropic(api_key=key, max_retries=2, timeout=120.0)
        self.model = model

    def __call__(self, facts: dict) -> tuple[str, dict, str]:
        ly = int(facts["period_last_year"][:4])
        msg = self.client.messages.create(
            model=self.model, max_tokens=WEEKLY_MAX_TOKENS, system=weekly_system(ly),
            output_config={"effort": WEEKLY_EFFORT},
            messages=[{"role": "user", "content": json.dumps(facts, ensure_ascii=False, default=float)}],
        )
        return parse_response(msg)


def parse_response(msg) -> tuple[str, dict, str]:
    """Text, token usage and model of a Messages API response. A response without a finished text
    is a failed run (it is not a draft the number check could judge)."""
    u = msg.usage
    usage = {k: int(getattr(u, k, 0) or 0) for k in
             ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}
    text = "".join(b.text for b in msg.content if b.type == "text")
    if msg.stop_reason != "end_turn" or not text.strip():
        raise RuntimeError(f"no usable text from the model (stop_reason={msg.stop_reason}, "
                           f"output_tokens={usage['output_tokens']})")
    return text, usage, msg.model
