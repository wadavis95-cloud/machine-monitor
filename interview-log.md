# Interview log

- 2026-11-21 | selection optimism | partial | Got "best could be lucky"; mixed in seed instability; must say "chose on validation, test once"
- 2026-11-21 | RUL cap at 125 | partial | Got "early wear invisible"; wrongly said info isn't discarded / framed as saving resources; it's about unlearnable targets
- 2026-11-23 | p95 vs average | missed | Didn't know; average hides rare slow requests (19×10ms + 1×1000ms → avg 60ms, p95 10ms); users make many requests so they hit the tail
- 2026-11-26 | agent loop walkthrough | review | Said "agent looks through data"; core: model decides (requests tool), code acts, loop until answer
- 2026-11-26 | tools vs pasting DB | partial | Got cost; core: fetch only what you need, when you need it (fit, focus, fresh, traceable)
- 2026-11-26 | polling vs long request | partial | Got unpredictable duration; wait is same, polling avoids timeouts/blocked worker + shows progress
- 2026-11-26 | eval not in CI | partial | Got code vs model distinction; missing: model output varies + slow -> flaky CI
- 2026-11-26 | eval failures = grader bug | review | Thought model read the fixed code; it was the scorer rejecting "Unit 27"; check the measuring tool first
