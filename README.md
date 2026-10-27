# 测试报告与用例管理平台

一个极简但完整的测试开发（测开）项目：用 Flask + SQLite 统一收集多个项目的测试报告，提供 Web 页面和 JSON API，同时支持手动维护测试用例库。

## 核心理念

平台不关心你测的是什么项目，只认一种统一格式：**JUnit XML**。任何项目只要把测试结果转成 JUnit XML，再推到平台，就会自动归档到对应项目下。

## 功能

- 上传 / 自动上报 JUnit XML 报告，自动解析并入库
- 多项目维度：按项目查看仪表盘、运行记录、用例库
- 仪表盘：累计用例、通过率、通过率趋势、最近失败用例速览
- 运行记录：总数 / 通过 / 失败 / 错误 / 跳过 / 通过率 / 耗时，支持删除
- 用例列表：按状态筛选、按名称 / 类名 / 文件搜索
- 用例库：手动新建 / 编辑 / 删除测试用例，按项目、模块与优先级管理
- 单次运行详情：逐条用例状态与失败信息
- 失败取证：为失败用例或整次运行上传截图 / 日志，运行详情页直接查看“为什么挂”
- 运行对比（回归）：两次运行对比，自动归类新增失败 / 仍失败 / 已修复 / 已移除等变化
- 质量分析：自动检测 Flaky 用例（近 N 次运行时好时坏）并做失败根因聚类，把失败按签名归并成可读的根因
- 告警通知：通过率低于阈值 / 新增失败数达标 / Flaky 数超限时自动推 Webhook（钉钉 / 飞书 / Server 酱），并记录发送日志
- 自动化覆盖率：手工用例通过 `automation_id` 关联到 JUnit 的 `classname::name`，统计「已关联 / 已执行覆盖 / 覆盖率」
- 质量报表：通过率 / 执行耗时趋势图（内联 SVG）、失败根因 Top10、运行明细，并支持导出 CSV
- 定时回归：GitHub Actions 每天定时跑 `demo_tests` 并自动上报；`workflow_dispatch` 可手动触发一次演示失败
- JSON API：`/api/runs`、`/api/runs/<id>`、`/api/import`、`/api/attachments`、`/api/analysis`、`/api/alerts`

## 技术栈

- Flask（Web 框架）
- SQLite（存储，标准库 sqlite3，零配置）
- Jinja2（服务端模板）
- Python 标准库 `xml.etree.ElementTree`（解析 / 生成 JUnit XML）

## 快速开始

```bash
pip install -r requirements.txt
python app.py
```

浏览器打开 http://127.0.0.1:5000

## 接入一个 pytest 项目（统一入口）

在任意 pytest 项目里生成报告：

```bash
pytest --junitxml=report.xml
```

然后三种方式任选其一上报：

```bash
# 1. 页面导入：打开「导入报告」，选择项目并上传 report.xml

# 2. curl 自动上报（推荐，可写进 CI）
curl -F "project=model" -F "name=backend-regression" -F "file=@report.xml" http://127.0.0.1:5000/api/import

# 3. 直接 POST XML 文本
curl -X POST -F "project=blaster" -F "name=ue-smoke" -F "xml=$(cat report.xml)" http://127.0.0.1:5000/api/import
```

## 接入 UE 自动化测试

UE 自动化测试框架会把结果写到 `Saved/AutomationReports/index.json`，用 `ue_to_junit.py` 转成 JUnit XML 再上报。

一键跑完整流程（运行 UE 测试 -> 转换 -> 上报平台）：

```bat
run_ue_tests_and_report.bat Blaster blaster ue-automation
```

也可以拆开手动执行：

```bash
# 只转换，生成 ue_report.xml
python ue_to_junit.py "D:\ueproject\Blaster\Blaster\Saved\AutomationReports\index.json" -o ue_report.xml

# 转换后直接推送到平台
python ue_to_junit.py "D:\ueproject\Blaster\Blaster\Saved\AutomationReports\index.json" --project blaster --name ue-automation --push
```

转换规则：
- `state` 映射：`Success` / `SuccessWithWarnings` → 通过，`Fail` → 失败，`NotRun` / `Skipped` / `InProcess` → 跳过
- `fullTestPath` 作为用例名，`entries` 里的 `Error` / `Warning` 作为失败信息
- 失败取证：加 `--evidence` 传入日志 / 截图，会自动关联到第一个失败用例（没有失败则作为运行级证据）：
  `python ue_to_junit.py index.json --project blaster --push --evidence D:\ueproject\Blaster\Blaster\Saved\Logs\Blaster.log`

## API

```bash
curl http://127.0.0.1:5000/api/runs
curl "http://127.0.0.1:5000/api/runs?project=model"
curl http://127.0.0.1:5000/api/runs/1

# 给某次运行 / 某个失败用例上传证据（截图或日志）
curl -F "run_id=12" -F "case_id=340" -F "file=@screenshot.png" http://127.0.0.1:5000/api/attachments
```

## 安全 / 鉴权

本地开发不设置 token，写入接口保持开放，方便快速联调。公网部署前必须设置：

