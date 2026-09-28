# CLAUDE.md

This project uses **gstack** for web browsing and other skills.

## gstack

Use the `/browse` skill from gstack for all web browsing. Never use `mcp__claude-in-chrome__*` tools.

### Available gstack skills:
- `/office-hours` — YC Office Hours: two modes
- `/plan-ceo-review` — CEO/founder-mode plan review
- `/plan-eng-review` — Eng manager-mode plan review
- `/plan-design-review` — Designer's eye plan review
- `/plan-devex-review` — Interactive developer experience plan review
- `/design-consultation` — Understands your product, researches landscape, proposes complete design system
- `/design-shotgun` — Generate multiple AI design variants, open comparison board, collect structured feedback
- `/design-html` — Generates production-quality Pretext-native HTML/CSS
- `/design-review` — Designer's eye QA: finds visual inconsistency, spacing issues, hierarchy problems
- `/review` — Pre-landing PR review
- `/deslop-shared-libs` — Find worthwhile shared-code extractions
- `/ship` — Ship workflow: run tests, review diff, bump VERSION, update CHANGELOG, commit, push, create PR
- `/land-and-deploy` — Land and deploy workflow
- `/canary` — Post-deploy canary monitoring
- `/benchmark` — Performance regression detection
- `/browse` — Drive a real browser through Aside: open page, read, click, screenshot, check console errors
- `/connect-chrome` — Launch GStack Browser with sidebar extension
- `/qa` — Systematically QA test a web application and fix bugs
- `/qa-only` — Report-only QA testing
- `/setup-browser-cookies` — Import cookies from real Chromium browser
- `/setup-deploy` — Configure deployment settings for `/land-and-deploy`
- `/setup-gbrain` — Set up gbrain: install CLI, initialize local brain, register MCP
- `/retro` — Weekly engineering retrospective
- `/investigate` — Systematic debugging with root cause investigation
- `/document-release` — Post-ship documentation update
- `/document-generate` — Generate missing documentation from scratch
- `/codex` — OpenAI Codex CLI wrapper (three modes)
- `/cso` — Security audit
- `/autoplan` — Auto-review pipeline (CEO, design, eng, DX reviews)
- `/devex-review` — Live developer experience audit
- `/careful` — Safety guardrails for destructive commands
- `/freeze` — Restrict file edits to specific directory
- `/unfreeze` — Clear freeze boundary
- `/gstack-upgrade` — Upgrade gstack to latest version
- `/learn` — Manage project learnings