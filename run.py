"""Monthly KPI report with a verified commentary.

  python run.py --draft examples/draft_ok.md          # check a saved draft (no API needed)
  python run.py --llm                                  # ask the LLM for a draft, then check it
Exit code 1 if the commentary has any unverified number (the release gate).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from kpicheck import kpis, report, verify  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default="2026-09")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--draft", type=Path)
    g.add_argument("--llm", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "report.html")
    args = ap.parse_args()

    facts = kpis.compute(ROOT / "data", args.month)
    args.out.parent.mkdir(exist_ok=True)
    (args.out.parent / "kpi_facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    if args.llm:
        from kpicheck import draft
        text, note = draft.draft(facts), "Borrador generado por un LLM"
        (args.out.parent / "draft_llm.md").write_text(text, encoding="utf-8")
    else:
        text, note = args.draft.read_text(encoding="utf-8"), f"Borrador: {args.draft.name}"
    findings = verify.check(text, facts)
    report.render(facts, text, findings, args.out, note)
    bad = [f for f in findings if f.status != "OK"]
    print(f"{len(findings)} numbers checked, {len(bad)} problems -> {'RELEASED' if not bad else 'BLOCKED'}")
    for f in bad:
        print(f"  {f.status:16} {f.text:>8}  | {f.sentence}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
