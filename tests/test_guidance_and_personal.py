import json
import stat
from datetime import date

import pytest

from navigator import guidance, personal


def test_guidance_file_is_valid():
    data = guidance.load_guidance()
    assert [s["id"] for s in data["stages"]] == guidance.STAGE_ORDER
    for stage in data["stages"]:
        for section in guidance.SECTIONS:
            assert stage[section], f"{stage['id']} has no {section}"


def test_verified_items_need_a_known_source(tmp_path):
    data = guidance.load_guidance()
    data["stages"][0]["contacts"].append({"text": "Made-up contact", "source": None, "status": "verified"})
    path = tmp_path / "pathway.json"
    path.write_text(json.dumps(data))
    with pytest.raises(guidance.GuidanceError):
        guidance.load_guidance(path)


def test_only_one_benchmark_per_clock():
    data = guidance.load_guidance()
    clocks = [b["clock"] for b in data["benchmarks"]]
    assert sorted(clocks) == ["autism", "paediatric"]
    autism = next(b for b in data["benchmarks"] if b["clock"] == "autism")
    assert autism["status"] == "verified" and autism["stage"] == "specialist_assessment"


def test_save_load_delete(tmp_path):
    path = tmp_path / "local_data" / "my_child.json"
    record = {
        "paed_referral_date": date(2026, 3, 2),
        "paed_accepted_date": None,
        "autism_referral_date": date(2026, 7, 1),
        "autism_accepted_date": None,
        "current_stage": "specialist_assessment",
        "contact_notes": "Phoned admin",
        "checklist": {"referral": {"A"}},
    }
    personal.save(record, path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    loaded = personal.load(path)
    assert loaded["paed_referral_date"] == date(2026, 3, 2)
    assert loaded["paed_accepted_date"] is None
    assert loaded["checklist"] == {"referral": {"A"}}
    assert personal.delete(path) is True
    assert not path.exists()
    assert personal.load(path) is None
    assert personal.delete(path) is False


def test_elapsed_and_months():
    assert personal.describe_elapsed(date(2026, 1, 1), date(2026, 1, 16)) == "2 weeks and 1 day (15 days)"
    assert personal.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert personal.add_months(date(2027, 11, 30), 3) == date(2028, 2, 29)


def test_personal_data_is_gitignored():
    from pathlib import Path

    ignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text()
    assert "local_data/" in ignore
    assert ".streamlit/secrets.toml" in ignore
