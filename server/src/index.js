const express = require("express");
const cors = require("cors");
const path = require("path");
const sqlite3 = require("sqlite3").verbose();

const app = express();
const PORT = 3001;
const dbPath = path.join(__dirname, "..", "data.db");
const db = new sqlite3.Database(dbPath);

app.use(cors());
app.use(express.json());

db.serialize(() => {
  db.run(`
    CREATE TABLE IF NOT EXISTS tasks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      description TEXT DEFAULT '',
      isImportant INTEGER NOT NULL DEFAULT 0,
      isUrgent INTEGER NOT NULL DEFAULT 0,
      dueAt TEXT DEFAULT NULL,
      remindAt TEXT DEFAULT NULL,
      completed INTEGER NOT NULL DEFAULT 0,
      reminded INTEGER NOT NULL DEFAULT 0,
      createdAt TEXT NOT NULL,
      updatedAt TEXT NOT NULL
    )
  `);
});

function normalizeTask(row) {
  return {
    ...row,
    isImportant: Boolean(row.isImportant),
    isUrgent: Boolean(row.isUrgent),
    completed: Boolean(row.completed),
    reminded: Boolean(row.reminded),
  };
}

function taskQuadrant(task) {
  if (task.isImportant && task.isUrgent) return "Q1";
  if (task.isImportant && !task.isUrgent) return "Q2";
  if (!task.isImportant && task.isUrgent) return "Q3";
  return "Q4";
}

app.get("/api/health", (_req, res) => {
  res.json({ ok: true, service: "quadrant-schedule-api" });
});

app.get("/api/tasks", (_req, res) => {
  db.all("SELECT * FROM tasks ORDER BY createdAt DESC", [], (err, rows) => {
    if (err) return res.status(500).json({ message: err.message });
    const tasks = rows.map(normalizeTask).map((task) => ({ ...task, quadrant: taskQuadrant(task) }));
    res.json(tasks);
  });
});

app.post("/api/tasks", (req, res) => {
  const { title, description = "", isImportant = false, isUrgent = false, dueAt = null, remindAt = null } = req.body;

  if (!title || !title.trim()) {
    return res.status(400).json({ message: "title is required" });
  }

  const now = new Date().toISOString();
  const sql = `
    INSERT INTO tasks (title, description, isImportant, isUrgent, dueAt, remindAt, completed, reminded, createdAt, updatedAt)
    VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
  `;

  db.run(
    sql,
    [title.trim(), description, Number(isImportant), Number(isUrgent), dueAt, remindAt, now, now],
    function onInsert(err) {
      if (err) return res.status(500).json({ message: err.message });

      db.get("SELECT * FROM tasks WHERE id = ?", [this.lastID], (getErr, row) => {
        if (getErr) return res.status(500).json({ message: getErr.message });
        const task = normalizeTask(row);
        res.status(201).json({ ...task, quadrant: taskQuadrant(task) });
      });
    }
  );
});

app.put("/api/tasks/:id", (req, res) => {
  const { id } = req.params;
  const { title, description = "", isImportant = false, isUrgent = false, dueAt = null, remindAt = null, completed = false } = req.body;

  if (!title || !title.trim()) {
    return res.status(400).json({ message: "title is required" });
  }

  const now = new Date().toISOString();
  const reminded = remindAt ? 0 : 1;
  const sql = `
    UPDATE tasks
    SET title = ?, description = ?, isImportant = ?, isUrgent = ?, dueAt = ?, remindAt = ?, completed = ?, reminded = ?, updatedAt = ?
    WHERE id = ?
  `;

  db.run(
    sql,
    [title.trim(), description, Number(isImportant), Number(isUrgent), dueAt, remindAt, Number(completed), reminded, now, id],
    function onUpdate(err) {
      if (err) return res.status(500).json({ message: err.message });
      if (this.changes === 0) return res.status(404).json({ message: "task not found" });

      db.get("SELECT * FROM tasks WHERE id = ?", [id], (getErr, row) => {
        if (getErr) return res.status(500).json({ message: getErr.message });
        const task = normalizeTask(row);
        res.json({ ...task, quadrant: taskQuadrant(task) });
      });
    }
  );
});

app.patch("/api/tasks/:id/toggle", (req, res) => {
  const { id } = req.params;
  const now = new Date().toISOString();
  const sql = "UPDATE tasks SET completed = CASE completed WHEN 1 THEN 0 ELSE 1 END, updatedAt = ? WHERE id = ?";

  db.run(sql, [now, id], function onToggle(err) {
    if (err) return res.status(500).json({ message: err.message });
    if (this.changes === 0) return res.status(404).json({ message: "task not found" });

    db.get("SELECT * FROM tasks WHERE id = ?", [id], (getErr, row) => {
      if (getErr) return res.status(500).json({ message: getErr.message });
      const task = normalizeTask(row);
      res.json({ ...task, quadrant: taskQuadrant(task) });
    });
  });
});

app.delete("/api/tasks/:id", (req, res) => {
  const { id } = req.params;
  db.run("DELETE FROM tasks WHERE id = ?", [id], function onDelete(err) {
    if (err) return res.status(500).json({ message: err.message });
    if (this.changes === 0) return res.status(404).json({ message: "task not found" });
    res.status(204).send();
  });
});

app.get("/api/reminders/due", (_req, res) => {
  const now = new Date().toISOString();
  const sql = `
    SELECT * FROM tasks
    WHERE remindAt IS NOT NULL
      AND reminded = 0
      AND completed = 0
      AND remindAt <= ?
    ORDER BY remindAt ASC
  `;

  db.all(sql, [now], (err, rows) => {
    if (err) return res.status(500).json({ message: err.message });
    const tasks = rows.map(normalizeTask).map((task) => ({ ...task, quadrant: taskQuadrant(task) }));
    if (tasks.length === 0) return res.json([]);

    const ids = tasks.map((task) => task.id).join(",");
    db.run(`UPDATE tasks SET reminded = 1 WHERE id IN (${ids})`, [], (updateErr) => {
      if (updateErr) return res.status(500).json({ message: updateErr.message });
      res.json(tasks);
    });
  });
});

app.listen(PORT, () => {
  console.log(`Server running at http://localhost:${PORT}`);
});
