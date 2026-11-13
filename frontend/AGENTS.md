# AGENTS.md — frontend

Next.js screens reused from `liranostack/vv` (decision in the ERD), with internal engine calls replaced by a
WebSocket client (`lib/ws.ts`) that mirrors `vv_contracts.ws`. Modes: live (`NEXT_PUBLIC_WS_URL`),
mock (`NEXT_PUBLIC_WS_MOCK=1`) and replay of a recorded journey (`NEXT_PUBLIC_REPLAY=<file>`).

**Does not:** call models, hold business rules, or import Supabase/Gemini.

- User-facing text in pt-BR. Screens: consent + retention (30 days), quick-choice onboarding, chat with streaming,
  progress (layer n of 4 → Pre-Core → Core), layer syntheses with source excerpts, Pre-Core review,
  Essential Core with before/after and 7-day plan.
- Checks: `npm ci && npm run lint && npm run build && npx vitest run`.
