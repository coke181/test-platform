import xml.etree.ElementTree as ET

import conftest  # noqa: F401  (确保 app 可导入)


TESTSUITES_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="s1" tests="4" failures="1" errors="1" skipped="1" time="1.5" timestamp="2026-01-01T00:00:00">
    <testcase name="pass" classname="SuiteA" time="0.1"/>
    <testcase name="fail" classname="SuiteA" time="0.2"><failure message="boom">tb</failure></testcase>
    <testcase name="err" classname="SuiteA" time="0.3"><error message="err">tb</error></testcase>
    <testcase name="skip" classname="SuiteA" time="0.4"><skipped message="skip"/></testcase>
  </testsuite>
</testsuites>
"""

TESTSUITE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="single" tests="1" time="0.5">
  <testcase name="only" classname="SuiteB" time="0.5"/>
</testsuite>
"""


def test_parse_testsuites():
    import app
    run, cases = app.parse_junit(TESTSUITES_XML, "r1")
    assert run["total"] == 4
    assert run["passed"] == 1
    assert run["failed"] == 1
    assert run["errors"] == 1
    assert run["skipped"] == 1
    assert run["duration"] == 1.5
    assert run["started_at"] == "2026-01-01T00:00:00"
    assert [c["status"] for c in cases] == ["passed", "failed", "error", "skipped"]


def test_parse_single_testsuite():
    import app
    run, cases = app.parse_junit(TESTSUITE_XML, "r2")
    assert run["total"] == 1
    assert run["passed"] == 1
    assert cases[0]["name"] == "only"


def test_parse_invalid_xml_raises():
    import app
    try:
        app.parse_junit(b"<bad>", "r3")
    except ET.ParseError:
        return
    raise AssertionError("expected ET.ParseError")