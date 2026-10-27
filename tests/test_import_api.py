import io

import conftest  # noqa: F401
import app as appmod

XML = b"""<testsuite name="s" tests="1">
  <testcase name="ok" classname="SuiteA"/>
</testsuite>"""


def test_import_requires_token_when_configured(client):
    appmod.PLATFORM_API_TOKEN = "secret"
    resp = client.post("/api/import", data={"project": "demo", "file": (io.BytesIO(XML), "r.xml")})
    assert resp.status_code == 401


def test_import_with_token(client):
    appmod.PLATFORM_API_TOKEN = "secret"
    resp = client.post("/api/import", data={"project": "demo", "name": "r1", "file": (io.BytesIO(XML), "r.xml")},
                       headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["project"] == "demo"
    assert body["total"] == 1
    assert body["passed"] == 1


def test_import_invalid_xml(client):
    appmod.PLATFORM_API_TOKEN = "secret"
    resp = client.post("/api/import", data={"project": "demo", "file": (io.BytesIO(b"<bad>"), "r.xml")},
                       headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 400