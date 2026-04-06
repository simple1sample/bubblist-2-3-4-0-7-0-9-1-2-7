import { useEffect, useMemo, useState } from "react";
import "./App.css";

const API_BASE = "http://localhost:5000/api";

const emptyForm = {
  title: "",
  description: "",
  isImportant: false,
  isUrgent: false,
  dueAt: "",
  remindAt: "",
};

function toDateInput(isoString) {
  if (!isoString) return "";
  const date = new Date(isoString);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function fromDateInput(value) {
  if (!value) return null;
  return new Date(value).toISOString();
}

function App() {
  const [tasks, setTasks] = useState([]);
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState(null);
  const [message, setMessage] = useState("");

  async function fetchTasks() {
    const response = await fetch(`${API_BASE}/tasks`);
    const data = await response.json();
    setTasks(data);
  }

  useEffect(() => {
    let cancelled = false;

    async function loadInitialTasks() {
      try {
        const response = await fetch(`${API_BASE}/tasks`);
        const data = await response.json();
        if (!cancelled) setTasks(data);
      } catch {
        if (!cancelled) setMessage("加载任务失败，请确认后端已启动。");
      }
    }

    loadInitialTasks();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
  }, []);

  useEffect(() => {
    const timer = setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE}/reminders/due`);
        const dueTasks = await response.json();

        dueTasks.forEach((task) => {
          const text = `提醒：${task.title}（${task.quadrant}）`;
          if ("Notification" in window && Notification.permission === "granted") {
            new Notification("四象限日程提醒", { body: text });
          } else {
            window.alert(text);
          }
        });
      } catch {
        // Keep silent for interval failures to avoid noisy alerts.
      }
    }, 15000);

    return () => clearInterval(timer);
  }, []);

  const groupedTasks = useMemo(() => {
    return {
      Q1: tasks.filter((task) => task.quadrant === "Q1"),
      Q2: tasks.filter((task) => task.quadrant === "Q2"),
      Q3: tasks.filter((task) => task.quadrant === "Q3"),
      Q4: tasks.filter((task) => task.quadrant === "Q4"),
    };
  }, [tasks]);

  function handleInputChange(event) {
    const { name, type, checked, value } = event.target;
    setForm((prev) => ({
      ...prev,
      [name]: type === "checkbox" ? checked : value,
    }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!form.title.trim()) {
      setMessage("标题不能为空。");
      return;
    }

    const payload = {
      ...form,
      dueAt: fromDateInput(form.dueAt),
      remindAt: fromDateInput(form.remindAt),
    };

    const endpoint = editingId ? `${API_BASE}/tasks/${editingId}` : `${API_BASE}/tasks`;
    const method = editingId ? "PUT" : "POST";

    const response = await fetch(endpoint, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      setMessage("保存失败，请检查输入。");
      return;
    }

    setMessage(editingId ? "任务已更新。" : "任务已创建。");
    setForm(emptyForm);
    setEditingId(null);
    fetchTasks();
  }

  function startEdit(task) {
    setEditingId(task.id);
    setForm({
      title: task.title,
      description: task.description ?? "",
      isImportant: task.isImportant,
      isUrgent: task.isUrgent,
      dueAt: toDateInput(task.dueAt),
      remindAt: toDateInput(task.remindAt),
    });
  }

  async function removeTask(id) {
    await fetch(`${API_BASE}/tasks/${id}`, { method: "DELETE" });
    fetchTasks();
  }

  async function toggleCompleted(id) {
    await fetch(`${API_BASE}/tasks/${id}/toggle`, { method: "PATCH" });
    fetchTasks();
  }

  const quadrantMeta = {
    Q1: "Q1 重要且紧急",
    Q2: "Q2 重要不紧急",
    Q3: "Q3 紧急不重要",
    Q4: "Q4 不重要不紧急",
  };

  return (
    <main className="app">
      <header>
        <h1>四象限日程提醒系统</h1>
        <p>支持创建任务、四象限分类、到点提醒（浏览器通知/弹窗）</p>
      </header>

      <section className="panel">
        <h2>{editingId ? "编辑任务" : "创建任务"}</h2>
        <form onSubmit={handleSubmit} className="task-form">
          <input name="title" value={form.title} onChange={handleInputChange} placeholder="任务标题" />
          <textarea
            name="description"
            value={form.description}
            onChange={handleInputChange}
            placeholder="任务描述（可选）"
            rows={3}
          />

          <div className="check-group">
            <label>
              <input type="checkbox" name="isImportant" checked={form.isImportant} onChange={handleInputChange} />
              重要
            </label>
            <label>
              <input type="checkbox" name="isUrgent" checked={form.isUrgent} onChange={handleInputChange} />
              紧急
            </label>
          </div>

          <label>
            截止时间：
            <input type="datetime-local" name="dueAt" value={form.dueAt} onChange={handleInputChange} />
          </label>
          <label>
            提醒时间：
            <input type="datetime-local" name="remindAt" value={form.remindAt} onChange={handleInputChange} />
          </label>

          <div className="row">
            <button type="submit">{editingId ? "更新任务" : "创建任务"}</button>
            {editingId && (
              <button
                type="button"
                onClick={() => {
                  setEditingId(null);
                  setForm(emptyForm);
                }}
              >
                取消编辑
              </button>
            )}
          </div>
        </form>
        {message && <p className="message">{message}</p>}
      </section>

      <section className="quadrant-grid">
        {Object.keys(groupedTasks).map((key) => (
          <article key={key} className="panel">
            <h2>{quadrantMeta[key]}</h2>
            <ul className="task-list">
              {groupedTasks[key].map((task) => (
                <li key={task.id} className={task.completed ? "task done" : "task"}>
                  <strong>{task.title}</strong>
                  {task.description && <p>{task.description}</p>}
                  <small>
                    截止: {task.dueAt ? new Date(task.dueAt).toLocaleString() : "未设置"} | 提醒:{" "}
                    {task.remindAt ? new Date(task.remindAt).toLocaleString() : "未设置"}
                  </small>
                  <div className="row">
                    <button type="button" onClick={() => toggleCompleted(task.id)}>
                      {task.completed ? "标记未完成" : "标记完成"}
                    </button>
                    <button type="button" onClick={() => startEdit(task)}>
                      编辑
                    </button>
                    <button type="button" onClick={() => removeTask(task.id)}>
                      删除
                    </button>
                  </div>
                </li>
              ))}
              {groupedTasks[key].length === 0 && <li className="task empty">暂无任务</li>}
            </ul>
          </article>
        ))}
      </section>
    </main>
  );
}

export default App;
