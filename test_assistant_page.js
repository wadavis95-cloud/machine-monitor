const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const { runInNewContext } = require("node:vm");

function element(tagName) {
  return {
    tagName,
    children: [],
    attributes: {},
    dataset: {},
    events: {},
    addEventListener(name, listener) { this.events[name] = listener; },
    setAttribute(name, value) { this.attributes[name] = value; },
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

function json(data, ok = true) {
  return { ok, json: async () => data };
}

function descendants(node) {
  return [node, ...node.children.flatMap(descendants)];
}

function buttons(row) {
  return descendants(row).filter(node => node.tagName === "button");
}

function badge(row) {
  return row.children.find(node => node.className === "draft-badge");
}

function workOrder(status, id = `WO-${status}`) {
  return { id, kind: "work_order", unit: 1, summary: "Inspect compressor", status };
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

test("approval shows the sent status and external ID after refreshing", async () => {
  const draftId = "WO-12345678-1234-1234-1234-123456789abc";
  const draft = workOrder("draft", draftId);
  const requests = [];
  const { get } = await startPage(async (url, options) => {
    requests.push([url, options?.method ?? "GET"]);
    if (url === "/api/drafts") return json(requests.length === 1 ? [draft] : []);
    if (url === `/api/drafts/${draftId}`) {
      return json({ ...draft, status: "sent", external_id: "WO-EAM-7" });
    }
    assert.equal(url, `/api/drafts/${draftId}/approve`);
    return json({ id: draftId, status: "open" });
  });

  const drafts = get("drafts");
  const row = drafts.children[0];
  assert.match(row.textContent, /WO-12345.*Inspect compressor/);
  assert.ok(!row.textContent.includes(draftId));
  await buttons(row).find(button => button.textContent === "Approve").events.click();

  assert.deepEqual(requests, [
    ["/api/drafts", "GET"],
    [`/api/drafts/${draftId}/approve`, "POST"],
    [`/api/drafts/${draftId}`, "GET"],
    ["/api/drafts", "GET"],
  ]);
  assert.equal(drafts.children.length, 1);
  const sent = drafts.children[0];
  assert.equal(badge(sent).textContent, "Sent");
  assert.ok(sent.children.some(node => node.textContent === "EAM ID WO-EAM-7"));
  assert.deepEqual(buttons(sent), []);
});

test("shows lifecycle badges and only the actions allowed by each status in API order", async () => {
  const expected = [
    ["send_failed", "Send failed", ["Retry"]],
    ["stale", "Stale", []],
    ["draft", "Draft", ["Approve", "Reject"]],
    ["sent", "Sent", []],
    ["approved", "Approved · not sent", ["Retry"]],
    ["rejected", "Rejected", []],
    ["sending", "Sending", []],
  ];
  const { get } = await startPage(async url => {
    assert.equal(url, "/api/drafts");
    return json(expected.map(([status]) => workOrder(status)));
  });

  assert.deepEqual(Array.from(get("drafts").children, row => [
    badge(row).dataset.status,
    badge(row).textContent,
    buttons(row).map(button => button.textContent),
  ]), expected);
});

test("retry posts to the retry endpoint and shows a failed send inline", async () => {
  let status = "approved";
  const id = "WO-retry";
  const { get } = await startPage(async (url, options) => {
    if (url === "/api/drafts") return json([workOrder(status, id)]);
    assert.equal(url, `/api/drafts/${id}/retry`);
    assert.equal(options.method, "POST");
    status = "send_failed";
    return json({ id, status });
  });

  const drafts = get("drafts");
  await buttons(drafts.children[0])[0].events.click();

  const row = drafts.children[0];
  assert.equal(badge(row).textContent, "Send failed");
  assert.equal(
    row.children.find(node => node.attributes.role === "alert").textContent,
    "Could not send to the EAM. Try again.",
  );
  assert.equal(buttons(row)[0].textContent, "Retry");
  assert.equal(buttons(row)[0].disabled, false);
});

test("rejected stays visible after the API removes it from the review queue", async () => {
  const id = "WO-reject";
  let pending = [workOrder("draft", id)];
  const { get } = await startPage(async (url, options) => {
    if (url === "/api/drafts") return json(pending);
    assert.equal(url, `/api/drafts/${id}/reject`);
    assert.equal(options.method, "POST");
    pending = [];
    return json({ id, status: "rejected" });
  });

  const drafts = get("drafts");
  await buttons(drafts.children[0]).find(button => button.textContent === "Reject").events.click();

  assert.equal(badge(drafts.children[0]).textContent, "Rejected");
  assert.deepEqual(buttons(drafts.children[0]), []);
});

test("shows changed evidence from the API on a stale draft", async () => {
  const draft = {
    ...workOrder("stale"),
    evidence_changes: {
      rul: { stored: 14, current: null },
      stock: {
        stored: { "P-HPC-01": { main: 0, backup: 4 } },
        current: { "P-HPC-01": { main: 12, backup: 4 } },
      },
      work_orders: {
        stored: { "WO-7": { status: "open", comments: "Check" } },
        current: { "WO-7": { status: "closed", comments: "Checked" } },
      },
    },
  };
  const { get } = await startPage(async () => json([draft, workOrder("draft")]));

  const [stale, pending] = get("drafts").children;
  const text = descendants(stale).map(node => node.textContent);
  assert.equal(badge(stale).textContent, "Stale");
  assert.ok(text.includes("Changed since draft"));
  assert.ok(text.includes("P-HPC-01 (main) stock was 0, now 12"));
  assert.ok(text.includes("Remaining life was 14, now unavailable"));
  assert.ok(text.includes("WO-7 status was open, now closed"));
  assert.ok(text.includes("WO-7 comments changed"));
  assert.ok(!text.some(line => line?.includes("backup")));
  assert.ok(!descendants(pending).some(node => node.textContent === "Changed since draft"));
});

for (const [status, action] of [["draft", "Approve"], ["approved", "Retry"]]) {
  test(`${action} errors stay inline after the queue refreshes`, async () => {
    const draft = workOrder(status);
    const { get } = await startPage(async (url, options) => {
      if (url === "/api/drafts") return json([draft]);
      assert.equal(url, `/api/drafts/${draft.id}/${action.toLowerCase()}`);
      assert.equal(options.method, "POST");
      return json({ error: "Draft service unavailable." }, false);
    });

    const drafts = get("drafts");
    await buttons(drafts.children[0]).find(button => button.textContent === action).events.click();

    const row = drafts.children[0];
    assert.equal(row.children.find(node => node.attributes.role === "alert").textContent,
      "Draft service unavailable.");
    assert.equal(buttons(row).find(button => button.textContent === action).disabled, false);
  });
}
