# DRP MVP

仿冒网站自动化处置 Bot 的本地 MVP。

## 当前能力
- 中文 Web GUI
- 案例录入与截图存储
- RDAP-first 责任商识别
- 渠道配置驱动的处置计划生成
- 中文/英文模板渲染
- Email / Playwright 执行器 MVP 模拟
- OpenClaw 友好的 `/api/tools/*` 接口

## 启动

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
```

打开：

- http://127.0.0.1:8000
