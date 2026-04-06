import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import requests
from flask import Flask, g, jsonify, redirect, render_template, request, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "schedule.db"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-only-change-in-production")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False  # 开发环境下禁用HTTPS
app.config["PREFERRED_URL_SCHEME"] = "http"  # 开发环境下使用HTTP
app.config["SESSION_COOKIE_DOMAIN"] = None  # 不设置域名，使用默认值
app.config["SESSION_COOKIE_PATH"] = "/"  # 会话cookie路径设置为根路径

# 初始化速率限制器
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# HTTPS重定向中间件
@app.before_request
def redirect_to_https():
    if request.headers.get('X-Forwarded-Proto') == 'http':
        url = request.url.replace('http://', 'https://', 1)
        return redirect(url, code=301)


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_db():
    """
    获取数据库连接
    
    Returns:
        sqlite3.Connection: 数据库连接对象
        
    Raises:
        sqlite3.Error: 数据库连接失败时抛出
    """
    if "db" not in g:
        try:
            g.db = sqlite3.connect(DB_PATH)
            g.db.row_factory = sqlite3.Row
            # 启用外键约束
            g.db.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error as e:
            raise sqlite3.Error(f"数据库连接失败: {str(e)}")
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _table_columns(db, table):
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}


def migrate_db():
    db = sqlite3.connect(DB_PATH)
    # 启用外键约束
    db.execute("PRAGMA foreign_keys = ON")
    
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            reminder_mode TEXT NOT NULL DEFAULT 'browser',
            created_at TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            bio TEXT DEFAULT '',
            theme TEXT DEFAULT 'peach',
            time_blocks TEXT DEFAULT ''
        )
        """
    )
    # 添加用户表索引
    try:
        db.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    except sqlite3.OperationalError:
        pass
    
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            is_important INTEGER NOT NULL DEFAULT 0,
            is_urgent INTEGER NOT NULL DEFAULT 0,
            due_at TEXT DEFAULT NULL,
            remind_at TEXT DEFAULT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            reminded INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            user_id INTEGER,
            completed_at TEXT DEFAULT NULL,
            recurrence_type TEXT DEFAULT NULL,
            recurrence_interval INTEGER DEFAULT 1,
            recurrence_end_date TEXT DEFAULT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    cols = _table_columns(db, "tasks")
    if "user_id" not in cols:
        db.execute("ALTER TABLE tasks ADD COLUMN user_id INTEGER")
    if "completed_at" not in cols:
        db.execute("ALTER TABLE tasks ADD COLUMN completed_at TEXT")
    if "recurrence_type" not in cols:
        db.execute("ALTER TABLE tasks ADD COLUMN recurrence_type TEXT DEFAULT NULL")
    if "recurrence_interval" not in cols:
        db.execute("ALTER TABLE tasks ADD COLUMN recurrence_interval INTEGER DEFAULT 1")
    if "recurrence_end_date" not in cols:
        db.execute("ALTER TABLE tasks ADD COLUMN recurrence_end_date TEXT DEFAULT NULL")
    # 添加任务表索引
    try:
        db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_completed ON tasks(completed)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_due_at ON tasks(due_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_remind_at ON tasks(remind_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at)")
    except sqlite3.OperationalError:
        pass
    
    ucols = _table_columns(db, "users")
    if "display_name" not in ucols:
        db.execute("ALTER TABLE users ADD COLUMN display_name TEXT DEFAULT ''")
    if "bio" not in ucols:
        db.execute("ALTER TABLE users ADD COLUMN bio TEXT DEFAULT ''")
    if "theme" not in ucols:
        db.execute("ALTER TABLE users ADD COLUMN theme TEXT DEFAULT 'peach'")
    if "time_blocks" not in ucols:
        db.execute("ALTER TABLE users ADD COLUMN time_blocks TEXT DEFAULT ''")
    
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS pomodoro_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            planned_seconds INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL DEFAULT 'completed',
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    # 添加番茄钟日志表索引
    try:
        db.execute("CREATE INDEX IF NOT EXISTS idx_pomodoro_logs_user_id ON pomodoro_logs(user_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_pomodoro_logs_started_at ON pomodoro_logs(started_at)")
    except sqlite3.OperationalError:
        pass
    
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS plan_ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    # 添加计划创意表索引
    try:
        db.execute("CREATE INDEX IF NOT EXISTS idx_plan_ideas_user_id ON plan_ideas(user_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_plan_ideas_created_at ON plan_ideas(created_at)")
    except sqlite3.OperationalError:
        pass
    
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS plan_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            domain TEXT DEFAULT '',
            project TEXT DEFAULT '',
            role TEXT DEFAULT '',
            priority_rule TEXT DEFAULT '',
            priority_level TEXT DEFAULT '',
            scene TEXT DEFAULT '',
            planned_at TEXT DEFAULT NULL,
            start_time TEXT DEFAULT NULL,
            end_time TEXT DEFAULT NULL,
            time_block TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'planning',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            recurrence_type TEXT DEFAULT NULL,
            recurrence_interval INTEGER DEFAULT 1,
            recurrence_end_date TEXT DEFAULT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    # 检查并添加计划项表的 start_time 和 end_time 字段
    plan_cols = _table_columns(db, "plan_items")
    if "start_time" not in plan_cols:
        db.execute("ALTER TABLE plan_items ADD COLUMN start_time TEXT DEFAULT NULL")
    if "end_time" not in plan_cols:
        db.execute("ALTER TABLE plan_items ADD COLUMN end_time TEXT DEFAULT NULL")
    # 检查并添加计划项表的循环提醒相关字段
    if "recurrence_type" not in plan_cols:
        db.execute("ALTER TABLE plan_items ADD COLUMN recurrence_type TEXT DEFAULT NULL")
    if "recurrence_interval" not in plan_cols:
        db.execute("ALTER TABLE plan_items ADD COLUMN recurrence_interval INTEGER DEFAULT 1")
    if "recurrence_end_date" not in plan_cols:
        db.execute("ALTER TABLE plan_items ADD COLUMN recurrence_end_date TEXT DEFAULT NULL")
    # 添加计划项表索引
    try:
        db.execute("CREATE INDEX IF NOT EXISTS idx_plan_items_user_id ON plan_items(user_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_plan_items_planned_at ON plan_items(planned_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_plan_items_updated_at ON plan_items(updated_at)")
    except sqlite3.OperationalError:
        pass
    
    db.commit()
    db.close()


def task_to_json(row):
    item = dict(row)
    item["is_important"] = bool(item["is_important"])
    item["is_urgent"] = bool(item["is_urgent"])
    item["completed"] = bool(item["completed"])
    item["reminded"] = bool(item["reminded"])
    if item["is_important"] and item["is_urgent"]:
        item["quadrant"] = "Q1"
    elif item["is_important"] and not item["is_urgent"]:
        item["quadrant"] = "Q2"
    elif not item["is_important"] and item["is_urgent"]:
        item["quadrant"] = "Q3"
    else:
        item["quadrant"] = "Q4"
    return item


def require_user_id():
    uid = session.get("user_id")
    if not uid:
        return None
    return int(uid)

# 缓存装饰器，用于缓存统计数据
def cache_stats(func):
    """
    缓存装饰器，用于缓存统计数据
    
    缓存键包含用户ID和当前日期，每天自动更新缓存
    
    Args:
        func: 要缓存的函数
        
    Returns:
        function: 包装后的函数
    """
    cache = {}
    
    def wrapper():
        uid = require_user_id()
        if not uid:
            return func()
        
        # 生成缓存键，包含用户ID和当前日期（每天更新一次）
        today = date.today().isoformat()
        cache_key = f"{uid}:{today}"
        
        if cache_key in cache:
            return cache[cache_key]
        
        result = func()
        cache[cache_key] = result
        return result
    
    # 为包装函数设置与原函数相同的名称，避免Flask路由冲突
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    
    return wrapper


def _offline_suggest(text: str) -> str:
    snippet = (text.strip()[:24] + ("…" if len(text.strip()) > 24 else "")) or "这件事"
    return (
        f"（本地备用建议，未连接 Ollama 时也可用）\n"
        f"• 把「{snippet}」拆成 3 个能在 25 分钟内开动的小步骤，写进任务里。\n"
        "• 今天必须交：勾「重要+紧急」放进 Q1，并设好截止时间。\n"
        "• 不赶但可以沉淀的：只勾「重要」，放 Q2 每天推进一点点。"
    )


@lru_cache(maxsize=128)
def _ollama_generate(prompt: str) -> tuple[str | None, str | None]:
    """
    调用Ollama API生成响应
    
    Args:
        prompt: 提示词
        
    Returns:
        tuple: (生成的响应, 错误信息)
    """
    try:
        # 尝试使用 /api/generate 端点
        response = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=20,
        )
        if response.status_code == 404:
            # 如果 404，尝试使用 /api/chat 端点
            chat_url = OLLAMA_URL.replace('/api/generate', '/api/chat')
            response = requests.post(
                chat_url,
                json={"model": OLLAMA_MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False},
                timeout=20,
            )
            if response.status_code == 404:
                return None, "Ollama 接口 404，请确认服务已启动并使用正确的 API 端点。"
        response.raise_for_status()
        data = response.json()
        # 检查不同端点的响应格式
        if "response" in data:
            return (data.get("response") or "").strip(), None
        elif "message" in data and "content" in data["message"]:
            return (data["message"]["content"] or "").strip(), None
        else:
            return None, "Ollama 响应格式不正确。"
    except requests.exceptions.ConnectionError:
        return None, "无法连接本机 Ollama（请先运行 `ollama serve` 并确认端口 11434）。"
    except Exception as exc:
        return None, str(exc)


def _offline_qa(question: str) -> str:
    q = question.strip()
    low = q.lower()
    if not q:
        return "先输入一句话，我再答你～"
    if "四象限" in q or "象限" in q:
        return (
            "四象限就是把事情按「重要 / 紧急」分成四格：Q1 又急又重要要先做，"
            "Q2 重要不急要规划，Q3 急不重要可委派或压缩，Q4 不急不重要尽量少做。"
        )
    if "番茄" in q or "专注" in q or "focus" in low:
        return "番茄钟一般是专注 25 分钟、休息 5 分钟；你可以在本页「番茄钟」里自己改分钟数和名称。"
    if "提醒" in q:
        return "提醒可以在任务里设「提醒时间」，并在「我的资料」里选浏览器通知、置顶弹窗或闹钟音。"
    if "ollama" in low or "模型" in q:
        return "智能建议和问答会优先走本机 Ollama；没开服务时我会用本地规则回答简单问题。"
    if q in ("你好", "您好", "hi", "hello"):
        return "你好呀～今天排好 Q1 里最重要的一件事就赢了一半。"
    return (
        "我暂时只能回答很基础的问题（四象限、番茄钟、提醒、Ollama 等）。"
        "把问题说具体一点，或先去启动 Ollama 再问～"
    )


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "flask-quadrant-schedule"})


@app.post("/api/auth/register")
def register():
    try:
        payload = request.get_json(silent=True) or {}
        username = (payload.get("username") or "").strip()
        password = payload.get("password") or ""
        
        if not username:
            return jsonify({"message": "用户名不能为空"}), 400
        if len(username) < 2:
            return jsonify({"message": "用户名至少 2 个字符"}), 400
        if len(password) < 6:
            return jsonify({"message": "密码至少 6 位"}), 400

        now = utc_now_iso()
        h = generate_password_hash(password)
        db = get_db()
        try:
            cur = db.execute(
                """
                INSERT INTO users (username, password_hash, reminder_mode, created_at, display_name, bio)
                VALUES (?, ?, 'browser', ?, ?, ?)
                """,
                (username, h, now, username, ""),
            )
            db.commit()
        except sqlite3.IntegrityError:
            return jsonify({"message": "用户名已存在"}), 409

        session["user_id"] = cur.lastrowid
        row = db.execute(
            """
            SELECT id, username, reminder_mode, display_name, bio, theme, time_blocks
            FROM users WHERE id = ?
            """,
            (cur.lastrowid,),
        ).fetchone()
        return jsonify({"user": dict(row)}), 201
    except Exception as e:
        return jsonify({"message": f"注册失败: {str(e)}"}), 500


@app.post("/api/auth/login")
def login():
    try:
        payload = request.get_json(silent=True) or {}
        username = (payload.get("username") or "").strip()
        password = payload.get("password") or ""
        
        if not username or not password:
            return jsonify({"message": "用户名和密码不能为空"}), 400
        
        db = get_db()
        row = db.execute(
            """
            SELECT id, username, password_hash, reminder_mode, display_name, bio, theme, time_blocks
            FROM users WHERE username = ?
            """,
            (username,),
        ).fetchone()
        if not row or not check_password_hash(row["password_hash"], password):
            return jsonify({"message": "用户名或密码错误"}), 401

        session["user_id"] = row["id"]
        return jsonify(
            {
                "user": {
                    "id": row["id"],
                    "username": row["username"],
                    "reminder_mode": row["reminder_mode"],
                    "display_name": row["display_name"] or "",
                    "bio": row["bio"] or "",
                    "theme": row["theme"] or "peach",
                    "time_blocks": row["time_blocks"] or "",
                }
            }
        )
    except Exception as e:
        return jsonify({"message": f"登录失败: {str(e)}"}), 500


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/auth/me")
def me():
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    db = get_db()
    row = db.execute(
        """
        SELECT id, username, reminder_mode, display_name, bio, theme, time_blocks
        FROM users WHERE id = ?
        """,
        (uid,),
    ).fetchone()
    if not row:
        session.clear()
        return jsonify({"message": "未登录"}), 401
    return jsonify({"user": dict(row)})


@app.patch("/api/auth/me")
def update_me():
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    payload = request.get_json(silent=True) or {}
    allowed_modes = {"desktop_modal", "browser", "local_alarm"}
    allowed_themes = {"peach", "mint", "ocean", "sunset"}
    db = get_db()
    did = False
    if "reminder_mode" in payload and (payload.get("reminder_mode") or "").strip():
        mode = payload["reminder_mode"].strip()
        if mode not in allowed_modes:
            return jsonify({"message": "reminder_mode 无效，可选 desktop_modal / browser / local_alarm"}), 400
        db.execute("UPDATE users SET reminder_mode = ? WHERE id = ?", (mode, uid))
        did = True
    if "display_name" in payload:
        dn = (payload.get("display_name") or "").strip()[:64]
        db.execute("UPDATE users SET display_name = ? WHERE id = ?", (dn, uid))
        did = True
    if "bio" in payload:
        bio = (payload.get("bio") or "").strip()[:500]
        db.execute("UPDATE users SET bio = ? WHERE id = ?", (bio, uid))
        did = True
    if "theme" in payload and (payload.get("theme") or "").strip():
        theme = payload["theme"].strip()
        if theme not in allowed_themes:
            return jsonify({"message": "theme 无效，可选 peach / mint / ocean / sunset"}), 400
        db.execute("UPDATE users SET theme = ? WHERE id = ?", (theme, uid))
        did = True
    if "time_blocks" in payload:
        blocks = (payload.get("time_blocks") or "").strip()[:2000]
        db.execute("UPDATE users SET time_blocks = ? WHERE id = ?", (blocks, uid))
        did = True
    if not did:
        return jsonify({"message": "无有效字段"}), 400
    db.commit()
    row = db.execute(
        """
        SELECT id, username, reminder_mode, display_name, bio, theme, time_blocks
        FROM users WHERE id = ?
        """,
        (uid,),
    ).fetchone()
    return jsonify({"user": dict(row)})


@app.get("/api/tasks")
def list_tasks():
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    rows = get_db().execute(
        "SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC",
        (uid,),
    ).fetchall()
    return jsonify([task_to_json(row) for row in rows])


@app.post("/api/tasks")
def create_task():
    try:
        uid = require_user_id()
        if not uid:
            return jsonify({"message": "未登录"}), 401
        
        payload = request.get_json(silent=True) or {}
        title = (payload.get("title") or "").strip()
        if not title:
            return jsonify({"message": "任务标题不能为空"}), 400

        now = utc_now_iso()
        db = get_db()
        cursor = db.execute(
            """
            INSERT INTO tasks (
                title, description, is_important, is_urgent, due_at, remind_at,
                completed, reminded, created_at, updated_at, user_id, completed_at,
                recurrence_type, recurrence_interval, recurrence_end_date
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (
                title,
                payload.get("description", ""),
                int(bool(payload.get("is_important"))),
                int(bool(payload.get("is_urgent"))),
                payload.get("due_at"),
                payload.get("remind_at"),
                now,
                now,
                uid,
                payload.get("recurrence_type"),
                payload.get("recurrence_interval", 1),
                payload.get("recurrence_end_date"),
            ),
        )
        db.commit()
        row = db.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return jsonify(task_to_json(row)), 201
    except Exception as e:
        return jsonify({"message": f"创建任务失败: {str(e)}"}), 500


