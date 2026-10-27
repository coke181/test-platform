# -*- coding: utf-8 -*-
"""测试报告与用例管理平台（Flask + SQLite）

功能：
- 上传 pytest 的 JUnit XML 报告，解析入库
- 展示运行记录、用例列表、仪表盘统计
- 提供 JSON API 供其他工具调用

用法：
    python app.py
然后浏览器打开 http://127.0.0.1:5000
"""
import csv
import io
import json
import os
import re
import urllib.request
import secrets
import sqlite3
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from flask import (Flask, Response, g, jsonify, render_template, request, redirect, url_for, flash, send_from_directory)

from db import SCHEMA

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "report.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 公网部署时设置 TEST_PLATFORM_TOKEN，写入接口将强制校验；
# 本地开发不设置则保持无鉴权，方便快速联调。
PLATFORM_API_TOKEN = (os.environ.get("TEST_PLATFORM_TOKEN", "") or "").strip().lstrip("\ufeff")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
TEXT_EXTS = {".log", ".txt", ".json", ".xml", ".html", ".md", ".csv"}
ALLOWED_EXTS = IMAGE_EXTS | TEXT_EXTS | {".zip", ".pdf"}

app = Flask(__name__)
app.secret_key = "dev-secret-change-me"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.executescript(SCHEMA)
        _migrate(db)


def _migrate(db):
    for table, column, ddl in (
        ("runs", "project", "TEXT NOT NULL DEFAULT '默认项目'"),
        ("test_cases", "project", "TEXT DEFAULT '默认项目'"),
        ("test_cases", "automation_id", "TEXT DEFAULT ''"),
        ("test_cases", "tags", "TEXT DEFAULT ''"),
    ):
        cols = [row[1] for row in db.execute("PRAGMA table_info(%s)" % table).fetchall()]
        if column not in cols:
            db.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, ddl))
    db.commit()


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def api_token_ok():
    if not PLATFORM_API_TOKEN:
        return True
    supplied = request.headers.get("Authorization", "")
    if supplied.startswith("Bearer "):
        supplied = supplied[7:].strip()
    api_key = request.headers.get("X-API-Key", "").strip()
    return secrets.compare_digest(supplied, PLATFORM_API_TOKEN) or \
        secrets.compare_digest(api_key, PLATFORM_API_TOKEN)

def attachment_kind(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext == ".log":
        return "log"
    if ext in TEXT_EXTS:
        return "text"
    return "file"


def save_attachment(file_storage, run_id=None, case_id=None):
    original = os.path.basename(file_storage.filename or "attachment")
    ext = os.path.splitext(original)[1].lower()
    if ext and ext not in ALLOWED_EXTS:
        raise ValueError("不支持的文件类型：" + ext)
    stored = "run%s_%s_%s" % (run_id if run_id is not None else "x", uuid.uuid4().hex[:8], original)
    stored = re.sub(r"[^\w.\-]", "_", stored)
    file_storage.save(os.path.join(UPLOAD_DIR, stored))
    db = get_db()
    db.execute(
        "INSERT INTO attachments(run_id, case_id, kind, filename, stored_name, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, case_id, attachment_kind(original), original, stored, now_iso()),
    )
    db.commit()
    return stored


def read_text_attachment(stored_name, limit=20000):
    try:
        with open(os.path.join(UPLOAD_DIR, stored_name), "r", encoding="utf-8", errors="replace") as f:
            data = f.read(limit)
        if len(data) >= limit:
            data += "\n...(内容过长，已截断)"
        return data
    except OSError:
        return ""


def parse_junit(xml_bytes, run_name):
    root = ET.fromstring(xml_bytes)
    suites = []
    if root.tag == "testsuites":
        suites = list(root)
    elif root.tag == "testsuite":
        suites = [root]

    cases = []
    total = passed = failed = errors = skipped = 0
    duration = 0.0
    started_at = None

    for suite in suites:
        if suite.tag != "testsuite":
            continue
        if suite.get("timestamp"):
            started_at = suite.get("timestamp")
        duration += float(suite.get("time") or 0)
        for tc in suite.findall("testcase"):
            name = tc.get("name", "")
            classname = tc.get("classname", "")
            file_ = tc.get("file", "")
            line = tc.get("line")
            time_ = float(tc.get("time") or 0)
            status = "passed"
            message = ""
            traceback = ""
            fail = tc.find("failure")
            err = tc.find("error")
            skip = tc.find("skipped")
            if fail is not None:
                status = "failed"
                failed += 1
                message = fail.get("message") or ""
                traceback = (fail.text or "")[:8000]
            elif err is not None:
                status = "error"
                errors += 1
                message = err.get("message") or ""
                traceback = (err.text or "")[:8000]
            elif skip is not None:
                status = "skipped"
                skipped += 1
                message = skip.get("message") or (skip.text or "")
            else:
                passed += 1
            total += 1
            cases.append({
                "name": name,
                "classname": classname,
                "file": file_,
                "line": int(line) if line and line.isdigit() else None,
                "time": time_,
                "status": status,
                "message": message,
                "traceback": traceback,
            })

    run = {
        "name": run_name,
        "started_at": started_at,
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "duration": round(duration, 3),
    }
    return run, cases


def import_run(run, cases):
    db = get_db()
    cur = db.execute(
        "INSERT INTO runs(name, project, started_at, total, passed, failed, errors, skipped, duration, imported_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run["name"], run.get("project") or "默认项目", run["started_at"], run["total"], run["passed"],
         run["failed"], run["errors"], run["skipped"], run["duration"], now_iso()),
    )
    run_id = cur.lastrowid
    for c in cases:
        db.execute(
            "INSERT INTO cases(run_id, name, classname, file, line, time, status, message, traceback) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, c["name"], c["classname"], c["file"], c["line"],
             c["time"], c["status"], c["message"], c["traceback"]),
        )
    db.commit()
    return run_id


