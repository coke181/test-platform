# -*- coding: utf-8 -*-
"""把 demo_tests 生成的 JUnit XML 上报到测试平台（供 GitHub Actions 定时回归使用）。"""
import os
import sys
import uuid
from urllib.request import Request, urlopen


def multipart_post(url, token, fields, file_path):
    boundary = "----codex%s" % uuid.uuid4().hex
    body = b""
    for key, value in fields.items():
        body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, key, value)).encode("utf-8")
    filename = os.path.basename(file_path)
    body += ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\nContent-Type: application/xml\r\n\r\n" % (boundary, filename)).encode("utf-8")
    with open(file_path, "rb") as f:
        body += f.read()
    body += ("\r\n--%s--\r\n" % boundary).encode("utf-8")

    req = Request(url, data=body, headers={
        "Content-Type": "multipart/form-data; boundary=%s" % boundary,
        "Authorization": "Bearer %s" % token,
    })
    with urlopen(req, timeout=30) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def main():
    if len(sys.argv) < 2:
        print("usage: python report_demo_to_platform.py <junit.xml>")
        return 2

    xml_path = sys.argv[1]
    if not os.path.exists(xml_path):
        print("junit file not found:", xml_path)
        return 1

    url = (os.environ.get("TEST_PLATFORM_URL") or "").strip().rstrip("/")
    token = (os.environ.get("TEST_PLATFORM_TOKEN") or "").strip()
    if not url or not token:
        print("TEST_PLATFORM_URL / TEST_PLATFORM_TOKEN 未配置，跳过上报")
        return 0

    project = os.environ.get("TEST_PROJECT", "demo").strip()
    run_name = os.environ.get("TEST_RUN_NAME", "daily-regression").strip()
    status, text = multipart_post(url + "/api/import", token, {
        "project": project,
        "name": run_name,
    }, xml_path)
    print("report status:", status)
    print(text[:500])
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())