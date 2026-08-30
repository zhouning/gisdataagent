from sqlalchemy.engine import make_url

from scripts.certify_martin_active_release import (
    MARTIN_DATABASE_PORT,
    _url_without_sqlalchemy_driver,
)


def test_martin_fixture_connection_uses_the_docker_postgres_port():
    source = make_url("postgresql+psycopg://postgres:postgres@127.0.0.1:5433/gis_agent")

    container_url = _url_without_sqlalchemy_driver(
        source.set(
            username="martin_fixture",
            password="fixture_password",
            host="db",
            port=MARTIN_DATABASE_PORT,
            database="gda_martin_release_cert_fixture",
        )
    )

    assert container_url.drivername == "postgresql"
    assert container_url.host == "db"
    assert container_url.port == 5432
    assert container_url.database == "gda_martin_release_cert_fixture"