@app.put("/api/tasks/<int:task_id>")
def update_task(task_id):
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip()
    if not title:
        return jsonify({"message": "title is required"}), 400

    now = utc_now_iso()
    remind_at = payload.get("remind_at")
    reminded = 0 if remind_at else 1
    completed = int(bool(payload.get("completed")))
    db = get_db()
    existing = db.execute(
        "SELECT completed_at FROM tasks WHERE id = ? AND user_id = ?",
        (task_id, uid),
    ).fetchone()
    if not existing:
        return jsonify({"message": "task not found"}), 404
    if completed:
        completed_at = existing["completed_at"] or now
    else:
        completed_at = None
    result = db.execute(
        """
        UPDATE tasks
        SET title = ?, description = ?, is_important = ?, is_urgent = ?, due_at = ?, remind_at = ?,
            completed = ?, reminded = ?, updated_at = ?, completed_at = ?,
            recurrence_type = ?, recurrence_interval = ?, recurrence_end_date = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            title,
            payload.get("description", ""),
            int(bool(payload.get("is_important"))),
            int(bool(payload.get("is_urgent"))),
            payload.get("due_at"),
            remind_at,
            completed,
            reminded,
            now,
            completed_at,
            payload.get("recurrence_type"),
            payload.get("recurrence_interval", 1),
            payload.get("recurrence_end_date"),
            task_id,
            uid,
        ),
    )
    if result.rowcount == 0:
        return jsonify({"message": "task not found"}), 404
    db.commit()
    row = db.execute(
        "SELECT * FROM tasks WHERE id = ? AND user_id = ?", (task_id, uid)
    ).fetchone()
    return jsonify(task_to_json(row))


@app.patch("/api/tasks/<int:task_id>/toggle")
def toggle_task(task_id):
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    db = get_db()
    row = db.execute(
        "SELECT completed FROM tasks WHERE id = ? AND user_id = ?",
        (task_id, uid),
    ).fetchone()
    if not row:
        return jsonify({"message": "task not found"}), 404
    new_completed = 0 if row["completed"] else 1
    now = utc_now_iso()
    completed_at = now if new_completed else None
    db.execute(
        """
        UPDATE tasks
        SET completed = ?, updated_at = ?, completed_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (new_completed, now, completed_at, task_id, uid),
    )
    db.commit()
    row = db.execute(
        "SELECT * FROM tasks WHERE id = ? AND user_id = ?", (task_id, uid)
    ).fetchone()
    return jsonify(task_to_json(row))


