# 部署到 Railway（面试演示级）

目标：把测试平台挂到公网，让 GitHub Actions 在 push 后自动把测试结果上报到平台，形成完整闭环。

## 一、把平台推到 GitHub

在 GitHub 新建一个仓库（建议私有），把 `test-platform` 目录推上去：

```powershell
cd D:\code	est-platform
git init
git add .
git commit -m "test platform"
git branch -M main
git remote add origin https://github.com/<你的用户名>/test-platform.git
git push -u origin main
```

推送前确认 `.gitignore` 已忽略 `report.db`、`uploads/`、`ue_report.xml`（本地数据库和证据不上传）。

## 二、在 Railway 部署

1. 打开 https://railway.com ，用 GitHub 账号登录。
2. `New Project` → `Deploy from GitHub repo` → 选择 `test-platform` 仓库。
3. Railway 会读取根目录的 `railway.json`，自动执行：
   - `pip install -r requirements-prod.txt`（安装 Flask + gunicorn）
   - `gunicorn wsgi:application --bind 0.0.0.0:$PORT`（生产 WSGI 服务器启动）
4. 在 `Variables` 里新增一个变量：
   - `TEST_PLATFORM_TOKEN` = 你自己生成的一个随机串（比如 `openssl rand -hex 24`，或随便一串长密码）
5. 部署完成后，Railway 会给你一个公网域名，形如：
   - `https://<项目名>.up.railway.app`
6. 浏览器打开这个域名，能看到仪表盘即成功。

## 三、后端仓库配置 GitHub Secrets

在后端项目 `model_framework` 的 GitHub 仓库里：

1. `Settings` → `Secrets and variables` → `Actions` → `New repository secret`。
2. 添加两个 Secret：
   - `TEST_PLATFORM_URL` = 上面的 Railway 域名（不带结尾斜杠）
   - `TEST_PLATFORM_TOKEN` = 与 Railway 里设置的 token 完全一致

之后每次 push 后端代码，`backend-tests.yml` 会：

1. 构建服务并跑三层测试，生成 JUnit XML。
2. 调用 `scripts/report_to_platform.py` 合并报告。
3. 带 `Authorization: Bearer <token>` 上报到 Railway 上的平台。
4. 平台网页即时显示本次运行、失败取证与回归对比。

如果 Secrets 没配，`report_to_platform.py` 会自动跳过上报，不影响 CI 结果。

## 四、验证闭环

```powershell
cd D:\code\model
git add .
git commit -m "trigger ci report"
git push
```

打开 GitHub 的 `Actions` 页面看工作流，结束后再打开平台域名，应能看到一条新的 `model` 运行记录。

## 注意事项（演示级）

- Railway 免费/试用容器的磁盘是临时的，**重新部署或重启后 `report.db` 和 `uploads/` 会被清空**。演示级没问题，需要长期保留请改用 Railway 的 Postgres 插件或付费卷。
- 公网部署必须设置 `TEST_PLATFORM_TOKEN`，否则任何知道域名的人都能往平台塞数据。
- 平台读接口（`/api/runs`、网页）目前公开，演示足够；如需保密可再加登录鉴权。