def case_key(c):
    return ((c["classname"] or "") + "::" + (c["name"] or ""))


def failure_signature(text):
    if not text or not text.strip():
        return "(无失败信息)"
    s = text.strip()
    s = re.sub(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "UUID", s)
    s = re.sub(r"\b0x[0-9a-fA-F]+\b", "HEX", s)
    s = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "IP", s)
    s = re.sub(r"[A-Za-z]:[\\/][^\s\"']+", "PATH", s)
    s = re.sub(r"(?<=[^\w])/[^\s\"']+", "PATH", s)
    s = re.sub(r"\b\d+(?:\.\d+)?\b", "N", s)
    s = re.sub(r'"[^"]*"', 'STR', s)
    s = re.sub(r"'[^']*'", 'STR', s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:200]


def analyze_project(project, run_limit=20, cluster_limit=20):
    db = get_db()
    if project:
        recent = db.execute(
            "SELECT * FROM runs WHERE project = ? ORDER BY id DESC LIMIT ?",
            (project, run_limit),
        ).fetchall()
    else:
        recent = db.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?",
            (run_limit,),
        ).fetchall()

    run_ids = [r["id"] for r in recent]
    if not run_ids:
        return {
            "project": project,
            "run_limit": run_limit,
            "run_count": 0,
            "case_count": 0,
            "flaky": [],
            "flaky_count": 0,
            "flaky_rate": 0,
            "clusters": [],
            "total_failures": 0,
        }

    placeholders = ",".join("?" for _ in run_ids)
    case_rows = db.execute(
        "SELECT * FROM cases WHERE run_id IN (%s) ORDER BY id DESC" % placeholders,
        run_ids,
    ).fetchall()

    BAD = ("failed", "error")
    groups = {}
    for c in case_rows:
        key = case_key(c)
        groups.setdefault(key, []).append(c)

    flaky = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        statuses = [c["status"] for c in items]
        fail_count = sum(1 for s in statuses if s in BAD)
        pass_count = sum(1 for s in statuses if s == "passed")
        if fail_count > 0 and pass_count > 0:
            latest = items[0]
            flaky.append({
                "key": key,
                "name": latest["name"],
                "classname": latest["classname"],
                "total_runs": len(items),
                "fail_count": fail_count,
                "pass_count": pass_count,
                "last_status": latest["status"],
                "last_message": (latest["message"] or "")[:200],
            })
    flaky.sort(key=lambda x: (-x["fail_count"], x["key"]))

    clusters = {}
    total_failures = 0
    for c in case_rows:
        if c["status"] not in BAD:
            continue
        total_failures += 1
        raw = c["message"] or c["traceback"] or ""
        sig = failure_signature(raw)
        bucket = clusters.setdefault(sig, {
            "signature": sig,
            "count": 0,
            "cases": set(),
            "sample_message": "",
            "sample_case": "",
        })
        bucket["count"] += 1
        bucket["cases"].add(case_key(c))
        if not bucket["sample_message"]:
            bucket["sample_message"] = (c["message"] or c["traceback"] or "")[:300]
            bucket["sample_case"] = (c["name"] or "")[:120]
    cluster_list = []
    for bucket in clusters.values():
        cluster_list.append({
            "signature": bucket["signature"],
            "count": bucket["count"],
            "case_count": len(bucket["cases"]),
            "sample_case": bucket["sample_case"],
            "sample_message": bucket["sample_message"],
        })
    cluster_list.sort(key=lambda x: (-x["count"], x["signature"]))
    cluster_list = cluster_list[:cluster_limit]

    flaky_rate = round(len(flaky) / len(groups) * 100, 1) if groups else 0
    return {
        "project": project,
        "run_limit": run_limit,
        "run_count": len(recent),
        "case_count": len(case_rows),
        "flaky": flaky,
        "flaky_count": len(flaky),
        "flaky_rate": flaky_rate,
        "clusters": cluster_list,
        "total_failures": total_failures,
    }


