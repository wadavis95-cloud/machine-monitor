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
| Data leakage | Seeing tomorrow's weather report while taking today's forecasting quiz. | "I kept future readings and held-out data out of the training inputs so the scores reflect what the model can actually know." |
| Split by engine | Put each person's whole photo album into one pile. | "I split the 100 engines into 80 for training and 20 for validation so no engine appears in both." |
| Fit the scaler on training data only | Mark a ruler using one set of samples, then use it to measure the rest. | "I found each feature's minimum and maximum on training engines and reused that range for validation." |
| Sliding window | Show the latest 30 frames of a video, ending at the current frame. | "Each input window ends at the prediction cycle. At the beginning, I fill missing history by repeating the first reading." |
| Validation mimics the test | Pause a practice video before the ending and guess what happens next. | "I sample five pre-failure cycles per validation engine to practice predicting from incomplete histories." |
| Baseline | Guess the usual commute time before trying a route planner. | "I compared linear regression with a constant prediction so I could measure what the sensor readings added." |
| Root mean squared error (RMSE) | Missing a target by ten steps counts much more than missing by one. | "RMSE summarizes the size of prediction errors in cycles and gives bigger misses more weight." |
| Asymmetric score | Arriving ten minutes late for a flight matters more than arriving ten minutes early. | "NASA's score penalizes predicting too many cycles left more heavily because that can delay maintenance." |
| RUL (Remaining Useful Life) | Miles left before the oil change, but for an engine | "RUL is how many cycles an engine has left before failure; that's what my models predict." |
| RMSE (Root Mean Square Error) | Your typical miss, where big misses count extra | "RMSE is the typical prediction error in cycles. Squaring makes big misses count more, which matters when a miss means a surprise failure." |
| LSTM (Long Short-Term Memory) | A neural network that reads readings in order, like reading a sentence, and remembers what matters | "An LSTM is a neural network for sequences. It reads the last 30 cycles in order and keeps a memory of the trend." |
| Baseline | The simplest reasonable guess, the bar every fancier model must clear | "My baseline was linear regression; each more complex model had to beat its error to justify itself." |
| Feature engineering | Summarize a week of temperatures by its average and how quickly it warmed. | "I gave the tree model two numbers per sensor window, the average reading and its change per cycle." |
| Random forest and gradient boosting | A forest averages guesses from independent teams. Boosting sends each new team to work on what the earlier teams missed. | "I compared both on the same validation rows and chose boosting because it gave lower error across three seeds." |
| LSTM readout | Read the whole weather diary, then use the final notes to make one forecast. | "I used the LSTM's final window step and a linear output layer to predict one number, the cycles left." |
| Early stopping | Save your best practice lap and stop after several slower laps. | "I stopped after four epochs without better validation RMSE and restored the weights from the best epoch." |
| Seeds and reproducibility | Start each card shuffle from a recorded random starting point. | "I fixed the seed for the model's starting weights and batch order, then tried three seeds to measure variation." |
| Holdout used once | Seal the final exam until practice is finished. | "I froze the models and the shipping decision on validation, then scored all three models once on the untouched test set." |
| Capped and uncapped RMSE | Compare a countdown that displays at most 125 with the actual time remaining. | "I scored the same predictions against capped and uncapped labels to show how the training cap affects the reported error." |
| Selection optimism | Picking your best day on a practice test: some of that score was luck, which doesn't carry over to the real exam | "If you use data to make a choice, like when to stop training, scores on that same data look too good. My LSTM slipped from 13.3 on validation to 13.5 on test for that reason." |
| Prediction export | A printed timetable with the edition and print date at the top. | "I saved one prediction row per engine cycle and stamped the file with the model commit and run date so stale exports are easier to spot." |
| Clipping and rounding | Set a speed dial within its allowed range, then snap it to the nearest marked tick. | "I clipped exported estimates to 0–125 cycles and rounded them to whole cycles for the dashboard." |
| Offline vs live inference | Look up a departure in a printed timetable instead of recalculating the schedule for every rider. | "I ran the model offline and saved its estimates, so Flask can look them up by engine and cycle without running the model on each request." |
| Showing model context in the UI | Mark worksheet answers as practice or unseen questions so readers know what was familiar. | "I showed each estimate with a training or validation badge, and cleared it when the latest reading had no prediction." |
| Architecture decision record (ADR) | Leave a note explaining why you chose one route at a fork in the road. | "I write down the context, choice, and reason so someone can understand the tradeoff later." |
| Ubiquitous language / glossary | Use the same words on a map, its signs, and the directions you give. | "I use one agreed term per idea so the docs, code discussions, and UI describe the same thing." |
| Make target | Press a button that starts a saved sequence on an appliance. | "I put linting, formatting checks, and tests behind `make check` so contributors can run them in the same order." |
| Continuous integration | Use the same inspection checklist for each new batch from a factory. | "GitHub Actions runs `make check` in a clean environment on pushes and pull requests to catch problems early." |
| Git branch and pull request | Edit a copy of a shared recipe, then ask someone to review your changes before updating the original. | "I made my changes on a branch and used a pull request to ask for review before merging into main." |
| Branch protection | A door opens only after an inspection passes, even for the building manager. | "I protected `main` so GitHub requires the automated checks to pass before anyone can merge, including admins." |
| PR template | A repair request form prompts everyone to describe the problem and say what they tried. | "I used a pull request template so reviewers always know where to find what changed, why, and how it was tested." |
