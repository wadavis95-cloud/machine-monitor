---
name: zoom-out
description: Recap a project's main components and explain how a new change fits into the system. Use when the user asks to zoom out, requests a big-picture walkthrough, or finishes a meaningful change in a project where they want ongoing learning recaps.
---

# Zoom out

After a meaningful change, pause before moving to the next feature. Give a short walkthrough grounded in the current code. For a standalone recap, describe the current system and connect the most recent relevant change to it.

1. Start with what the project does for its user in one sentence.
2. Name the main components and give each one job. Trace one real request, reading, or action through them in order.
3. Point out where the change fits. Explain what was added, why it was needed, and what now owns any affected data or state. Describe the old behavior when it helps explain the change.
4. Explain one or two concrete system trade-offs. Tie each to observable behavior, such as how retries, restarts, or multiple viewers work. State what was verified and where evidence is still missing.
5. Give one file or line to start reading. Use plain language and keep the overview short. Walk through individual lines only when the user asks. When the user asks to see the code, bring the relevant file and line into view if editor control is available.

For Machine-Monitor, a useful example is following one operating cycle from the source file through the loader and Flask API to the browser chart. For a replay change, point out who owns the cycle counter and what happens on restart or retry. Verify the current code before using this example.
