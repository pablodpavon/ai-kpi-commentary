"""Compute the month's KPI facts. These numbers are the only source of truth for the commentary."""
from pathlib import Path

import pandas as pd

KPI_DEF = {
    "revenue_m": ("Facturación", "ARS M"),
    "orders": ("Pedidos", "pedidos"),
    "aov": ("Ticket promedio", "ARS"),
    "gross_margin_pct": ("Margen bruto", "%"),
    "return_rate_pct": ("Tasa de devolución", "%"),
    "new_customers": ("Clientes nuevos", "clientes"),
    "cac": ("Costo de adquisición (CAC)", "ARS"),
}


def _month(orders, spend, period):
    o = orders[orders.period == period]
    s = spend[spend.period == period]
    new = int(o.new_customer.sum())
    return {
        "revenue_m": o.revenue_ars.sum() / 1e6,
        "orders": len(o),
        "aov": o.revenue_ars.mean(),
        "gross_margin_pct": 100 * o.gross_margin_ars.sum() / o.revenue_ars.sum(),
        "return_rate_pct": 100 * o.returned.mean(),
        "new_customers": new,
        "cac": s.spend_ars.sum() / new,
    }


def compute(data_dir: Path, month: str) -> dict:
    orders = pd.read_csv(data_dir / "orders.csv", parse_dates=["date"])
    spend = pd.read_csv(data_dir / "marketing_spend.csv", parse_dates=["date"])
    for df in (orders, spend):
        df["period"] = df.date.dt.to_period("M").astype(str)
    p = pd.Period(month)
    cur, prev, ly = (_month(orders, spend, str(x)) for x in (p, p - 1, p - 12))
    facts = {"month": month, "kpis": {}, "by_channel": {}}
    for k, (label, unit) in KPI_DEF.items():
        is_rate = unit == "%"
        facts["kpis"][k] = {
            "label": label, "unit": unit, "value": cur[k], "prev": prev[k], "last_year": ly[k],
            # rates move in percentage points; everything else in percent
            "mom": cur[k] - prev[k] if is_rate else 100 * (cur[k] / prev[k] - 1),
            "yoy": cur[k] - ly[k] if is_rate else 100 * (cur[k] / ly[k] - 1),
            "change_unit": "pp" if is_rate else "%",
        }
    o = orders[orders.period == month]
    op = orders[orders.period == str(p - 1)]
    for ch in sorted(o.channel.unique()):
        r, rp = o[o.channel == ch].revenue_ars.sum(), op[op.channel == ch].revenue_ars.sum()
        facts["by_channel"][ch] = {"revenue_m": r / 1e6, "share_pct": 100 * r / o.revenue_ars.sum(),
                                   "mom": 100 * (r / rp - 1)}
    return facts
