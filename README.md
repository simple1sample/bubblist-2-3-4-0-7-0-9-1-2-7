# 鱼鱼日程-日程提醒系统（Flask + Vue）

本项目按新要求实现：
- 前端：HTML5、CSS3、JavaScript、Vue（CDN）
- 后端：Python + Flask
- 数据库：SQLite
- API：REST
- 本地 AI：Ollama（可选）

## 技术栈

- 前端：`Vue 3 CDN + 原生 HTML/CSS/JS`
- 后端：`Flask`
- 数据库：`SQLite`
- API：`Flask REST API`
- AI 增强：本地 `Ollama`（`/api/ai/suggest`，失败可降级）
- 图表：`Chart.js`（CDN）
- 会话：`Flask session`（Cookie）
- 提醒：可选「页内置顶弹窗 / 浏览器通知 / 本页闹钟音」，确认后 `ACK` 写入数据库，避免重复骚扰

## 核心功能

- 用户注册、登录、退出（密码 `werkzeug` 哈希）
- 四象限日程（Q1/Q2/Q3/Q4）分类展示（任务按用户隔离）
- 任务增删改查、完成状态切换（记录 `completed_at` 供统计）
- 截止时间与提醒时间
- 到点提醒（15 秒轮询 → 用户确认后 `POST /reminders/ack`）
- 本周每日完成数 + 近 N 周每周完成数统计图
- 本地 Ollama 日程建议（非核心，需登录）

## API 列表

Base URL: `http://localhost:5000/api`

- `GET /health`
- `POST /auth/register`、`POST /auth/login`、`POST /auth/logout`
- `GET /auth/me`、`PATCH /auth/me`（`reminder_mode`: `desktop_modal` | `browser` | `local_alarm`）
- `GET /tasks`、`POST /tasks`、`PUT /tasks/<id>`、`PATCH /tasks/<id>/toggle`、`DELETE /tasks/<id>`
- `GET /reminders/due`（不自动消标，需客户端确认）
- `POST /reminders/ack`（body: `{"ids":[1,2]}`）
- `GET /stats/weekly?weeks=8`
- `GET /stats/overview`（饼图数据：四象限数量、本周按日完成）
- `GET /pomodoro/logs`、`POST /pomodoro/logs`
- `POST /ai/suggest`（优先 Ollama，失败返回离线备用建议，仍 200）
- `POST /qa/ask`（优先 Ollama，失败走本地规则）

## 运行步骤

```bash
cd flask_app
pip install -r requirements.txt
python app.py
```

启动后访问：`http://localhost:5000`

生产环境请设置强随机 `FLASK_SECRET_KEY`。

## Ollama 使用

先在本机启动 Ollama 服务（默认 `11434` 端口），并确保模型可用。
可通过环境变量调整：

```bash
set OLLAMA_URL=http://localhost:11434/api/generate
set OLLAMA_MODEL=qwen2.5:3b
```

## Skill（项目内）

已创建项目级 skill：
- `.cursor/skills/natural-product-scheduler/SKILL.md`

用于后续按你的要求继续生成"无 AI 味、产品化强"的迭代改造。
