const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const { runInNewContext } = require("node:vm");

function element() {
  return {
    children: [],
    dataset: {},
    events: {},
    addEventListener(name, listener) { this.events[name] = listener; },
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
  };
}

async function startPage(fetch) {
  const elements = new Map();
  const timers = [];
  let start;
  runInNewContext(
    readFileSync(join(__dirname, "templates", "assistant.html"), "utf8")
      .match(/<script>\s*([\s\S]*?)<\/script>/)[1],
    {
      window: { addEventListener: (_, listener) => { start = listener; } },
      document: {
        createElement: element,
        getElementById(id) {
          if (!elements.has(id)) elements.set(id, element());
          return elements.get(id);
        },
      },
      fetch,
      setTimeout(callback) { timers.push(callback); },
    },
  );
  await start();
  return { get: id => elements.get(id), timers };
}

function json(data) {
  return { ok: true, json: async () => data };
}

test("renders new steps from a poll without duplicating old ones", async () => {
  const model = { kind: "model", name: "model", args: {}, result: "", duration_ms: 12 };
  const tool = {
    kind: "tool", name: "fleet_status", args: { top_n: 3 },
    result: "Three engines", duration_ms: 5,
  };
  const runs = [
    { status: "running", steps: [model], answer: null, tool_calls: [], drafts: [], error: null },
    {
      status: "done", steps: [model, tool], answer: "Fleet checked.",
      tool_calls: [{ name: "fleet_status", args: { top_n: 3 } }], drafts: [], error: null,
    },
  ];
  const { get, timers } = await startPage(async (url, options) => {
    if (url === "/api/drafts") return json([]);
    if (url === "/api/assistant") {
      assert.equal(options.method, "POST");
      assert.deepEqual(JSON.parse(options.body), { question: "Check the fleet." });
      return json({ run_id: "run-1" });
    }
    assert.equal(url, "/api/assistant/runs/run-1");
    return json(runs.shift());
  });

  get("question").value = "Check the fleet.";
  await get("question-form").events.submit({ preventDefault() {} });
  const steps = get("steps");
  assert.equal(steps.children.length, 1);
  const firstStep = steps.children[0];
  assert.match(firstStep.textContent, /model.*12 ms/);

  await timers.shift()();
  assert.equal(steps.children.length, 2);
  assert.equal(steps.children[0], firstStep);
  assert.match(steps.children[1].textContent, /tool.*fleet_status.*top_n.*Three engines.*5 ms/);
  assert.equal(get("answer").textContent, "Fleet checked.");
  assert.equal(timers.length, 0);
});

test("approve button posts and refreshes drafts", async () => {
  const draftId = "WO-12345678-1234-1234-1234-123456789abc";
  const draft = { id: draftId, kind: "work_order", unit: 1, summary: "Inspect compressor" };
  const requests = [];
  const { get } = await startPage(async (url, options) => {
    requests.push([url, options?.method ?? "GET"]);
    if (url === "/api/drafts") return json(requests.length === 1 ? [draft] : []);
    assert.equal(url, `/api/drafts/${draftId}/approve`);
    return json({ id: draftId, status: "open" });
  });

  const drafts = get("drafts");
  const row = drafts.children[0];
  assert.match(row.textContent, /WO-12345.*Inspect compressor/);
  assert.ok(!row.textContent.includes(draftId));
  const approve = row.children.find(button => button.textContent === "Approve");
  await approve.events.click();

  assert.deepEqual(requests, [
    ["/api/drafts", "GET"],
    [`/api/drafts/${draftId}/approve`, "POST"],
    ["/api/drafts", "GET"],
  ]);
  assert.equal(drafts.children.length, 0);
});
