import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import pytest


@pytest.fixture(autouse=True)
def _keep_dashboard_data_out_of_repo(tmp_path, monkeypatch):
    """테스트가 실제 docs/data 파일을 덮어쓰지 않게 임시 폴더로 돌린다."""
    import rsi_oversold_alert as kr

    monkeypatch.setattr(kr, "DASHBOARD_DATA_DIR", tmp_path / "dashboard_data")