@app.delete("/api/tasks/<int:task_id>")
def delete_task(task_id):
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    db = get_db()
    result = db.execute(
        "DELETE FROM tasks WHERE id = ? AND user_id = ?",
        (task_id, uid),
    )
    if result.rowcount == 0:
        return jsonify({"message": "task not found"}), 404
    db.commit()
    return "", 204


@app.get("/api/reminders/due")
def due_reminders():
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    now = utc_now_iso()
    db = get_db()
    rows = db.execute(
        """
        SELECT * FROM tasks
        WHERE user_id = ?
          AND remind_at IS NOT NULL
          AND remind_at <= ?
          AND reminded = 0
          AND completed = 0
        ORDER BY remind_at ASC
        """,
        (uid, now),
    ).fetchall()
    return jsonify([task_to_json(row) for row in rows])


@app.post("/api/reminders/ack")
def ack_reminders():
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    payload = request.get_json(silent=True) or {}
    ids = payload.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return jsonify({"message": "ids required"}), 400
    clean = [int(i) for i in ids if str(i).isdigit()]
    if not clean:
        return jsonify({"message": "invalid ids"}), 400
    db = get_db()
    placeholders = ",".join("?" for _ in clean)
    db.execute(
        f"UPDATE tasks SET reminded = 1 WHERE user_id = ? AND id IN ({placeholders})",
        [uid] + clean,
    )
    db.commit()
    return jsonify({"ok": True, "marked": len(clean)})


