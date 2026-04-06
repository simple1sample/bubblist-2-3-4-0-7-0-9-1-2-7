const { createApp } = Vue;

const emptyForm = () => ({
  title: "",
  description: "",
  is_important: false,
  is_urgent: false,
  due_at: "",
  remind_at: "",
});

function fromIsoToInput(iso) {
  if (!iso) return "";
  const dt = new Date(iso);
  const local = new Date(dt.getTime() - dt.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function fromInputToIso(text) {
  if (!text) return null;
  return new Date(text).toISOString();
}

let alarmTimer = null;
let audioCtx = null;

function ensureAudio() {
  if (!audioCtx) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (Ctx) audioCtx = new Ctx();
  }
  return audioCtx;
}

function beepOnce() {
  const ctx = ensureAudio();
  if (!ctx) return;
  const o = ctx.createOscillator();
  const g = ctx.createGain();
  o.type = "sine";
  o.frequency.value = 920;
  o.connect(g);
  g.connect(ctx.destination);
  const t = ctx.currentTime;
  g.gain.setValueAtTime(0.001, t);
  g.gain.exponentialRampToValueAtTime(0.1, t + 0.02);
  g.gain.exponentialRampToValueAtTime(0.001, t + 0.22);
  o.start(t);
  o.stop(t + 0.25);
}

function startAlarmLoop() {
  if (alarmTimer) return;
  ensureAudio();
  if (audioCtx && audioCtx.state === "suspended") {
    audioCtx.resume().catch(() => {});
  }
  alarmTimer = setInterval(() => {
    try {
      beepOnce();
    } catch (_) {}
  }, 900);
}

function stopAlarmLoop() {
  if (alarmTimer) {
    clearInterval(alarmTimer);
    alarmTimer = null;
  }
}

const fetchJSON = (url, options = {}) =>
  fetch(url, {
    credentials: "same-origin",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });

createApp({
  data() {
    return {
      navItems: [
        { id: "flow", label: "计划流", icon: "" },
        { id: "tasks", label: "四象限", icon: "" },
        { id: "calendar", label: "日历", icon: "" },
        { id: "stats", label: "统计", icon: "" },
        { id: "pomodoro", label: "番茄钟", icon: "" },
        { id: "qa", label: "问答", icon: "" },
        { id: "profile", label: "我的", icon: "" },
      ],
      currentPage: "flow",
      user: null,
      isRegister: false,
      auth: { username: "", password: "" },
      authError: "",
      reminderMode: "browser",
      theme: "peach",
      timeBlocksText: "",
      profileForm: { display_name: "", bio: "" },
      profileMsg: "",
      planIdeas: [],
      planIdeaForm: { title: "", notes: "" },
      planItems: [],
      planForm: {
        title: "",
        domain: "",
        project: "",
        role: "",
        priority_rule: "四象限",
        priority_level: "",
        quadrant: "Q2",
        scene: "",
        planned_at: "",
        time_block: "",
        notes: "",
        status: "planning",
      },
      editingPlanId: null,
      planMsg: "",
      planSearch: "",
      planFilterType: "all",
      planFilterValue: "all",
      filterOptions: {
        priority_rule: ["四象限", "两分钟法则", "135法则"],
        domain: [],
        role: [],
        scene: [],
        time_block: []
      },
      // 历史输入记录
      inputHistory: {
        domain: [],
        project: [],
        role: [],
        scene: [],
        time_block: []
      },
      // 当前激活的输入框
      activeInput: null,
      // 输入建议
      inputSuggestions: [],
      calendar: {
        year: new Date().getFullYear(),
        month: new Date().getMonth() + 1,
        grid: [],
        items: {},
      },
      statsInsights: null,
      tasks: [],
      form: emptyForm(),
      quadrantOrder: ["Q1", "Q2", "Q3", "Q4"],
      quadrantTitle: {
        Q1: "重要 · 紧急",
        Q2: "重要 · 不紧急",
        Q3: "紧急 · 不重要",
        Q4: "不紧急 · 不重要",
      },
      quadrantEmoji: {
        Q1: "🔥",
        Q2: "🌱",
        Q3: "⚡",
        Q4: "☁️",
      },
      reminderModal: { open: false, tasks: [] },
      pollBusy: false,
      message: "",
      suggestion: "",
      suggestHint: "",
      editingId: null,
      qaQuestion: "",
      qaAnswer: "",
      qaHint: "",
      qaLoading: false,
      pomoLogs: [],
      pomo: {
        name: "专心一小会儿",
        presets: [15, 25, 45],
        chosenPreset: 25,
        customMin: 25,
        running: false,
        remaining: 25 * 60,
        tick: null,
      },
    };
  },
  computed: {
    grouped() {
      const base = { Q1: [], Q2: [], Q3: [], Q4: [] };
      this.tasks.forEach((task) => base[task.quadrant].push(task));
      return base;
    },
    timeBlockOptions() {
      const raw = (this.timeBlocksText || "").split(/\n|,|;|\|/).map((x) => x.trim()).filter(Boolean);
      return raw.length ? raw : ["08:00-09:30", "10:00-11:30", "14:00-16:00", "20:00-21:00"];
    },
    filteredPlanItems() {
      let filtered = this.planItems;
      // 按筛选类型和值筛选
      if (this.planFilterType !== "all" && this.planFilterValue !== "all") {
        filtered = filtered.filter(item => item[this.planFilterType] === this.planFilterValue);
      }
      // 按搜索词筛选
      if (this.planSearch) {
        const searchLower = this.planSearch.toLowerCase();
        filtered = filtered.filter(item => 
          item.title.toLowerCase().includes(searchLower) || 
          (item.notes && item.notes.toLowerCase().includes(searchLower)) ||
          (item.domain && item.domain.toLowerCase().includes(searchLower)) ||
          (item.project && item.project.toLowerCase().includes(searchLower)) ||
          (item.role && item.role.toLowerCase().includes(searchLower)) ||
          (item.scene && item.scene.toLowerCase().includes(searchLower)) ||
          (item.time_block && item.time_block.toLowerCase().includes(searchLower))
        );
      }
      return filtered;
    },
    pomoDisplay() {
      const s = Math.max(0, this.pomo.remaining);
      const m = Math.floor(s / 60);
      const r = s % 60;
      return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
    },
  },
  methods: {
    // 更新筛选选项
    updateFilterOptions() {
      // 从计划项中提取唯一的选项
      const options = {
        domain: new Set(),
        role: new Set(),
        scene: new Set(),
        time_block: new Set()
      };
      
      this.planItems.forEach(item => {
        if (item.domain) options.domain.add(item.domain);
        if (item.role) options.role.add(item.role);
        if (item.scene) options.scene.add(item.scene);
        if (item.time_block) options.time_block.add(item.time_block);
      });
      
      // 更新filterOptions
      this.filterOptions.domain = Array.from(options.domain);
      this.filterOptions.role = Array.from(options.role);
      this.filterOptions.scene = Array.from(options.scene);
      this.filterOptions.time_block = Array.from(options.time_block);
    },
    // 更新输入建议
    updateInputSuggestions(field) {
      const value = this.planForm[field]?.toLowerCase() || '';
      if (value) {
        this.inputSuggestions = this.inputHistory[field].filter(item => 
          item.toLowerCase().includes(value)
        );
      } else {
        this.inputSuggestions = [...this.inputHistory[field]];
      }
    },
    // 处理输入框失去焦点
    blurInput() {
      setTimeout(() => {
        this.activeInput = null;
      }, 200);
    },
    // 从历史记录中删除相关的领域、角色、场景、时间块
    removeFromHistory(item) {
      const fields = ['domain', 'project', 'role', 'scene', 'time_block'];
      fields.forEach(field => {
        const value = item[field];
        if (value) {
          const index = this.inputHistory[field].indexOf(value);
          if (index !== -1) {
            this.inputHistory[field].splice(index, 1);
          }
        }
      });
    },
  },
  watch: {
    user(nv) {
      if (nv) {
        this.reminderMode = nv.reminder_mode || "browser";
        this.theme = nv.theme || "peach";
        this.timeBlocksText = nv.time_blocks || "";
        this.profileForm = {
          display_name: nv.display_name || nv.username || "",
          bio: nv.bio || "",
        };
        this.$nextTick(() => {
          this.bootstrapAfterLogin();
        });
      } else {
        stopAlarmLoop();
        this.reminderModal = { open: false, tasks: [] };
        this.destroyPieCharts();
      }
    },
    currentPage(page) {
      this.$nextTick(async () => {
        if (page === "stats") await this.refreshPieCharts();
        if (page === "pomodoro") await this.fetchPomoLogs();
        if (page === "calendar") await this.loadCalendar();
      });
    },
    "pomo.customMin"(v) {
      if (this.pomo.running) return;
      const n = Math.max(1, Math.min(120, Number(v) || 25));
      this.pomo.customMin = n;
      this.pomo.remaining = n * 60;
    },
  },
  methods: {
    go(page) {
      this.currentPage = page;
      if (typeof history !== "undefined") {
        history.replaceState(null, "", "#/" + page);
      }
    },
    syncRoute() {
      const h = (location.hash || "#/flow").replace(/^#\/?/, "").split("/")[0] || "flow";
      const ok = this.navItems.some((x) => x.id === h);
      this.currentPage = ok ? h : "flow";
    },
    localTime(iso) {
      return new Date(iso).toLocaleString();
    },
    destroyPieCharts() {
      const a = document.getElementById("chartPieQuadrant");
      const b = document.getElementById("chartPieWeek");
      if (a && Chart.getChart(a)) Chart.getChart(a).destroy();
      if (b && Chart.getChart(b)) Chart.getChart(b).destroy();
    },
    async bootstrapAfterLogin() {
      if ("Notification" in window && this.reminderMode === "browser" && Notification.permission === "default") {
        await Notification.requestPermission();
      }
      await this.fetchTasks();
      await this.fetchPlanIdeas();
      await this.fetchPlanItems();
      await this.loadCalendar();
      if (this.currentPage === "stats") await this.refreshPieCharts();
      if (this.currentPage === "pomodoro") await this.fetchPomoLogs();
    },
    async trySession() {
      const res = await fetch("/api/auth/me", { credentials: "same-origin" });
      if (!res.ok) {
        this.user = null;
        return;
      }
      const data = await res.json();
      this.user = data.user;
      this.reminderMode = data.user.reminder_mode || "browser";
      this.theme = data.user.theme || "peach";
      this.timeBlocksText = data.user.time_blocks || "";
    },
    async doLogin() {
      this.authError = "";
      const res = await fetchJSON("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          username: this.auth.username,
          password: this.auth.password,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        this.authError = data.message || "登录失败";
        return;
      }
      this.user = data.user;
      this.reminderMode = data.user.reminder_mode || "browser";
      this.theme = data.user.theme || "peach";
      this.timeBlocksText = data.user.time_blocks || "";
      this.auth.password = "";
      this.message = "";
      await this.bootstrapAfterLogin();
    },
    async doRegister() {
      this.authError = "";
      const res = await fetchJSON("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({
          username: this.auth.username,
          password: this.auth.password,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        this.authError = data.message || "注册失败";
        return;
      }
      this.user = data.user;
      this.reminderMode = data.user.reminder_mode || "browser";
      this.theme = data.user.theme || "peach";
      this.timeBlocksText = data.user.time_blocks || "";
      this.auth.password = "";
      this.message = "";
      await this.bootstrapAfterLogin();
    },
    async doLogout() {
      await fetchJSON("/api/auth/logout", { method: "POST", body: JSON.stringify({}) });
      this.user = null;
      this.auth.username = "";
      this.auth.password = "";
    },
    async saveProfile() {
      this.profileMsg = "";
      const res = await fetchJSON("/api/auth/me", {
        method: "PATCH",
        body: JSON.stringify({
          display_name: this.profileForm.display_name,
          bio: this.profileForm.bio,
          reminder_mode: this.reminderMode,
          theme: this.theme,
          time_blocks: this.timeBlocksText,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        this.profileMsg = data.message || "保存失败";
        return;
      }
      this.user = data.user;
      this.profileMsg = "保存好啦 ✓";
      if (this.reminderMode === "browser" && "Notification" in window && Notification.permission === "default") {
        await Notification.requestPermission();
      }
    },
    pickPreset(m) {
      this.pomo.chosenPreset = m;
      this.pomo.customMin = m;
      if (!this.pomo.running) this.pomo.remaining = m * 60;
    },
    resetPomo() {
      if (this.pomo.tick) {
        clearInterval(this.pomo.tick);
        this.pomo.tick = null;
      }
      this.pomo.running = false;
      const m = Math.max(1, Number(this.pomo.customMin) || 25);
      this.pomo.customMin = m;
      this.pomo.remaining = m * 60;
    },
    togglePomo() {
      const secs = Math.max(1, this.pomo.customMin) * 60;
      if (!this.pomo.running) {
        if (this.pomo.remaining <= 0) this.pomo.remaining = secs;
        this.pomo.running = true;
        if (!this.pomo.tick) {
          this.pomo.tick = setInterval(async () => {
            this.pomo.remaining -= 1;
            if (this.pomo.remaining <= 0) {
              clearInterval(this.pomo.tick);
              this.pomo.tick = null;
              this.pomo.running = false;
              beepOnce();
              await fetchJSON("/api/pomodoro/logs", {
                method: "POST",
                body: JSON.stringify({
                  name: this.pomo.name || "番茄钟",
                  planned_seconds: secs,
                  status: "completed",
                }),
              });
              this.fetchPomoLogs();
            }
          }, 1000);
        }
      } else {
        this.pomo.running = false;
        if (this.pomo.tick) {
          clearInterval(this.pomo.tick);
          this.pomo.tick = null;
        }
      }
    },
    async fetchPomoLogs() {
      const res = await fetch("/api/pomodoro/logs", { credentials: "same-origin" });
      if (res.ok) this.pomoLogs = await res.json();
    },
    async fetchTasks() {
      const res = await fetch("/api/tasks", { credentials: "same-origin" });
      if (res.status === 401) {
        this.user = null;
        return;
      }
      this.tasks = await res.json();
    },
    buildCalendarGrid() {
      const first = new Date(this.calendar.year, this.calendar.month - 1, 1);
      const startDay = (first.getDay() + 6) % 7; // Monday=0
      const daysInMonth = new Date(this.calendar.year, this.calendar.month, 0).getDate();
      const prevMonthDays = new Date(this.calendar.year, this.calendar.month - 1, 0).getDate();
      const cells = [];
      for (let i = 0; i < startDay; i += 1) {
        const day = prevMonthDays - startDay + i + 1;
        const date = new Date(this.calendar.year, this.calendar.month - 2, day);
        cells.push({ day, inMonth: false, dateKey: date.toISOString().slice(0, 10) });
      }
      for (let d = 1; d <= daysInMonth; d += 1) {
        const date = new Date(this.calendar.year, this.calendar.month - 1, d);
        cells.push({ day: d, inMonth: true, dateKey: date.toISOString().slice(0, 10) });
      }
      while (cells.length % 7 !== 0) {
        const day = cells.length - (startDay + daysInMonth) + 1;
        const date = new Date(this.calendar.year, this.calendar.month, day);
        cells.push({ day, inMonth: false, dateKey: date.toISOString().slice(0, 10) });
      }
      this.calendar.grid = cells;
    },
    async loadCalendar() {
      this.buildCalendarGrid();
      const res = await fetch(
        `/api/calendar/month?year=${this.calendar.year}&month=${this.calendar.month}`,
        { credentials: "same-origin" }
      );
      if (!res.ok) return;
      const data = await res.json();
      const items = {};
      (data.tasks || []).forEach((t) => {
        const key = (t.due_at || t.remind_at || "").slice(0, 10);
        if (!key) return;
        if (!items[key]) items[key] = [];
        items[key].push({ key: `task-${t.id}`, type: "task", title: t.title });
      });
      (data.plan_items || []).forEach((p) => {
        const key = (p.planned_at || "").slice(0, 10);
        if (!key) return;
        if (!items[key]) items[key] = [];
        items[key].push({ key: `plan-${p.id}`, type: "plan", title: p.title });
      });
      this.calendar.items = items;
    },
    shiftMonth(step) {
      let y = this.calendar.year;
      let m = this.calendar.month + step;
      if (m < 1) {
        m = 12;
        y -= 1;
      }
      if (m > 12) {
        m = 1;
        y += 1;
      }
      this.calendar.year = y;
      this.calendar.month = m;
      this.loadCalendar();
    },
    async fetchPlanIdeas() {
      const res = await fetch("/api/plan/ideas", { credentials: "same-origin" });
      if (res.ok) this.planIdeas = await res.json();
    },
    async addPlanIdea() {
      if (!this.planIdeaForm.title.trim()) return;
      const res = await fetchJSON("/api/plan/ideas", {
        method: "POST",
        body: JSON.stringify(this.planIdeaForm),
      });
      if (res.ok) {
        this.planIdeaForm = { title: "", notes: "" };
        await this.fetchPlanIdeas();
      }
    },
    async deletePlanIdea(id) {
      await fetch(`/api/plan/ideas/${id}`, { method: "DELETE", credentials: "same-origin" });
      await this.fetchPlanIdeas();
    },
    async fetchPlanItems() {
      const res = await fetch("/api/plan/items", { credentials: "same-origin" });
      if (res.ok) {
        this.planItems = await res.json();
        // 检查updateFilterOptions是否存在
        if (typeof this.updateFilterOptions === 'function') {
          this.updateFilterOptions();
        }
      }
    },
    async savePlanItem() {
      try {
        if (!this.planForm.title.trim()) {
          this.planMsg = "计划项要写标题";
          return;
        }
        
        // 如果是编辑模式，先删除原计划项
        if (this.editingPlanId) {
          // 获取原计划项信息
          const originalItem = this.planItems.find(item => item.id === this.editingPlanId);
          const self = this; // 保存this的引用
          
          // 删除原计划项
          try {
            await fetch(`/api/plan/items/${this.editingPlanId}`, { method: "DELETE", credentials: "same-origin" });
            // 从历史记录中删除相关的领域、角色、场景、时间块
            if (originalItem && typeof self.removeFromHistory === 'function') {
              self.removeFromHistory(originalItem);
            }
          } catch (error) {
            console.error("删除原计划项失败:", error);
          }
          
          // 查找并删除关联的四象限任务（如果有）
          const tasks = this.tasks.filter(task => 
            task.title === this.planForm.title && 
            task.description === (this.planForm.notes || "")
          );
          for (const task of tasks) {
            try {
              await fetch(`/api/tasks/${task.id}`, { method: "DELETE", credentials: "same-origin" });
            } catch (error) {
              console.error("删除关联任务失败:", error);
            }
          }
        }
        
        // 创建新的计划项
        const payload = {
          ...this.planForm,
          planned_at: fromInputToIso(this.planForm.planned_at),
        };
        const res = await fetchJSON("/api/plan/items", { method: "POST", body: JSON.stringify(payload) });
        if (!res.ok) {
          this.planMsg = "保存失败";
          return;
        }
        
        // 根据优先级规则创建对应的任务或番茄钟
        if (this.planForm.priority_rule === "四象限") {
          // 根据选择的象限设置任务的重要性和紧急性
          let is_important = false;
          let is_urgent = false;
          switch (this.planForm.quadrant) {
            case "Q1":
              is_important = true;
              is_urgent = true;
              break;
            case "Q2":
              is_important = true;
              is_urgent = false;
              break;
            case "Q3":
              is_important = false;
              is_urgent = true;
              break;
            case "Q4":
              is_important = false;
              is_urgent = false;
              break;
          }
          // 创建四象限任务
          const taskPayload = {
            title: this.planForm.title,
            description: this.planForm.notes || "",
            is_important: is_important,
            is_urgent: is_urgent,
            due_at: fromInputToIso(this.planForm.planned_at),
            remind_at: null
          };
          try {
            await fetchJSON("/api/tasks", {
              method: "POST",
              body: JSON.stringify(taskPayload)
            });
            await this.fetchTasks();
          } catch (error) {
            console.error("创建四象限任务失败:", error);
          }
        } else if (this.planForm.priority_rule === "两分钟法则") {
          // 创建番茄钟
          this.pomo.name = this.planForm.title;
          this.pomo.customMin = 2;
          this.pomo.remaining = 2 * 60;
          this.go("pomodoro");
        }
        
        // 更新历史输入记录
        const fields = ['domain', 'project', 'role', 'scene', 'time_block'];
        fields.forEach(field => {
          const value = this.planForm[field];
          if (value) {
            // 如果值不存在于历史记录中，添加它
            if (!this.inputHistory[field].includes(value)) {
              this.inputHistory[field].push(value);
              // 保持历史记录不超过10个
              if (this.inputHistory[field].length > 10) {
                this.inputHistory[field].shift();
              }
            }
          }
        });
        
        this.planMsg = "已保存";
        this.editingPlanId = null;
        this.planForm = {
          title: "",
          domain: "",
          project: "",
          role: "",
          priority_rule: "四象限",
          priority_level: "",
          quadrant: "Q2",
          scene: "",
          planned_at: "",
          time_block: "",
          notes: "",
          status: "planning",
        };
        await this.fetchPlanItems();
        await this.loadCalendar();
      } catch (error) {
        console.error("保存计划项失败:", error);
        this.planMsg = "保存失败";
      }
    },
    editPlanItem(item) {
      this.editingPlanId = item.id;
      this.planForm = {
        title: item.title || "",
        domain: item.domain || "",
        project: item.project || "",
        role: item.role || "",
        priority_rule: item.priority_rule || "四象限",
        priority_level: item.priority_level || "",
        quadrant: item.quadrant || "Q2",
        scene: item.scene || "",
        planned_at: fromIsoToInput(item.planned_at),
        time_block: item.time_block || "",
        notes: item.notes || "",
        status: item.status || "planning",
      };
    },
    async deletePlanItem(id) {
      // 获取计划项信息
      const item = this.planItems.find(item => item.id === id);
      const self = this; // 保存this的引用
      
      // 删除计划项
      await fetch(`/api/plan/items/${id}`, { method: "DELETE", credentials: "same-origin" });
      
      // 同步删除对应的四象限任务（如果有）
      if (item && item.priority_rule === "四象限") {
        const tasks = this.tasks.filter(task => 
          task.title === item.title && 
          task.description === (item.notes || "")
        );
        for (const task of tasks) {
          try {
            await fetch(`/api/tasks/${task.id}`, { method: "DELETE", credentials: "same-origin" });
          } catch (error) {
            console.error("删除关联任务失败:", error);
          }
        }
      }
      
      // 从历史记录中删除相关的领域、角色、场景、时间块
      if (item && typeof self.removeFromHistory === 'function') {
        self.removeFromHistory(item);
      }
      
      await this.fetchPlanItems();
      await this.fetchTasks();
      await this.loadCalendar();
    },
    pickTimeBlock(block) {
      this.planForm.time_block = block;
    },
    async refreshPieCharts() {
      if (!this.user || typeof Chart === "undefined") return;
      await this.$nextTick();
      const elQ = document.getElementById("chartPieQuadrant");
      const elW = document.getElementById("chartPieWeek");
      if (!elQ || !elW) return;
      const res = await fetch("/api/stats/overview", { credentials: "same-origin" });
      if (!res.ok) return;
      const d = await res.json();
      const qc = d.quadrant_counts || {};
      const labelsQ = ["Q1", "Q2", "Q3", "Q4"];
      const dataQ = labelsQ.map((k) => qc[k] ?? 0);
      const pieColors = ["#ff8a95", "#6eb5ff", "#ffc857", "#7ed9a6"];

      if (Chart.getChart(elQ)) Chart.getChart(elQ).destroy();
      new Chart(elQ, {
        type: "pie",
        data: {
          labels: labelsQ.map((x, i) => `${x} ${["重要紧急", "重要", "紧急", "缓冲"][i]}`),
          datasets: [
            {
              data: dataQ,
              backgroundColor: pieColors,
              borderWidth: 3,
              borderColor: "#3d2f4f",
            },
          ],
        },
        options: {
          responsive: true,
          plugins: {
            legend: { position: "bottom", labels: { font: { family: "Nunito" } } },
          },
        },
      });

      const wp = d.current_week_pie || { labels: [], values: [] };
      const weekColors = ["#ffb5c2", "#ffd6a8", "#c5f0c3", "#a8d8ff", "#e0c3ff", "#fff1a6", "#b5e8ff"];
      if (Chart.getChart(elW)) Chart.getChart(elW).destroy();
      new Chart(elW, {
        type: "pie",
        data: {
          labels: wp.labels || [],
          datasets: [
            {
              data: wp.values || [],
              backgroundColor: weekColors,
              borderWidth: 3,
              borderColor: "#3d2f4f",
            },
          ],
        },
        options: {
          responsive: true,
          plugins: {
            legend: { position: "bottom", labels: { font: { family: "Nunito" } } },
          },
        },
      });

      const insightRes = await fetch("/api/stats/insights", { credentials: "same-origin" });
      if (insightRes.ok) {
        this.statsInsights = await insightRes.json();
      }
    },
    async saveTask() {
      if (!this.form.title) {
        this.message = "标题要写哦";
        return;
      }
      const payload = {
        ...this.form,
        due_at: fromInputToIso(this.form.due_at),
        remind_at: fromInputToIso(this.form.remind_at),
      };
      if (this.editingId) {
        const t = this.tasks.find((x) => x.id === this.editingId);
        if (t) payload.completed = t.completed;
      }
      const url = this.editingId ? `/api/tasks/${this.editingId}` : "/api/tasks";
      const method = this.editingId ? "PUT" : "POST";
      payload.description = payload.description ?? "";
      const res = await fetchJSON(url, { method, body: JSON.stringify(payload) });
      if (!res.ok) {
        this.message = "保存失败";
        return;
      }
      
      // 同步更新计划流中的计划项
      // 确定象限
      let quadrant = "Q4";
      if (payload.is_important && payload.is_urgent) {
        quadrant = "Q1";
      } else if (payload.is_important && !payload.is_urgent) {
        quadrant = "Q2";
      } else if (!payload.is_important && payload.is_urgent) {
        quadrant = "Q3";
      }
      
      if (this.editingId) {
        // 编辑模式：先删除原计划项
        const oldTask = this.tasks.find(t => t.id === this.editingId);
        if (oldTask) {
          const oldPlanItems = this.planItems.filter(item => 
            item.title === oldTask.title && 
            item.notes === (oldTask.description || "") &&
            item.priority_rule === "四象限"
          );
          for (const item of oldPlanItems) {
            await fetch(`/api/plan/items/${item.id}`, { method: "DELETE", credentials: "same-origin" });
          }
        }
      }
      
      // 创建新的计划项
      const planPayload = {
        title: payload.title,
        domain: "",
        project: "",
        role: "",
        priority_rule: "四象限",
        priority_level: quadrant,
        quadrant: quadrant,
        scene: "",
        planned_at: payload.due_at,
        time_block: "",
        notes: payload.description,
        status: "scheduled"
      };
      await fetchJSON("/api/plan/items", { method: "POST", body: JSON.stringify(planPayload) });
      
      this.form = emptyForm();
      this.editingId = null;
      this.message = "记下啦";
      await this.fetchTasks();
      await this.fetchPlanItems();
      if (this.currentPage === "stats") await this.refreshPieCharts();
    },
    editTask(task) {
      this.go("tasks");
      this.editingId = task.id;
      this.form = {
        title: task.title || "",
        description: task.description || "",
        is_important: !!task.is_important,
        is_urgent: !!task.is_urgent,
        due_at: fromIsoToInput(task.due_at),
        remind_at: fromIsoToInput(task.remind_at),
      };
    },
    cancelEdit() {
      this.editingId = null;
      this.form = emptyForm();
    },
    async removeTask(id) {
      try {
        // 先获取任务信息，用于找到对应的计划项
        const task = this.tasks.find(t => t.id === id);
        const self = this; // 保存this的引用
        
        // 删除任务
        await fetch(`/api/tasks/${id}`, { method: "DELETE", credentials: "same-origin" });
        
        // 同步删除对应的计划项
        if (task) {
          const planItems = this.planItems.filter(item => 
            item.title === task.title && 
            item.notes === (task.description || "") &&
            item.priority_rule === "四象限"
          );
          for (const item of planItems) {
            try {
              await fetch(`/api/plan/items/${item.id}`, { method: "DELETE", credentials: "same-origin" });
              // 从历史记录中删除相关的领域、角色、场景、时间块
              if (typeof self.removeFromHistory === 'function') {
                self.removeFromHistory(item);
              }
            } catch (error) {
              console.error("删除计划项失败:", error);
            }
          }
        }
        
        await this.fetchTasks();
        await this.fetchPlanItems();
        if (this.currentPage === "stats") await this.refreshPieCharts();
      } catch (error) {
        console.error("删除任务失败:", error);
      }
    },
    async toggleDone(task) {
      await fetch(`/api/tasks/${task.id}/toggle`, { method: "PATCH", credentials: "same-origin" });
      await this.fetchTasks();
      if (this.currentPage === "stats") await this.refreshPieCharts();
    },
    async ackReminderIds(ids) {
      if (!ids.length) return;
      await fetchJSON("/api/reminders/ack", { method: "POST", body: JSON.stringify({ ids }) });
    },
    async dismissReminders() {
      const ids = this.reminderModal.tasks.map((t) => t.id);
      stopAlarmLoop();
      this.reminderModal = { open: false, tasks: [] };
      await this.ackReminderIds(ids);
    },
    ensureNotificationPermission() {
      if ("Notification" in window && Notification.permission === "default") {
        Notification.requestPermission();
      }
    },
    async pollReminders() {
      if (!this.user || this.reminderModal.open || this.pollBusy) return;
      this.pollBusy = true;
      try {
        const res = await fetch("/api/reminders/due", { credentials: "same-origin" });
        if (!res.ok) return;
        const due = await res.json();
        if (!due.length) return;
        const ids = due.map((t) => t.id);
        const line = (t) => `提醒：${t.title}（${t.quadrant}）`;
        if (this.reminderMode === "browser") {
          if ("Notification" in window && Notification.permission === "granted") {
            due.forEach((t) => new Notification("鱼鱼日程提醒", { body: line(t), tag: String(t.id) }));
            await this.ackReminderIds(ids);
          } else {
            this.message = "没开浏览器通知，这次用页面卡片提醒你～";
            this.reminderModal = { open: true, tasks: due };
            this.ensureNotificationPermission();
          }
          return;
        }
        if (this.reminderMode === "desktop_modal") {
          this.reminderModal = { open: true, tasks: due };
          return;
        }
        if (this.reminderMode === "local_alarm") {
          startAlarmLoop();
          this.reminderModal = { open: true, tasks: due };
        }
      } finally {
        this.pollBusy = false;
      }
    },
    async generateSuggestion() {
      this.suggestion = "";
      this.suggestHint = "";
      const input = this.form.title || this.form.description;
      if (!input) {
        this.message = "先写点标题或描述嘛";
        return;
      }
      const res = await fetchJSON("/api/ai/suggest", {
        method: "POST",
        body: JSON.stringify({ text: input }),
      });
      const data = await res.json();
      if (!res.ok) {
        this.message = data.message || "建议失败";
        return;
      }
      this.suggestion = data.suggestion || "";
      if (data.hint) this.suggestHint = data.hint;
      else if (data.source === "offline") this.suggestHint = "（当前为离线备用版，启动 Ollama 可换模型建议）";
      this.message = "";
    },
    async askQA() {
      this.qaAnswer = "";
      this.qaHint = "";
      if (!this.qaQuestion.trim()) return;
      this.qaLoading = true;
      try {
        const res = await fetchJSON("/api/qa/ask", {
          method: "POST",
          body: JSON.stringify({ question: this.qaQuestion }),
        });
        const data = await res.json();
        if (!res.ok) {
          this.qaAnswer = data.message || "问不了";
          return;
        }
        this.qaAnswer = data.answer || "";
        if (data.hint) this.qaHint = data.hint;
        if (data.source === "local" && !data.hint) {
          this.qaHint = "本地小抄回答中，装了 Ollama 可以更聪明～";
        }
      } finally {
        this.qaLoading = false;
      }
    },
  },
  async mounted() {
    const unlockAudio = () => {
      const ctx = ensureAudio();
      if (ctx && ctx.state === "suspended") ctx.resume().catch(() => {});
      document.removeEventListener("click", unlockAudio);
    };
    document.addEventListener("click", unlockAudio);

    this.ensureNotificationPermission();

    this.syncRoute();
    window.addEventListener("hashchange", this.syncRoute);

    await this.trySession();
    if (this.user) await this.bootstrapAfterLogin();
    setInterval(() => this.pollReminders().catch(() => {}), 15000);
  },
}).mount("#app");
