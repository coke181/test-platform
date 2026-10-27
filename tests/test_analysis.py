import conftest  # noqa: F401
import app as appmod


def _run(name, cases):
    appmod.import_run({
        "name": name, "project": "demo", "started_at": None,
        "total": len(cases),
        "passed": sum(1 for c in cases if c["status"] == "passed"),
        "failed": sum(1 for c in cases if c["status"] == "failed"),
        "errors": 0, "skipped": 0, "duration": 0.1,
    }, cases)


def _case(name, cls, status, message=""):
    return {"name": name, "classname": cls, "file": "", "line": None, "time": 0.01,
            "status": status, "message": message, "traceback": message}


def test_flaky_and_clustering(client):
    with appmod.app.app_context():
        _run("r1", [_case("test_a", "SuiteA", "passed"), _case("test_b", "SuiteB", "passed")])
        _run("r2", [_case("test_a", "SuiteA", "failed", "Connection timeout to 10.0.0.1"),
                    _case("test_b", "SuiteB", "passed")])
        _run("r3", [_case("test_a", "SuiteA", "passed"),
                    _case("test_b", "SuiteB", "failed", "Connection timeout to 10.0.0.1")])

        data = appmod.analyze_project("demo")
        assert data["flaky_count"] == 2
        assert data["total_failures"] == 2
        assert len(data["clusters"]) == 1
        assert data["clusters"][0]["count"] == 2
        assert data["clusters"][0]["signature"] == "Connection timeout to IP"


def test_empty_project(client):
    with appmod.app.app_context():
        data = appmod.analyze_project("nothing")
        assert data["run_count"] == 0
        assert data["flaky_count"] == 0