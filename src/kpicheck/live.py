"""Weekly live pipeline: synthetic feed -> data check -> KPIs -> LLM draft -> number check -> released or blocked.

Each run writes reports/<YYYY-Www>/ (run.json, facts.json, draft.md, report.html) and the
index of all runs is rebuilt from those folders, so the folders are the only source of truth.
"""
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import data_checks, kpis, report, verify, weekly_data
from .report import fmt

MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
             "septiembre", "octubre", "noviembre", "diciembre"]
REASONS_ES = {"NOT_FOUND": "no está en los datos", "WRONG_METRIC": "es de otra métrica",
              "WRONG_PERIOD": "es de otro período", "WRONG_DIRECTION": "dirección contraria al dato"}


def week_title(week: str) -> str:
    days = weekly_data.week_days(week)
    a, b = days[0], days[-1]
    _, w = weekly_data.parse_week(week)
    if a.month == b.month:
        span = f"{a.day} al {b.day} de {MONTHS_ES[b.month - 1]} de {b.year}"
    elif a.year == b.year:
        span = f"{a.day} de {MONTHS_ES[a.month - 1]} al {b.day} de {MONTHS_ES[b.month - 1]} de {b.year}"
    else:
        span = f"{a.day} de {MONTHS_ES[a.month - 1]} de {a.year} al {b.day} de {MONTHS_ES[b.month - 1]} de {b.year}"
    return f"Semana {w} · {span}"


def week_facts(week: str) -> tuple[dict | None, list, str | None]:
    """(facts, data issues, planted anomaly). facts is None when the delivered feed fails the data check."""
    o, s, anomaly = weekly_data.generate_week(week, delivered=True)
    issues = data_checks.check(o, s, weekly_data.week_days(week))
    if issues:
        return None, issues, anomaly
    prev, ly = weekly_data.previous_week(week), weekly_data.same_week_last_year(week)
    po, ps, _ = weekly_data.generate_week(prev, delivered=False)
    lo, ls, _ = weekly_data.generate_week(ly, delivered=False)
    facts = kpis.compute_frames(week, (o, s), (po, ps), (lo, ls))
    facts.update(period_prev=prev, period_last_year=ly)
    return facts, [], anomaly


def offline_draft(facts: dict) -> tuple[str, dict, str]:
    """A correct draft written from the facts without any LLM. Used by --dry-run and the tests."""
    k, ly = facts["kpis"], facts["period_last_year"][:4]

    def ch(x, d=1):
        return fmt(abs(x), d)

    def verb(x, up="subió", down="bajó"):
        return up if x > 0 else down
    r, o, a, m, rr, n, c = (k[x] for x in ("revenue_m", "orders", "aov", "gross_margin_pct",
                                         "return_rate_pct", "new_customers", "cac"))
    lines = [
        f"La facturación {verb(r['mom'])} {ch(r['mom'])}% contra la semana anterior y cerró en ARS {fmt(r['value'])} M.",
        f"Los pedidos {verb(o['mom'], 'subieron', 'bajaron')} {ch(o['mom'])}% contra la semana anterior, a {fmt(o['value'], 0)}.",
        f"El ticket promedio fue ARS {fmt(a['value'], 0)}, {ch(a['yoy'])}% {'más' if a['yoy'] > 0 else 'menos'} que en la misma semana de {ly}.",
        f"El margen bruto fue {fmt(m['value'])}%.",
        f"La tasa de devolución quedó en {fmt(rr['value'])}%.",
        f"Los clientes nuevos fueron {fmt(n['value'], 0)} y el CAC, ARS {fmt(c['value'], 0)}.",
        "Próximos pasos: revisar la mezcla de canales y el costo de adquisición.",
    ]
    return "\n".join(lines), {"input_tokens": 0, "output_tokens": 0}, "offline-template"