```bash
# Windows PowerShell
$env:TEST_PLATFORM_TOKEN='改成你自己的随机串'
python run.py
```

设置后，`POST /api/import` 与 `POST /api/attachments` 会强制校验，请求头二选一：

- `Authorization: Bearer <token>`
- `X-API-Key: <token>`

```bash
curl -H "Authorization: Bearer $TEST_PLATFORM_TOKEN" \
  -F "project=model" -F "name=backend-ci" -F "file=@report.xml" \
  http://你的域名/api/import
```

GitHub Actions 里对应配置两个 Secrets：

- `TEST_PLATFORM_URL`：平台公网地址
- `TEST_PLATFORM_TOKEN`：与平台端相同的 token

脚本 `scripts/report_to_platform.py`（在后端项目）会自动读取这两个环境变量。

公网部署与 push 自动上报的完整步骤见 [DEPLOY.md](DEPLOY.md)。


## 运行平台自身测试

```bash
pip install -r requirements.txt pytest
python -m pytest tests
```

`tests/` 覆盖：JUnit 解析、Flaky 检测、失败聚类、覆盖率统计、告警触发与失败落日志、`/api/import` 鉴权。全部用例用临时 SQLite 库，不碰线上 `report.db`。

## 定时回归（GitHub Actions）

`.github/workflows/demo-regression.yml` 里有两个 job：`unit` 跑平台自身 `tests/`，`demo` 每天 UTC 17:00（北京时间次日 01:00）跑一遍 `demo_tests`，生成 JUnit XML 后用 `scripts/report_demo_to_platform.py` 上报到平台。

在 test-platform 仓库配置两个 Secrets：

- `TEST_PLATFORM_URL`：平台公网地址（不带结尾斜杠）
- `TEST_PLATFORM_TOKEN`：与 Railway 端一致的 token

没配置 Secrets 时脚本会打印“跳过上报”并正常结束，不影响 CI。手动触发时把 `force_fail` 设为 `1`，会制造一条失败用例，用于验证告警与失败取证。

## 数据模型

- `runs`：一次测试运行（项目、名称、时间、总数、通过、失败、错误、跳过、耗时）
- `cases`：某次运行里的单条用例（状态、失败信息、文件位置），外键关联 `runs`
- `test_cases`：手动维护的用例库（项目、标题、模块、优先级、前置条件、步骤、预期结果）
- `attachments`：失败取证附件（类型、原始文件名、磁盘文件名），可关联 `runs` 或 `cases`，外键级联删除
- `alert_rules` / `alert_logs`：告警规则（项目、指标、阈值、Webhook）与发送日志

## 目录结构

```
app.py                        Flask 应用与路由、XML 解析、入库逻辑、用例库 CRUD
db.py                         SQLite 建表语句
ue_to_junit.py                UE 自动化报告(index.json) -> JUnit XML 转换器（支持证据上报）
run_ue_tests_and_report.bat   一键跑 UE 测试、转换、上报，并自动附带最新日志作为证据
run.py                        本地开发启动入口（读 PORT 环境变量）
wsgi.py                       gunicorn 生产入口（部署时先 init_db 再暴露 app）
requirements-prod.txt         云端依赖（Flask + gunicorn）
Procfile / railway.json       Render / Railway 部署配置
DEPLOY.md                     公网部署与 CI 上报闭环步骤
uploads/                      证据文件存储目录（不入库，不入 git）
templates/                    Jinja2 页面模板（含 compare.html 运行对比）
static/         CSS
requirements.txt
```

## 设计要点（面试可讲）

- 统一入口：平台只认 JUnit XML 标准格式，新项目接入零改动
- 报告解析独立成 `parse_junit()`，兼容 `testsuites` / `testsuite` 两种根节点
- UE 适配层独立成 `ue_to_junit.py`，平台核心不依赖任何游戏框架
- 用例按 `failure` / `error` / `skipped` 子元素判断状态，而非只看 exit code
- 数据模型拆成 `runs`（一次运行）与 `cases`（单条用例）两张表，外键级联删除
- 用例库与运行报告分离：手工设计的用例存 `test_cases`，执行结果存 `cases`
- `init_db()` 用 `PRAGMA table_info` + `ALTER TABLE` 做轻量迁移，老数据库升级不丢数据
- Web 页面与 JSON API 共用同一套数据库查询，体现前后端分离的思路
- 删除运行使用 POST + 前端确认，避免误删，同时依赖外键 `ON DELETE CASCADE` 清理关联用例
- 失败取证：附件统一落到 `uploads/`，按扩展名自动识别 `image` / `log` / `text`，日志直接内联展示，截图内联预览
- 运行对比：以 `classname::name` 作为用例主键匹配两侧用例，按“新增失败 > 仍失败 > 已修复 > 已移除”排序，回归结论一眼可见
- 证据上报做成通用 API `/api/attachments`，UE 转换器与 pytest 脚本都能复用，平台核心不绑定具体工具
- 质量分析：Flaky 检测按 `classname::name` 聚合最近 N 次运行的通过/失败交替；失败聚类把失败信息做归一化签名（数字 / IP / 路径 / UUID / 引号串 → 占位符），同一根因自动合并
