from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from assistant.eam import load_predictions
from assistant.seed import build_eam
from assistant.sqlite_eam import SQLiteEAM
from loader import load_data
from mock_hexagon import app

DATA_DIR = Path(__file__).with_name("data")
AUTH = {"X-API-Key": "test-key"}
WORK = {
    "REFERENCE": "WO-draft",
    "ASSET": {"ID": "ENG-001"},
    "SUMMARY": "Inspect compressor",
    "COMMENTS": "Chk T24 probe",
    "PROBLEM": {"CODE": "HIGH_TEMP"},
}
PART = {
    "REFERENCE": "PR-draft",
    "STORE": "main",
    "ASSET": {"ID": "ENG-001"},
    "LINES": [{"PART": {"ID": "P-HPC-01"}, "QUANTITY": 2}],
}


@pytest.fixture
def client():
    return app.create_app(
        api_key="test-key", mode="normal", ignore_idempotency=False
    ).test_client()


def test_auth_rejects_missing_or_wrong_key_for_reads_and_writes(client):
    for headers in ({}, {"X-API-Key": "wrong"}):
        assert client.get("/assets", headers=headers).status_code == 401
        assert (
            client.post("/workrequests", headers=headers, json=WORK).status_code == 401
        )

    assert client.get("/assets", headers=AUTH).status_code == 200


def test_asset_and_order_lookup_and_filters(client):
    asset = client.get("/assets/ENG-003", headers=AUTH).get_json()
    assert (asset["ID"], asset["NAME"], asset["LOCATION"]) == (
        "ENG-003",
        "Engine 3",
        "Line 3",
    )
    assert client.get("/assets/unknown", headers=AUTH).status_code == 404
    assert client.get("/workorders/unknown", headers=AUTH).status_code == 404

    response = client.get("/workorders?asset=ENG-003&status=open", headers=AUTH)
    (order,) = response.get_json()
    assert order["ID"] == "WO-1003"
    assert order["ASSET"] == {"ID": "ENG-003"}
    assert order["STATUS"] == {"CODE": "OPEN"}
    assert order["ORDER_TYPE"] == {"CODE": "REPAIR"}
    assert order["PROBLEM"] is None
    assert order["COMMENTS"] == "Chk speed pikup at nxt svc window."
    assert client.get("/workorders/WO-1003", headers=AUTH).get_json() == order
    assert (
        client.get("/workorders?asset=ENG-003&status=closed", headers=AUTH).get_json()
        == []
    )


def test_mock_rebuilds_the_same_fleet_stock_and_orders_with_shorthand(client, tmp_path):
    path = tmp_path / "eam.sqlite"
    build_eam(
        path,
        load_data(DATA_DIR / "train_FD001.txt"),
        load_predictions(DATA_DIR / "predictions_FD001.csv"),
        seed=0,
    )
    eam = SQLiteEAM(path)
    assets = eam.list_assets()
    mock_assets = client.get("/assets", headers=AUTH).get_json()
    assert [
        (row["ID"], row["NAME"], row["LOCATION"], row["CURRENT_CYCLE"])
        for row in mock_assets
    ] == [
        (asset.asset_id, asset.name, asset.location, asset.current_cycle)
        for asset in assets
    ]
    mock_parts = client.get("/parts", headers=AUTH).get_json()
    parts = eam.list_parts()
    assert [
        (row["ID"], row["NAME"], row["UOM"], row["LEAD_DAYS"], row["UNIT_COST"])
        for row in mock_parts
    ] == [
        (
            part.part_id,
            part.name,
            part.unit_of_measure,
            part.lead_time_days,
            part.unit_cost,
        )
        for part in parts
    ]
    assert [
        [(stock["STORE"], stock["ON_HAND"]) for stock in row["STOCK"]]
        for row in mock_parts
    ] == [[(stock.store, stock.on_hand) for stock in part.stock] for part in parts]
    orders = [
        order for asset in assets for order in eam.list_work_orders(asset.asset_id)
    ]
    mock_orders = client.get("/workorders", headers=AUTH).get_json()
    assert [
        (
            row["ID"],
            row["ASSET"]["ID"],
            row["STATUS"]["CODE"].lower(),
            row["OPENED"],
            row["CLOSED"],
            row["SUMMARY"],
            row["PROBLEM_DESCRIPTION"],
        )
        for row in mock_orders
    ] == [
        (
            order.wo_id,
            order.asset_id,
            order.status,
            order.opened,
            order.closed,
            order.summary,
            order.problem_description,
        )
        for order in orders
    ]
    assert Counter(row["COMMENTS"] for row in mock_orders) == {
        "T24 back in norm rng on nxt run.": 34,
        "Oil pressure held steady during tst run.": 33,
        "Chk speed pikup at nxt svc window.": 33,
    }


