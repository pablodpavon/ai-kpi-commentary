# AI KPI commentary, with every number checked

Case study on synthetic data · [Case page on pablodpavon.com](https://pablodpavon.com/proyectos/reporte-con-ia.html) · MIT license

**A KPI report (monthly sample, plus a weekly live run) where an LLM drafts the commentary and a checker verifies every number against the data before anyone reads it. If a single number cannot be backed by the data, the report is blocked.**

*Versión en español más abajo. The sample report itself is in Spanish, written for an Argentine online retailer (fictional).*

![Blocked report: five numbers in the commentary cannot be backed by the data](output/report_blocked.png)

## Live: a new report every Monday

*Case study on synthetic data.* The same check now runs by itself once a week on a fictional store's weekly feed:

1. **Feed.** [`weekly_data.py`](src/kpicheck/weekly_data.py) generates the week's orders and marketing spend. Each ISO week has its own seed (the week string, e.g. `2026-W43`), so a week always regenerates identically and last week's published figures are exactly this week's comparison base. The numbers move like a real store's: price drift, seasonality, day-of-week pattern, campaigns that change intensity, an occasional promotion week.
2. **Data check.** About one week in eight, the feed arrives with a load problem planted on purpose: a day loaded twice, a missing day, refunds loaded as orders, or a paid channel without spend. [`data_checks.py`](src/kpicheck/data_checks.py) must catch it. If it does, the report is blocked and the LLM is never called.
3. **Draft.** The week's KPIs (against the previous week and the same week last year) go to Claude Haiku (`claude-haiku-5-5`), which writes the commentary. The cost of each call is computed from the token `usage` the API returns.
4. **Number check.** The same [`verify.py`](src/kpicheck/verify.py) checks every number. One unsupported figure blocks the report.
5. **History.** Each run leaves `reports/<YYYY-Www>/` (`run.json`, `facts.json`, `draft.md`, `report.html`) and the index of all runs, [`reports/index.md`](reports/index.md), is rebuilt from those folders.

It runs on a Mac with launchd, Mondays at 07:30 (Berlin), for the week that just closed. The API key stays in a local file outside the repository; [`run_weekly.py`](run_weekly.py) reads it only when it calls the model.

<!-- LIVE:START -->
**Last run:** week 2026-W43 (2026-10-19 to 2026-10-25), run 2026-11-01T11:13:55Z: **RELEASED**, 14 numbers checked, LLM cost US$ 0.0014.  
**History:** 2 weekly runs, 1 released, 1 blocked (1 by the data check, 0 by the number check). Every run: [reports/index.md](reports/index.md).
<!-- LIVE:END -->

**What a block looks like.** A data-check block lists the failed control (`MISSING_DAY: no orders on 2026-10-12`) and costs nothing, because the model is not called. A number-check block keeps the draft and marks the unsupported figure in red with its reason, the same way as the monthly example below. Either way nothing is released for that week, and the next run starts clean.

```bash
python run_weekly.py --dry-run --week 2026-W43   # template draft instead of the LLM, no key, temp folder
python run_weekly.py --estimate                  # cost estimate for last week, no call
python run_weekly.py --key-file PATH             # live run: last week, Claude Haiku, writes reports/
```

## Why

LLMs write good first drafts of a monthly commentary, and they also do the things that make finance teams stop trusting a report: a figure that is close but not right, the year-on-year number quoted as month-on-month, "grew" where the data says it fell, a rate borrowed from the next metric, or an outside figure ("inflation of about 30 %") that nobody sourced. Reading every sentence against the KPI table by hand defeats the point of automating the draft.

## How it works

1. **Facts first.** [`kpis.py`](src/kpicheck/kpis.py) computes the month's KPIs from the raw orders and marketing spend: revenue, orders, average ticket, gross margin, return rate, new customers and CAC, each against the previous month and the same month last year, plus revenue by channel. These numbers are the only source of truth.
2. **Draft.** The LLM receives only the facts (JSON) and a short instruction ([`draft.py`](src/kpicheck/draft.py)).
3. **Check.** [`verify.py`](src/kpicheck/verify.py) reads the draft sentence by sentence and checks every number:
   - **exists:** it equals a fact once the fact is rounded to the decimals the text shows (Argentine format, 1.234,5);
   - **right metric:** if the sentence names a metric, the number belongs to that metric;
   - **right period:** "contra agosto" must quote a month-on-month value, "contra el mismo mes de 2025" a year-on-year one;
   - **right direction:** "subió" cannot sit next to a change that is negative.
4. **Release gate.** The HTML report shows every number in green (verified) or red (blocked, with the reason). The command exits with an error if anything is red, so it can sit in a scheduled job or a CI step.

## Example

Two drafts are included so it runs without an API key: [`draft_ok.md`](examples/draft_ok.md) and [`draft_with_errors.md`](examples/draft_with_errors.md), which plants the five mistakes above.

```text
$ python run.py --draft examples/draft_ok.md
18 numbers checked, 0 problems -> RELEASED

$ python run.py --draft examples/draft_with_errors.md
13 numbers checked, 5 problems -> BLOCKED
  NOT_FOUND             4,8  | La facturación bajó 4,8% contra agosto ...
  WRONG_DIRECTION      10,6  | Los clientes nuevos crecieron 10,6% contra agosto ...
  WRONG_METRIC          7,9  | La tasa de devolución fue 7,9% ...
  WRONG_PERIOD         30,7  | El CAC subió 30,7% contra agosto.
  NOT_FOUND              30  | ... una inflación cercana al 30% anual.
```

The released version: [`output/report_released.png`](output/report_released.png).

## Run it

```bash
pip install -r requirements.txt
python scripts/generate_data.py                      # synthetic orders (seeded)
python run.py --draft examples/draft_ok.md           # check a saved draft
python -m pytest -q                                  # 22 tests, no network

# with a live LLM draft (needs the anthropic package and an API key)
export ANTHROPIC_API_KEY=...  ANTHROPIC_MODEL=...    # model name from the provider's docs
python run.py --llm
```

## Limits, stated plainly

The checker proves that each number in the text exists in the data for the metric and period the sentence names. It does not judge whether the explanation is the right one; that is still the analyst's job, and the reason the report has a human owner.

## Data

Synthetic: about 47,000 orders of a fictional online store, September 2025 to September 2026, with a paid-social campaign paused in the last month so there is a story to tell.

---

## Versión en español

**Un reporte mensual de KPIs en el que un LLM redacta el comentario y un control verifica cada número contra los datos antes de publicarlo. Si un solo número no se puede respaldar, el reporte queda bloqueado.**

**Por qué.** Los LLM escriben buenos primeros borradores, pero también cometen los errores que hacen que finanzas deje de confiar en un reporte: una cifra parecida pero no exacta, el interanual citado como mensual, "creció" cuando el dato cayó, el número de otra métrica, o un dato externo sin fuente. Revisar oración por oración a mano anula el beneficio de automatizar.

**Cómo funciona.** Primero se calculan los KPIs del mes (la única fuente de verdad). El LLM recibe solo esos datos y redacta. Después, cada número del texto se valida: que exista en los datos con el redondeo que muestra, que sea de la métrica que nombra la oración, del período que dice ("contra agosto" o "contra el mismo mes de 2025") y que el verbo ("subió", "cayó") coincida con el signo. El reporte HTML marca cada número en verde o en rojo, y el proceso termina con error si hay alguno en rojo.

**Límite.** El control asegura que los números son correctos; si la explicación es la acertada lo sigue decidiendo el analista.

**Datos.** Sintéticos: unas 47.000 órdenes de una tienda online ficticia.

**En vivo, cada lunes.** El mismo control corre solo una vez por semana (lunes 07:30, hora de Berlín) sobre un feed semanal sintético: datos de la semana generados con su propia semilla, control de calidad de datos, borrador de Claude Haiku y verificación de cada número. Más o menos una semana de cada ocho el feed llega con un problema de carga sembrado a propósito (un día duplicado, un día faltante, devoluciones cargadas como ventas o un canal pago sin gasto), y el control de datos lo tiene que frenar antes de llamar al modelo. Cada corrida queda en `reports/` con su resultado, sus motivos y su costo.

---

Pablo Pavon · Senior Business & Data Analyst · [pablodpavon.com](https://pablodpavon.com)
