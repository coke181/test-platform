import conftest  # noqa: F401
import app as appmod


def _insert_run(project, name, passed, total, failed=0, errors=0):
    with appmod.app.app_context():
        db = appmod.get_db()
        db.execute("INSERT INTO runs(name, project, total, passed, failed, errors, skipped, duration, imported_at) VALUES (?,?,?,?,?,?,?,?,?)",
                   (name, project, total, passed, failed, errors, 0, 0.1, appmod.now_iso()))
        db.commit()
        return db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def test_pass_rate_alert_triggers(client, monkeypatch):
    monkeypatch.setattr(appmod, "send_webhook", lambda url, payload: (True, "ok"))
    run_id = _insert_run("model", "r1", 90, 100)
    with appmod.app.app_context():
        db = appmod.get_db()
        db.execute("INSERT INTO alert_rules(name, project, metric, threshold, webhook_url, enabled, created_at) VALUES (?,?,?,?,?,?,?)",
                   ("pass_rate", "model", "pass_rate_below", 95, "http://x", 1, appmod.now_iso()))
        db.commit()
        logs = appmod.evaluate_alerts(run_id)
        assert len(logs) == 1
        assert logs[0]["status"] == "sent"

        row = db.execute("SELECT COUNT(*) AS c FROM alert_logs").fetchone()
        assert row["c"] == 1


def test_rule_other_project_skipped(client, monkeypatch):
    monkeypatch.setattr(appmod, "send_webhook", lambda url, payload: (True, "ok"))
    run_id = _insert_run("model", "r1", 90, 100)
    with appmod.app.app_context():
        db = appmod.get_db()
        db.execute("INSERT INTO alert_rules(name, project, metric, threshold, webhook_url, enabled, created_at) VALUES (?,?,?,?,?,?,?)",
                   ("pass_rate", "other", "pass_rate_below", 95, "http://x", 1, appmod.now_iso()))
        db.commit()
        logs = appmod.evaluate_alerts(run_id)
        assert logs == []


def test_webhook_failure_logs(client, monkeypatch):
    monkeypatch.setattr(appmod, "send_webhook", lambda url, payload: (False, "timeout"))
    run_id = _insert_run("model", "r1", 90, 100)
    with appmod.app.app_context():
        db = appmod.get_db()
        db.execute("INSERT INTO alert_rules(name, project, metric, threshold, webhook_url, enabled, created_at) VALUES (?,?,?,?,?,?,?)",
                   ("pass_rate", "model", "pass_rate_below", 95, "http://x", 1, appmod.now_iso()))
        db.commit()
        logs = appmod.evaluate_alerts(run_id)
        assert logs[0]["status"] == "failed"