def _data_block_page(week: str, issues: list) -> str:
    rows = "".join(f"<tr><td>{html.escape(i.code)}</td><td>{html.escape(i.detail)}</td></tr>" for i in issues)
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reporte semanal · {week} · bloqueado</title>
<style>body{{margin:0;background:#fbfaf7;color:#14213d;font:15px/1.55 Inter,system-ui,sans-serif}}main{{max-width:880px;margin:0 auto;padding:36px 20px}}
.kicker{{color:#d97706;font-weight:600;letter-spacing:.06em;text-transform:uppercase;font-size:12px}}
.fail{{background:#fdecea;border:1px solid #f3b8b3;color:#7a1610;padding:12px 16px;border-radius:8px;margin:0 0 22px}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e3e8ef}}td,th{{padding:8px 12px;border-bottom:1px solid #e3e8ef;text-align:left}}</style>
</head><body><main><div class="kicker">Reporte semanal · tienda online ficticia (datos sintéticos)</div>
<h1>{html.escape(week_title(week))}</h1>
<div class="fail"><b>Bloqueado por el control de datos.</b> Los datos recibidos tienen un problema de carga, así que no se calcularon KPIs ni se le pidió el borrador al modelo.</div>
<table><tr><th>Control</th><th>Detalle</th></tr>{rows}</table>
<p style="color:#5c6b80;font-size:13px">Anomalía sembrada a propósito en el feed sintético para probar el control.</p></main></body></html>"""


def run_week(week: str, reports_dir: Path, drafter, model_hint: str = "", now: datetime | None = None,
             max_estimate_usd: float = 0.50) -> dict:
    now = now or datetime.now(timezone.utc)
    out = reports_dir / week
    out.mkdir(parents=True, exist_ok=True)
    days = weekly_data.week_days(week)
    rec = {"week": week, "from": days[0].isoformat(), "to": days[-1].isoformat(),
           "run_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "data": "synthetic"}
    facts, issues, anomaly = week_facts(week)
    rec["planted_anomaly"] = anomaly
    if issues:
        rec.update(status="BLOCKED", blocked_by="data_check", numbers_checked=0, problems=len(issues),
                   reasons=[f"{i.code}: {i.detail}" for i in issues], model=None, usage=None,
                   cost_usd=0.0, cost_estimate_usd=0.0)
        (out / "report.html").write_text(_data_block_page(week, issues), encoding="utf-8")
    else:
        from . import draft
        (out / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
        est = draft.estimate_usd(facts)
        if est > max_estimate_usd:
            raise RuntimeError(f"estimated cost US$ {est:.4f} is above the US$ {max_estimate_usd:.2f} cap; not called")
        text, usage, model = drafter(facts)
        (out / "draft.md").write_text(text, encoding="utf-8")
        findings = verify.check(text, facts, verify.WEEK_WOW_WORDS, verify.WEEK_YOY_WORDS, verify.WEEK_SKIP)
        bad = [f for f in findings if f.status != "OK"]
        ly = facts["period_last_year"][:4]
        report.render(facts, text, findings, out / "report.html",
                      f"Borrador: {model}" if usage.get("output_tokens") else "Borrador: plantilla sin LLM (prueba)",
                      labels={"kicker": "Reporte semanal · tienda online ficticia (datos sintéticos)",
                              "title": week_title(week), "kpi_heading": "KPIs de la semana",
                              "cols": ("Semana", "vs semana anterior", f"vs misma semana {ly}"),
                              "page_title": f"Reporte semanal · {week}"})
        if not findings:
            bad_reason = ["NO_NUMBERS: the draft quotes no numbers"]
        else:
            bad_reason = [f"{f.status}: {f.text} | {f.sentence}" for f in bad]
        blocked = bool(bad) or not findings
        rec.update(status="BLOCKED" if blocked else "RELEASED", blocked_by="number_check" if blocked else None,
                   numbers_checked=len(findings), problems=len(bad) or (0 if findings else 1),
                   reasons=bad_reason if blocked else [], model=model, usage=usage,
                   cost_usd=round(draft.cost_usd(model, usage) or 0.0, 6) if usage.get("output_tokens") else 0.0,
                   cost_estimate_usd=round(est, 6))
    (out / "run.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


def rebuild_index(reports_dir: Path) -> dict:
    runs = []
    for f in sorted(reports_dir.glob("*-W*/run.json")):
        runs.append(json.loads(f.read_text(encoding="utf-8")))
    runs.sort(key=lambda r: weekly_data.week_days(r["week"])[0])
    blocked = [r for r in runs if r["status"] == "BLOCKED"]
    idx = {"data": "synthetic", "runs": len(runs), "released": len(runs) - len(blocked), "blocked": len(blocked),
           "blocked_by_data_check": sum(r.get("blocked_by") == "data_check" for r in blocked),
           "blocked_by_number_check": sum(r.get("blocked_by") == "number_check" for r in blocked),
           "total_cost_usd": round(sum(r.get("cost_usd") or 0 for r in runs), 6),
           "last": runs[-1] if runs else None,
           "history": [{k: r.get(k) for k in ("week", "from", "to", "run_utc", "status", "blocked_by",
                                              "numbers_checked", "problems", "reasons", "model", "cost_usd")}
                       for r in runs]}
    (reports_dir / "index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# Weekly runs (synthetic data)", "",
             f"{idx['runs']} runs: {idx['released']} released, {idx['blocked']} blocked "
             f"({idx['blocked_by_data_check']} by the data check, {idx['blocked_by_number_check']} by the number check). "
             f"LLM cost so far: US$ {idx['total_cost_usd']:.4f}.", "",
             "| Week | Dates | Result | Numbers checked | Reason | Cost (US$) |", "|---|---|---|---|---|---|"]
    for r in reversed(idx["history"]):
        reason = "; ".join(r["reasons"])[:160].replace("|", "/") if r["reasons"] else ""
        lines.append(f"| [{r['week']}]({r['week']}/report.html) | {r['from']} to {r['to']} | {r['status']}"
                     f"{' (' + r['blocked_by'].replace('_', ' ') + ')' if r['blocked_by'] else ''} | "
                     f"{r['numbers_checked']} | {reason} | {r['cost_usd']:.4f} |")
    (reports_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return idx


def live_block(idx: dict) -> str:
    last = idx["last"]
    if not last:
        return "No weekly run yet."
    res = last["status"] + (f" ({last['blocked_by'].replace('_', ' ')})" if last["blocked_by"] else "")
    return (f"**Last run:** week {last['week']} ({last['from']} to {last['to']}), run {last['run_utc']}: **{res}**, "
            f"{last['numbers_checked']} numbers checked, LLM cost US$ {last['cost_usd']:.4f}.  \n"
            f"**History:** {idx['runs']} weekly runs, {idx['released']} released, {idx['blocked']} blocked "
            f"({idx['blocked_by_data_check']} by the data check, {idx['blocked_by_number_check']} by the number check). "
            f"Every run: [reports/index.md](reports/index.md).")


def update_readme(readme: Path, idx: dict) -> None:
    s = readme.read_text(encoding="utf-8")
    new = f"<!-- LIVE:START -->\n{live_block(idx)}\n<!-- LIVE:END -->"
    s2, n = re.subn(r"<!-- LIVE:START -->.*?<!-- LIVE:END -->", lambda _: new, s, flags=re.S)
    if n:
        readme.write_text(s2, encoding="utf-8")


def status_payload(idx: dict, ok: bool, note: str, now: datetime) -> dict:
    """One-line status for a public dashboard: last run only, no paths, no secrets, strings under 200 characters."""
    last = idx.get("last") or {}
    history = f"{idx.get('runs', 0)} weekly runs, {idx.get('blocked', 0)} blocked"
    return {
        "system": "kpi-report",
        "title_en": "AI KPI report, verified weekly",
        "title_es": "Reporte de KPIs con IA, verificado cada semana",
        "last_run_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ok": ok,
        "items": last.get("numbers_checked") if ok else None,
        "items_label_en": "numbers checked",
        "items_label_es": "números verificados",
        "cost_usd": last.get("cost_usd") if ok else None,
        "schedule_en": "Weekly, Mondays 07:30 Berlin",
        "schedule_es": "Semanal, lunes 07:30 Berlín",
        "note": f"{note}. {history}. Synthetic data."[:200],
    }


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
