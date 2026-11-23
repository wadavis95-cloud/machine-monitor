import pytest

from app import create_app
from assistant import eam, tools


@pytest.fixture
def work_order_id(conn):
    # Seed the draft directly so the route tests can run without the draft tool.
    draft_id = "WO-TEST"
    conn.execute(
        "INSERT INTO work_orders (wo_id, unit, type, status) VALUES (?, ?, ?, ?)",
        (draft_id, 1, "corrective", "draft"),
    )
    conn.commit()
    return draft_id


def _draft_client(db_path):
    app = create_app(eam_path=db_path)
    app.config["TESTING"] = True
    return app.test_client()


def _work_order(conn, draft_id):
    return conn.execute(
        "SELECT * FROM work_orders WHERE wo_id = ?", (draft_id,)
    ).fetchone()


# A work order is saved as a draft and appears in the draft list.
def test_draft_work_order_inserts_draft_row(ctx, conn):
    result = tools.draft_work_order(ctx, 1, "Inspect compressor", "High T24")

    draft_id = result["draft_id"]
    assert result == {"draft_id": draft_id}
    assert draft_id.startswith("WO-")
    assert ctx.drafts_made == [draft_id]
    row = _work_order(conn, draft_id)
    assert (row["unit"], row["status"]) == (1, "draft")
    (draft,) = eam.list_drafts(conn)
    assert (draft["id"], draft["kind"], draft["unit"], draft["summary"]) == (
        draft_id,
        "work_order",
        1,
        "Inspect compressor",
    )


# Work orders and part requests share one three-draft limit per question.
def test_draft_limit_is_three(ctx, conn):
    first = tools.draft_work_order(ctx, 1, "Inspect compressor", "High T24")
    second = tools.draft_part_request(ctx, "P-HPC-01", 1, "Seal kit needed")
    third = tools.draft_work_order(ctx, 2, "Inspect compressor", "High T24")

    expected_ids = [first["draft_id"], second["draft_id"], third["draft_id"]]
    assert second["draft_id"].startswith("PR-")
    assert tools.draft_work_order(ctx, 3, "Inspect compressor", "High T24") == {
        "error": "Draft limit reached (3 per question)."
    }
    assert ctx.drafts_made == expected_ids
    drafts = eam.list_drafts(conn)
    assert sorted(draft["id"] for draft in drafts) == sorted(expected_ids)
    part = next(draft for draft in drafts if draft["id"] == second["draft_id"])
    assert (part["kind"], part["part_id"], part["qty"], part["reason"]) == (
        "part_request",
        "P-HPC-01",
        1,
        "Seal kit needed",
    )


# An unknown part returns an error and creates no draft.
def test_draft_part_request_rejects_unknown_part(ctx, conn):
    result = tools.draft_part_request(ctx, "P-UNKNOWN", 1, "Seal kit needed")

    assert isinstance(result["error"], str) and result["error"]
    assert ctx.drafts_made == []
    assert conn.execute("SELECT COUNT(*) FROM part_requests").fetchone()[0] == 0


# Approving a work order saves it as open.
def test_approve_work_order_moves_to_open(ctx, conn, work_order_id):
    response = _draft_client(ctx.db_path).post(f"/api/drafts/{work_order_id}/approve")

    assert response.status_code == 200
    assert response.get_json() == {"id": work_order_id, "status": "open"}
    assert _work_order(conn, work_order_id)["status"] == "open"


# Approving a part request saves it as submitted.
def test_approve_part_request_moves_to_submitted(ctx, conn):
    draft_id = "PR-TEST"
    conn.execute(
        "INSERT INTO part_requests (pr_id, part_id, qty, reason, status, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (draft_id, "P-HPC-01", 1, "Seal kit needed", "draft", "assistant"),
    )
    conn.commit()

    response = _draft_client(ctx.db_path).post(f"/api/drafts/{draft_id}/approve")

    assert response.status_code == 200
    assert response.get_json() == {"id": draft_id, "status": "submitted"}
    row = conn.execute(
        "SELECT status FROM part_requests WHERE pr_id = ?", (draft_id,)
    ).fetchone()
    assert row["status"] == "submitted"


# Rejecting a draft saves it as rejected.
def test_reject_sets_rejected(ctx, conn, work_order_id):
    response = _draft_client(ctx.db_path).post(f"/api/drafts/{work_order_id}/reject")

    assert response.status_code == 200
    assert response.get_json() == {"id": work_order_id, "status": "rejected"}
    assert _work_order(conn, work_order_id)["status"] == "rejected"


# A second approval returns 409 and leaves the saved work order unchanged.
def test_second_approve_returns_409_and_no_change(ctx, conn, work_order_id):
    client = _draft_client(ctx.db_path)
    url = f"/api/drafts/{work_order_id}/approve"
    assert client.post(url).status_code == 200
    approved_row = _work_order(conn, work_order_id)

    assert client.post(url).status_code == 409
    assert _work_order(conn, work_order_id) == approved_row


# Approving an unknown draft returns 404.
def test_unknown_draft_returns_404(ctx):
    response = _draft_client(ctx.db_path).post("/api/drafts/WO-UNKNOWN/approve")

    assert response.status_code == 404


# The drafts API returns 503 with seed instructions when the database is missing.
def test_drafts_api_503_without_eam(tmp_path):
    db_path = tmp_path / "missing.sqlite"
    client = _draft_client(db_path)

    for response in (
        client.get("/api/drafts"),
        client.post("/api/drafts/WO-TEST/approve"),
        client.post("/api/drafts/WO-TEST/reject"),
    ):
        assert response.status_code == 503
        assert response.get_json() == {"error": "Run make seed first."}
    assert not db_path.exists()
