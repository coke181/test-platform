# 测试报告与用例管理平台

一个极简但完整的测试开发（测开）项目：用 Flask + SQLite 把 pytest 的 JUnit XML 报告导入数据库，提供 Web 页面和 JSON API，展示运行记录、用例列表与统计仪表盘。

## 功能

- 上传 pytest JUnit XML 报告，自动解析并入库
- 仪表盘：累计用例、通过率、最近运行
- 运行记录：每次测试的总数 / 通过 / 失败 / 错误 / 跳过 / 耗时
- 用例列表：按状态筛选、按名称 / 类名 / 文件搜索
- 单次运行详情：逐条用例状态与失败信息
- JSON API：`/api/runs`、`/api/runs/<id>`，供其他工具调用

## 技术栈

- Flask（Web 框架）
- SQLite（存储，标准库 sqlite3，零配置）
- Jinja2（服务端模板）
- Python 标准库 `xml.etree.ElementTree`（解析 JUnit XML）

## 快速开始

```bash
pip install -r requirements.txt
python app.py
```

浏览器打开 http://127.0.0.1:5000

## 生成并导入报告

先在任意 pytest 项目里生成 JUnit XML：

```bash
pytest --junitxml=report.xml
```

然后在页面「导入报告」上传 `report.xml`，或调用 API 导入（见下）。

## API

```bash
curl http://127.0.0.1:5000/api/runs
curl http://127.0.0.1:5000/api/runs/1
```

## 目录结构

```
app.py          Flask 应用与路由、XML 解析、入库逻辑
db.py           SQLite 建表语句
templates/      Jinja2 页面模板
static/         CSS
requirements.txt
```

## 设计要点（面试可讲）

- 报告解析独立成 `parse_junit()`，兼容 `testsuites` / `testsuite` 两种根节点
- 用例按 `failure` / `error` / `skipped` 子元素判断状态，而非只看 exit code
- 数据模型拆成 `runs`（一次运行）与 `cases`（单条用例）两张表，外键级联删除
- Web 页面与 JSON API 共用同一套数据库查询，体现前后端分离的思路
- 可扩展点：接入趋势图、告警、定时执行、多项目维度
