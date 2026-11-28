from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace

import pytest

from app import create_app
from assistant import drafts, routes, tools
from assistant.eam import connect


@pytest.fixture
def work_order_id(ctx):
    return tools.draft_work_order(ctx, 1, "Inspect compressor", "High T24")["draft_id"]


def _draft_client(db_path):
    app = create_app(eam_path=db_path)
    app.config["TESTING"] = True
    return app.test_client()


def _work_order(conn, draft_id):
    return conn.execute(
        "SELECT * FROM work_orders WHERE wo_id = ?", (draft_id,)
    ).fetchone()


def _audit(ctx, draft_id):
    with closing(connect(ctx.drafts.path)) as conn:
        return [
            (row["action"], row["actor"], datetime.fromisoformat(row["at"]))
            for row in conn.execute(
                "SELECT action, actor, at FROM audit WHERE draft_id = ? ORDER BY id",
                (draft_id,),
            )
        ]


def test_draft_only_exists_in_assistant_db(ctx, conn, work_order_id):
    assert ctx.drafts_made == [work_order_id]
    assert _work_order(conn, work_order_id) is None
    (draft,) = _draft_client(ctx.db_path).get("/api/drafts").get_json()
    assert (draft["id"], draft["kind"], draft["unit"], draft["summary"]) == (
        work_order_id,
        "work_order",
        1,
        "Inspect compressor",
    )
    assert draft["status"] == "draft"
    assert draft["payload"]["asset_id"] == "ENG-001"
    assert draft["payload"]["wo_id"] == work_order_id
    assert draft["evidence"]["created_by"] == "assistant"


def test_draft_limit_is_three(ctx):
    first = tools.draft_work_order(ctx, 1, "Inspect compressor", "High T24")
    second = tools.draft_part_request(ctx, "P-HPC-01", 1, "Seal kit needed")
    third = tools.draft_work_order(ctx, 2, "Inspect compressor", "High T24")

    expected_ids = [first["draft_id"], second["draft_id"], third["draft_id"]]
    assert second["draft_id"].startswith("PR-")
    assert tools.draft_work_order(ctx, 3, "Inspect compressor", "High T24") == {
        "error": "Draft limit reached (3 per question)."
    }
    assert ctx.drafts_made == expected_ids
    queue = _draft_client(ctx.db_path).get("/api/drafts").get_json()
    assert {draft["id"] for draft in queue} == set(expected_ids)
    part = next(draft for draft in queue if draft["id"] == second["draft_id"])
    assert (part["kind"], part["part_id"], part["qty"], part["reason"]) == (
        "part_request",
        "P-HPC-01",
        1,
        "Seal kit needed",
    )


def test_draft_part_request_rejects_unknown_part(ctx, conn):
    result = tools.draft_part_request(ctx, "P-UNKNOWN", 1, "Seal kit needed")

    assert result == {"error": "Unknown part P-UNKNOWN."}
    assert ctx.drafts_made == []
    assert ctx.drafts.review_queue() == []
    assert conn.execute("SELECT COUNT(*) FROM part_requests").fetchone()[0] == 0


def test_approve_work_order_moves_to_open(ctx, conn, work_order_id):
    client = _draft_client(ctx.db_path)
    response = client.post(
        f"/api/drafts/{work_order_id}/approve", json={"actor": "Morgan"}
    )

    assert response.status_code == 200
    assert response.get_json() == {"id": work_order_id, "status": "open"}
    sent = _work_order(conn, work_order_id)
    assert (sent["status"], sent["reference"], sent["action"]) == (
        "open",
        work_order_id,
        "Inspect compressor",
    )
    assert ctx.eam.find_by_reference(work_order_id) == work_order_id
    assert client.get("/api/drafts").get_json() == []
    draft = client.get(f"/api/drafts/{work_order_id}").get_json()
    assert draft["status"] == "sent"
    assert draft["external_id"] == work_order_id
    assert draft["attempts"] == 0
    audit = _audit(ctx, work_order_id)
    assert [(action, actor) for action, actor, _ in audit] == [
        ("drafted", "assistant"),
        ("approved", "Morgan"),
        ("sending", "Morgan"),
        ("sent", "system"),
    ]
    assert all(at.utcoffset() == timedelta(0) for _, _, at in audit)


def test_approve_part_request_moves_to_submitted(ctx, conn):
    draft_id = tools.draft_part_request(ctx, "P-HPC-01", 2, "Seal kit needed", unit=1)[
        "draft_id"
    ]
    response = _draft_client(ctx.db_path).post(f"/api/drafts/{draft_id}/approve")

    assert response.status_code == 200
    assert response.get_json() == {"id": draft_id, "status": "submitted"}
    request = conn.execute(
        "SELECT * FROM part_requests WHERE reference = ?", (draft_id,)
    ).fetchone()
    assert (
        request["pr_id"],
        request["unit"],
        request["status"],
        request["reason"],
    ) == (
        draft_id,
        1,
        "submitted",
        "Seal kit needed",
    )
    line = conn.execute(
        "SELECT part_id, qty, unit FROM part_request_lines WHERE pr_id = ?", (draft_id,)
    ).fetchone()
    assert tuple(line) == ("P-HPC-01", 2, "each")
    assert ctx.eam.find_by_reference(draft_id) == draft_id


