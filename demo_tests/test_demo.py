import os


def test_login_success():
    assert True


def test_payment_success():
    assert True


def test_search_basic():
    assert True


def test_api_health():
    assert True


def test_optional_demo_failure():
    if os.environ.get("DEMO_FORCE_FAIL") == "1":
        assert False, "手动触发的演示失败：用于验证告警与失败取证"
    assert True