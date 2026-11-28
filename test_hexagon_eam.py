from threading import Thread

import httpx
import pytest

from app import create_app
from assistant import routes, tools
from assistant.drafts import build_draft_db
from assistant.eam_contract import EAM_UNAVAILABLE_MESSAGE, EAMUnavailable
from assistant.hexagon_eam import HexagonEAM
from assistant.sqlite_eam import SQLiteEAM
from mock_hexagon import app as mock_app

API_KEY = "test-key"
URL = "http://hexagon.test"


def _mock_and_adapter(*, mode="normal", ignore_idempotency=False):
    mock = mock_app.create_app(
        api_key=API_KEY, mode=mode, ignore_idempotency=ignore_idempotency
    )
    return mock, HexagonEAM(URL, API_KEY, transport=httpx.WSGITransport(app=mock))


def _draft_order(ctx):
    return tools.draft_work_order(ctx, 1, "Inspect compressor", "High T24")["draft_id"]


def test_down_response_counts_as_failed_attempt(ctx):
    _, eam = _mock_and_adapter(mode="down")
    draft_id = _draft_order(ctx)

    assert ctx.drafts.send(draft_id, "Morgan", eam) == "approved"

    draft = ctx.drafts.get(draft_id)
    assert draft["attempts"] == 1
    assert draft["external_id"] is None
    assert draft["sending_since"] is None


def test_slow_mock_exceeds_three_second_timeout_and_counts_as_failure(ctx, monkeypatch):
    elapsed = []
    read_timeouts = []
    monkeypatch.setattr(mock_app, "sleep", elapsed.append)
    mock = mock_app.create_app(api_key=API_KEY, mode="slow")

    class TimeoutTransport(httpx.WSGITransport):
        def handle_request(self, request):
            # WSGI runs in-process. Compare the mock delay with HTTPX's read budget.
            start = len(elapsed)
            response = super().handle_request(request)
            timeout = request.extensions["timeout"]["read"]
            read_timeouts.append(timeout)
            if sum(elapsed[start:]) > timeout:
                response.close()
                raise httpx.ReadTimeout(
                    "Mock response exceeded read timeout", request=request
                )
            return response

    eam = HexagonEAM(URL, API_KEY, transport=TimeoutTransport(app=mock))
    draft_id = _draft_order(ctx)
    assert ctx.drafts.send(draft_id, "Morgan", eam) == "approved"
    assert read_timeouts == [3]
    assert elapsed == [mock_app.SLOW_SECONDS]
    assert ctx.drafts.get(draft_id)["attempts"] == 1


def test_lost_reply_retry_finds_one_record_with_idempotency_ignored(ctx):
    mock, eam = _mock_and_adapter(mode="lost-reply", ignore_idempotency=True)
    draft_id = _draft_order(ctx)

    assert ctx.drafts.send(draft_id, "Morgan", eam) == "approved"
    assert ctx.drafts.send(draft_id, "Morgan", eam, retry=True) == "sent"

    records = (
        mock.test_client()
        .get(
            "/references",
            query_string={"reference": draft_id},
            headers={"X-API-Key": API_KEY},
        )
        .get_json()
    )
    (record,) = records
    draft = ctx.drafts.get(draft_id)
    assert draft["attempts"] == 1
    assert draft["external_id"] == record["ID"]
    assert (
        sum(order.wo_id == record["ID"] for order in eam.list_work_orders("ENG-001"))
        == 1
    )


def test_connection_error_maps_to_eam_unavailable():
    def disconnect(request):
        raise httpx.ConnectError("Connection refused", request=request)

    eam = HexagonEAM(URL, API_KEY, transport=httpx.MockTransport(disconnect))
    with pytest.raises(EAMUnavailable):
        eam.list_assets()


def test_bad_key_surfaces_without_counting_as_a_send_failure(ctx):
    mock, _ = _mock_and_adapter()
    eam = HexagonEAM(URL, "wrong-key", transport=httpx.WSGITransport(app=mock))
    draft_id = _draft_order(ctx)

    with pytest.raises(httpx.HTTPStatusError) as error:
        ctx.drafts.send(draft_id, "Morgan", eam)
    assert error.value.response.status_code == 401
    assert ctx.drafts.get(draft_id)["attempts"] == 0


def test_configured_hexagon_works_without_a_local_eam_db(tmp_path, monkeypatch):
    mock, _ = _mock_and_adapter()
    monkeypatch.setenv("EAM_ADAPTER", "hexagon")
    monkeypatch.setenv("HEXAGON_URL", URL)
    monkeypatch.setenv("HEXAGON_API_KEY", API_KEY)
    monkeypatch.setattr(
        "assistant.eam_factory.HexagonEAM",
        lambda url, key: HexagonEAM(url, key, transport=httpx.WSGITransport(app=mock)),
    )
    draft_path = tmp_path / "assistant.sqlite"
    build_draft_db(draft_path)
    application = create_app(eam_path=None, assistant_db_path=draft_path)
    client = application.test_client()
    assert client.get("/api/drafts").get_json() == []

    context = tools.load_context(
        None,
        application.config["ASSISTANT_DATA_DIR"],
        eam=routes.create_eam(application.config),
        draft_path=draft_path,
    )
    draft_id = _draft_order(context)
    assert client.post(f"/api/drafts/{draft_id}/approve").get_json()["status"] == "open"
    detail = client.get(f"/api/drafts/{draft_id}").get_json()
    assert detail["status"] == "sent"
    assert detail["external_id"] != draft_id
    assert context.eam.find_by_reference(draft_id) == detail["external_id"]


def test_review_queue_stays_available_during_an_eam_outage(ctx, monkeypatch):
    draft_id = _draft_order(ctx)
    _, eam = _mock_and_adapter(mode="down")
    monkeypatch.setattr(routes, "create_eam", lambda config: eam)

    client = create_app(eam_path=ctx.db_path).test_client()
    assert (
        client.post(f"/api/drafts/{draft_id}/approve").get_json()["status"]
        == "approved"
    )
    (draft,) = client.get("/api/drafts").get_json()
    assert (draft["status"], draft["attempts"]) == ("approved", 1)
    assert draft["evidence_error"] == EAM_UNAVAILABLE_MESSAGE
    assert "evidence_changes" not in draft


def test_outage_during_run_setup_reports_eam_error(ctx, monkeypatch):
    _, eam = _mock_and_adapter(mode="down")
    workers = []

    def track_thread(**kwargs):
        worker = Thread(**kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr(routes, "create_eam", lambda config: eam)
    monkeypatch.setattr(routes, "Thread", track_thread)
    client = create_app(eam_path=ctx.db_path).test_client()
    started = client.post("/api/assistant", json={"question": "Check the fleet."})
    assert started.status_code == 202
    workers[0].join(timeout=5)
    assert not workers[0].is_alive()
    run_id = started.get_json()["run_id"]
    run = client.get(f"/api/assistant/runs/{run_id}").get_json()
    assert (run["status"], run["error"]) == ("error", EAM_UNAVAILABLE_MESSAGE)


def test_missing_sqlite_file_maps_to_eam_unavailable(tmp_path):
    db_path = tmp_path / "missing.sqlite"

    with pytest.raises(EAMUnavailable):
        SQLiteEAM(db_path).list_assets()

    assert not db_path.exists()