@pytest.mark.parametrize(
    ("path", "body", "kind", "state"),
    [
        ("/workrequests", WORK, "WORK_REQUEST", "REQUESTED"),
        ("/partrequisitions", PART, "PART_REQUISITION", "SUBMITTED"),
    ],
)
def test_idempotent_submit_and_reference_lookup(client, path, body, kind, state):
    headers = {**AUTH, "Idempotency-Key": "request-key"}
    created = client.post(path, headers=headers, json=body)
    assert created.status_code == 201
    record = created.get_json()
    assert record["STATUS"] == {"CODE": state}

    replay = client.post(path, headers=headers, json={**body, "REFERENCE": "changed"})
    assert replay.status_code == 200
    assert replay.get_json() == record
    lookup = client.get(
        "/references", headers=AUTH, query_string={"reference": body["REFERENCE"]}
    )
    assert lookup.get_json() == [
        {"ID": record["ID"], "KIND": kind, "REFERENCE": body["REFERENCE"]}
    ]
    assert client.get("/references?reference=unknown", headers=AUTH).get_json() == []

    if kind == "WORK_REQUEST":
        date.fromisoformat(record["OPENED"])
        assert record["COMMENTS"] == WORK["COMMENTS"]
        assert record["PROBLEM"] == {"CODE": "HIGH_TEMP"}
        assert (
            client.get(f"/workorders/{record['ID']}", headers=AUTH).get_json() == record
        )
        orders = client.get(
            "/workorders?asset=ENG-001&status=open", headers=AUTH
        ).get_json()
        assert orders == [record]
    else:
        assert record["LINES"] == [
            {"PART": {"ID": "P-HPC-01"}, "QUANTITY": 2, "UOM": "each"}
        ]


def test_invalid_requests_do_not_create_records(client):
    assert (
        client.post(
            "/workrequests", headers=AUTH, json={"SUMMARY": "No reference"}
        ).status_code
        == 400
    )
    invalid_asset = {**WORK, "ASSET": {"ID": "ENG-999"}}
    assert (
        client.post("/workrequests", headers=AUTH, json=invalid_asset).status_code
        == 400
    )
    invalid_line = {**PART, "LINES": [{"PART": {"ID": "P-HPC-01"}, "QUANTITY": False}]}
    assert (
        client.post("/partrequisitions", headers=AUTH, json=invalid_line).status_code
        == 400
    )
    for reference in (WORK["REFERENCE"], PART["REFERENCE"]):
        assert (
            client.get(f"/references?reference={reference}", headers=AUTH).get_json()
            == []
        )


def test_down_mode_returns_503_after_auth(monkeypatch):
    monkeypatch.setenv("MOCK_HEXAGON_MODE", "down")
    monkeypatch.setenv("MOCK_HEXAGON_API_KEY", "test-key")
    client = app.create_app().test_client()

    assert client.get("/assets").status_code == 401
    assert client.get("/assets", headers=AUTH).status_code == 503
    assert client.post("/workrequests", headers=AUTH, json=WORK).status_code == 503


def test_slow_mode_waits_past_client_timeout(monkeypatch):
    waits = []
    monkeypatch.setattr(app, "sleep", waits.append)
    client = app.create_app(api_key="test-key", mode="slow").test_client()

    assert client.get("/parts", headers=AUTH).status_code == 200
    assert len(waits) == 1
    assert waits[0] > 3


@pytest.mark.parametrize("ignore_key", [False, True])
def test_lost_reply_saves_before_failure_and_can_ignore_replay_key(
    monkeypatch, ignore_key
):
    monkeypatch.setenv("MOCK_HEXAGON_IGNORE_IDEMPOTENCY", "1" if ignore_key else "0")
    client = app.create_app(api_key="test-key", mode="lost-reply").test_client()
    headers = {**AUTH, "Idempotency-Key": "WO-draft"}
    query = "/references?reference=WO-draft"

    assert client.post("/workrequests", headers=headers, json=WORK).status_code == 502
    (first,) = client.get(query, headers=AUTH).get_json()
    assert client.get(f"/workorders/{first['ID']}", headers=AUTH).status_code == 200

    replay = client.post("/workrequests", headers=headers, json=WORK)
    records = client.get(query, headers=AUTH).get_json()
    if ignore_key:
        assert replay.status_code == 502
        assert len({item["ID"] for item in records}) == 2
    else:
        assert replay.status_code == 200
        assert replay.get_json()["ID"] == first["ID"]
        assert records == [first]
