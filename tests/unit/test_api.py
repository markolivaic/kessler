"""The HTTP surface, through the real entry point.

One of these is the end-to-end path the standard asks for: pick an object, take a real
passage off it, apply a burn, and get a changed miss distance back, all through the
app rather than around it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from kessler.api import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_health_reports_the_snapshot_it_loaded(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["snapshot"]
    assert body["passages"] > 0


def test_provenance_says_no_model_is_trained(client):
    body = client.get("/api/provenance").json()
    assert body["trained_model"] is False
    assert body["model_output"] is True
    assert "no covariance" in body["covariance"].lower()
    assert "not a substitute" in body["not_a_warning_service"].lower()


def test_provenance_carries_coverage_as_a_number(client):
    coverage = client.get("/api/provenance").json()["coverage"]
    assert coverage["on_orbit_catalogued"] > coverage["screened"] > 0
    assert 0 < coverage["screened_percent"] < 100
    assert coverage["debris_screened"] < coverage["debris_on_orbit"]


def test_the_catalogue_arrays_are_all_the_same_length(client):
    body = client.get("/api/catalogue").json()
    count = body["count"]
    for key in ("norad", "name", "type", "group", "perigee_km", "apogee_km"):
        assert len(body[key]) == count, f"{key} is {len(body[key])} against count {count}"


def test_the_tle_endpoint_returns_three_lines_per_object(client):
    body = client.get("/api/catalogue.tle").text
    lines = body.strip().split("\n")
    count = client.get("/api/catalogue").json()["count"]
    assert len(lines) == count * 3
    assert lines[1].startswith("1 ")
    assert lines[2].startswith("2 ")


def test_the_tle_order_matches_the_catalogue_order(client):
    """The browser ties a point to its name by index, so the two must not diverge."""
    catalogue = client.get("/api/catalogue").json()
    lines = client.get("/api/catalogue.tle").text.strip().split("\n")
    for i in (0, 1, 500, 5000, catalogue["count"] - 1):
        assert lines[i * 3] == catalogue["name"][i], f"index {i} disagrees"


def test_an_unknown_object_is_a_404_not_an_empty_answer(client):
    response = client.get("/api/object/99999999")
    assert response.status_code == 404
    assert "not in the" in response.json()["detail"]


def test_a_known_object_returns_its_record(client):
    body = client.get("/api/object/25544").json()
    assert body["name"] == "ISS (ZARYA)"
    assert body["object_type"] == "PAY"
    assert body["screened_to_km"] == 5.0


def test_the_station_reports_its_docked_vehicles_as_artefacts_not_passages(client):
    """The trap this project exists to avoid, checked through the API."""
    body = client.get("/api/object/25544").json()
    assert len(body["artefacts"]) > 0
    for row in body["artefacts"]:
        assert row["classification"] != "passage"
    for row in body["passages"]:
        assert row["classification"] == "passage"


def test_the_artefacts_endpoint_explains_itself(client):
    body = client.get("/api/artefacts").json()
    assert body["count"] > 0
    assert "shared-element-set" in body["rules"]
    assert "co-orbiting" in body["rules"]
    assert "space station" in body["note"]


@pytest.fixture(scope="module")
def a_real_passage(client):
    """A genuine passage from the precomputed screen, to drive the manoeuvre with."""
    rows = client.get("/api/artefacts").json()["rows"]
    assert rows
    for norad in (57681, 25544, 900):
        body = client.get(f"/api/object/{norad}").json()
        for passage in body["passages"]:
            return body["norad"], passage
    pytest.skip("no passage available in this snapshot to exercise the manoeuvre")


def test_the_encounter_curve_has_its_minimum_inside_the_window(client, a_real_passage):
    norad, passage = a_real_passage
    from datetime import UTC, datetime

    start = datetime.strptime(
        client.get("/api/provenance").json()["snapshot_date"], "%Y-%m-%d"
    ).replace(tzinfo=UTC)
    offset = (datetime.fromisoformat(passage["tca_utc"]) - start).total_seconds()
    body = client.get(
        f"/api/encounter?a={passage['norad_a']}&b={passage['norad_b']}&tca_offset_s={offset}"
    ).json()
    assert body["min_km"] == pytest.approx(passage["miss_km"], abs=0.02)
    assert len(body["offsets_s"]) == len(body["separation_km"])


def test_a_burn_changes_the_miss_distance_end_to_end(client, a_real_passage):
    """Input to output through the real entry point, which is the path that matters."""
    from datetime import UTC, datetime

    norad, passage = a_real_passage
    start = datetime.strptime(
        client.get("/api/provenance").json()["snapshot_date"], "%Y-%m-%d"
    ).replace(tzinfo=UTC)
    tca_offset = (datetime.fromisoformat(passage["tca_utc"]) - start).total_seconds()
    burn_offset = max(0.0, tca_offset - 3 * 3600.0)
    partner = passage["norad_b"] if passage["norad_a"] == norad else passage["norad_a"]

    response = client.post(
        "/api/manoeuvre",
        json={
            "norad": norad,
            "partner_norad": partner,
            "tca_offset_s": tca_offset,
            "burn_offset_s": burn_offset,
            "in_track_ms": 0.05,
            "position_sigma_km": 0.5,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["before"]["min_km"] == pytest.approx(passage["miss_km"], abs=0.05)
    assert body["inversion"]["converged"] is True
    # The whole point of the tool: a 5 cm/s burn hours ahead moves the encounter.
    assert abs(body["change_km"]) > 0.01, "a 50 mm/s burn should move a miss distance"
    assert body["probability"]["before"]["position_sigma_km"] == 0.5
    assert "orders of magnitude" in body["probability"]["warning"]


def test_a_burn_after_the_encounter_is_refused(client, a_real_passage):
    norad, passage = a_real_passage
    partner = passage["norad_b"] if passage["norad_a"] == norad else passage["norad_a"]
    response = client.post(
        "/api/manoeuvre",
        json={
            "norad": norad,
            "partner_norad": partner,
            "tca_offset_s": 3600.0,
            "burn_offset_s": 7200.0,
            "in_track_ms": 0.05,
        },
    )
    assert response.status_code == 422
    assert "before the encounter" in response.json()["detail"]


def test_no_probability_is_returned_when_no_uncertainty_is_supplied(client, a_real_passage):
    """Omitting sigma must mean silence, not a default that looks authoritative."""
    from datetime import UTC, datetime

    norad, passage = a_real_passage
    start = datetime.strptime(
        client.get("/api/provenance").json()["snapshot_date"], "%Y-%m-%d"
    ).replace(tzinfo=UTC)
    tca_offset = (datetime.fromisoformat(passage["tca_utc"]) - start).total_seconds()
    partner = passage["norad_b"] if passage["norad_a"] == norad else passage["norad_a"]
    body = client.post(
        "/api/manoeuvre",
        json={
            "norad": norad,
            "partner_norad": partner,
            "tca_offset_s": tca_offset,
            "burn_offset_s": max(0.0, tca_offset - 3600.0),
            "in_track_ms": 0.0,
        },
    ).json()
    assert "probability" not in body


def test_a_zero_burn_reports_essentially_no_change(client, a_real_passage):
    from datetime import UTC, datetime

    norad, passage = a_real_passage
    start = datetime.strptime(
        client.get("/api/provenance").json()["snapshot_date"], "%Y-%m-%d"
    ).replace(tzinfo=UTC)
    tca_offset = (datetime.fromisoformat(passage["tca_utc"]) - start).total_seconds()
    partner = passage["norad_b"] if passage["norad_a"] == norad else passage["norad_a"]
    body = client.post(
        "/api/manoeuvre",
        json={
            "norad": norad,
            "partner_norad": partner,
            "tca_offset_s": tca_offset,
            "burn_offset_s": max(0.0, tca_offset - 3600.0),
            "in_track_ms": 0.0,
        },
    ).json()
    assert abs(body["change_km"]) < 0.001
    assert body["inversion"]["residual_m"] < 0.001