@app.route("/analysis")
def analysis():
    db = get_db()
    projects = [r["project"] for r in db.execute(
        "SELECT DISTINCT project FROM runs WHERE project IS NOT NULL AND project != '' ORDER BY project"
    ).fetchall()]
    project = request.args.get("project", "").strip()
    limit = request.args.get("limit", 20, type=int)
    data = analyze_project(project, run_limit=limit)
    return render_template("analysis.html", projects=projects, project=project,
                           data=data, limit=limit)


@app.route("/api/analysis")
def api_analysis():
    project = request.args.get("project", "").strip()
    limit = request.args.get("limit", 20, type=int)
    return jsonify(analyze_project(project, run_limit=limit))


def send_webhook(url, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return True, "HTTP %s" % resp.status
    except Exception as exc:
        return False, str(exc)


def evaluate_alerts(run_id):
    db = get_db()
    run = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        return []
    project = run["project"] or "默认项目"
    rules = db.execute(
        "SELECT * FROM alert_rules WHERE enabled = 1 AND (project = '' OR project = ?)",
        (project,),
    ).fetchall()
    if not rules:
        return []

    total = run["total"] or 0
    passed = run["passed"] or 0
    pass_rate = round(passed / total * 100, 1) if total else 100.0

    prev = db.execute(
        "SELECT * FROM runs WHERE project = ? AND id < ? ORDER BY id DESC LIMIT 1",
        (project, run_id),
    ).fetchone()
    BAD = ("failed", "error")
    if prev:
        prev_cases = db.execute("SELECT * FROM cases WHERE run_id = ?", (prev["id"],)).fetchall()
        cur_cases = db.execute("SELECT * FROM cases WHERE run_id = ?", (run_id,)).fetchall()
        prev_status = {case_key(c): c["status"] for c in prev_cases}
        new_failures = 0
        for c in cur_cases:
            if c["status"] in BAD:
                old = prev_status.get(case_key(c))
                if old is None or old not in BAD:
                    new_failures += 1
    else:
        new_failures = (run["failed"] or 0) + (run["errors"] or 0)

    flaky_count = analyze_project(project, run_limit=20)["flaky_count"]

    logs = []
    for rule in rules:
        metric = rule["metric"]
        if metric == "pass_rate_below":
            value = pass_rate
        elif metric == "new_failure":
            value = new_failures
        elif metric == "flaky_count_above":
            value = flaky_count
        else:
            continue

        threshold = float(rule["threshold"] or 0)
        triggered = value < threshold if metric == "pass_rate_below" else value >= threshold
        if not triggered:
            continue

        payload = {
            "event": "test-platform-alert",
            "rule": rule["name"],
            "project": project,
            "run": run["name"],
            "run_id": run_id,
            "metric": metric,
            "value": value,
            "threshold": threshold,
            "pass_rate": pass_rate,
            "failed": run["failed"],
            "errors": run["errors"],
            "new_failures": new_failures,
            "flaky_count": flaky_count,
        }
        ok, message = send_webhook(rule["webhook_url"], payload)
        db.execute(
            "INSERT INTO alert_logs(rule_id, run_id, status, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (rule["id"], run_id, "sent" if ok else "failed", message[:500], now_iso()),
        )
        logs.append({"rule": rule["name"], "status": "sent" if ok else "failed", "message": message})
    db.commit()
    return logs


def coverage_stats(db, project):
    if project:
        rows = db.execute(
            "SELECT id, automation_id FROM test_cases WHERE project = ?",
            (project,),
        ).fetchall()
    else:
        rows = db.execute("SELECT id, automation_id FROM test_cases").fetchall()

    total = len(rows)
    linked = sum(1 for r in rows if (r["automation_id"] or "").strip())
    executed_keys = set()
    if rows:
        for r in db.execute(
            "SELECT DISTINCT (COALESCE(classname,'') || '::' || COALESCE(name,'')) AS key FROM cases"
        ).fetchall():
            if r["key"]:
                executed_keys.add(r["key"])
    covered = sum(1 for r in rows if (r["automation_id"] or "").strip() and r["automation_id"] in executed_keys)
    rate = round(covered / total * 100, 1) if total else 0
    return {"total": total, "linked": linked, "covered": covered, "rate": rate}


def automation_status(db, rows):
    ids = [r["automation_id"] for r in rows if (r["automation_id"] or "").strip()]
    result = {}
    if not ids:
        return result
    placeholders = ",".join("?" for _ in ids)
    sql = (
        "SELECT (COALESCE(classname,'') || '::' || COALESCE(name,'')) AS key, status "
        "FROM cases WHERE (COALESCE(classname,'') || '::' || COALESCE(name,'')) IN (%s) "
        "ORDER BY id DESC" % placeholders
    )
    for r in db.execute(sql, ids).fetchall():
        if r["key"] not in result:
            result[r["key"]] = r["status"]
    return result


@app.route("/alerts")
def alerts():
    db = get_db()
    projects = [r["project"] for r in db.execute(
        "SELECT DISTINCT project FROM runs WHERE project IS NOT NULL AND project != '' ORDER BY project"
    ).fetchall()]
    rules = db.execute("SELECT * FROM alert_rules ORDER BY id DESC").fetchall()
    logs = db.execute("SELECT * FROM alert_logs ORDER BY id DESC LIMIT 50").fetchall()
    return render_template("alerts.html", projects=projects, rules=rules, logs=logs)


@app.route("/alerts/new", methods=["POST"])
def alerts_new():
    name = request.form.get("name", "").strip()
    webhook_url = request.form.get("webhook_url", "").strip()
    metric = request.form.get("metric", "").strip()
    if not name or not webhook_url or metric not in ("pass_rate_below", "new_failure", "flaky_count_above"):
        flash("名称、Webhook 地址和指标均不能为空", "error")
        return redirect(url_for("alerts"))
    try:
        threshold = float(request.form.get("threshold", "0"))
    except ValueError:
        threshold = 0
    db = get_db()
    db.execute(
        "INSERT INTO alert_rules(name, project, metric, threshold, webhook_url, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?)",
        (name, request.form.get("project", "").strip(), metric, threshold, webhook_url, now_iso()),
    )
    db.commit()
    flash("告警规则已创建", "ok")
    return redirect(url_for("alerts"))


@app.route("/alerts/<int:rule_id>/delete", methods=["POST"])
def alerts_delete(rule_id):
    db = get_db()
    db.execute("DELETE FROM alert_rules WHERE id = ?", (rule_id,))
    db.commit()
    flash("告警规则已删除", "ok")
    return redirect(url_for("alerts"))


@app.route("/alerts/<int:rule_id>/test", methods=["POST"])
def alerts_test(rule_id):
    db = get_db()
    rule = db.execute("SELECT * FROM alert_rules WHERE id = ?", (rule_id,)).fetchone()
    if rule is None:
        flash("告警规则不存在", "error")
        return redirect(url_for("alerts"))
    payload = {"event": "test-platform-alert-test", "rule": rule["name"], "message": "这是一条测试消息"}
    ok, message = send_webhook(rule["webhook_url"], payload)
    db.execute(
        "INSERT INTO alert_logs(rule_id, run_id, status, message, created_at) VALUES (?, NULL, ?, ?, ?)",
        (rule["id"], "sent" if ok else "failed", message[:500], now_iso()),
    )
    db.commit()
    flash(("测试发送成功：" if ok else "测试发送失败：") + message, "ok" if ok else "error")
    return redirect(url_for("alerts"))


@app.route("/api/alerts")
def api_alerts():
    db = get_db()
    rules = db.execute("SELECT * FROM alert_rules ORDER BY id DESC").fetchall()
    logs = db.execute("SELECT * FROM alert_logs ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify({"rules": [dict(r) for r in rules], "logs": [dict(l) for l in logs]})


def _svg_points(values, width, height, pad=26.0, ymin=None, ymax=None):
    if not values:
        return ""
    if ymin is None:
        ymin = min(values)
    if ymax is None:
        ymax = max(values)
    if ymax - ymin < 1e-9:
        ymin -= 1
        ymax += 1
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = pad + (i * inner_w / (n - 1) if n > 1 else inner_w / 2)
        y = height - pad - (v - ymin) / (ymax - ymin) * inner_h
        pts.append("%.1f,%.1f" % (x, y))
    return " ".join(pts)


@app.route("/reports")
def reports():
    db = get_db()
    project = request.args.get("project", "").strip()
    where = " WHERE project = ?" if project else ""
    params = [project] if project else []

    runs = db.execute("SELECT * FROM runs" + where + " ORDER BY id ASC", params).fetchall()
    run_rows = []
    pass_rates = []
    durations = []
    total_failures = 0
    for r in runs:
        total = r["total"] or 0
        rate = round(r["passed"] / total * 100, 1) if total else 0
        dur = round(r["duration"] or 0, 3)
        run_rows.append({
            "id": r["id"], "name": r["name"], "project": r["project"],
            "total": r["total"], "passed": r["passed"], "failed": r["failed"],
            "errors": r["errors"], "skipped": r["skipped"], "duration": dur,
            "rate": rate, "imported_at": r["imported_at"],
        })
        pass_rates.append(rate)
        durations.append(dur)
        total_failures += (r["failed"] or 0) + (r["errors"] or 0)

    avg_rate = round(sum(pass_rates) / len(pass_rates), 1) if pass_rates else 0
    avg_dur = round(sum(durations) / len(durations), 3) if durations else 0
    analysis_data = analyze_project(project, run_limit=20)
    pass_points = _svg_points(pass_rates, 960, 220, ymin=0, ymax=100)
    dur_points = _svg_points(durations, 960, 180)
    projects = [r["project"] for r in db.execute(
        "SELECT DISTINCT project FROM runs WHERE project IS NOT NULL AND project != '' ORDER BY project"
    ).fetchall()]
    return render_template(
        "reports.html", runs=run_rows, project=project, projects=projects,
        run_count=len(run_rows), avg_rate=avg_rate, avg_dur=avg_dur,
        total_failures=total_failures, flaky_count=analysis_data["flaky_count"],
        clusters=analysis_data["clusters"][:10],
        pass_points=pass_points, dur_points=dur_points,
    )


@app.route("/reports/export.csv")
def reports_export():
    db = get_db()
    project = request.args.get("project", "").strip()
    where = " WHERE project = ?" if project else ""
    params = [project] if project else []
    rows = db.execute("SELECT * FROM runs" + where + " ORDER BY id ASC", params).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "project", "name", "total", "passed", "failed", "errors",
                     "skipped", "pass_rate", "duration", "imported_at"])
    for r in rows:
        total = r["total"] or 0
        rate = round(r["passed"] / total * 100, 1) if total else 0
        writer.writerow([r["id"], r["project"], r["name"], r["total"], r["passed"],
                         r["failed"], r["errors"], r["skipped"], rate,
                         r["duration"], r["imported_at"]])
    csv_text = buf.getvalue()
    return Response("\ufeff" + csv_text, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=test-report.csv"})


@app.route("/")
def index():
    db = get_db()
    project = request.args.get("project", "").strip()
    where = ""
    params = []
    if project:
        where = " WHERE project = ?"
        params.append(project)

    total_runs = db.execute("SELECT COUNT(*) AS c FROM runs" + where, params).fetchone()["c"]
    agg = db.execute(
        "SELECT COALESCE(SUM(total),0) AS total, COALESCE(SUM(passed),0) AS passed, "
        "COALESCE(SUM(failed),0) AS failed, COALESCE(SUM(errors),0) AS errors, "
        "COALESCE(SUM(skipped),0) AS skipped FROM runs" + where, params
    ).fetchone()
    recent = db.execute("SELECT * FROM runs" + where + " ORDER BY id DESC LIMIT 5", params).fetchall()
    trends = db.execute("SELECT id, name, passed, total FROM runs" + where + " ORDER BY id ASC", params).fetchall()
    manual_count = db.execute("SELECT COUNT(*) AS c FROM test_cases" + where, params).fetchone()["c"]
    recent_failures = db.execute(
        "SELECT c.*, r.name AS run_name, r.project AS project FROM cases c JOIN runs r ON c.run_id = r.id "
        "WHERE c.status IN ('failed','error')" + (" AND r.project = ?" if project else "") +
        " ORDER BY c.id DESC LIMIT 10", params
    ).fetchall()
    pass_rate = round(agg["passed"] / agg["total"] * 100, 1) if agg["total"] else 0
    projects = [r["project"] for r in db.execute(
        "SELECT DISTINCT project FROM runs WHERE project IS NOT NULL AND project != '' ORDER BY project"
    ).fetchall()]
    return render_template("index.html", total_runs=total_runs, agg=agg,
                           pass_rate=pass_rate, recent=recent, trends=trends,
                           manual_count=manual_count, recent_failures=recent_failures,
                           projects=projects, project=project)


@app.route("/runs")
def runs():
    db = get_db()
    project = request.args.get("project", "").strip()
    if project:
        rows = db.execute("SELECT * FROM runs WHERE project = ? ORDER BY id DESC", (project,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
    projects = [r["project"] for r in db.execute(
        "SELECT DISTINCT project FROM runs WHERE project IS NOT NULL AND project != '' ORDER BY project"
    ).fetchall()]
    return render_template("runs.html", runs=rows, projects=projects, project=project)


@app.route("/runs/<int:run_id>")
def run_detail(run_id):
    db = get_db()
    run = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        flash("运行记录不存在", "error")
        return redirect(url_for("runs"))
    cases = db.execute(
        "SELECT * FROM cases WHERE run_id = ? ORDER BY status, name", (run_id,)
    ).fetchall()
    attachments = db.execute(
        "SELECT * FROM attachments WHERE run_id = ? ORDER BY id", (run_id,)
    ).fetchall()
    attachments_by_case = {}
    run_attachments = []
    attachment_content = {}
    for a in attachments:
        if a["case_id"] is not None:
            attachments_by_case.setdefault(a["case_id"], []).append(a)
        else:
            run_attachments.append(a)
        if a["kind"] in ("log", "text"):
            attachment_content[a["id"]] = read_text_attachment(a["stored_name"])
    return render_template("run_detail.html", run=run, cases=cases,
                           attachments_by_case=attachments_by_case,
                           run_attachments=run_attachments,
                           attachment_content=attachment_content)


@app.route("/runs/<int:run_id>/delete", methods=["POST"])
def delete_run(run_id):
    db = get_db()
    run = db.execute("SELECT name FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        flash("运行记录不存在", "error")
    else:
        db.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        db.commit()
        flash("已删除运行记录：" + run["name"], "ok")
    return redirect(url_for("runs"))


@app.route("/cases")
def cases():
    db = get_db()
    status = request.args.get("status", "")
    q = request.args.get("q", "")
    sql = ("SELECT c.*, r.name AS run_name FROM cases c "
           "JOIN runs r ON c.run_id = r.id WHERE 1=1")
    params = []
    if status:
        sql += " AND c.status = ?"
        params.append(status)
    if q:
        sql += " AND (c.name LIKE ? OR c.classname LIKE ? OR c.file LIKE ?)"
        like = "%" + q + "%"
        params.extend([like, like, like])
    sql += " ORDER BY c.id DESC LIMIT 500"
    rows = db.execute(sql, params).fetchall()
    return render_template("cases.html", cases=rows, status=status, q=q)


@app.route("/import", methods=["GET", "POST"])
def import_page():
    if request.method == "POST":
        uploaded = request.files.get("report")
        run_name = request.form.get("name", "").strip() or "report"
        project = request.form.get("project", "").strip() or "默认项目"
        if uploaded and uploaded.filename:
            xml_bytes = uploaded.read()
        else:
            flash("请选择一个 JUnit XML 文件", "error")
            return redirect(url_for("import_page"))
        try:
            run, case_list = parse_junit(xml_bytes, run_name)
            run["project"] = project
        except ET.ParseError as exc:
            flash("XML 解析失败：" + str(exc), "error")
            return redirect(url_for("import_page"))
        run_id = import_run(run, case_list)
        evaluate_alerts(run_id)
        flash("导入成功：共 %d 条用例" % run["total"], "ok")
        return redirect(url_for("run_detail", run_id=run_id))
    return render_template("import.html")


@app.route("/library")
def library():
    db = get_db()
    q = request.args.get("q", "")
    module = request.args.get("module", "")
    priority = request.args.get("priority", "")
    project = request.args.get("project", "").strip()
    sql = "SELECT * FROM test_cases WHERE 1=1"
    params = []
    if q:
        sql += " AND (title LIKE ? OR module LIKE ?)"
        like = "%" + q + "%"
        params.extend([like, like])
    if module:
        sql += " AND module = ?"
        params.append(module)
    if priority:
        sql += " AND priority = ?"
        params.append(priority)
    if project:
        sql += " AND project = ?"
        params.append(project)
    sql += " ORDER BY id DESC"
    rows = db.execute(sql, params).fetchall()
    modules = [r["module"] for r in db.execute(
        "SELECT DISTINCT module FROM test_cases WHERE module IS NOT NULL AND module != '' ORDER BY module"
    ).fetchall()]
    projects = [r["project"] for r in db.execute(
        "SELECT DISTINCT project FROM test_cases WHERE project IS NOT NULL AND project != '' ORDER BY project"
    ).fetchall()]
    coverage = coverage_stats(db, project)
    status_by_key = automation_status(db, rows)
    return render_template("library.html", cases=rows, q=q, module=module,
                           priority=priority, project=project, modules=modules,
                           projects=projects, coverage=coverage,
                           status_by_key=status_by_key)


@app.route("/library/new", methods=["GET", "POST"])
def library_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("标题不能为空", "error")
            return redirect(url_for("library_new"))
        db = get_db()
        db.execute(
            "INSERT INTO test_cases(title, module, priority, precondition, steps, expected, project, automation_id, tags, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (title,
             request.form.get("module", "").strip(),
             request.form.get("priority", "P2").strip(),
             request.form.get("precondition", "").strip(),
             request.form.get("steps", "").strip(),
             request.form.get("expected", "").strip(),
             request.form.get("project", "").strip() or "默认项目",
             request.form.get("automation_id", "").strip(),
             request.form.get("tags", "").strip(),
             now_iso()),
        )
        db.commit()
        flash("用例已创建", "ok")
        return redirect(url_for("library"))
    return render_template("case_form.html", case=None)


@app.route("/library/<int:case_id>/edit", methods=["GET", "POST"])
def library_edit(case_id):
    db = get_db()
    case = db.execute("SELECT * FROM test_cases WHERE id = ?", (case_id,)).fetchone()
    if case is None:
        flash("用例不存在", "error")
        return redirect(url_for("library"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("标题不能为空", "error")
            return redirect(url_for("library_edit", case_id=case_id))
        db.execute(
            "UPDATE test_cases SET title=?, module=?, priority=?, precondition=?, steps=?, expected=?, project=?, automation_id=?, tags=? "
            "WHERE id=?", (
                title,
                request.form.get("module", "").strip(),
                request.form.get("priority", "P2").strip(),
                request.form.get("precondition", "").strip(),
                request.form.get("steps", "").strip(),
                request.form.get("expected", "").strip(),
                request.form.get("project", "").strip() or "默认项目",
                request.form.get("automation_id", "").strip(),
                request.form.get("tags", "").strip(),
                case_id,
            ),
        )
        db.commit()
        flash("用例已更新", "ok")
        return redirect(url_for("library"))
    return render_template("case_form.html", case=case)


@app.route("/library/<int:case_id>/delete", methods=["POST"])
def library_delete(case_id):
    db = get_db()
    db.execute("DELETE FROM test_cases WHERE id = ?", (case_id,))
    db.commit()
    flash("用例已删除", "ok")
    return redirect(url_for("library"))


@app.route("/api/import", methods=["POST"])
def api_import():
    if not api_token_ok():
        return jsonify({"error": "unauthorized"}), 401
    db = get_db()
    run_name = request.form.get("name", "").strip() or "report"
    project = request.form.get("project", "").strip() or "默认项目"
    uploaded = request.files.get("file") or request.files.get("report")
    if uploaded and uploaded.filename:
        xml_bytes = uploaded.read()
    elif request.form.get("xml"):
        xml_bytes = request.form["xml"].encode("utf-8")
    elif request.data:
        xml_bytes = request.data
    else:
        return jsonify({"error": "missing file or xml"}), 400
    try:
        run, case_list = parse_junit(xml_bytes, run_name)
        run["project"] = project
    except ET.ParseError as exc:
        return jsonify({"error": "xml parse failed: " + str(exc)}), 400
    run_id = import_run(run, case_list)
    alerts = evaluate_alerts(run_id)
    return jsonify({"run_id": run_id, "name": run_name, "project": project,
                    "total": run["total"], "passed": run["passed"],
                    "failed": run["failed"], "errors": run["errors"],
                    "skipped": run["skipped"], "alerts": alerts})


@app.route("/api/runs")
def api_runs():
    db = get_db()
    project = request.args.get("project", "").strip()
    if project:
        rows = db.execute("SELECT * FROM runs WHERE project = ? ORDER BY id DESC LIMIT 100", (project,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/runs/<int:run_id>")
def api_run_detail(run_id):
    db = get_db()
    run = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        return jsonify({"error": "not found"}), 404
    cases = db.execute("SELECT * FROM cases WHERE run_id = ?", (run_id,)).fetchall()
    return jsonify({"run": dict(run), "cases": [dict(c) for c in cases]})


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/runs/<int:run_id>/attachments", methods=["POST"])
def upload_run_attachment(run_id):
    db = get_db()
    run = db.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        flash("运行记录不存在", "error")
        return redirect(url_for("runs"))
    case_id = request.form.get("case_id", "").strip()
    case_id = int(case_id) if case_id.isdigit() else None
    files = request.files.getlist("file")
    if not files or all(not f.filename for f in files):
        flash("请选择要上传的文件", "error")
        return redirect(url_for("run_detail", run_id=run_id))
    count = 0
    for f in files:
        if not f.filename:
            continue
        try:
            save_attachment(f, run_id=run_id, case_id=case_id)
            count += 1
        except ValueError as exc:
            flash(str(exc), "error")
    if count:
        flash("已上传 %d 个证据文件" % count, "ok")
    return redirect(url_for("run_detail", run_id=run_id))


@app.route("/api/attachments", methods=["POST"])
def api_attachments():
    if not api_token_ok():
        return jsonify({"error": "unauthorized"}), 401
    db = get_db()
    run_id = request.form.get("run_id", "").strip()
    case_id = request.form.get("case_id", "").strip()
    run_id = int(run_id) if run_id.isdigit() else None
    case_id = int(case_id) if case_id.isdigit() else None
    if run_id is None and case_id is None:
        return jsonify({"error": "run_id or case_id required"}), 400
    if run_id is not None:
        run = db.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            return jsonify({"error": "run not found"}), 404
    files = request.files.getlist("file")
    if not files or all(not f.filename for f in files):
        return jsonify({"error": "missing file"}), 400
    saved = []
    for f in files:
        if not f.filename:
            continue
        try:
            stored = save_attachment(f, run_id=run_id, case_id=case_id)
            saved.append({"filename": f.filename, "stored_name": stored,
                          "kind": attachment_kind(f.filename)})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    return jsonify({"saved": saved, "run_id": run_id, "case_id": case_id})


@app.route("/compare")
def compare():
    db = get_db()
    projects = [r["project"] for r in db.execute(
        "SELECT DISTINCT project FROM runs WHERE project IS NOT NULL AND project != '' ORDER BY project"
    ).fetchall()]
    base_id = request.args.get("base", type=int)
    target_id = request.args.get("target", type=int)
    runs = db.execute("SELECT id, name, project, imported_at FROM runs ORDER BY id DESC").fetchall()

    if base_id is None or target_id is None:
        return render_template("compare.html", runs=runs, projects=projects,
                               base_id=base_id, target_id=target_id, comparison=None)

    base = db.execute("SELECT * FROM runs WHERE id = ?", (base_id,)).fetchone()
    target = db.execute("SELECT * FROM runs WHERE id = ?", (target_id,)).fetchone()
    if base is None or target is None:
        flash("运行记录不存在", "error")
        return redirect(url_for("compare"))

    def case_key(c):
        return ((c["classname"] or "") + "::" + (c["name"] or ""))

    base_cases = db.execute("SELECT * FROM cases WHERE run_id = ?", (base_id,)).fetchall()
    target_cases = db.execute("SELECT * FROM cases WHERE run_id = ?", (target_id,)).fetchall()
    base_map = {case_key(c): c for c in base_cases}
    target_map = {case_key(c): c for c in target_cases}

    BAD = ("failed", "error")
    rows = []
    for key, tc in target_map.items():
        bc = base_map.get(key)
        if bc is None:
            if tc["status"] in BAD:
                change = "new_failure"
            elif tc["status"] == "skipped":
                change = "new_skip"
            else:
                change = "new_pass"
            rows.append({"key": key, "name": tc["name"], "classname": tc["classname"],
                         "base_status": None, "target_status": tc["status"],
                         "change": change, "base_id": None, "target_id": tc["id"],
                         "target_msg": tc["message"] or ""})
            continue
        b, t = bc["status"], tc["status"]
        if b in BAD and t not in BAD:
            change = "fixed" if t == "passed" else "still_skip"
        elif b not in BAD and t in BAD:
            change = "new_failure"
        elif b in BAD and t in BAD:
            change = "still_failing"
        elif b == t:
            change = "unchanged"
        else:
            change = "changed"
        rows.append({"key": key, "name": tc["name"], "classname": tc["classname"],
                     "base_status": b, "target_status": t,
                     "change": change, "base_id": bc["id"], "target_id": tc["id"],
                     "target_msg": tc["message"] or ""})
    for key, bc in base_map.items():
        if key not in target_map:
            rows.append({"key": key, "name": bc["name"], "classname": bc["classname"],
                         "base_status": bc["status"], "target_status": None,
                         "change": "removed", "base_id": bc["id"], "target_id": None,
                         "target_msg": ""})

    order = {"new_failure": 0, "still_failing": 1, "fixed": 2, "still_skip": 3,
             "removed": 4, "new_skip": 5, "new_pass": 6, "changed": 7, "unchanged": 8}
    rows.sort(key=lambda r: (order.get(r["change"], 9), r["classname"], r["name"]))

    counts = {}
    for r in rows:
        counts[r["change"]] = counts.get(r["change"], 0) + 1

    comparison = {"base": dict(base), "target": dict(target), "rows": rows, "counts": counts}
    return render_template("compare.html", runs=runs, projects=projects,
                           base_id=base_id, target_id=target_id, comparison=comparison)


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
