"""Synthetic weekly feed for the fictional Argentine online store, one ISO week at a time.

Every week is generated on its own, from a seed derived from the ISO week string
("2026-W43"). The same week therefore always produces the same orders, and the
"previous week" in one report is exactly the week that was published the week before.

Realistic variation: price drift (~2.2 % a month), seasonality, day-of-week pattern,
channel intensity that moves from week to week and the odd promotion week.

Planted anomalies: about one week in eight, the feed *as delivered* has a load problem
(a day loaded twice, a day missing, refunds loaded as orders, or a paid channel with no
spend). The data check must catch it and block the report before the LLM is called.
When that week is later used as a comparison base, the corrected feed is used, as it
would be once the source system re-delivers it.
"""
import hashlib
from datetime import date, timedelta

import numpy as np
import pandas as pd

CHANNELS = {"Orgánico": 0.34, "Paid social": 0.26, "Búsqueda paga": 0.22, "Marketplace": 0.18}
PAID = [c for c in CHANNELS if c != "Orgánico"]
DOW = [1.04, 1.00, 0.98, 1.00, 1.06, 0.95, 0.90]       # Monday .. Sunday
BASE_DAY = date(2025, 9, 1)                              # start of the monthly case study
ANOMALIES = ["duplicate_day", "missing_day", "refunds_as_orders", "spend_missing"]
ANOMALY_RATE = 0.12


def parse_week(week: str) -> tuple[int, int]:
    y, w = week.upper().split("-W")
    return int(y), int(w)


def week_label(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_days(week: str) -> list[date]:
    y, w = parse_week(week)
    monday = date.fromisocalendar(y, w, 1)
    return [monday + timedelta(days=i) for i in range(7)]


def previous_week(week: str) -> str:
    return week_label(week_days(week)[0] - timedelta(days=7))


def same_week_last_year(week: str) -> str:
    y, w = parse_week(week)
    try:
        date.fromisocalendar(y - 1, w, 1)
    except ValueError:          # week 53 does not exist in every year
        w = 52
    return f"{y - 1}-W{w:02d}"


def seed(week: str) -> int:
    return int.from_bytes(hashlib.sha256(week.encode()).digest()[:8], "big")


def planted_anomaly(week: str) -> str | None:
    """Which anomaly (if any) the delivered feed of this week carries. Independent stream from the orders."""
    rng = np.random.default_rng([seed(week), 1])
    return str(rng.choice(ANOMALIES)) if rng.random() < ANOMALY_RATE else None


def generate_week(week: str, delivered: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, str | None]:
    """Orders and marketing spend for one ISO week.

    delivered=True returns the feed as first delivered (with the planted anomaly, if any);
    delivered=False returns the corrected feed.
    """
    rng = np.random.default_rng([seed(week), 0])
    days = week_days(week)
    promo = rng.random() < 0.10                                   # a promotion week now and then
    intensity = {ch: rng.normal(1.0, 0.07) for ch in CHANNELS}    # campaigns move week to week
    if promo:
        intensity["Paid social"] *= 1.25
        intensity["Búsqueda paga"] *= 1.15
    rows, spend = [], []
    for d in days:
        months = (d - BASE_DAY).days / 30.44
        inflation = 1.022 ** months
        season = 1.25 if d.month in (11, 12) else (0.9 if d.month in (1, 2) else 1.0)
        for ch, share in CHANNELS.items():
            lam = 110 * share * season * (1 + 0.01 * months) * DOW[d.weekday()] * intensity[ch]
            n = rng.poisson(max(lam, 1))
            for _ in range(n):
                ticket = rng.lognormal(10.35, 0.45) * inflation * (0.93 if promo else 1.0)
                margin = rng.normal(0.38 if ch != "Marketplace" else 0.27, 0.04) - (0.03 if promo else 0.0)
                rows.append({"order_id": f"{week}-{len(rows) + 1:05d}", "date": d, "channel": ch,
                             "revenue_ars": round(ticket, 2), "gross_margin_ars": round(ticket * margin, 2),
                             "returned": bool(rng.random() < rng.normal(0.064, 0.004)),
                             "new_customer": bool(rng.random() < 0.31)})
            if ch in PAID:
                spend.append({"date": d, "channel": ch,
                              "spend_ars": round(n * rng.normal(4200, 300) * inflation * intensity[ch], 2)})
    orders, spend = pd.DataFrame(rows), pd.DataFrame(spend)
    anomaly = planted_anomaly(week)
    if not delivered or anomaly is None:
        return orders, spend, None
    arng = np.random.default_rng([seed(week), 2])
    day = days[int(arng.integers(0, 7))]
    if anomaly == "duplicate_day":
        orders = pd.concat([orders, orders[orders.date == day]], ignore_index=True)
    elif anomaly == "missing_day":
        orders = orders[orders.date != day].reset_index(drop=True)
    elif anomaly == "refunds_as_orders":
        idx = arng.choice(len(orders), size=12, replace=False)
        orders.loc[idx, "revenue_ars"] *= -1
        orders.loc[idx, "gross_margin_ars"] *= -1
    elif anomaly == "spend_missing":
        ch = PAID[int(arng.integers(0, len(PAID)))]
        spend = spend[spend.channel != ch].reset_index(drop=True)
    return orders, spend, anomaly
