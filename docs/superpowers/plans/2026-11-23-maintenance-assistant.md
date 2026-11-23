# Maintenance Assistant (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this project Codex implements each task via the `codex-run` skill; Claude reviews.

**Goal:** A local-LLM assistant at `/assistant` that answers fleet-planning questions from tool results and drafts work orders / part requests for a person to approve.

**Architecture:** A seeded fake EAM in SQLite plus the existing sensor data and RUL predictions feed plain-Python tools. A hand-built LangGraph `StateGraph` (model node ⇄ tool node) runs `ChatOllama` over those tools. Flask runs each question in a background thread and the page polls for steps, so the graph is seen executing live.

**Tech Stack:** Python 3.14, Flask, pandas, sqlite3 (stdlib), langchain-core, langgraph, langchain-ollama, Ollama (`qwen3:8b`), mermaid.js (CDN), pytest, node:test.

**Spec:** `docs/superpowers/specs/2026-11-23-maintenance-assistant-design.md`

## Global Constraints

- Drafts only: nothing the agent does may change state except inserting rows with `status='draft'`. Only a person (approve/reject endpoints) moves a draft.
- Tools never expose `rul_true`, final cycle, or readings past an engine's `current_cycle`.
- Generic invented names only. No real company data, names, or part numbers.
- `make check` and CI must pass without Ollama installed. The dashboard (`/`, `/engines`) behaviour is unchanged apart from a link to `/assistant`.
- 1 cycle = 1 day. Order buffer = 10 days. Max 6 tool calls and max 3 drafts per question.
- Model from env `ASSISTANT_MODEL`, default `qwen3:8b`, temperature 0.
- New dependencies pinned (`==`) in `requirements.txt`: `langchain-core`, `langgraph`, `langchain-ollama`. Studio CLI goes in `requirements-dev.txt` only if Task 8 finds it needed.
- `data/eam.sqlite` is generated (`make seed`) and gitignored.
- Each model call and tool call writes one key=value log line: `event=assistant_step kind=<model|tool> name=<...> duration_ms=<int> outcome=<ok|error>`, same style as the request logs in `app.py`.

## Spec deviation (approved by the user 2026-11-23)

The spec says `POST /api/assistant` is synchronous and returns `{answer, tool_calls, drafts}`, but also that each step appears on screen *as it happens*. Both can't hold. This plan uses the dashboard's existing pattern (polling): `POST /api/assistant` → `202 {run_id}`; `GET /api/assistant/runs/<run_id>` → `{status: running|done|error, steps: [...], answer, tool_calls, drafts, error}`. Still no token streaming. Server-Sent Events (the server pushes each step) are noted in the spec's "Later phases" as a possible upgrade.

## Review Focus

1. **Ollama not running or model not pulled** → the run ends `status=error` with "Can't reach the local model (is Ollama running? `ollama pull qwen3:8b`)", never a hung page or a 500. (Task 6)
2. **No prediction at an engine's current cycle** → `rul: null`, `needs_order: null`, and the tool text says the estimate is missing; ranking puts it last. (Tasks 3, 1)
3. **The model calls a tool with an unknown unit or part ID** → the tool returns an error string the model can read; the graph keeps running. (Tasks 3, 4)
4. **Approve/reject clicked twice, or on an unknown ID** → second call returns 409 (not a draft) / 404 (unknown), no state change. (Task 4)
5. **Empty or very long question** → `POST /api/assistant` returns 400 for empty/whitespace or > 500 chars; no run starts. (Task 6)

---

### Task 1: Warning flag rule and T24 band in Python

**Files:**
- Create: `assistant/__init__.py` (empty), `assistant/flags.py`
- Modify: `app.py:79-82` (use `t24_band`)
- Test: `test_assistant_flags.py`

