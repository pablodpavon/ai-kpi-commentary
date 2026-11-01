"""Checks on the delivered feed, run before any KPI is computed or any LLM is called.

If the data is wrong, a perfectly verified commentary would still be wrong, so a failed
data check blocks the report and the LLM is never called (no cost).
"""
from dataclasses import dataclass

import pandas as pd

PAID_CHANNELS = ("Paid social", "Búsqueda paga", "Marketplace")


@dataclass
class Issue:
    code: str
    detail: str


def check(orders: pd.DataFrame, spend: pd.DataFrame, days: list) -> list[Issue]:
    issues = []
    dup = orders.order_id.duplicated(keep="first")
    if dup.any():
        issues.append(Issue("DUPLICATE_ORDERS", f"{int(dup.sum())} order ids appear twice (a day loaded twice?)"))
    dates = pd.to_datetime(orders.date).dt.date
    present = set(dates)
    missing = [d for d in days if d not in present]
    if missing:
        issues.append(Issue("MISSING_DAY", "no orders on " + ", ".join(d.isoformat() for d in missing)))
    outside = int((~dates.isin(days)).sum())
    if outside:
        issues.append(Issue("OUT_OF_PERIOD", f"{outside} orders dated outside the week"))
    neg = int((orders.revenue_ars <= 0).sum())
    if neg:
        issues.append(Issue("NON_POSITIVE_REVENUE", f"{neg} orders with revenue <= 0 (refunds loaded as orders?)"))
    sold = set(orders.channel) & set(PAID_CHANNELS)
    paid = set(spend.channel[spend.spend_ars > 0]) if len(spend) else set()
    for ch in sorted(sold - paid):
        issues.append(Issue("SPEND_MISSING", f"'{ch}' has orders but no marketing spend in the feed"))
    return issues
