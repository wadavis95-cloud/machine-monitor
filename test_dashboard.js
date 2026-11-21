const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const { runInNewContext } = require("node:vm");

const template = readFileSync(join(__dirname, "templates", "index.html"), "utf8");
const script = template.match(/<script>\s*([\s\S]*?)<\/script>/)[1];

function enginePanel(unit, finalCycle, live) {
  const cycle = { dataset: { reading: "cycle" }, textContent: "—" };
  const status = { textContent: "Waiting" };
  const elements = {
    "[data-status]": status,
    canvas: {
      dataset: {
        unit: String(unit), finalCycle: String(finalCycle), live: live ? "1" : "0",
        bandLower: "640", bandUpper: "645",
      },
    },
    "[data-warning]": { dataset: {}, hidden: true },
    "[data-warning-message]": {},
    "[data-acknowledge]": { addEventListener() {} },
  };
  return {
    cycle,
    status,
    querySelector: selector => elements[selector],
    querySelectorAll: () => [cycle],
  };
}

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