**Interfaces:**
- Produces: `t24_band(data: pd.DataFrame, unit: int) -> tuple[float, float]` (5th/95th percentile of `s_2` over cycles 1–30 of all *other* units, exactly today's `app.py` logic). `flag_level(t24: list[float], lower: float, upper: float) -> str` returning `"red" | "yellow" | "none"`, judged at the last reading using the last 10 readings.

Rule: `red` if the last 5 readings are all outside `[lower, upper]`; else `yellow` if ≥ 3 of the last 10 are `> upper`; else `none`. (Unlike the JS, yellow doesn't require the *current* reading to be high: the tool reports state, not an event.)

- [ ] **Step 1: Write failing tests** (band 10–20)
  - `test_flag_none_when_inside_band`: `flag_level([15]*10, 10, 20) == "none"`
  - `test_flag_yellow_three_highs_in_last_ten`: `[15]*7 + [21, 15, 21, 15, 21]` → `"yellow"`
  - `test_flag_ignores_highs_older_than_ten`: `[21,21,21] + [15]*10` → `"none"`
  - `test_flag_red_five_consecutive_outside`: `[15]*5 + [9, 21, 9, 21, 9]` → `"red"`
  - `test_flag_red_beats_yellow`: `[21]*5` → `"red"`
  - `test_flag_short_history`: `[]` → `"none"`; `[21, 21]` → `"none"`
  - `test_band_excludes_own_unit`: a 3-unit frame where unit 1 has extreme early values; `t24_band(df, 1)` is unaffected by them.
- [ ] **Step 2:** `.venv/bin/python -m pytest test_assistant_flags.py -v` → FAIL (module missing)
- [ ] **Step 3:** Implement both functions; replace the inline quantile in `app.py` with `t24_band`.
- [ ] **Step 4:** `make check` → all pass (existing app + JS tests unchanged).
- [ ] **Step 5:** Commit `feat(assistant): port warning flag rule to Python`

### Task 2: Fake EAM schema and deterministic seed

**Files:**
- Create: `assistant/eam.py`, `assistant/seed.py`
- Modify: `.gitignore` (add `data/eam.sqlite`), `Makefile` (add `seed: $(PYTHON) -m assistant.seed`)
- Test: `test_assistant_seed.py`

**Interfaces:**
- Produces: `connect(db_path: Path) -> sqlite3.Connection` (`row_factory = sqlite3.Row`, foreign keys on). `create_schema(conn) -> None`. `build_eam(db_path: Path, data: pd.DataFrame, predictions: dict, seed: int = 0) -> None` (overwrites the file). `predictions` is the dict from `app._load_predictions` (move that function to `assistant/eam.py` as `load_predictions` and import it in `app.py`).
- Tables (columns the spec fixes; add others if needed):
  - `machines(unit PK, line, area, current_cycle, split)`
  - `parts(part_id PK, name, subsystem, on_hand, lead_time_days, unit_cost)`; 10–15 rows, IDs like `P-HPC-01`
  - `work_orders(wo_id PK 'WO-1001'…, unit, type 'corrective'|'pm', symptom, action, parts_used, tech, comments, opened, closed, status 'closed'|'open'|'draft'|'rejected')`
  - `part_requests(pr_id PK 'PR-1001'…, part_id FK, qty, reason, status 'draft'|'submitted'|'rejected', created_by)`
- `current_cycle = round(final_cycle * rng.uniform(0.40, 0.95))` with `numpy.random.default_rng(seed)`. Dates: day = `2026-01-01 + cycle`.

- [ ] **Step 1: Write failing tests** (build into `tmp_path`, from `data/train_FD001.txt` + `data/predictions_FD001.csv`)
  - `test_seed_is_deterministic`: two builds with seed 0 → identical dumps (`conn.iterdump()`).
  - `test_machines_one_row_per_engine`: 100 rows; every `current_cycle / final_cycle` in `[0.40, 0.95]` (±1 cycle for rounding).
  - `test_no_hindsight_columns`: no column in any table named `rul_true`, `final_cycle`, or `rul`.
  - `test_demo_has_an_order_now_case`: at least one part has `on_hand == 0` and at least one engine has predicted RUL at its current cycle ≤ that part's `lead_time_days + 10`.
  - `test_work_order_comments_nonempty`: every closed corrective WO has non-empty `comments`.
- [ ] **Step 2:** run → FAIL
- [ ] **Step 3:** Implement schema + seed + `if __name__ == "__main__"` writing `data/eam.sqlite`.
- [ ] **Step 4:** `make check` → pass; `make seed` creates the file.
- [ ] **Step 5:** Commit `feat(assistant): seed a fake EAM database`

### Task 3: Read-only tools

**Files:**
- Create: `assistant/tools.py`
- Test: `test_assistant_tools.py` (fixture: seed into `tmp_path`, then `load_context`)

**Interfaces:**
- Consumes: Task 1 `t24_band`, `flag_level`; Task 2 `connect`, `load_predictions`.
- Produces:
  - `@dataclass FleetContext(db_path: Path, readings: pd.DataFrame, predictions: dict, bands: dict[int, tuple[float, float]], drafts_made: list[str])`. `readings` holds only rows with `cycle <= current_cycle`.
  - `load_context(db_path: Path, data_dir: Path) -> FleetContext`
  - `fleet_status(ctx, top_n: int = 5) -> list[dict]` keys `unit, rul, flag, current_cycle, split`. Sort: RUL ascending, ties `red < yellow < none`, `rul None` last.
  - `engine_detail(ctx, unit: int) -> dict` keys `unit, rul, flag, split, current_cycle, t24_recent: [{cycle, t24}] (last 10), open_work_orders: [wo_id…]`
  - `parts_for(ctx, unit: int) -> list[dict]` keys `part_id, name, on_hand, lead_time_days, needs_order` where `needs_order = on_hand == 0 and lead_time_days >= rul - 10`, `None` when `rul` is `None`.
  - `work_orders(ctx, unit: int, status: str | None = None) -> list[dict]`
  - Unknown unit → `{"error": "Unknown engine <n>. Valid engines: 1-100."}` (dict, not exception).

- [ ] **Step 1: Write failing tests**
  - `test_fleet_status_sorted_by_rul_then_flag`
  - `test_fleet_status_top_n_limits_rows`
  - `test_tools_never_see_future_readings`: `engine_detail` last `t24_recent` cycle == machine `current_cycle`.
  - `test_parts_for_order_rule`: with RUL 25, part lead 20/on_hand 0 → `True`; lead 10 → `False`; on_hand 2 → `False` (monkeypatch predictions).
  - `test_missing_prediction_gives_none` (Review Focus 2): delete the prediction for one unit; `fleet_status` lists it last with `rul None`; `parts_for` gives `needs_order None`.
  - `test_unknown_unit_returns_error` (Review Focus 3): `engine_detail(ctx, 999)` has `"error"`.
  - `test_work_orders_filters_by_status`
- [ ] **Step 2:** run → FAIL
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `make check` → pass
- [ ] **Step 5:** Commit `feat(assistant): add read-only fleet tools`

### Task 4: Draft tools and approval endpoints

**Files:**
- Modify: `assistant/tools.py`, `assistant/eam.py`, `app.py`
- Create: `assistant/routes.py` (Flask Blueprint, keeps `app.py` small)
- Test: `test_assistant_drafts.py`

**Interfaces:**
- Consumes: Task 3 `FleetContext`.
- Produces:
  - `draft_work_order(ctx, unit: int, summary: str, reason: str) -> dict` → `{"draft_id": "WO-…"}`; `draft_part_request(ctx, part_id: str, qty: int, reason: str) -> dict` → `{"draft_id": "PR-…"}`. Both append to `ctx.drafts_made`; a 4th call returns `{"error": "Draft limit reached (3 per question)."}`. Unknown unit/part or `qty < 1` → `{"error": …}`.
  - `list_drafts(conn) -> list[dict]` keys `id, kind ('work_order'|'part_request'), unit|part_id, summary|reason, qty`.
  - `decide_draft(conn, draft_id: str, approve: bool) -> str` new status; raises `KeyError` (unknown) / `ValueError` (not a draft). WO: `open`/`rejected`; PR: `submitted`/`rejected`.
  - `create_app(predictions_path=..., eam_path: Path | None = DATA_DIR / "eam.sqlite", chat_model_factory=None)` registers the blueprint. Routes: `GET /api/drafts`, `POST /api/drafts/<id>/approve`, `POST /api/drafts/<id>/reject` → `200 {id, status}`, `404`, `409`. Missing EAM file → `503 {"error": "Run make seed first."}`.

- [ ] **Step 1: Write failing tests**
  - `test_draft_work_order_inserts_draft_row`
  - `test_draft_limit_is_three`
  - `test_draft_part_request_rejects_unknown_part`
  - `test_approve_work_order_moves_to_open`; `test_approve_part_request_moves_to_submitted`; `test_reject_sets_rejected`
  - `test_second_approve_returns_409_and_no_change` and `test_unknown_draft_returns_404` (Review Focus 4)
  - `test_drafts_api_503_without_eam`
- [ ] **Step 2:** run → FAIL
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `make check` → pass
- [ ] **Step 5:** Commit `feat(assistant): draft tools and approve/reject API`

### Task 5: LangGraph agent with a scripted fake model

**Files:**
- Modify: `requirements.txt` (pin the three libraries; confirm they install on Python 3.14)
- Create: `assistant/graph.py`
- Test: `test_assistant_graph.py`

**Interfaces:**
- Consumes: Tasks 3–4 tool functions and `FleetContext`.
- Produces:
  - `SYSTEM_PROMPT: str` covering the spec's four rules (tool results only; cite inline like `[fleet_status]`, `[WO-1001]`; never say ordered/submitted, only drafted; say plainly when data is missing).
  - `make_tools(ctx) -> list[BaseTool]`: wraps each tool with `StructuredTool.from_function` + `functools.partial` so the model sees only the typed args and docstring.
  - `build_graph(model, tools, on_step: Callable[[dict], None] = lambda s: None)` → compiled `StateGraph` over `MessagesState`: nodes `model` and `tools`, conditional edge `model → tools | END`, edge `tools → model`. `model` is already tool-bound (`.bind_tools`). After 6 tool calls total, route to END and append `AIMessage("Stopped: tool-call limit (6) reached.")`.
  - Step dict passed to `on_step` and logged: `{kind: "model"|"tool", name, args, result (≤200 chars), duration_ms}`. A tool exception becomes an error-string `ToolMessage` with `outcome=error`.
  - `run_question(graph, question: str) -> dict` → `{answer, tool_calls: [{name, args}], drafts: ctx.drafts_made}`.
  - `mermaid(graph) -> str` = `graph.get_graph().draw_mermaid()`.
- Fake model (in the test file): a class whose `invoke(messages)` pops the next scripted `AIMessage` (with or without `tool_calls`).

- [ ] **Step 1: Write failing tests**
  - `test_graph_calls_tool_then_answers`: script = [AIMessage calling `fleet_status{top_n:3}`, AIMessage("Engine X…")] → answer text matches, `tool_calls == [{"name": "fleet_status", "args": {"top_n": 3}}]`.
  - `test_tool_call_cap_is_six`: model always calls a tool → exactly 6 tool steps, answer mentions the limit.
  - `test_on_step_sees_every_step_in_order`: kinds `model, tool, model`.
  - `test_steps_are_logged` (`caplog`): one `event=assistant_step` line per step.
  - `test_tool_error_does_not_crash_graph`: tool raises → run finishes.
  - `test_mermaid_has_model_and_tools_nodes`
- [ ] **Step 2:** run → FAIL
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `make check` → pass (no Ollama needed).
- [ ] **Step 5:** Commit `feat(assistant): LangGraph agent loop`

### Task 6: Assistant run API (background thread + polling)

**Files:**
- Modify: `assistant/routes.py`, `app.py`
- Test: `test_assistant_api.py`

**Interfaces:**
- Consumes: Task 5 `build_graph`, `make_tools`, `run_question`; Task 4 blueprint and `chat_model_factory`.
- Produces:
  - Default `chat_model_factory()` → `ChatOllama(model=os.environ.get("ASSISTANT_MODEL", "qwen3:8b"), temperature=0)`. Tests inject the fake model.
  - `POST /api/assistant {question}` → `202 {run_id}`; `400` if empty/whitespace or > 500 chars. Each run gets a fresh `FleetContext.drafts_made`.
  - `GET /api/assistant/runs/<run_id>` → `{status, steps, answer, tool_calls, drafts, error}`; `404` unknown. Runs kept in a dict guarded by a `Lock` (same pattern as `playback_lock`).
  - Connection errors to Ollama → `status "error"`, `error` = the Review Focus 1 text.

- [ ] **Step 1: Write failing tests**
  - `test_run_completes_and_returns_answer` (poll until `done`, timeout 5 s)
  - `test_empty_and_long_questions_rejected` (Review Focus 5)
  - `test_unreachable_model_reports_error` (Review Focus 1): factory returns a model whose `invoke` raises `httpx.ConnectError` (or `ConnectionError`).
  - `test_unknown_run_404`
- [ ] **Step 2:** run → FAIL
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `make check` → pass
- [ ] **Step 5:** Commit `feat(assistant): assistant run API`

### Task 7: `/assistant` page with the live graph

**Files:**
- Create: `templates/assistant.html`
- Modify: `assistant/routes.py` (`GET /assistant`), `templates/index.html` (one link)
- Test: `test_assistant_api.py` (page tests), `test_assistant_page.js` (node:test, same `runInNewContext` pattern as `test_dashboard.js`); add it to `make check`.

**Interfaces:**
- Consumes: Task 5 `mermaid(graph)`; Task 6 run API; Task 4 drafts API.
- Page: question box; the Mermaid drawing (mermaid.js from jsDelivr, pinned version) with the active node highlighted; a step list that grows on each poll (kind, name, args, short result, ms); the answer; a collapsible `<details>` "How I got this" with tool calls; a drafts list with Approve/Reject buttons that call the drafts API and re-render.

- [ ] **Step 1: Write failing tests**
  - Python: `test_assistant_page_renders` (200, contains `graph TD`/mermaid source and `id="question"`); `test_dashboard_links_to_assistant`.
  - JS: `renders new steps from a poll without duplicating old ones`; `approve button posts and refreshes drafts`.
- [ ] **Step 2:** run → FAIL
- [ ] **Step 3:** Implement (vanilla JS, no build step).
- [ ] **Step 4:** `make check` → pass
- [ ] **Step 5:** Commit `feat(assistant): /assistant page with live graph`

### Task 8: Run it for real: Ollama, smoke test, LangGraph Studio

**Files:**
- Create: `langgraph.json`, `assistant/studio.py` (module-level `graph` for Studio)
- Modify: `Makefile` (`studio`), `README.md` (setup: Ollama official installer, `ollama pull qwen3:8b`, `make seed`, `make run`, `/assistant`, Studio requirements), `experiments.md` (only if the model is swapped)

- [ ] **Step 1 (user, manual):** install Ollama from ollama.com, `ollama pull qwen3:8b`.
- [ ] **Step 2:** `make seed && make run`; ask "Which 3 engines should we worry about for the next PM?" on `/assistant`. Expected: steps appear live, answer cites `[fleet_status]`, units match `fleet_status(top_n=3)`.
- [ ] **Step 3:** Ask "What parts should we order?" then "Draft a part request for it." Expected: no drafts on the first, one draft on the second; approve it in the UI → status `submitted`.
- [ ] **Step 4:** Check Studio's current requirements (account? network?) and record them in the README. If acceptable, add `langgraph-cli[inmem]` pinned to `requirements-dev.txt` and `studio: .venv/bin/langgraph dev`; run `make studio` and see the graph. If it needs something unacceptable, document why and skip the target.
- [ ] **Step 5:** If `qwen3:8b` mishandles tools, try another 8B model and record why in `experiments.md`.
- [ ] **Step 6:** `make check` → pass; commit `docs(assistant): local setup and Studio`

### Task 9: Golden-set evaluation

**Files:**
- Create: `evals/assistant_golden.py`, `assistant/scoring.py`, `scripts/eval_assistant.py`, `reports/assistant_eval.md`
- Modify: `Makefile` (`eval: $(PYTHON) -m scripts.eval_assistant`; not part of `check`)
- Test: `test_assistant_scoring.py`

**Interfaces:**
- Consumes: Task 3 tools (to compute expected facts at eval time from the same seeded data), Task 5 `run_question`.
- Produces:
  - Golden item: `{"id", "question", "expect_tools": set[str], "expected_facts": Callable[[FleetContext], list[str]], "should_draft": bool}`; ~15 items covering ranking, single-engine detail, parts/order-by, WO history, a missing-data case, and a "draft X" request.
  - `scoring.py`: `tools_ok(called: list[str], expected: set[str]) -> bool` (expected ⊆ called); `facts_ok(answer, facts) -> bool` (all substrings present); `invented_ids(answer, tool_results_text) -> list[str]` (regex `WO-\d+`, `PR-\d+`, `P-[A-Z]+-\d+`, `engine \d+` not found in tool results); `drafts_ok(drafts, should_draft) -> bool`.
  - Script runs each item against a fresh temp seed, prints a table, writes `reports/assistant_eval.md` (model, date, per-item pass/fail, totals).

- [ ] **Step 1: Write failing tests** for the four scoring functions, including `test_invented_ids_flags_wo_not_in_results` and `test_invented_ids_allows_cited_ids`.
- [ ] **Step 2:** run → FAIL
- [ ] **Step 3:** Implement scoring, golden set, script.
- [ ] **Step 4:** `make check` → pass; `make eval` (local, Ollama) → writes baseline report.
- [ ] **Step 5:** Commit `feat(assistant): golden-set eval and baseline`
