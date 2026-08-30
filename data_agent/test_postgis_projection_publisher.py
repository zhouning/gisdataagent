from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import geopandas as gpd
import pytest

from data_agent.postgis_projection_publisher import publish_geoparquet_to_postgis


class _Result:
    def __init__(self, value=None):
        self.value = value

    def scalar_one(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value


class _Connection:
    def __init__(self, relation_kind=None):
        self.relation_kind = relation_kind
        self.statements = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params))
        if "SELECT COUNT(*)" in sql:
            return _Result(3)
        if "SELECT c.relkind" in sql:
            return _Result(self.relation_kind)
        return _Result()


class _Engine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, relation_kind=None):
        self.connection = _Connection(relation_kind)

    @contextmanager
    def begin(self):
        yield self.connection


class _CRS:
    @staticmethod
    def to_epsg():
        return 4610


class _Frame:
    columns = ["BSM", "geometry"]
    geometry = SimpleNamespace(name="geometry")
    crs = _CRS()

    def __init__(self):
        self.publications = []

    @staticmethod
    def __len__():
        return 3

    def to_postgis(self, name, engine, **kwargs):
        self.publications.append((name, engine, kwargs))


def test_publisher_stages_validates_indexes_and_switches_stable_view(tmp_path, monkeypatch):
    source = tmp_path / "DLTB.parquet"
    source.write_bytes(b"governed")
    frame = _Frame()
    engine = _Engine()
    monkeypatch.setattr(gpd, "read_parquet", lambda _path: frame)

    result = publish_geoparquet_to_postgis(
        source,
        projection_id="a" * 32,
        engine=engine,
    )

    assert result["table_name"] == "public.land_parcel_current"
    assert result["row_count"] == 3
    assert result["srid"] == 4610
    assert frame.publications[0][2]["if_exists"] == "fail"
    statements = "\n".join(sql for sql, _params in engine.connection.statements)
    assert "CREATE INDEX" in statements
    assert 'CREATE VIEW "public"."land_parcel_current"' in statements


def test_publisher_refuses_to_replace_non_view_relation(tmp_path, monkeypatch):
    source = tmp_path / "DLTB.parquet"
    source.write_bytes(b"governed")
    monkeypatch.setattr(gpd, "read_parquet", lambda _path: _Frame())

    with pytest.raises(RuntimeError, match="refusing to replace a non-view"):
        publish_geoparquet_to_postgis(
            source,
            projection_id="b" * 32,
            engine=_Engine(relation_kind="r"),
        )