def test_reject_sets_rejected(ctx, conn, work_order_id):
    response = _draft_client(ctx.db_path).post(
        f"/api/drafts/{work_order_id}/reject", json={"actor": "Morgan"}
    )

    assert response.get_json() == {"id": work_order_id, "status": "rejected"}
    assert ctx.drafts.get(work_order_id)["status"] == "rejected"
    assert _audit(ctx, work_order_id)[-1][:2] == ("rejected", "Morgan")
    assert _work_order(conn, work_order_id) is None


def test_overlapping_approvals_send_once(ctx, work_order_id, monkeypatch):
    entered_send = Event()
    finish_send = Event()
    sent_refs = []

    def send(order, ref):
        sent_refs.append(ref)
        entered_send.set()
        assert finish_send.wait(timeout=5)
        return "WO-EXTERNAL"

    monkeypatch.setattr(
        routes, "SQLiteEAM", lambda path: SimpleNamespace(submit_work_request=send)
    )
    url = f"/api/drafts/{work_order_id}/approve"
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(lambda: _draft_client(ctx.db_path).post(url))
        try:
            assert entered_send.wait(timeout=5)
            assert ctx.drafts.get(work_order_id)["status"] == "sending"
            assert _draft_client(ctx.db_path).post(url).status_code == 409
        finally:
            finish_send.set()
        assert first.result(timeout=5).status_code == 200
    assert sent_refs == [work_order_id]
    assert ctx.drafts.get(work_order_id)["external_id"] == "WO-EXTERNAL"


def test_lost_reply_retry_uses_reference_before_sending(
    ctx, work_order_id, monkeypatch
):
    created = {}
    calls = []

    def send(order, ref):
        calls.append(("submit", ref))
        assert order.wo_id == ref
        # This fake creates a new record on every send.
        created[ref] = f"external-{len(calls)}"
        raise TimeoutError("response lost")

    def lookup(ref):
        calls.append(("lookup", ref))
        return created.get(ref)

    fake = SimpleNamespace(submit_work_request=send, find_by_reference=lookup)
    monkeypatch.setattr(routes, "SQLiteEAM", lambda path: fake)
    client = _draft_client(ctx.db_path)
    base = f"/api/drafts/{work_order_id}"
    assert client.post(base + "/approve").get_json()["status"] == "approved"
    assert client.post(base + "/retry").get_json() == {
        "id": work_order_id,
        "status": "sent",
    }
    assert client.post(base + "/retry").status_code == 409
    assert calls == [("submit", work_order_id), ("lookup", work_order_id)]
    draft = ctx.drafts.get(work_order_id)
    assert draft["attempts"] == 1
    assert draft["external_id"] == created[work_order_id]


def test_three_failures_mark_send_failed_and_lookup_failure_never_submits(
    ctx, work_order_id
):
    calls = []

    def fail(*args):
        calls.append("submit")
        raise ConnectionError("EAM unavailable")

    def lookup(ref):
        calls.append("lookup")
        raise ConnectionError("EAM unavailable")

    fake = SimpleNamespace(submit_work_request=fail, find_by_reference=lookup)
    assert ctx.drafts.send(work_order_id, "Morgan", fake) == "approved"
    assert ctx.drafts.send(work_order_id, "Morgan", fake, retry=True) == "approved"
    assert ctx.drafts.send(work_order_id, "Morgan", fake, retry=True) == "send_failed"
    draft = ctx.drafts.get(work_order_id)
    assert draft["attempts"] == 3
    assert draft["external_id"] is None
    assert draft["sending_since"] is None
    assert calls == ["submit", "lookup", "lookup"]
    actions = [action for action, _, _ in _audit(ctx, work_order_id)]
    assert actions.count("attempt_failed") == 2
    assert actions[-1] == "send_failed"
    # Manual retry is still available after the threshold.
    fake.find_by_reference = lambda ref: "WO-FOUND"
    assert ctx.drafts.send(work_order_id, "Morgan", fake, retry=True) == "sent"
    assert ctx.drafts.get(work_order_id)["attempts"] == 3


def test_stuck_sending_recovers_and_checks_reference(ctx, work_order_id):
    previous = (
        datetime.now(UTC) - timedelta(seconds=drafts.SENDING_TIMEOUT + 1)
    ).isoformat()
    with closing(connect(ctx.drafts.path)) as conn, conn:
        conn.execute(
            "UPDATE drafts SET status = 'sending', sending_since = ? WHERE id = ?",
            (previous, work_order_id),
        )

    (draft,) = ctx.drafts.review_queue()
    assert (draft["status"], draft["sending_since"], draft["attempts"]) == (
        "approved",
        None,
        0,
    )
    lookups = []

    def lookup(ref):
        lookups.append(ref)

    fake = SimpleNamespace(
        find_by_reference=lookup, submit_work_request=lambda order, ref: "WO-NEW"
    )
    assert ctx.drafts.send(work_order_id, "reviewer", fake, retry=True) == "sent"
    assert lookups == [work_order_id]
    assert ("recovered", "system") in [
        (action, actor) for action, actor, _ in _audit(ctx, work_order_id)
    ]


