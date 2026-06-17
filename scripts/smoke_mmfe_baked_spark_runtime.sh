#!/usr/bin/env bash
set -euo pipefail

IMAGE="${MMFE_SPARK_RUNTIME_IMAGE:-gisdataagent/mmfe-spark-runtime:local}"
NETWORK="${MMFE_DOCKER_NETWORK:-gisdataagent_agent-net}"
JAVA_HOME_VALUE="${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-arm64}"

REQUIRED_JARS=(
  "hadoop-aws-3.3.4.jar"
  "aws-java-sdk-bundle-1.12.262.jar"
  "wildfly-openssl-1.0.7.Final.jar"
  "iceberg-spark-runtime-3.5_2.12-1.6.1.jar"
  "sedona-spark-shaded-3.5_2.12-1.9.0.jar"
  "geotools-wrapper-1.9.0-33.5.jar"
)

echo "[mmfe-baked-runtime] image=${IMAGE}"
echo "[mmfe-baked-runtime] network=${NETWORK}"

docker run --rm \
  -e JAVA_HOME="${JAVA_HOME_VALUE}" \
  "${IMAGE}" \
  sh -lc "$(printf 'test -f /usr/local/spark/jars/%q && ' "${REQUIRED_JARS[@]}") echo baked-jars-present"

run_smoke() {
  local script_path="$1"
  shift
  echo "[mmfe-baked-runtime] running ${script_path}"
  docker run --rm --network "${NETWORK}" \
    -e JAVA_HOME="${JAVA_HOME_VALUE}" \
    -e ICEBERG_SPARK_PACKAGES="" \
    -e SEDONA_SPARK_PACKAGES="" \
    -e SEDONA_TWM_SPARK_PACKAGES="" \
    -e SEDONA_RASTER_ZONAL_SPARK_PACKAGES="" \
    -e SEDONA_RASTER_CLIP_SPARK_PACKAGES="" \
    -e SPARK_JARS_PACKAGES="" \
    -v "$(pwd):/workspace" \
    -w /workspace \
    "${IMAGE}" \
    python "${script_path}" "$@"
}

run_smoke scripts/smoke_mmfe_spark_minio.py --packages ""
run_smoke scripts/smoke_mmfe_iceberg_minio.py --packages ""
run_smoke scripts/smoke_mmfe_sedona_sql.py --packages ""
run_smoke scripts/smoke_mmfe_sedona_twm_geojson.py --packages ""
run_smoke scripts/smoke_mmfe_sedona_raster.py --packages ""
run_smoke scripts/smoke_mmfe_sedona_raster_zonal.py --packages ""
run_smoke scripts/smoke_mmfe_sedona_raster_clip.py --packages ""
run_smoke scripts/smoke_mmfe_sedona_raster_clip_stac.py --packages ""

echo "[mmfe-baked-runtime] ok"
