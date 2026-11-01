"""Weekly live pipeline, all offline: the LLM is replaced by a template drafter."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kpicheck import data_checks, draft, live, verify, weekly_data  # noqa: E402

CLEAN = "2026-W43"
NOW = datetime(2026, 11, 2, 6, 30, tzinfo=timezone.utc)
STATUS_KEYS = {"system", "title_en", "title_es", "last_run_utc", "ok", "items", "items_label_en",
               "items_label_es", "cost_usd", "schedule_en", "schedule_es", "note"}


def weeks_with(anomaly):
    return [w for w in (f"{y}-W{n:02d}" for y in (2025, 2026, 2027) for n in range(1, 53))
            if weekly_data.planted_anomaly(w) == anomaly]


def test_same_week_regenerates_identically():
    a, sa, _ = weekly_data.generate_week(CLEAN)
    b, sb, _ = weekly_data.generate_week(CLEAN)
    pd.testing.assert_frame_equal(a, b)
    pd.testing.assert_frame_equal(sa, sb)
    other, _, _ = weekly_data.generate_week("2026-W44")
    assert len(a) != len(other) or not a.revenue_ars.equals(other.revenue_ars)


def test_previous_week_in_a_report_equals_last_weeks_published_value():
    cur, _, _ = live.week_facts("2026-W44")
    prev, _, _ = live.week_facts("2026-W43")
    for k in ("revenue_m", "orders", "new_customers", "cac"):
        assert cur["kpis"][k]["prev"] == pytest.approx(prev["kpis"][k]["value"])


def test_iso_week_edges():
    assert weekly_data.previous_week("2027-W01") == "2026-W53"
    assert weekly_data.same_week_last_year("2026-W53") == "2025-W52"   # 2025 has no week 53
    assert live.week_title("2026-W43") == "Semana 43 · 19 al 25 de octubre de 2026"


@pytest.mark.parametrize("anomaly,code", [("duplicate_day", "DUPLICATE_ORDERS"), ("missing_day", "MISSING_DAY"),
                                          ("refunds_as_orders", "NON_POSITIVE_REVENUE"), ("spend_missing", "SPEND_MISSING")])
def test_every_planted_anomaly_is_caught_by_the_data_check(anomaly, code):
    weeks = weeks_with(anomaly)
    assert weeks, f"no week carries {anomaly} in 2025-2027"
    for w in weeks:
        o, s, planted = weekly_data.generate_week(w, delivered=True)
        assert planted == anomaly
        assert code in {i.code for i in data_checks.check(o, s, weekly_data.week_days(w))}
        o, s, _ = weekly_data.generate_week(w, delivered=False)      # the corrected feed passes
        assert data_checks.check(o, s, weekly_data.week_days(w)) == []


def test_anomalies_are_occasional():
    weeks = [f"{y}-W{n:02d}" for y in (2025, 2026, 2027) for n in range(1, 53)]
    share = sum(weekly_data.planted_anomaly(w) is not None for w in weeks) / len(weeks)
    assert 0.04 < share < 0.25


def test_clean_week_with_correct_draft_is_released(tmp_path):
    rec = live.run_week(CLEAN, tmp_path, live.offline_draft, now=NOW)
    assert rec["status"] == "RELEASED" and rec["numbers_checked"] >= 8 and rec["cost_usd"] == 0.0
    assert (tmp_path / CLEAN / "report.html").exists()


def test_planted_number_error_is_blocked_by_the_number_check(tmp_path):
    def wrong(facts):
        text, usage, model = live.offline_draft(facts)
        rev = facts["kpis"]["revenue_m"]["mom"]
        bad = text.replace(f"{abs(rev):.1f}".replace(".", ","), f"{abs(rev) + 1.3:.1f}".replace(".", ","), 1)
        assert bad != text
        return bad, usage, model
    rec = live.run_week(CLEAN, tmp_path, wrong, now=NOW)
    assert rec["status"] == "BLOCKED" and rec["blocked_by"] == "number_check"
    assert rec["reasons"][0].startswith("NOT_FOUND")


def test_data_blocked_week_never_calls_the_llm(tmp_path):
    w = weeks_with("missing_day")[0]

    def must_not_run(facts):
        raise AssertionError("LLM called on bad data")
    rec = live.run_week(w, tmp_path, must_not_run, now=NOW)
    assert rec["status"] == "BLOCKED" and rec["blocked_by"] == "data_check" and rec["cost_usd"] == 0.0


def test_week_numbers_and_dates_in_text_are_not_treated_as_data():
    facts, _, _ = live.week_facts(CLEAN)
    num = f"{abs(facts['kpis']['revenue_m']['mom']):.1f}".replace(".", ",")
    verb = "subió" if facts["kpis"]["revenue_m"]["mom"] > 0 else "bajó"
    txt = f"En la semana 43, del 19 al 25 de octubre, la facturación {verb} {num}% contra la semana anterior."
    f = verify.check(txt, facts, verify.WEEK_WOW_WORDS, verify.WEEK_YOY_WORDS, verify.WEEK_SKIP)
    assert [x.text for x in f] == [num] and verify.passed(f)


def test_weekly_period_words_catch_a_wrong_period():
    facts, _, _ = live.week_facts(CLEAN)
    yoy = facts["kpis"]["orders"]["yoy"]
    s = f"Los pedidos {'subieron' if yoy > 0 else 'bajaron'} {abs(yoy):.1f}% contra la semana anterior.".replace(".", ",", 1)
    f = verify.check(s, facts, verify.WEEK_WOW_WORDS, verify.WEEK_YOY_WORDS, verify.WEEK_SKIP)
    assert [x.status for x in f] == ["WRONG_PERIOD"]


def test_index_is_rebuilt_from_folders_and_status_has_the_contract(tmp_path):
    live.run_week(CLEAN, tmp_path, live.offline_draft, now=NOW)
    live.run_week(weeks_with("missing_day")[0], tmp_path, live.offline_draft, now=NOW)
    live.run_week(CLEAN, tmp_path, live.offline_draft, now=NOW)          # re-run: no duplicate entry
    idx = live.rebuild_index(tmp_path)
    assert (idx["runs"], idx["released"], idx["blocked"], idx["blocked_by_data_check"]) == (2, 1, 1, 1)
    assert json.loads((tmp_path / "index.json").read_text())["runs"] == 2
    assert "2 runs: 1 released, 1 blocked" in (tmp_path / "index.md").read_text()
    st = live.status_payload(idx, True, "x", NOW)
    assert set(st) == STATUS_KEYS and st["last_run_utc"] == "2026-11-02T06:30:00Z"
    assert st["system"] == "kpi-report" and st["items"] == idx["last"]["numbers_checked"] and "2 weekly runs, 1 blocked" in st["note"]
    assert all(len(v) <= 200 and "/Users" not in v for v in st.values() if isinstance(v, str))
    live.write_json_atomic(tmp_path / "s.json", st)
    assert json.loads((tmp_path / "s.json").read_text()) == st


def test_readme_block_is_replaced_between_markers(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("top\n<!-- LIVE:START -->\nold\n<!-- LIVE:END -->\nbottom\n")
    live.run_week(CLEAN, tmp_path, live.offline_draft, now=NOW)
    live.update_readme(readme, live.rebuild_index(tmp_path))
    s = readme.read_text()
    assert "old" not in s and "week 2026-W43" in s and s.startswith("top") and s.endswith("bottom\n")


def test_cost_from_usage_and_key_loader(tmp_path):
    assert draft.cost_usd("claude-haiku-5-5", {"input_tokens": 1_000_000, "output_tokens": 1_000_000}) == pytest.approx(0.60)
    assert draft.cost_usd("unknown-model", {"input_tokens": 1}) is None
    f = tmp_path / "k.env"
    f.write_text("ANTHROPIC_API_KEY=sk-ant-test-not-a-real-key\n")
    assert draft.load_key(f) == "sk-ant-test-not-a-real-key"
    f.write_text("ANTHROPIC_API_KEY=abc\n")
    with pytest.raises(RuntimeError):
        draft.load_key(f)
    with pytest.raises(RuntimeError):
        draft.load_key(tmp_path / "missing.env")


def test_cost_cap_stops_before_calling(tmp_path):
    def must_not_run(facts):
        raise AssertionError("called above the cap")
    with pytest.raises(RuntimeError, match="cap"):
        live.run_week(CLEAN, tmp_path, must_not_run, now=NOW, max_estimate_usd=0.0)


def test_response_cut_by_max_tokens_is_a_failed_run_not_a_draft():
    from types import SimpleNamespace as NS
    usage = NS(input_tokens=1200, output_tokens=4000, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    cut = NS(usage=usage, content=[NS(type="thinking", thinking="")], stop_reason="max_tokens", model="claude-haiku-5-5")
    with pytest.raises(RuntimeError, match="max_tokens"):
        draft.parse_response(cut)
    ok = NS(usage=usage, content=[NS(type="text", text="La facturación subió.")], stop_reason="end_turn", model="m")
    assert draft.parse_response(ok)[0] == "La facturación subió."
