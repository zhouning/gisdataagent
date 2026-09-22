from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.api import abu_dhabi_flood_routes as flood_routes
from data_agent.uwm.abu_dhabi_flood.customer_hotspots_506 import build_private_bundle


def _write_delivery(path: Path) -> None:
    placemarks = []
    for index, (priority, latitude, longitude, description, center) in enumerate(
        [
            ("Very Important", 24.5, 54.6, "نفق", "المدينة"),
            ("Important", 24.6, 54.7, "شارع", "الشهامة"),
        ],
        start=1,
    ):
        placemarks.append(
            f"""
            <Placemark><name>{index}</name><ExtendedData><SchemaData>
              <SimpleData name="الاولوية">{priority}</SimpleData>
              <SimpleData name="LATIDUE">{latitude}</SimpleData>
              <SimpleData name="LONGITUDE">{longitude}</SimpleData>
              <SimpleData name="الوصف">{description}</SimpleData>
              <SimpleData name="المركز">{center}</SimpleData>
              <SimpleData name="م">{index}</SimpleData>
            </SchemaData></ExtendedData><Point><coordinates>{longitude},{latitude},0</coordinates></Point></Placemark>
            """
        )
    placemarks.append(
        "<Placemark><name>auxiliary</name><Polygon><outerBoundaryIs><LinearRing>"
        "<coordinates>54,24,0 55,24,0 55,25,0 54,24,0</coordinates>"
        "</LinearRing></outerBoundaryIs></Polygon></Placemark>"
    )
    kml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        + "".join(placemarks)
        + "</Document></kml>"
    ).encode("utf-8")
    kmz_buffer = BytesIO()
    with ZipFile(kmz_buffer, "w", ZIP_DEFLATED) as kmz:
        kmz.writestr("doc.kml", kml)
    with ZipFile(path, "w", ZIP_DEFLATED) as delivery:
        delivery.writestr("506 Hot Spots AUH.kmz", kmz_buffer.getvalue())


def test_latest_customer_hotspot_bundle_filters_auxiliary_kml_geometry(tmp_path: Path) -> None:
    source = tmp_path / "FW__Hot_Spots_506.zip"
    output = tmp_path / "private"
    _write_delivery(source)
    manifest = build_private_bundle(source, output, expected_count=2)
    assert manifest["status"] == "ready"
    assert manifest["inventory"]["record_count"] == 2
    assert manifest["quality"]["placemark_count"] == 3
    assert manifest["quality"]["ignored_auxiliary_placemark_count"] == 1


def test_latest_customer_hotspot_routes_require_authentication(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "FW__Hot_Spots_506.zip"
    output = tmp_path / "private"
    _write_delivery(source)
    build_private_bundle(source, output, expected_count=2)
    monkeypatch.setenv("ABU_DHABI_HOTSPOT_506_BUNDLE_ROOT", str(output))
    app = Starlette(routes=flood_routes.get_abu_dhabi_flood_routes())
    with TestClient(app) as client:
        assert client.get("/api/abu-dhabi/flood/hotspots/latest-506/map").status_code == 401

    monkeypatch.setattr(
        flood_routes,
        "_get_user_from_request",
        lambda request: SimpleNamespace(identifier="analyst", metadata={"role": "analyst"}),
    )
    monkeypatch.setattr(flood_routes, "_set_user_context", lambda user: None)
    app = Starlette(routes=flood_routes.get_abu_dhabi_flood_routes())
    with TestClient(app) as client:
        catalog = client.get("/api/abu-dhabi/flood/hotspots/latest-506/catalog")
        assert catalog.status_code == 200
        assert catalog.json()["inventory"]["record_count"] == 2
        response = client.get("/api/abu-dhabi/flood/hotspots/latest-506/map")
        assert response.status_code == 200
        assert len(response.json()["features"]) == 2
        assert response.json()["features"][0]["properties"]["priority"] == "Very Important"
