import os
from threading import Thread
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, render_template, request
from httpx import ConnectError
from langchain_ollama import ChatOllama
from ollama import ResponseError

from assistant.asset_ids import unit_for_asset_id
from assistant.drafts import DraftStore
from assistant.eam import load_predictions
from assistant.evidence import recheck_evidence
from assistant.graph import build_graph, make_tools, mermaid, run_question
from assistant.guardrails import finalize_answer
from assistant.sqlite_eam import SQLiteEAM
from assistant.tools import load_context

assistant_routes = Blueprint("assistant", __name__)
MODEL_ERROR = "Can't reach the local model (is Ollama running? `ollama pull qwen3:8b`)"


@assistant_routes.get("/assistant")
def assistant_page():
    # Drawing the graph doesn't call the model or tools.
    graph = build_graph(None, [])
    return render_template("assistant.html", graph_source=mermaid(graph))


def chat_model_factory():
    return ChatOllama(
        model=os.environ.get("ASSISTANT_MODEL", "qwen3:8b"), temperature=0
    )


def _run_in_background(app, run, lock, question):
    def on_step(step):
        with lock:
            run["steps"].append(step)

    db_path = app.config["EAM_PATH"]
    draft_path = app.config["ASSISTANT_DB_PATH"]
    if (
        db_path is None
        or not db_path.exists()
        or draft_path is None
        or not draft_path.exists()
    ):
        with lock:
            run.update(status="error", error="Run make seed first.")
        return

    try:
        # A fresh context starts this question with an empty draft list.
        ctx = load_context(
            db_path, app.config["ASSISTANT_DATA_DIR"], draft_path=draft_path
        )
        tools = make_tools(ctx)
        factory = app.config["CHAT_MODEL_FACTORY"] or chat_model_factory
        model = factory()
        # Ollama needs the tool definitions. Scripted test models already know their calls.
        if hasattr(model, "bind_tools"):
            model = model.bind_tools(tools)
        graph = build_graph(model, tools, ctx=ctx, on_step=on_step)
        result = run_question(graph, question)
        result["answer"] = finalize_answer(
            result["answer"], result["tool_calls"], result["drafts"]
        )
    except Exception as error:
        if isinstance(error, (ConnectError, ConnectionError)) or (
            isinstance(error, ResponseError) and error.status_code == 404
        ):
            message = MODEL_ERROR
        else:
            app.logger.exception("Assistant run failed")
            message = "The assistant could not complete this run."
        with lock:
            run.update(status="error", error=message)
    else:
        with lock:
            run.update(result, status="done")


@assistant_routes.post("/api/assistant")
def start_assistant_run():
    body = request.get_json(silent=True)
    question = body.get("question") if isinstance(body, dict) else None
    if not isinstance(question, str) or not question.strip() or len(question) > 500:
        return jsonify(error="Question must contain 1 to 500 characters."), 400

    app = current_app._get_current_object()
    runs, lock = app.extensions["assistant_runs"]
    run_id = uuid4().hex
    run = {
        "status": "running",
        "steps": [],
        "answer": None,
        "tool_calls": [],
        "drafts": [],
        "error": None,
    }
    with lock:
        runs[run_id] = run
    Thread(
        target=_run_in_background, args=(app, run, lock, question), daemon=True
    ).start()
    return jsonify(run_id=run_id), 202


@assistant_routes.get("/api/assistant/runs/<run_id>")
def get_assistant_run(run_id):
    runs, lock = current_app.extensions["assistant_runs"]
    with lock:
        run = runs.get(run_id)
        if run is None:
            return jsonify(error="Run not found."), 404
        response = jsonify(run)
    response.headers["Cache-Control"] = "no-store"
    return response


def _draft_dependencies():
    eam_path = current_app.config["EAM_PATH"]
    draft_path = current_app.config["ASSISTANT_DB_PATH"]
    if (
        eam_path is None
        or draft_path is None
        or not eam_path.exists()
        or not draft_path.exists()
    ):
        return None
    return DraftStore(draft_path), SQLiteEAM(eam_path)


def _review_payload(draft, eam, predictions):
    payload = draft["payload"]
    record = {
        key: draft[key]
        for key in (
            "id",
            "kind",
            "status",
            "payload",
            "evidence",
            "external_id",
            "attempts",
            "created_at",
            "updated_at",
            "sending_since",
        )
    }
    record["evidence_changes"] = recheck_evidence(draft, eam, predictions)
    if draft["kind"] == "work_order":
        record.update(
            unit=unit_for_asset_id(payload["asset_id"]), summary=payload["summary"]
        )
    else:
        line = payload["lines"][0]
        record.update(
            part_id=line["part_id"], qty=line["qty"], reason=payload["reason"]
        )
    return record


@assistant_routes.get("/api/drafts", defaults={"draft_id": None})
@assistant_routes.get("/api/drafts/<draft_id>")
def get_drafts(draft_id):
    dependencies = _draft_dependencies()
    if dependencies is None:
        return jsonify(error="Run make seed first."), 503
    store, eam = dependencies
    data_dir = current_app.config["ASSISTANT_DATA_DIR"]
    predictions = load_predictions(data_dir / "predictions_FD001.csv")
    if draft_id is None:
        return jsonify(
            [_review_payload(draft, eam, predictions) for draft in store.review_queue()]
        )
    try:
        draft = store.get(draft_id)
    except KeyError:
        return jsonify(error="Draft not found."), 404
    return jsonify(_review_payload(draft, eam, predictions))


@assistant_routes.post("/api/drafts/<draft_id>/approve", defaults={"action": "approve"})
@assistant_routes.post("/api/drafts/<draft_id>/reject", defaults={"action": "reject"})
@assistant_routes.post("/api/drafts/<draft_id>/retry", defaults={"action": "retry"})
def post_draft_decision(draft_id, action):
    dependencies = _draft_dependencies()
    if dependencies is None:
        return jsonify(error="Run make seed first."), 503
    store, eam = dependencies
    body = request.get_json(silent=True)
    actor = body.get("actor", "reviewer") if isinstance(body, dict) else "reviewer"
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 100:
        return jsonify(error="Actor must contain 1 to 100 characters."), 400
    try:
        if action == "reject":
            status = store.reject(draft_id, actor.strip())
        else:
            status = store.send(draft_id, actor.strip(), eam, retry=action == "retry")
    except KeyError:
        return jsonify(error="Draft not found."), 404
    except ValueError as error:
        return jsonify(error=str(error)), 409
    if action == "approve" and status == "sent":
        status = "open" if draft_id.startswith("WO-") else "submitted"
    return jsonify(id=draft_id, status=status)
