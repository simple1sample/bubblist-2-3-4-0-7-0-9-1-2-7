---
name: natural-product-scheduler
description: Build and iterate a production-like schedule app with clean UX and practical workflows. Use when users ask for full-stack schedule systems, quadrant planning, reminders, Flask/Vue stacks, SQLite APIs, or "no AI vibe" product polish.
---

# Natural Product Scheduler

## Goal
Deliver a full-featured schedule product with strong product feel: clear information architecture, practical interactions, and realistic defaults.

## Stack Defaults
- Frontend: HTML5 + CSS3 + JavaScript + Vue (CDN first, Vite optional)
- Backend: Python + Flask
- Database: SQLite by default (switchable to MySQL/Redis if user asks)
- API: REST with explicit status codes and validation
- Optional AI: local Ollama only; never make AI the core path

## Implementation Rules
1. Build non-AI core first: CRUD, filtering, reminders, persistence.
2. Keep UI purposeful: avoid generic “AI app” chrome; if the user wants playful styling (cartoon, soft shapes), use readable fonts, pastels, and bold borders without clutter.
3. Encode business logic in backend APIs, not only in frontend state.
4. Use predictable naming (`is_important`, `remind_at`, `completed`).
5. Add graceful degradation for reminders (Notification -> alert fallback).
6. Return user-facing errors in concise Chinese when project language is Chinese.

## Quadrant Scheduling Checklist
- [ ] Create/edit/delete tasks
- [ ] Important/Urgent to Q1-Q4 mapping
- [ ] Due time + reminder time
- [ ] Reminder polling endpoint marks reminded records
- [ ] Task completion toggle
- [ ] Mobile-friendly layout

## Ollama Integration Pattern
- Keep endpoint optional (`/api/ai/suggest`)
- Timeout and return `503` with clear message when local model is unavailable
- Output suggestions as utility text, not chat-like persona output

## Response Style
- Speak like a teammate shipping product code.
- Explain what changed, where, and how to run.
- Offer concrete next product upgrades (auth, stats, export, recurring tasks).
