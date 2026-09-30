import os

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "sb_publishable_test_key")
os.environ.setdefault("GROQ_API_KEY", "test")


import pytest


@pytest.fixture(autouse=True)
def isolate_analysis_cache(tmp_path, monkeypatch):
    """테스트가 실제 캐시 파일(app/data/analysis_cache.json)을 오염시키지 않도록 격리한다.

    가짜 성분이 실제 캐시에 남으면 그게 진짜 판정인 것처럼 사용자에게 나간다.
    알레르기 앱에서는 절대 있어서는 안 되는 일이라 모든 테스트에 자동 적용한다.
    """
    from app.services import analysis_cache

    monkeypatch.setattr(analysis_cache, "PATH", tmp_path / "analysis_cache.json")
    analysis_cache.clear()
    yield
    analysis_cache.clear()
