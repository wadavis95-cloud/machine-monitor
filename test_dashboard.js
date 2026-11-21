const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const { runInNewContext } = require("node:vm");

const template = readFileSync(join(__dirname, "templates", "index.html"), "utf8");
const script = template.match(/<script>\s*([\s\S]*?)<\/script>/)[1];

function enginePanel(unit, finalCycle, live) {
  const cycle = { dataset: { reading: "cycle" }, textContent: "—" };
  const temperature = { dataset: { reading: "s_2" }, textContent: "—" };
  const status = { textContent: "Waiting" };
  const chartArea = { hidden: false };
  const chartNotice = { hidden: true };
  const warning = { dataset: {}, hidden: true };
  const warningMessage = { textContent: "" };
  const rulSummary = { hidden: true };
  const rul = { hidden: true, textContent: "" };
  const split = { hidden: true, textContent: "", dataset: {} };
  const elements = {
    "[data-status]": status,
    "[data-chart-notice]": chartNotice,
    "[data-rul-summary]": rulSummary,
    "[data-rul]": rul,
    "[data-split]": split,
    canvas: {
      parentElement: chartArea,
      dataset: {
        unit: String(unit), finalCycle: String(finalCycle), live: live ? "1" : "0",
        bandLower: "640", bandUpper: "645",
      },
    },
    "[data-warning]": warning,
    "[data-warning-message]": warningMessage,
    "[data-acknowledge]": { addEventListener() {} },
  };
  return {
    cycle,
    temperature,
    status,
    chartArea,
    chartNotice,
    warning,
    warningMessage,
    rulSummary,
    rul,
    split,
    querySelector: selector => elements[selector],
    querySelectorAll: () => [cycle, temperature],
  };
}

function startRulPolling(panels, responses) {
  const ticks = [];
  runInNewContext(script, {
    window: { addEventListener: (_, start) => start() },
    document: { getElementById: () => null, querySelectorAll: () => panels },
    setInterval(callback) { ticks.push(callback); },
    async fetch(url) {
      assert.ok(responses.has(url), `Unexpected fetch: ${url}`);
      return { ok: true, json: async () => responses.get(url) };
    },
  });
  return ticks;
}

test("rul text and badge render from readings", async () => {
  const replay = enginePanel(1, 10, false);
  const live = enginePanel(2, 10, true);
  const [tickReplay, tickLive] = startRulPolling([replay, live], new Map([
    ["/api/engine/1/cycle/1", { cycle: 1, s_2: 642, rul_pred: 42, split: "train" }],
    ["/api/engine/2/live?after=0", {
      readings: [{ cycle: 1, s_2: 643, rul_pred: 0, split: "val" }], done: false,
    }],
  ]));

  await tickReplay();
  await tickLive();

  assert.equal(replay.rul.textContent, "Est. ~42 cycles left");
  assert.equal(replay.split.textContent, "seen in training");
  assert.equal(replay.split.dataset.split, "train");
  assert.equal(live.rul.textContent, "Est. ~0 cycles left");
  assert.equal(live.split.textContent, "validation (unseen)");
  assert.equal(live.split.dataset.split, "val");
  for (const panel of [replay, live]) {
    assert.equal(panel.rulSummary.hidden, false);
    assert.equal(panel.rul.hidden, false);
    assert.equal(panel.split.hidden, false);
  }
});

test("rul elements stay hidden without rul_pred", async () => {
  const panel = enginePanel(1, 10, false);
  const [tick] = startRulPolling([panel], new Map([
    ["/api/engine/1/cycle/1", { cycle: 1, s_2: 642 }],
    ["/api/engine/1/cycle/2", { cycle: 2, s_2: 642, rul_pred: 10, split: "train" }],
    ["/api/engine/1/cycle/3", { cycle: 3, s_2: 642, split: "train" }],
  ]));

  await tick();
  assert.equal(panel.rul.hidden, true);
  assert.equal(panel.split.hidden, true);
  await tick();
  assert.equal(panel.rul.hidden, false);
  assert.equal(panel.split.hidden, false);
  await tick();
  assert.equal(panel.cycle.textContent, 3);
  assert.equal(panel.rulSummary.hidden, true);
  assert.equal(panel.rul.hidden, true);
  assert.equal(panel.split.hidden, true);
});