# 日期工具函数
def get_week_start_monday(d):
    """获取指定日期所在周的周一"""
    return d - timedelta(days=d.weekday())


def get_day_labels_cn():
    """获取中文星期标签"""
    return ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def parse_local_date(iso_str):
    """解析ISO格式的日期字符串为本地日期"""
    if not iso_str:
        return None
    try:
        s = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().date()
    except ValueError:
        return None


@app.get("/api/stats/overview")
@cache_stats
def stats_overview():
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    db = get_db()
    counts = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}
    for r in db.execute(
        """
        SELECT is_important, is_urgent, COUNT(*) AS c
        FROM tasks WHERE user_id = ?
        GROUP BY is_important, is_urgent
        """,
        (uid,),
    ).fetchall():
        imp, urg, c = bool(r["is_important"]), bool(r["is_urgent"]), int(r["c"])
        if imp and urg:
            counts["Q1"] = c
        elif imp and not urg:
            counts["Q2"] = c
        elif not imp and urg:
            counts["Q3"] = c
        else:
            counts["Q4"] = c
    todo = done = 0
    for r in db.execute(
        "SELECT completed, COUNT(*) AS c FROM tasks WHERE user_id = ? GROUP BY completed",
        (uid,),
    ).fetchall():
        if r["completed"]:
            done = int(r["c"])
        else:
            todo = int(r["c"])
    today = date.today()
    week_start = get_week_start_monday(today)
    week_dates = [week_start + timedelta(days=i) for i in range(7)]
    counts_by_day = {}
    for r in db.execute(
        """
        SELECT completed_at FROM tasks
        WHERE user_id = ? AND completed = 1 AND completed_at IS NOT NULL
        """,
        (uid,),
    ).fetchall():
        d = parse_local_date(r["completed_at"])
        if d:
            counts_by_day[d] = counts_by_day.get(d, 0) + 1
    week_labels = []
    week_values = []
    for i, d in enumerate(week_dates):
        week_labels.append(get_day_labels_cn()[i])
        week_values.append(counts_by_day.get(d, 0))
    return jsonify(
        {
            "quadrant_counts": counts,
            "status": {"todo": todo, "done": done},
            "current_week_pie": {"labels": week_labels, "values": week_values},
        }
    )


