from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from threading import Barrier

import pytest

from app import create_app


class ElementIdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = Counter()

    def handle_starttag(self, tag, attrs):
        self.ids.update(value for name, value in attrs if name == "id")


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_dashboard_returns_http_200(client):
    response = client.get("/")
    assert response.status_code == 200


def test_dashboard_has_required_element_ids(client):
    response = client.get("/")
    parser = ElementIdParser()
    parser.feed(response.get_data(as_text=True))
    assert {"cycle", "s_2", "s_3", "s_4", "chart", "restart"} <= parser.ids.keys()


def test_multi_engine_view_defaults_to_four_engines(client):
    response = client.get("/engines")
    page = response.get_data(as_text=True)
    parser = ElementIdParser()
    parser.feed(page)

    assert response.status_code == 200
    for unit, final_cycle in [(1, 192), (2, 287), (3, 179), (4, 189)]:
        assert f'<h2 id="engine-heading-{unit}">Engine {unit}</h2>' in page
        assert f'data-unit="{unit}"' in page
        assert f'data-final-cycle="{final_cycle}"' in page
        assert f"chart-{unit}" in parser.ids
    assert all(count == 1 for count in parser.ids.values())
    assert 'href="/engines?mode=replay"' in client.get("/").get_data(as_text=True)


def test_multi_engine_view_preserves_selected_engines_and_mode(client):
    response = client.get("/engines?unit=3&unit=1&unit=3&mode=live")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert page.index('data-unit="3"') < page.index('data-unit="1"')
    assert page.count('data-unit="3"') == 1
    assert page.count('data-live="1"') == 2
    assert 'data-unit="2"' not in page
    assert 'href="/engines?unit=1&amp;mode=live"' in page
    assert 'href="/?unit=3&amp;mode=live"' in page


@pytest.mark.parametrize("unit", ["999", "invalid"])
def test_multi_engine_view_rejects_invalid_engine(client, unit):
    assert (
        client.get("/engines", query_string=[("unit", "1"), ("unit", unit)]).status_code
        == 404
    )


def test_cycle_lookup_can_restart_without_advancing_another_client(client):
    other_tab = client.application.test_client()
    first = client.get("/api/engine/1/cycle/1").get_json()
    second = other_tab.get("/api/engine/1/cycle/2").get_json()

    assert (first["unit"], first["cycle"], second["cycle"]) == (1, 1, 2)
    assert client.get("/api/engine/1/cycle/1").get_json() == first
    assert other_tab.get("/api/engine/1/cycle/2").get_json() == second
    assert client.get("/api/engine/1/cycle/193").status_code == 404


def test_dashboard_loads_selected_engine_and_its_final_cycle(client):
    response = client.get("/?unit=2")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Engine 2 · Simulated run to failure" in page
    assert '<option value="2" selected>' in page
    assert 'data-unit="2"' in page
    assert 'data-final-cycle="287"' in page
    assert client.get("/api/engine/2/cycle/287").get_json()["unit"] == 2


@pytest.mark.parametrize("unit", ["999", "invalid"])
def test_dashboard_rejects_invalid_engine(client, unit):
    assert client.get("/", query_string={"unit": unit}).status_code == 404


def test_live_readings_follow_shared_server_clock(client, monkeypatch):
    now = 100.0
    monkeypatch.setattr("app.monotonic", lambda: now)
    other_tab = client.application.test_client()

    def cycles(viewer, after):
        response = viewer.get(f"/api/engine/1/live?after={after}")
        assert response.status_code == 200
        body = response.get_json()
        return [row["cycle"] for row in body["readings"]], body["done"]

    assert cycles(client, 0) == ([1], False)
    assert cycles(other_tab, 0) == ([1], False)
    assert cycles(client, 1) == ([], False)
    now += 1.5
    assert cycles(client, 1) == ([2, 3, 4], False)
    assert cycles(other_tab, 3) == ([4], False)
    now += 100
    assert cycles(client, 190) == ([191, 192], True)
    assert cycles(other_tab, 192) == ([], True)