def test_old_unreviewed_draft_becomes_stale_without_deletion(ctx, work_order_id):
    created_at = datetime.fromisoformat(ctx.drafts.get(work_order_id)["created_at"])
    with closing(connect(ctx.drafts.path)) as conn, conn:
        conn.execute(
            "UPDATE drafts SET created_at = ? WHERE id = ?",
            ((created_at - timedelta(days=8)).isoformat(), work_order_id),
        )

    client = _draft_client(ctx.db_path)
    assert client.post(f"/api/drafts/{work_order_id}/approve").status_code == 409
    assert _audit(ctx, work_order_id)[-1][:2] == ("stale", "system")
    (draft,) = client.get("/api/drafts").get_json()
    assert (draft["id"], draft["status"]) == (work_order_id, "stale")


def test_work_order_dedupe_matches_asset_and_problem_and_retains_id(ctx):
    first = tools.draft_work_order(ctx, 1, "Inspect seal", "High T24", "Seal")
    revised = tools.draft_work_order(
        ctx, 1, "Inspect seal housing", "Updated evidence", " seal "
    )
    another_problem = tools.draft_work_order(
        ctx, 1, "Inspect bearing", "Noise", "bearing"
    )
    another_asset = tools.draft_work_order(ctx, 2, "Inspect seal", "High T24", "seal")

    assert first == revised
    assert (
        len({first["draft_id"], another_problem["draft_id"], another_asset["draft_id"]})
        == 3
    )
    assert (
        ctx.drafts.get(first["draft_id"])["payload"]["comments"] == "Updated evidence"
    )


def test_work_order_dedupe_prefers_problem_code(ctx):
    first = tools.draft_work_order(ctx, 1, "Inspect seal", "High T24", "seal", "LEAK")
    revised = tools.draft_work_order(
        ctx, 1, "Investigate leak", "Updated", "housing", "leak"
    )

    assert first == revised
    assert ctx.drafts.get(first["draft_id"])["payload"]["summary"] == "Investigate leak"


def test_part_dedupe_matches_asset_and_part_and_updates_quantity(ctx):
    first = tools.draft_part_request(ctx, "P-HPC-01", 1, "Seal kit needed", unit=1)
    revised = tools.draft_part_request(ctx, "P-HPC-01", 2, "Include a spare", unit=1)
    another_asset = tools.draft_part_request(
        ctx, "P-HPC-01", 1, "Seal kit needed", unit=2
    )
    another_part = tools.draft_part_request(ctx, "P-HPC-02", 1, "Vane", unit=1)

    assert first == revised
    assert (
        len({first["draft_id"], another_asset["draft_id"], another_part["draft_id"]})
        == 3
    )
    assert ctx.drafts.get(first["draft_id"])["payload"]["lines"][0]["qty"] == 2
    assert _audit(ctx, first["draft_id"])[-1][:2] == ("updated", "assistant")


def test_drafts_api_shows_evidence_changes_without_overwriting_snapshot(ctx, conn):
    draft_id = tools.draft_part_request(ctx, "P-HPC-01", 1, "Seal kit needed", unit=1)[
        "draft_id"
    ]
    client = _draft_client(ctx.db_path)
    url = f"/api/drafts/{draft_id}"
    before = client.get(url).get_json()
    assert before["evidence_changes"] == {}
    with conn:
        conn.execute("UPDATE parts SET on_hand = 12 WHERE part_id = 'P-HPC-01'")
        conn.execute("UPDATE work_orders SET status = 'open' WHERE wo_id = 'WO-1001'")
        conn.execute("UPDATE machines SET current_cycle = 999 WHERE unit = 1")

    after = client.get(url).get_json()
    assert after["evidence"] == before["evidence"]
    changes = after["evidence_changes"]
    assert changes["stock"] == {
        "stored": {"P-HPC-01": {"main": 0}},
        "current": {"P-HPC-01": {"main": 12}},
    }
    assert changes["work_orders"]["current"]["WO-1001"]["status"] == "open"
    assert changes["rul"] == {"stored": before["evidence"]["rul"], "current": None}
    assert client.get("/api/drafts").get_json()[0]["evidence_changes"] == changes


def test_unknown_draft_returns_404(ctx):
    client = _draft_client(ctx.db_path)
    assert client.post("/api/drafts/WO-UNKNOWN/approve").status_code == 404
    assert client.get("/api/drafts/WO-UNKNOWN").status_code == 404


def test_drafts_api_503_when_database_missing(tmp_path):
    db_path = tmp_path / "missing.sqlite"
    client = _draft_client(db_path)

    for response in (
        client.get("/api/drafts"),
        client.post("/api/drafts/WO-TEST/approve"),
        client.post("/api/drafts/WO-TEST/reject"),
        client.post("/api/drafts/WO-TEST/retry"),
    ):
        assert response.status_code == 503
        assert response.get_json() == {"error": "Run make seed first."}
    assert not db_path.exists()
