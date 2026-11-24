from threading import Event, Thread

import httpx
import pytest
from langchain_core.messages import AIMessage
from ollama import ResponseError

from app import create_app
from assistant import routes
from test_assistant_graph import ScriptedModel, _tool_call


@pytest.fixture
def threads(monkeypatch):
    workers = []

    def track_thread(**kwargs):
        worker = Thread(**kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr(routes, "Thread", track_thread, raising=False)
    return workers


def _start_run(client, question):
    response = client.post("/api/assistant", json={"question": question})
    assert response.status_code == 202
    return f"/api/assistant/runs/{response.get_json()['run_id']}"


def _finished_run(client, url, worker):
    worker.join(timeout=5)
    assert not worker.is_alive()
    response = client.get(url)
    assert response.status_code == 200
    return response.get_json()


# A poll shows completed steps while the model is still working, then the answer.
def test_run_completes_and_returns_answer(ctx, threads):
    waiting_for_answer = Event()
    release_answer = Event()
    answer = "Fleet checked."

    class PausingModel(ScriptedModel):
        def invoke(self, messages):
            if len(self.replies) == 1:
                waiting_for_answer.set()
                assert release_answer.wait(timeout=5)
            return super().invoke(messages)

    def model_factory():
        return PausingModel(_tool_call(), AIMessage(content=answer))

    client = create_app(
        eam_path=ctx.db_path, chat_model_factory=model_factory
    ).test_client()
    try:
        url = _start_run(client, "Check the fleet.")
        assert waiting_for_answer.wait(timeout=5)
        response = client.get(url)
        assert response.status_code == 200
        running = response.get_json()
        assert running["status"] == "running"
        assert [step["kind"] for step in running["steps"]] == ["model", "tool"]
    finally:
        release_answer.set()

    result = _finished_run(client, url, threads[-1])
    steps = result.pop("steps")
    assert result == {
        "status": "done",
        "answer": answer + "\n\nSources: [fleet_status]",
        "tool_calls": [{"name": "fleet_status", "args": {"top_n": 3}}],
        "drafts": [],
        "error": None,
    }
    assert steps[:2] == running["steps"]
    assert [step["kind"] for step in steps] == ["model", "tool", "model"]


# Invalid questions return 400 before a worker starts.
def test_empty_and_long_questions_rejected(threads):
    client = create_app().test_client()
    for body in ({}, {"question": ""}, {"question": " \t "}, {"question": "x" * 501}):
        assert client.post("/api/assistant", json=body).status_code == 400
    assert threads == []


# Both a stopped Ollama server and a missing model end the run with setup help.
@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("Connection refused"), ResponseError("Model not found", 404)],
    ids=["server-down", "model-missing"],
)
def test_unreachable_model_reports_error(ctx, threads, failure):
    class UnreachableModel:
        def invoke(self, messages):
            raise failure

    client = create_app(
        eam_path=ctx.db_path, chat_model_factory=UnreachableModel
    ).test_client()
    url = _start_run(client, "Check the fleet.")

    result = _finished_run(client, url, threads[-1])
    assert result["status"] == "error"
    assert result["error"] == (
        "Can't reach the local model (is Ollama running? `ollama pull qwen3:8b`)"
    )


# Polling an unknown run returns a JSON 404.
def test_unknown_run_404():
    response = create_app().test_client().get("/api/assistant/runs/unknown")

    assert response.status_code == 404
    assert response.get_json() == {"error": "Run not found."}


# Each question can create three drafts even after the previous run used its budget.
def test_each_run_gets_its_own_draft_budget(ctx, threads):
    def model_factory():
        args = {"unit": 1, "summary": "Inspect compressor", "reason": "High T24"}
        calls = [_tool_call("draft_work_order", args, f"call-{i}") for i in range(4)]
        return ScriptedModel(*calls, AIMessage(content="Drafts checked."))

    client = create_app(
        eam_path=ctx.db_path, chat_model_factory=model_factory
    ).test_client()
    draft_ids = []
    for question in ("Draft work orders.", "Draft another set."):
        url = _start_run(client, question)
        result = _finished_run(client, url, threads[-1])
        assert result["status"] == "done"
        assert len(result["drafts"]) == 3
        draft_ids.extend(result["drafts"])

    assert len(set(draft_ids)) == 6


def test_assistant_page_renders():
    response = create_app().test_client().get("/assistant")

    assert response.status_code == 200
    assert b"graph TD" in response.data
    assert b'id="question"' in response.data


def test_dashboard_links_to_assistant():
    client = create_app().test_client()

    for path in ("/", "/engines"):
        response = client.get(path)
        assert response.status_code == 200
        assert b'href="/assistant"' in response.data
