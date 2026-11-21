# Learning log

Concepts from this project, in plain words. Review it now and then. Repetition beats cramming.

| Concept | Plain-words picture | Interview one-liner |
|---|---|---|
| Endpoint | A counter at a store; each one handles one kind of request | "An endpoint is a URL on the server that handles one kind of request, e.g. `/live` returns new readings." |
| Simulated live feed | A recorded game replayed on TV as if live | "`/live` replays historical data at 2 cycles/sec so it behaves like a real-time feed." |
| Cursor / `after=N` | A bookmark: "give me everything after page N" | "The client sends its cursor, so the server only returns new rows and no duplicates." |
| Stateless endpoint | The server remembers nothing about you; each request brings its own bookmark | "`/live` is stateless, so each tab is independent. The old `/next` kept one shared cursor on the server, and tabs skipped each other's readings." |
| Race condition | Two people trying to use a one-person bathroom at once | "Two requests at the same moment could both try to start the clock and overwrite each other." |
| Lock | The bathroom door lock: one at a time | "A lock makes check-then-write happen as one step, so the clock starts exactly once." |
| Removing dead code | Don't repair a room nobody uses; remove it | "I confirmed only tests called `/next`, removed it to cut maintenance and a known bug, and verified with tests in an isolated commit." |
| 404 vs 400 | 404 = "that doesn't exist"; 400 = "your request is malformed" | "404 for an unknown engine, 400 for a garbage cursor like `after=banana`." |
| Graceful degradation | If the station display breaks, the announcement still tells you when the train arrives. | "If Chart.js fails to load, the dashboard shows a notice and keeps updating readings and warnings." |
| Optional chaining (`?.`) | Update the whiteboard if there is one, then keep going. | "I used `chart?.update()` to redraw only when the chart exists." |
| Port | An apartment number in your computer's "building" (`127.0.0.1`); one server per apartment | "A port identifies which program on a machine receives traffic. Two servers can't listen on the same port." |
| Restart after code changes | A server reads your code once at startup, like printing a page; editing the file doesn't change the printout | "A running server keeps the code it started with, so after a change you restart it, or use a dev/reload mode." |
| Remaining useful life (RUL) label | A countdown to the engine's last cycle, with zero at failure. | "For each training row, I subtract its cycle from that engine's failure cycle to get the true cycles left." |
| Capping RUL at 125 | A road sign says “more than 125 miles” until the destination gets closer. | "For training, all labels above 125 become 125, because early readings may give little evidence of exactly how far away failure is." |
| Virtual environment | A toolbox for one project with its own set of tools. | "A virtual environment keeps the project's Python packages separate from other projects, and pinning versions records the ones I used." |
| scikit-learn | A toolbox of ready-made power tools; every model has the same `fit` / `predict` buttons | "I used scikit-learn for the baselines because its shared fit/predict interface makes models quick to swap and compare." |
| PyTorch | LEGO for neural networks: you build the network and write the training loop (forward → loss → backward → step) | "I used PyTorch for the LSTM because sequence models need a custom architecture and training loop. It runs offline only; the app serves saved predictions." |