@app.get("/api/stats/weekly")
@cache_stats
def weekly_stats():
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401

    today = date.today()
    week_start = get_week_start_monday(today)
    week_dates = [week_start + timedelta(days=i) for i in range(7)]

    db = get_db()
    rows = db.execute(
        """
        SELECT completed_at FROM tasks
        WHERE user_id = ? AND completed = 1 AND completed_at IS NOT NULL
        """,
        (uid,),
    ).fetchall()

    counts_by_day = {}
    for r in rows:
        d = parse_local_date(r["completed_at"])
        if d:
            counts_by_day[d] = counts_by_day.get(d, 0) + 1

    current_week_daily = []
    for i, d in enumerate(week_dates):
        current_week_daily.append(
            {
                "date": d.isoformat(),
                "label": get_day_labels_cn()[i],
                "completed": counts_by_day.get(d, 0),
            }
        )

    num_weeks = max(1, min(int(request.args.get("weeks", 8)), 24))
    recent_weeks = []
    for w in range(num_weeks):
        ws = week_start - timedelta(weeks=w)
        we = ws + timedelta(days=6)
        total = 0
        cur = ws
        while cur <= we:
            total += counts_by_day.get(cur, 0)
            cur += timedelta(days=1)
        recent_weeks.append(
            {
                "week_start": ws.isoformat(),
                "label": f"{ws.month}/{ws.day} 起",
                "completed": total,
            }
        )
    recent_weeks.reverse()

    return jsonify(
        {
            "current_week_daily": current_week_daily,
            "recent_weeks": recent_weeks,
            "timezone_note": "按本机时区解析完成时间",
        }
    )


