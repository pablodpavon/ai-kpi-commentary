"""Render the monthly report as a single HTML page: KPI table, commentary with every
number marked as verified or not, and the release decision."""
import html
import re
from pathlib import Path

from .verify import NUM_RE

LABELS = {"NOT_FOUND": "no está en los datos", "WRONG_METRIC": "es de otra métrica",
          "WRONG_PERIOD": "es de otro período", "WRONG_DIRECTION": "dirección contraria al dato"}


def fmt(v, dec=1):
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _kpi_rows(facts):
    rows = []
    for k, f in facts["kpis"].items():
        unit = f["unit"]
        dec = 1 if unit in ("%", "ARS M") else 0
        val = (f"ARS {fmt(f['value'], dec)} M" if unit == "ARS M" else f"ARS {fmt(f['value'], 0)}" if unit == "ARS"
               else f"{fmt(f['value'], dec)}%" if unit == "%" else fmt(f["value"], 0))
        cu = f["change_unit"]
        lower_is_better = k in ("cac", "return_rate_pct")
        def chg(x):
            good = (x < 0) if lower_is_better else (x > 0)
            cls = "" if abs(x) < 0.05 else ("up" if good else "down")
            return f'<td class="num {cls}">{"+" if x > 0 else ""}{fmt(x, 1)} {cu}</td>'
        rows.append(f"<tr><td>{f['label']}</td><td class='num'>{val}</td>{chg(f['mom'])}{chg(f['yoy'])}</tr>")
    return "\n".join(rows)


def _mark(text, findings):
    status = {}
    for f in findings:
        status.setdefault((f.sentence, f.text), f.status)
    out = []
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        sentences = re.split(r"(?<=[.!?])\s+", line.strip())
        parts = []
        for s in sentences:
            esc = html.escape(s)
            def rep(m, s=s):
                st = status.get((s, m.group(0)))
                if st is None:
                    return m.group(0)
                cls = "ok" if st == "OK" else "bad"
                tip = "verificado" if st == "OK" else LABELS[st]
                return f'<span class="n {cls}" title="{tip}">{m.group(0)}</span>'
            parts.append(NUM_RE.sub(rep, esc))
        out.append("<p>" + " ".join(parts) + "</p>")
    return "\n".join(out)


def render(facts, text, findings, path: Path, source_note: str):
    bad = [f for f in findings if f.status != "OK"]
    ok_n = len(findings) - len(bad)
    banner = (f'<div class="banner pass"><b>Liberado.</b> Los {ok_n} números del comentario coinciden con los datos.</div>'
              if not bad else
              f'<div class="banner fail"><b>Bloqueado.</b> {len(bad)} de {len(findings)} números no se pueden respaldar con los datos. '
              f'El comentario vuelve al analista.</div>')
    issues = "".join(f"<tr><td class='num'>{html.escape(f.text)}</td><td>{LABELS[f.status]}</td>"
                     f"<td class='muted'>{html.escape(f.sentence)}</td></tr>" for f in bad)
    issues_html = f"<h2>Qué hay que corregir</h2><table class='issues'><tr><th>Número</th><th>Problema</th><th>Oración</th></tr>{issues}</table>" if bad else ""
    page = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reporte mensual · {facts['month']}</title>
<style>
:root{{--ink:#14213d;--muted:#5c6b80;--line:#e3e8ef;--bg:#fbfaf7;--ok:#1b7a4b;--bad:#b3261e;--accent:#d97706}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 Inter,system-ui,sans-serif}}
main{{max-width:880px;margin:0 auto;padding:36px 20px 48px}}
.kicker{{color:var(--accent);font-weight:600;letter-spacing:.06em;text-transform:uppercase;font-size:12px}}
h1{{font-size:26px;margin:4px 0 18px}}h2{{font-size:16px;margin:28px 0 10px}}
.banner{{padding:12px 16px;border-radius:8px;margin:0 0 22px;border:1px solid}}
.pass{{background:#e9f6ef;border-color:#b7e0c8;color:#0f5132}}.fail{{background:#fdecea;border-color:#f3b8b3;color:#7a1610}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:8px;overflow:hidden}}
th,td{{padding:8px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{font-size:12px;color:var(--muted);font-weight:600;background:#f6f7f9}}
.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}.up{{color:var(--ok)}}.down{{color:var(--bad)}}
.commentary{{background:#fff;border:1px solid var(--line);border-radius:8px;padding:6px 20px}}
.n{{padding:0 3px;border-radius:3px;font-weight:600}}.n.ok{{background:#e3f4ea;color:#0f5132}}.n.bad{{background:#fbd9d5;color:#7a1610;text-decoration:underline wavy}}
.muted{{color:var(--muted);font-size:13px}}footer{{margin-top:26px;color:var(--muted);font-size:12px}}
@media (max-width:600px){{td,th{{padding:6px 8px}}h1{{font-size:21px}}}}
</style></head><body><main>
<div class="kicker">Reporte mensual · tienda online (datos sintéticos)</div>
<h1>Septiembre 2026: KPIs y comentario</h1>
{banner}
<h2>KPIs del mes</h2>
<table><tr><th>Métrica</th><th class="num">Septiembre</th><th class="num">vs agosto</th><th class="num">vs sep. 2025</th></tr>
{_kpi_rows(facts)}</table>
<h2>Comentario</h2><div class="commentary">{_mark(text, findings)}</div>
{issues_html}
<footer>{html.escape(source_note)} · En la tabla, verde = mejora y rojo = empeora (en CAC y devoluciones, bajar es mejorar). · Cada número del comentario se compara con los datos antes de publicar: verde = verificado, rojo = bloqueado.</footer>
</main></body></html>"""
    path.write_text(page, encoding="utf-8")
