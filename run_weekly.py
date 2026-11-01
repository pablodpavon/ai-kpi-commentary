"""Weekly live run of the KPI report (synthetic data).

  python run_weekly.py --dry-run                    # template draft, no LLM, no key, writes to a temp folder
  python run_weekly.py --estimate                   # cost estimate for the week, no call
  python run_weekly.py --key-file ~/.anthropic_auto.env [--status-json PATH]
Default week: the ISO week that ended before today (run on Monday, it reports the week just closed).
Exit code: 0 released, 1 blocked, 2 error.
"""
import argparse
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from kpicheck import draft, live, weekly_data  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", default=weekly_data.week_label(date.today() - timedelta(days=7)))
    ap.add_argument("--reports", type=Path, default=ROOT / "reports")
    ap.add_argument("--key-file", type=Path, help="file with ANTHROPIC_API_KEY=... (never printed)")
    ap.add_argument("--model", default=draft.WEEKLY_MODEL)
    ap.add_argument("--status-json", type=Path, help="also write a one-line status for a dashboard")
    ap.add_argument("--force", action="store_true", help="re-run a week that already has a report")
    ap.add_argument("--dry-run", action="store_true", help="template draft instead of the LLM, output to a temp folder")
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--max-usd", type=float, default=0.50)
    a = ap.parse_args()

    if a.estimate:
        facts, issues, _ = live.week_facts(a.week)
        print(f"{a.week}: data check failed, no call needed" if issues else
              f"{a.week}: upper estimate US$ {draft.estimate_usd(facts, a.model):.5f} ({a.model})")
        return 0
    reports = Path(tempfile.mkdtemp(prefix="kpi_dry_")) if a.dry_run else a.reports
    if (reports / a.week / "run.json").exists() and not a.force:
        print(f"{a.week} already has a report in {reports}; use --force to run it again")
        return 0
    try:
        if a.dry_run:
            drafter = live.offline_draft
        else:
            if not a.key_file:
                raise RuntimeError("--key-file is required for a live run (or use --dry-run)")
            drafter = draft.AnthropicDrafter(draft.load_key(a.key_file), a.model)
        rec = live.run_week(a.week, reports, drafter, now=datetime.now(timezone.utc), max_estimate_usd=a.max_usd)
        idx = live.rebuild_index(reports)
        if not a.dry_run:
            live.update_readme(ROOT / "README.md", idx)
        note = (f"{rec['week']}: {rec['status']}"
                + (f" by the {rec['blocked_by'].replace('_', ' ')} ({rec['reasons'][0].split(':')[0]})" if rec["blocked_by"] else "")
                + f", {rec['numbers_checked']} numbers checked")
        ok, code = True, (0 if rec["status"] == "RELEASED" else 1)
        print(note + f", LLM cost US$ {rec['cost_usd']:.5f} -> {reports / a.week}")
        for r in rec["reasons"]:
            print("  " + r)
    except Exception as e:  # the status file must say the run failed, without any secret in it
        idx = live.rebuild_index(reports) if reports.exists() else {}
        note, ok, code = f"{a.week}: run failed ({type(e).__name__})", False, 2
        print(note + f": {e}", file=sys.stderr)
    if a.status_json and not a.dry_run:
        live.write_json_atomic(a.status_json, live.status_payload(idx, ok, note, datetime.now(timezone.utc)))
    return code


if __name__ == "__main__":
    sys.exit(main())