@app.get("/api/pomodoro/logs")
def pomodoro_logs_list():
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    rows = get_db().execute(
        """
        SELECT id, name, planned_seconds, started_at, ended_at, status
        FROM pomodoro_logs WHERE user_id = ? ORDER BY id DESC LIMIT 40
        """,
        (uid,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/pomodoro/logs")
def pomodoro_log_create():
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "专注番茄").strip()[:120]
    try:
        planned = int(payload.get("planned_seconds") or 1500)
    except (TypeError, ValueError):
        return jsonify({"message": "planned_seconds 无效"}), 400
    planned = max(60, min(planned, 7200))
    status = (payload.get("status") or "completed").strip()
    if status not in {"completed", "cancelled"}:
        status = "completed"
    now = utc_now_iso()
    db = get_db()
    cur = db.execute(
        """
        INSERT INTO pomodoro_logs (user_id, name, planned_seconds, started_at, ended_at, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (uid, name, planned, now, now, status),
    )
    db.commit()
    row = db.execute(
        "SELECT id, name, planned_seconds, started_at, ended_at, status FROM pomodoro_logs WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    return jsonify(dict(row)), 201


@app.get("/api/plan/ideas")
def list_plan_ideas():
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    rows = get_db().execute(
        "SELECT id, title, notes, created_at FROM plan_ideas WHERE user_id = ? ORDER BY id DESC",
        (uid,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/plan/ideas")
def create_plan_idea():
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip()
    if not title:
        return jsonify({"message": "title is required"}), 400
    notes = (payload.get("notes") or "").strip()
    now = utc_now_iso()
    db = get_db()
    cur = db.execute(
        "INSERT INTO plan_ideas (user_id, title, notes, created_at) VALUES (?, ?, ?, ?)",
        (uid, title, notes, now),
    )
    db.commit()
    row = db.execute(
        "SELECT id, title, notes, created_at FROM plan_ideas WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    return jsonify(dict(row)), 201


@app.delete("/api/plan/ideas/<int:idea_id>")
def delete_plan_idea(idea_id):
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    db = get_db()
    res = db.execute("DELETE FROM plan_ideas WHERE id = ? AND user_id = ?", (idea_id, uid))
    if res.rowcount == 0:
        return jsonify({"message": "not found"}), 404
    db.commit()
    return "", 204


@app.get("/api/plan/items")
def list_plan_items():
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    rows = get_db().execute(
        """
        SELECT * FROM plan_items
        WHERE user_id = ? ORDER BY updated_at DESC
        """,
        (uid,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/plan/items")
def create_plan_item():
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip()
    if not title:
        return jsonify({"message": "title is required"}), 400
    now = utc_now_iso()
    db = get_db()
    cur = db.execute(
        """
        INSERT INTO plan_items (
            user_id, title, domain, project, role, priority_rule, priority_level,
            scene, planned_at, start_time, end_time, time_block, notes, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uid,
            title,
            (payload.get("domain") or "").strip(),
            (payload.get("project") or "").strip(),
            (payload.get("role") or "").strip(),
            (payload.get("priority_rule") or "").strip(),
            (payload.get("priority_level") or "").strip(),
            (payload.get("scene") or "").strip(),
            payload.get("planned_at"),
            payload.get("start_time"),
            payload.get("end_time"),
            (payload.get("time_block") or "").strip(),
            (payload.get("notes") or "").strip(),
            (payload.get("status") or "planning").strip() or "planning",
            now,
            now,
        ),
    )
    db.commit()
    row = db.execute("SELECT * FROM plan_items WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@app.put("/api/plan/items/<int:item_id>")
def update_plan_item(item_id):
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip()
    if not title:
        return jsonify({"message": "title is required"}), 400
    now = utc_now_iso()
    db = get_db()
    res = db.execute(
        """
        UPDATE plan_items
        SET title = ?, domain = ?, project = ?, role = ?, priority_rule = ?, priority_level = ?,
            scene = ?, planned_at = ?, start_time = ?, end_time = ?, time_block = ?, notes = ?, status = ?, updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            title,
            (payload.get("domain") or "").strip(),
            (payload.get("project") or "").strip(),
            (payload.get("role") or "").strip(),
            (payload.get("priority_rule") or "").strip(),
            (payload.get("priority_level") or "").strip(),
            (payload.get("scene") or "").strip(),
            payload.get("planned_at"),
            payload.get("start_time"),
            payload.get("end_time"),
            (payload.get("time_block") or "").strip(),
            (payload.get("notes") or "").strip(),
            (payload.get("status") or "planning").strip() or "planning",
            now,
            item_id,
            uid,
        ),
    )
    if res.rowcount == 0:
        return jsonify({"message": "not found"}), 404
    db.commit()
    row = db.execute("SELECT * FROM plan_items WHERE id = ? AND user_id = ?", (item_id, uid)).fetchone()
    return jsonify(dict(row))


@app.delete("/api/plan/items/<int:item_id>")
def delete_plan_item(item_id):
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    db = get_db()
    res = db.execute("DELETE FROM plan_items WHERE id = ? AND user_id = ?", (item_id, uid))
    if res.rowcount == 0:
        return jsonify({"message": "not found"}), 404
    db.commit()
    return "", 204


@app.get("/api/calendar/month")
def calendar_month():
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    try:
        year = int(request.args.get("year"))
        month = int(request.args.get("month"))
    except (TypeError, ValueError):
        return jsonify({"message": "year/month required"}), 400
    if month < 1 or month > 12:
        return jsonify({"message": "month invalid"}), 400
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    db = get_db()
    tasks = db.execute(
        """
        SELECT id, title, due_at, remind_at, completed, is_important, is_urgent
        FROM tasks
        WHERE user_id = ? AND (due_at >= ? AND due_at < ?)
        """,
        (uid, start.isoformat(), end.isoformat()),
    ).fetchall()
    plan_items = db.execute(
        """
        SELECT id, title, planned_at, status, priority_level
        FROM plan_items
        WHERE user_id = ? AND (planned_at >= ? AND planned_at < ?)
        """,
        (uid, start.isoformat(), end.isoformat()),
    ).fetchall()
    return jsonify({"tasks": [dict(r) for r in tasks], "plan_items": [dict(r) for r in plan_items]})


@app.get("/api/stats/insights")
def stats_insights():
    """
    获取用户的统计洞察
    
    包括任务完成情况、四象限分布、计划项统计、番茄钟使用情况等
    并根据统计数据生成个性化建议
    """
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    db = get_db()
    
    # 任务总数和完成数
    total = db.execute("SELECT COUNT(*) AS c FROM tasks WHERE user_id = ?", (uid,)).fetchone()["c"]
    done = db.execute(
        "SELECT COUNT(*) AS c FROM tasks WHERE user_id = ? AND completed = 1", (uid,)
    ).fetchone()["c"]
    
    # 四象限分布
    q1 = db.execute(
        "SELECT COUNT(*) AS c FROM tasks WHERE user_id = ? AND is_important = 1 AND is_urgent = 1", (uid,)
    ).fetchone()["c"]
    q2 = db.execute(
        "SELECT COUNT(*) AS c FROM tasks WHERE user_id = ? AND is_important = 1 AND is_urgent = 0", (uid,)
    ).fetchone()["c"]
    q3 = db.execute(
        "SELECT COUNT(*) AS c FROM tasks WHERE user_id = ? AND is_important = 0 AND is_urgent = 1", (uid,)
    ).fetchone()["c"]
    q4 = db.execute(
        "SELECT COUNT(*) AS c FROM tasks WHERE user_id = ? AND is_important = 0 AND is_urgent = 0", (uid,)
    ).fetchone()["c"]
    
    # 即将到期的任务数（未来两天）
    due_soon = db.execute(
        """
        SELECT COUNT(*) AS c FROM tasks
        WHERE user_id = ? AND completed = 0 AND due_at IS NOT NULL
          AND due_at <= ?
        """,
        (uid, (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()),
    ).fetchone()["c"]
    
    # 计算完成率
    completion_rate = 0 if total == 0 else round(done * 100 / total)
    
    # 本周完成任务数
    today = date.today()
    week_start = get_week_start_monday(today)
    week_end = week_start + timedelta(days=6)
    week_done = db.execute(
        """
        SELECT COUNT(*) AS c FROM tasks
        WHERE user_id = ? AND completed = 1 AND completed_at IS NOT NULL
          AND completed_at >= ? AND completed_at <= ?
        """,
        (uid, week_start.isoformat(), week_end.isoformat()),
    ).fetchone()["c"]
    
    # 平均完成时间
    avg_time_result = db.execute(
        """
        SELECT AVG(JULIANDAY(completed_at) - JULIANDAY(created_at)) * 24 * 60 AS avg_minutes
        FROM tasks
        WHERE user_id = ? AND completed = 1 AND completed_at IS NOT NULL
        """,
        (uid,)
    ).fetchone()
    avg_completion_time = round(avg_time_result["avg_minutes"]) if avg_time_result["avg_minutes"] else 0
    
    # 计划项统计
    plan_total = db.execute("SELECT COUNT(*) AS c FROM plan_items WHERE user_id = ?", (uid,)).fetchone()["c"]
    plan_scheduled = db.execute("SELECT COUNT(*) AS c FROM plan_items WHERE user_id = ? AND status = 'scheduled'", (uid,)).fetchone()["c"]
    plan_done = db.execute("SELECT COUNT(*) AS c FROM plan_items WHERE user_id = ? AND status = 'done'", (uid,)).fetchone()["c"]
    
    # 番茄钟统计
    pomo_total = db.execute("SELECT COUNT(*) AS c FROM pomodoro_logs WHERE user_id = ?", (uid,)).fetchone()["c"]
    pomo_completed = db.execute("SELECT COUNT(*) AS c FROM pomodoro_logs WHERE user_id = ? AND status = 'completed'", (uid,)).fetchone()["c"]
    
    # 生成更多建议
    suggestions = []
    if q1 > q2:
        suggestions.append("Q1 比 Q2 多，先把重要不紧急的拆小，挪到每天固定时段。")
    if q3 > q2:
        suggestions.append("Q3 偏多，考虑能否委派或用 2 分钟法则快速清掉。")
    if q4 > (q1 + q2):
        suggestions.append("Q4 偏多，建议每天预留 1 个时间块做真正重要的事。")
    if due_soon >= 3:
        suggestions.append("未来两天到期任务多，建议先锁定 1-2 个最高优先级。")
    if completion_rate < 40 and total >= 5:
        suggestions.append("完成率偏低，试试 135 法则：每天 1 大 3 中 5 小。")
    if week_done < 3:
        suggestions.append("本周完成任务较少，建议每天至少完成 1-2 个任务。")
    if avg_completion_time > 120:
        suggestions.append("平均完成时间较长，试试将任务拆分成更小的步骤。")
    if plan_total > 0 and plan_scheduled / plan_total < 0.5:
        suggestions.append("计划项较多但排期较少，建议为重要计划项安排具体时间。")
    if pomo_total < 5:
        suggestions.append("番茄钟使用较少，建议用番茄钟提高专注度。")
    
    return jsonify(
        {
            "total": total,
            "done": done,
            "completion_rate": completion_rate,
            "quadrants": {"Q1": q1, "Q2": q2, "Q3": q3, "Q4": q4},
            "due_soon": due_soon,
            "week_done": week_done,
            "avg_completion_time": avg_completion_time,
            "plan_stats": {
                "total": plan_total,
                "scheduled": plan_scheduled,
                "done": plan_done
            },
            "pomo_stats": {
                "total": pomo_total,
                "completed": pomo_completed
            },
            "suggestions": suggestions,
        }
    )


@app.post("/api/ai/suggest")
@limiter.limit("10 per minute")
def ai_suggest():
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify({"message": "text is required"}), 400

    prompt = (
        "你是效率教练。请基于用户输入生成3条可执行的日程建议，"
        "每条不超过30字，使用简洁中文，返回纯文本列表。\n"
        f"用户输入：{text}"
    )
    out, err = _ollama_generate(prompt)
    if out:
        return jsonify({"suggestion": out, "source": "ollama"})
    return jsonify(
        {
            "suggestion": _offline_suggest(text),
            "source": "offline",
            "hint": err or "已使用本地备用建议，连接 Ollama 后可获得模型生成内容。",
        }
    )


@app.post("/api/qa/ask")
@limiter.limit("15 per minute")
def qa_ask():
    uid = require_user_id()
    if not uid:
        return jsonify({"message": "未登录"}), 401
    q = (request.get_json(silent=True) or {}).get("question") or ""
    q = q.strip()
    if not q:
        return jsonify({"message": "请输入问题"}), 400
    prompt = (
        "用很短的中文回答（不超过 120 字），像便签小贴士，不要开场白、不要写\"作为 AI\"。\n"
        f"问题：{q}"
    )
    out, err = _ollama_generate(prompt)
    if out:
        return jsonify({"answer": out, "source": "ollama"})
    return jsonify({"answer": _offline_qa(q), "source": "local", "hint": err})


# 全局异常处理器
@app.errorhandler(Exception)
def handle_exception(e):
    """
    全局异常处理器
    
    Args:
        e: 异常对象
        
    Returns:
        tuple: (JSON响应, 状态码)
    """
    import traceback
    traceback.print_exc()
    return jsonify({"message": f"服务器内部错误: {str(e)}"}), 500


if __name__ == "__main__":
    try:
        migrate_db()
        app.run(host="0.0.0.0", port=5000, debug=True)
    except Exception as e:
        print(f"启动失败: {str(e)}")
