"""Synthetic daily orders for a fictional Argentine online retailer (Sep 2025 - Sep 2026)."""
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(42)
OUT = Path(__file__).resolve().parents[1] / "data"
CHANNELS = {"Orgánico": 0.34, "Paid social": 0.26, "Búsqueda paga": 0.22, "Marketplace": 0.18}


def main():
    OUT.mkdir(exist_ok=True)
    rows, spend = [], []
    d, end = date(2025, 9, 1), date(2026, 9, 30)
    while d <= end:
        months = (d.year - 2025) * 12 + d.month - 9
        inflation = 1.022 ** months          # prices drift up ~2.2 % per month
        season = 1.25 if d.month in (11, 12) else (0.9 if d.month in (1, 2) else 1.0)
        for ch, share in CHANNELS.items():
            n = rng.poisson(110 * share * season * (1 + 0.01 * months))
            if ch == "Paid social" and d >= date(2026, 9, 1):
                n = int(n * 0.82)            # a campaign paused in September
            for _ in range(n):
                ticket = rng.lognormal(10.35, 0.45) * inflation
                margin = rng.normal(0.38 if ch != "Marketplace" else 0.27, 0.04)
                rows.append({"date": d, "channel": ch, "revenue_ars": round(ticket, 2),
                             "gross_margin_ars": round(ticket * margin, 2),
                             "returned": rng.random() < (0.061 if d.month != 9 or d.year != 2026 else 0.074),
                             "new_customer": rng.random() < 0.31})
            if ch != "Orgánico":
                spend.append({"date": d, "channel": ch, "spend_ars": round(n * rng.normal(4200, 300) * inflation, 2)})
        d += timedelta(days=1)
    pd.DataFrame(rows).to_csv(OUT / "orders.csv", index=False)
    pd.DataFrame(spend).to_csv(OUT / "marketing_spend.csv", index=False)
    print(len(rows), "orders")


if __name__ == "__main__":
    main()
