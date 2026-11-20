from pathlib import Path
from runpy import run_path

import pytest

compare = run_path(str(Path(__file__).resolve().parents[2] / "bench" / "checks.py"))["compare"]


@pytest.mark.parametrize("observed", [True, float("nan"), float("inf"), float("-inf")])
def test_numeric_constraints_reject_invalid_measurements(observed):
    assert compare({"target": 1, "tolerance": 0.1}, observed)
    assert compare({"min": 1}, observed)


def test_compare_reports_invalid_structure():
    assert compare({"passed": True}, None)
    assert compare({"passed": True}, {"passed": 1})
    assert not compare({"passed": True}, {"passed": True, "extra": 3})
