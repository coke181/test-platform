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
import os
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from flask import Flask, g, jsonify, render_template, request, redirect, url_for, flash

from db import SCHEMA

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "report.db")

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


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


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
        "INSERT INTO runs(name, started_at, total, passed, failed, errors, skipped, duration, imported_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run["name"], run["started_at"], run["total"], run["passed"],
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


@app.route("/")
def index():
    db = get_db()
    total_runs = db.execute("SELECT COUNT(*) AS c FROM runs").fetchone()["c"]
    agg = db.execute(
        "SELECT COALESCE(SUM(total),0) AS total, COALESCE(SUM(passed),0) AS passed, "
        "COALESCE(SUM(failed),0) AS failed, COALESCE(SUM(errors),0) AS errors, "
        "COALESCE(SUM(skipped),0) AS skipped FROM runs"
    ).fetchone()
    recent = db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 5").fetchall()
    trends = db.execute("SELECT id, name, passed, total FROM runs ORDER BY id ASC").fetchall()
    pass_rate = round(agg["passed"] / agg["total"] * 100, 1) if agg["total"] else 0
    return render_template("index.html", total_runs=total_runs, agg=agg,
                           pass_rate=pass_rate, recent=recent, trends=trends)


@app.route("/runs")
def runs():
    db = get_db()
    rows = db.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
    return render_template("runs.html", runs=rows)


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
    return render_template("run_detail.html", run=run, cases=cases)


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
        if uploaded and uploaded.filename:
            xml_bytes = uploaded.read()
        else:
            flash("请选择一个 JUnit XML 文件", "error")
            return redirect(url_for("import_page"))
        try:
            run, case_list = parse_junit(xml_bytes, run_name)
        except ET.ParseError as exc:
            flash("XML 解析失败：" + str(exc), "error")
            return redirect(url_for("import_page"))
        run_id = import_run(run, case_list)
        flash("导入成功：共 %d 条用例" % run["total"], "ok")
        return redirect(url_for("run_detail", run_id=run_id))
    return render_template("import.html")


@app.route("/api/runs")
def api_runs():
    db = get_db()
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


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
