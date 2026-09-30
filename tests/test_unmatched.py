from app.services import unmatched_log


def test_record_and_top(tmp_path, monkeypatch):
    monkeypatch.setattr(unmatched_log, "PATH", tmp_path / "u.json")
    unmatched_log.record("하가우")
    unmatched_log.record("하가우")
    unmatched_log.record("차슈바오")
    rows = unmatched_log.top(10)
    assert rows[0]["menu"] == "하가우" and rows[0]["count"] == 2
    assert unmatched_log.stats()["미매칭 메뉴 종류"] == 2
    unmatched_log.mark_added("하가우")
    assert unmatched_log.top(10, status="대기")[0]["menu"] == "차슈바오"


def test_ignores_junk(tmp_path, monkeypatch):
    monkeypatch.setattr(unmatched_log, "PATH", tmp_path / "u.json")
    unmatched_log.record("  ")
    unmatched_log.record("가" * 50)
    assert unmatched_log.top(10) == []
