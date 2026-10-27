import conftest  # noqa: F401
import app as appmod


def test_coverage_stats(client):
    with appmod.app.app_context():
        db = appmod.get_db()
        db.execute("INSERT INTO test_cases(title, project, automation_id, tags, created_at) VALUES (?,?,?,?,?)",
                   ("登录", "model", "tests/test_api.py::test_login", "核心", appmod.now_iso()))
        db.execute("INSERT INTO test_cases(title, project, automation_id, tags, created_at) VALUES (?,?,?,?,?)",
                   ("未自动化", "model", "", "", appmod.now_iso()))
        db.execute("INSERT INTO runs(name, project, total, passed, failed, errors, skipped, duration, imported_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   ("r1", "model", 1, 1, 0, 0, 0, 0.1, appmod.now_iso()))
        run_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        db.execute("INSERT INTO cases(run_id, name, classname, status) VALUES (?,?,?,?)",
                   (run_id, "test_login", "tests/test_api.py", "passed"))
        db.commit()

        stats = appmod.coverage_stats(db, "model")
        assert stats["total"] == 2
        assert stats["linked"] == 1
        assert stats["covered"] == 1
        assert stats["rate"] == 50.0