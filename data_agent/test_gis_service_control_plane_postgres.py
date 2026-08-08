import os

import pytest
from sqlalchemy import create_engine, text

from scripts.certify_gis_service_control_plane import certify

DATABASE_URL = os.environ.get("DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_postgres_gis_service_control_plane_certification():
    engine = create_engine(DATABASE_URL)
    try:
        with engine.connect() as connection:
            is_superuser = connection.execute(
                text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            ).scalar_one()
        if not is_superuser:
            pytest.skip("GIS service certification requires a PostgreSQL superuser")
    finally:
        engine.dispose()

    report = certify(DATABASE_URL)
    assert report["status"] == "passed"
    assert report["authority"]["inactive_product_source_rejected"] is True
    assert report["authority"]["mixed_layer_style_rejected"] is True
    assert report["authority"]["deployment_without_release_rejected"] is True
    assert report["authority"]["active_pointer_versions"] == [1, 2, 3]
    assert report["counts"]["release_bindings"] == 1
    assert report["security"]["cross_tenant_rows"] == 0
    assert report["migration_catalog"]["latest"] == "154_gis_service_release_binding"
