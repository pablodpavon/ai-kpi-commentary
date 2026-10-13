import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kpicheck import kpis, verify  # noqa: E402


@pytest.fixture(scope="module")
def facts():
    return kpis.compute(ROOT / "data", "2026-09")


def test_argentine_number_format():
    assert verify.parse_number("1.234,5") == (1234.5, 1)
    assert verify.parse_number("3.409") == (3409.0, 0)
    assert verify.parse_number("0,3") == (0.3, 1)


def test_correct_draft_is_released(facts):
    text = (ROOT / "examples" / "draft_ok.md").read_text(encoding="utf-8")
    findings = verify.check(text, facts)
    assert len(findings) >= 15
    assert verify.passed(findings), [f for f in findings if f.status != "OK"]


def test_each_planted_error_is_caught_with_the_right_reason(facts):
    text = (ROOT / "examples" / "draft_with_errors.md").read_text(encoding="utf-8")
    bad = {(f.text, f.status) for f in verify.check(text, facts) if f.status != "OK"}
    assert bad == {("4,8", "NOT_FOUND"), ("10,6", "WRONG_DIRECTION"), ("7,9", "WRONG_METRIC"),
                   ("30,7", "WRONG_PERIOD"), ("30", "NOT_FOUND")}


def test_rounding_must_match_the_shown_precision(facts):
    rev = facts["kpis"]["revenue_m"]["mom"]          # -5.98...
    assert verify.passed(verify.check(f"La facturación bajó {abs(rev):.1f}% contra agosto.".replace(".", ","), facts))
    assert not verify.passed(verify.check("La facturación bajó 5,8% contra agosto.", facts))
