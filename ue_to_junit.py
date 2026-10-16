# -*- coding: utf-8 -*-
"""UE 自动化测试报告(index.json) -> JUnit XML 转换器

UE 的自动化测试框架会把结果写到 Saved/AutomationReports/index.json，
本脚本把其中的 tests 列表转换成 pytest 风格的 JUnit XML，供测试平台导入。

用法：
    python ue_to_junit.py index.json -o ue_report.xml
    python ue_to_junit.py index.json --project blaster --name ue-smoke --push
    python ue_to_junit.py index.json --project blaster --push --evidence D:/path/Blaster.log

参数说明：
    input                UE 生成的 index.json 路径
    -o, --output         输出的 JUnit XML 路径（默认 ue_report.xml）
    --project            上报到平台时的项目名（默认 blaster）
    --name               上报到平台时的运行名（默认 ue-automation）
    --push               转换后直接推送到测试平台 /api/import
    --api                平台地址（默认 http://127.0.0.1:5000）
    --evidence           要一起上报的证据文件（截图/日志），可传多个
"""
import argparse
import json
import mimetypes
import os
import sys
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

STATE_MAP = {
    "Success": "passed",
    "SuccessWithWarnings": "passed",
    "Fail": "failed",
    "Failed": "failed",
    "NotRun": "skipped",
    "Skipped": "skipped",
    "InProcess": "skipped",
}


def load_report(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def build_junit(report):
    suite = ET.Element("testsuite")
    suite.set("name", "UE Automation")
    suite.set("timestamp", report.get("reportCreatedOn", ""))
    suite.set("time", "%.3f" % float(report.get("totalDuration") or 0))

    tests = report.get("tests", [])
    passed = failed = skipped = 0
    for item in tests:
        state = item.get("state", "")
        status = STATE_MAP.get(state, "skipped")
        messages = []
        for entry in item.get("entries", []):
            event = entry.get("event") or {}
            if event.get("type") in ("Error", "Warning"):
                text = event.get("message", "")
                if text:
                    messages.append(text)
        message = ("\n".join(messages))[:8000]

        case = ET.SubElement(suite, "testcase")
        case.set("name", item.get("fullTestPath") or item.get("testDisplayName") or "")
        case.set("classname", item.get("testDisplayName") or "")
        case.set("time", "%.6f" % float(item.get("duration") or 0))

        if status == "failed":
            failed += 1
            node = ET.SubElement(case, "failure")
            node.set("message", message or "UE automation test failed")
            node.text = message
        elif status == "skipped":
            skipped += 1
            node = ET.SubElement(case, "skipped")
            node.set("message", message)
        else:
            passed += 1
            if message:
                out = ET.SubElement(case, "system-out")
                out.text = message

    suite.set("tests", str(len(tests)))
    suite.set("failures", str(failed))
    suite.set("skipped", str(skipped))
    suite.set("errors", "0")
    return suite


def push_report(xml_text, project, name, api, token=""):
    data = urllib.parse.urlencode({
        "project": project,
        "name": name,
        "xml": xml_text,
    }).encode("utf-8")
    headers = {"Authorization": "Bearer " + token} if token else {}
    request = urllib.request.Request(api.rstrip("/") + "/api/import", data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _multipart_body(fields, filename, content, content_type):
    boundary = "----codex" + uuid.uuid4().hex
    body = b""
    for key, value in fields.items():
        body += ("--%s\r\n" % boundary).encode("utf-8")
        body += ("Content-Disposition: form-data; name=\"%s\"\r\n\r\n" % key).encode("utf-8")
        body += ("%s\r\n" % value).encode("utf-8")
    body += ("--%s\r\n" % boundary).encode("utf-8")
    body += ("Content-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n" % filename).encode("utf-8")
    body += ("Content-Type: %s\r\n\r\n" % content_type).encode("utf-8")
    body += content + b"\r\n"
    body += ("--%s--\r\n" % boundary).encode("utf-8")
    return body, boundary


def upload_attachment(api, run_id, case_id, path, token=""):
    filename = os.path.basename(path)
    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        content = f.read()
    fields = {}
    if run_id is not None:
        fields["run_id"] = str(run_id)
    if case_id is not None:
        fields["case_id"] = str(case_id)
    body, boundary = _multipart_body(fields, filename, content, content_type)
    headers = {"Content-Type": "multipart/form-data; boundary=" + boundary}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        api.rstrip("/") + "/api/attachments",
        data=body,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def first_failed_case_id(api, run_id):
    with urllib.request.urlopen(api.rstrip("/") + "/api/runs/%d" % run_id, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    for case in payload.get("cases", []):
        if case.get("status") in ("failed", "error"):
            return case.get("id")
    return None


def main():
    parser = argparse.ArgumentParser(description="UE automation report -> JUnit XML")
    parser.add_argument("input", help="UE 的 index.json 路径")
    parser.add_argument("-o", "--output", default="ue_report.xml")
    parser.add_argument("--project", default="blaster")
    parser.add_argument("--name", default="ue-automation")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--api", default="http://127.0.0.1:5000")
    parser.add_argument("--token", default=os.environ.get("TEST_PLATFORM_TOKEN", ""))
    parser.add_argument("--evidence", nargs="*", default=[], help="要一起上报的证据文件路径")
    args = parser.parse_args()
    args.token = (args.token or "").strip().lstrip("\ufeff")

    report = load_report(args.input)
    suite = build_junit(report)
    tree = ET.ElementTree(suite)
    tree.write(args.output, encoding="utf-8", xml_declaration=True)
    print("已生成 JUnit XML:", args.output)

    if args.push:
        xml_text = ET.tostring(suite, encoding="unicode")
        try:
            result = push_report(xml_text, args.project, args.name, args.api, args.token)
            print("已推送到平台:", result)
            run_id = result.get("run_id")
        except Exception as exc:
            print("[ERROR] 推送到平台失败：", exc)
            print("请先启动平台：cd /d", os.getcwd(), "&& python run.py")
            sys.exit(1)

        if args.evidence:
            try:
                case_id = first_failed_case_id(args.api, run_id)
                for path in args.evidence:
                    if not path or not os.path.isfile(path):
                        print("[WARN] 证据文件不存在，跳过：", path)
                        continue
                    saved = upload_attachment(args.api, run_id, case_id, path, args.token)
                    print("已上传证据:", os.path.basename(path), "->", saved)
            except Exception as exc:
                print("[WARN] 证据上传失败：", exc)


if __name__ == "__main__":
    main()