def test_live_feed_serves_concurrent_viewers_without_advancing(client, monkeypatch):
    now = 100.0
    monkeypatch.setattr("app.monotonic", lambda: now)
    viewer_count = 16

    def poll_together(cursors):
        barrier = Barrier(viewer_count)

        def poll(after):
            with client.application.test_client() as viewer:
                barrier.wait(timeout=10)
                response = viewer.get(
                    "/api/engine/1/live", query_string={"after": after}
                )
                assert response.status_code == 200
                assert response.cache_control.no_store
                payload = response.get_json()
                assert not payload["done"]
                assert all(row["unit"] == 1 for row in payload["readings"])
                return [row["cycle"] for row in payload["readings"]]

        with ThreadPoolExecutor(max_workers=viewer_count) as pool:
            return list(pool.map(poll, cursors))

    assert poll_together([0] * viewer_count) == [[1]] * viewer_count

    now += 4
    cursors = [0, 3, 8, 9] * 4
    expected = [list(range(after + 1, 10)) for after in cursors]
    assert poll_together(cursors) == expected


def test_live_engines_have_independent_clocks(client, monkeypatch):
    now = 100.0
    monkeypatch.setattr("app.monotonic", lambda: now)
    assert client.get("/api/engine/1/live").get_json()["readings"][0]["cycle"] == 1

    now += 2
    engine_2 = client.get("/api/engine/2/live").get_json()
    engine_1 = client.get("/api/engine/1/live?after=1").get_json()
    assert [(row["unit"], row["cycle"]) for row in engine_2["readings"]] == [(2, 1)]
    assert [row["cycle"] for row in engine_1["readings"]] == [2, 3, 4, 5]


@pytest.mark.parametrize("cursor", ["", "-1", "abc", "1.5", "12345678901"])
def test_live_feed_rejects_invalid_cursors(client, cursor):
    response = client.get("/api/engine/1/live", query_string={"after": cursor})
    assert response.status_code == 400


def test_live_feed_rejects_unknown_engine(client):
    assert client.get("/api/engine/999/live").status_code == 404


@pytest.fixture
def predictions_path(tmp_path):
    path = tmp_path / "predictions.csv"
    path.write_text(
        "# model_commit=abc123 run_date=2026-11-21\n"
        "unit,cycle,split,rul_linear,rul_trees,rul_lstm\n"
        "1,1,train,88,42,77\n"
        "1,4,train,90,NaN,80\n"
        "1,5,train,90,no estimate,80\n"
        "1,6,train,90,inf,80\n"
        "2,287,val,13,0,22\n"
    )
    return path


def test_live_includes_rul_and_split(predictions_path):
    client = create_app(predictions_path=predictions_path).test_client()
    response = client.get("/api/engine/1/live")
    reading = response.get_json()["readings"][0]

    assert response.status_code == 200
    assert reading["rul_pred"] == 42
    assert type(reading["rul_pred"]) is int
    assert reading["split"] == "train"


def test_cycle_includes_rul_and_split(predictions_path):
    client = create_app(predictions_path=predictions_path).test_client()
    response = client.get("/api/engine/2/cycle/287")
    reading = response.get_json()

    assert response.status_code == 200
    assert reading["rul_pred"] == 0
    assert reading["split"] == "val"


def test_live_without_predictions_file(tmp_path):
    client = create_app(predictions_path=tmp_path / "missing.csv").test_client()
    response = client.get("/api/engine/1/live")
    body = response.get_json()

    assert response.status_code == 200
    assert response.cache_control.no_store
    assert body["done"] is False
    (reading,) = body["readings"]
    assert (reading["unit"], reading["cycle"]) == (1, 1)
    assert "s_2" in reading
    assert "rul_pred" not in reading and "split" not in reading


def test_live_missing_row_omits_rul(predictions_path, monkeypatch):
    now = 100.0
    monkeypatch.setattr("app.monotonic", lambda: now)
    client = create_app(predictions_path=predictions_path).test_client()
    assert client.get("/api/engine/1/live").status_code == 200
    now += 2.5

    response = client.get("/api/engine/1/live?after=2")
    readings = response.get_json()["readings"]
    assert [reading["cycle"] for reading in readings] == [3, 4, 5, 6]
    assert all(
        "rul_pred" not in reading and "split" not in reading for reading in readings
    )


def test_duplicate_prediction_rows_raise(tmp_path):
    path = tmp_path / "predictions.csv"
    path.write_text("unit,cycle,split,rul_trees\n1,1,train,42\n1,1,val,NaN\n")

    with pytest.raises(ValueError, match=r"Duplicate.*unit.*cycle"):
        create_app(predictions_path=path)
