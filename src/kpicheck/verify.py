"""Check every number in a commentary against the KPI facts before it is released.

The rule is simple: a number may appear in the text only if it equals a fact once the
fact is rounded to the same number of decimals the text shows. Sentences that say a
metric went up or down must agree with the sign of the change they quote.
A commentary with any unverified number is blocked.
"""
import re
from dataclasses import dataclass

# Argentine number format: 1.234.567,8  ->  1234567.8
NUM_RE = re.compile(r"(?<![\w.,])[-+]?\d{1,3}(?:\.\d{3})*(?:,\d+)?(?![\w])|(?<![\w.,])[-+]?\d+(?:,\d+)?(?![\w])")
UP = re.compile(r"\b(sub(e|ió|ieron)|crec(e|ió|ieron)|aument(a|ó|aron)|mejor(a|ó)|super(a|ó))\b", re.I)
DOWN = re.compile(r"\b(baj(a|ó|aron)|ca(e|yó|yeron)|disminu(ye|yó)|retroced(e|ió)|empeor(a|ó)|se redujo|se redujeron)\b", re.I)
YEARS = {str(y) for y in range(2000, 2100)}
ALIASES = {
    "revenue_m": ["facturación", "ventas", "ingresos"], "orders": ["pedidos", "órdenes"],
    "aov": ["ticket"], "gross_margin_pct": ["margen"], "return_rate_pct": ["devolución", "devoluciones"],
    "new_customers": ["clientes nuevos", "nuevos clientes"], "cac": ["cac", "costo de adquisición"],
    "Paid social": ["paid social"], "Búsqueda paga": ["búsqueda paga"], "Marketplace": ["marketplace"],
    "Orgánico": ["orgánico"],
}
MOM_WORDS = re.compile(r"mes anterior|agosto|mensual|contra el mes", re.I)
YOY_WORDS = re.compile(r"interanual|año anterior|mismo mes de 2025|septiembre de 2025|contra 2025", re.I)


@dataclass
class Finding:
    sentence: str
    text: str
    value: float
    status: str      # OK, NOT_FOUND, WRONG_METRIC, WRONG_PERIOD, WRONG_DIRECTION
    matched: str = ""


def parse_number(tok: str) -> tuple[float, int]:
    decimals = len(tok.split(",")[1]) if "," in tok else 0
    return float(tok.replace(".", "").replace(",", ".")), decimals


def fact_values(facts: dict) -> list[tuple[str, float, bool]]:
    """(name, value, is_change) for every number the commentary is allowed to quote."""
    out = []
    for k, f in facts["kpis"].items():
        out += [(f"{k}.value", f["value"], False), (f"{k}.prev", f["prev"], False),
                (f"{k}.last_year", f["last_year"], False), (f"{k}.mom", f["mom"], True), (f"{k}.yoy", f["yoy"], True)]
    for ch, f in facts["by_channel"].items():
        out += [(f"{ch}.revenue_m", f["revenue_m"], False), (f"{ch}.share_pct", f["share_pct"], False),
                (f"{ch}.mom", f["mom"], True)]
    return out


def check(text: str, facts: dict) -> list[Finding]:
    allowed = fact_values(facts)
    findings = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        s = sentence.strip()
        if not s or s.startswith("#"):
            continue
        for tok in NUM_RE.findall(s):
            if tok in YEARS:
                continue
            val, dec = parse_number(tok)
            hits = [(n, v, ch) for n, v, ch in allowed if round(abs(v), dec) == round(abs(val), dec)]
            if not hits:
                findings.append(Finding(s, tok, val, "NOT_FOUND"))
                continue
            low = s.lower()
            named = {key for key, words in ALIASES.items() if any(w in low for w in words)}
            on_metric = [h for h in hits if h[0].split(".")[0] in named]
            if named and not on_metric:
                findings.append(Finding(s, tok, val, "WRONG_METRIC", hits[0][0]))
                continue
            pool = on_metric or hits
            says_mom, says_yoy = bool(MOM_WORDS.search(s)), bool(YOY_WORDS.search(s))
            if says_mom != says_yoy:  # the sentence names exactly one comparison period
                want = (".mom", ".prev") if says_mom else (".yoy", ".last_year")
                in_period = [h for h in pool if h[0].endswith(want) or h[0].endswith(".value")
                             or h[0].endswith(".share_pct") or h[0].endswith(".revenue_m")]
                if not in_period:
                    findings.append(Finding(s, tok, val, "WRONG_PERIOD", pool[0][0]))
                    continue
                pool = in_period
            name, v, is_change = pool[0]
            status = "OK"
            if is_change and (UP.search(s) or DOWN.search(s)):
                says_up = bool(UP.search(s)) and not DOWN.search(s)
                says_down = bool(DOWN.search(s)) and not UP.search(s)
                if (says_up and v < 0) or (says_down and v > 0):
                    status = "WRONG_DIRECTION"
            findings.append(Finding(s, tok, val, status, name))
    return findings


def passed(findings: list[Finding]) -> bool:
    return all(f.status == "OK" for f in findings)
