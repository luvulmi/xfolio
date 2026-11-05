"""실제 관리자와 충돌하지 않는 격리 HTTPS 시험 포트 설정."""

from runpy import run_path

import pytest

from tests.support.paths import ROOT


@pytest.mark.parametrize("port", [None, "18447"])
def test_browser_test_origin_and_listener_share_selected_port(monkeypatch, port):
    if port is None:
        monkeypatch.delenv("XFOLIO_BROWSER_TEST_PORT", raising=False)
    else:
        monkeypatch.setenv("XFOLIO_BROWSER_TEST_PORT", port)
    values = run_path(str(ROOT / "tests/support/browser_api_server.py"))
    expected = int(port or "8447")
    assert values["PORT"] == expected
    assert values["ORIGIN"] == f"https://127.0.0.1:{expected}"


@pytest.mark.parametrize("port", ["3000", "8000", "0", "65536", "invalid"])
def test_browser_test_rejects_forbidden_or_invalid_port(monkeypatch, port):
    monkeypatch.setenv("XFOLIO_BROWSER_TEST_PORT", port)
    with pytest.raises(ValueError):
        run_path(str(ROOT / "tests/support/browser_api_server.py"))
