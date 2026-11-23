import os
from contextlib import closing
from threading import Thread
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, render_template, request
from httpx import ConnectError
from langchain_ollama import ChatOllama
from ollama import ResponseError

from assistant.eam import connect, decide_draft, list_drafts
from assistant.graph import build_graph, make_tools, mermaid, run_question
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
    if db_path is None or not db_path.exists():
        with lock:
            run.update(status="error", error="Run make seed first.")
        return

    try:
        # A fresh context starts this question with an empty draft list.
        ctx = load_context(db_path, app.config["ASSISTANT_DATA_DIR"])
        tools = make_tools(ctx)
        factory = app.config["CHAT_MODEL_FACTORY"] or chat_model_factory
        model = factory()
        # Ollama needs the tool definitions. Scripted test models already know their calls.
        if hasattr(model, "bind_tools"):
            model = model.bind_tools(tools)
        graph = build_graph(model, tools, ctx=ctx, on_step=on_step)
        result = run_question(graph, question)
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


@assistant_routes.get("/api/drafts")
def get_drafts():
    db_path = current_app.config["EAM_PATH"]
    if db_path is None or not db_path.exists():
        return jsonify(error="Run make seed first."), 503
    with closing(connect(db_path)) as conn:
        return jsonify(list_drafts(conn))


@assistant_routes.post("/api/drafts/<draft_id>/approve", defaults={"approve": True})
@assistant_routes.post("/api/drafts/<draft_id>/reject", defaults={"approve": False})
def post_draft_decision(draft_id, approve):
    db_path = current_app.config["EAM_PATH"]
    if db_path is None or not db_path.exists():
        return jsonify(error="Run make seed first."), 503
    with closing(connect(db_path)) as conn:
        try:
            status = decide_draft(conn, draft_id, approve)
        except KeyError:
            return jsonify(error="Draft not found."), 404
        except ValueError as error:
            return jsonify(error=str(error)), 409
    return jsonify(id=draft_id, status=status)
