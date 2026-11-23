from contextlib import closing

from flask import Blueprint, current_app, jsonify

from assistant.eam import connect, decide_draft, list_drafts

assistant_routes = Blueprint("assistant", __name__)


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