test("live readings and warnings update without Chart.js", async () => {
  const panel = enginePanel(1, 10, true);
  let tick;
  runInNewContext(script, {
    window: { addEventListener: (_, start) => start() },
    document: { getElementById: () => null, querySelectorAll: () => [panel] },
    setInterval(callback) { tick = callback; },
    async fetch(url) {
      assert.equal(url, "/api/engine/1/live?after=0");
      return {
        ok: true,
        json: async () => ({
          readings: [1, 2, 3, 4, 5].map(cycle => ({ cycle, s_2: 646 })),
          done: false,
        }),
      };
    },
  });

  assert.equal(panel.chartArea.hidden, true);
  assert.equal(panel.chartNotice.hidden, false);
  await tick();
  assert.equal(panel.cycle.textContent, 5);
  assert.equal(panel.temperature.textContent, 646);
  assert.equal(panel.status.textContent, "Receiving simulated live readings");
  assert.equal(panel.warning.hidden, false);
  assert.match(panel.warningMessage.textContent, /Warning triggered at cycle 5/);
});

for (const mode of ["replay", "live"]) {
  test(`${mode} charts poll, retry, and complete independently`, async () => {
    const live = mode === "live";
    const first = enginePanel(1, 1, live);
    const second = enginePanel(2, 2, live);
    const timers = new Map();
    const requests = [];
    const traces = [];
    const removedTimers = [];
    let nextTimer = 1;
    let rejectFirst;
    const firstRequest = new Promise((_, reject) => { rejectFirst = reject; });

    function reading(cycle, temperature, done) {
      const row = { cycle, s_2: temperature };
      return { ok: true, json: async () => live ? { readings: [row], done } : row };
    }

    const endpoint = (unit, cycle) => `/api/engine/${unit}/${live ? `live?after=${cycle - 1}` : `cycle/${cycle}`}`;
    runInNewContext(script, {
      window: { addEventListener: (_, start) => start() },
      document: { getElementById: () => null, querySelectorAll: () => [first, second] },
      Chart: class {
        constructor(_, config) {
          this.data = config.data;
          traces.push(this.data.datasets[3].data);
        }
        update() {}
      },
      setInterval(tick, delay) {
        assert.equal(delay, 500);
        const id = nextTimer++;
        timers.set(id, tick);
        return id;
      },
      clearInterval(id) {
        removedTimers.push(id);
        timers.delete(id);
      },
      async fetch(url) {
        requests.push(url);
        if (requests.length === 1) return firstRequest;
        if (url === endpoint(2, 1)) return reading(1, 642, false);
        if (url === endpoint(2, 2)) return reading(2, 643, true);
        assert.equal(url, endpoint(1, 1));
        return reading(1, 641, true);
      },
    });

    assert.equal(timers.size, 2);
    const tickFirst = timers.get(1);
    const tickSecond = timers.get(2);
    const pending = tickFirst();
    await tickFirst();
    await tickSecond();
    assert.deepEqual(requests, [endpoint(1, 1), endpoint(2, 1)]);
    assert.equal(first.cycle.textContent, "—");
    assert.equal(second.cycle.textContent, 1);

    rejectFirst(new Error("Engine 1 request failed"));
    await pending;
    assert.match(first.status.textContent, /Retrying/);
    await tickSecond();
    assert.equal(second.cycle.textContent, 2);
    assert.match(second.status.textContent, /Simulation complete/);
    assert.deepEqual(removedTimers, [2]);

    await tickFirst();
    assert.deepEqual(requests, [endpoint(1, 1), endpoint(2, 1), endpoint(2, 2), endpoint(1, 1)]);
    assert.equal(first.cycle.textContent, 1);
    assert.match(first.status.textContent, /Simulation complete/);
    assert.deepEqual(removedTimers, [2, 1]);
    assert.deepEqual(Array.from(traces[0], point => point.y), [641]);
    assert.deepEqual(Array.from(traces[1], point => point.y), [642, 643]);
  });
}
