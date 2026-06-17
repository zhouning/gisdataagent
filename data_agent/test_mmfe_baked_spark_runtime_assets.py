"""Tests for MMFE baked Spark runtime assets."""

from pathlib import Path


def test_baked_runtime_dockerfile_contains_required_jars():
    dockerfile = Path("docker/mmfe-spark-runtime/Dockerfile")
    text = dockerfile.read_text(encoding="utf-8")

    expected_jars = [
        "hadoop-aws-3.3.4.jar",
        "aws-java-sdk-bundle-1.12.262.jar",
        "wildfly-openssl-1.0.7.Final.jar",
        "iceberg-spark-runtime-3.5_2.12-1.6.1.jar",
        "sedona-spark-shaded-3.5_2.12-1.9.0.jar",
        "geotools-wrapper-1.9.0-33.5.jar",
    ]
    for jar_name in expected_jars:
        assert jar_name in text

    assert "spark.jars.packages" not in text
    assert "USER 1000" in text


def test_baked_runtime_smoke_forces_empty_packages():
    script = Path("scripts/smoke_mmfe_baked_spark_runtime.sh")
    text = script.read_text(encoding="utf-8")

    assert "ICEBERG_SPARK_PACKAGES=\"\"" in text
    assert "SEDONA_SPARK_PACKAGES=\"\"" in text
    assert "SEDONA_TWM_SPARK_PACKAGES=\"\"" in text
    assert "SEDONA_RASTER_ZONAL_SPARK_PACKAGES=\"\"" in text
    assert "SEDONA_RASTER_CLIP_SPARK_PACKAGES=\"\"" in text
    assert "SPARK_JARS_PACKAGES=\"\"" in text
    assert 'run_smoke scripts/smoke_mmfe_spark_minio.py --packages ""' in text
    assert 'run_smoke scripts/smoke_mmfe_iceberg_minio.py --packages ""' in text
    assert 'run_smoke scripts/smoke_mmfe_sedona_sql.py --packages ""' in text
    assert 'run_smoke scripts/smoke_mmfe_sedona_twm_geojson.py --packages ""' in text
    assert 'run_smoke scripts/smoke_mmfe_sedona_raster.py --packages ""' in text
    assert 'run_smoke scripts/smoke_mmfe_sedona_raster_zonal.py --packages ""' in text
    assert 'run_smoke scripts/smoke_mmfe_sedona_raster_clip.py --packages ""' in text
    assert 'run_smoke scripts/smoke_mmfe_sedona_raster_clip_stac.py --packages ""' in text
