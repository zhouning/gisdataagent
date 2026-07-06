import gzip
import json

from data_agent.uwm.noaa_isd_weather_proxy import (
    NOAA_ISD_WEATHER_PROXY_SCHEMA,
    build_noaa_isd_weather_proxy,
    parse_isd_record,
    write_noaa_isd_weather_proxy_snapshot,
)


def _fixed_width_isd_line(
    *,
    date="20240701",
    time="0300",
    report_type="FM-15",
    lat="+29719",
    lon="+106642",
    call="ZUCK ",
    wind_dir="280",
    wind_speed="0020",
    visibility="010000",
    temp="+0250",
    dew="+0220",
    slp="10080",
) -> str:
    chars = list(" " * 105)

    def put(start, value):
        chars[start : start + len(value)] = list(value)

    put(0, "0260")
    put(4, "575160")
    put(10, "99999")
    put(15, date)
    put(23, time)
    put(27, "4")
    put(28, lat)
    put(34, lon)
    put(41, report_type)
    put(46, "+0416")
    put(51, call)
    put(56, "V020")
    put(60, wind_dir)
    put(63, "1")
    put(64, "N")
    put(65, wind_speed)
    put(69, "1")
    put(70, "99999")
    put(75, "9")
    put(76, "9")
    put(77, "N")
    put(78, visibility)
    put(84, "1")
    put(85, "9")
    put(86, "9")
    put(87, temp)
    put(92, "1")
    put(93, dew)
    put(98, "1")
    put(99, slp)
    put(104, "1")
    return "".join(chars)


def test_parse_isd_record_converts_mandatory_fields_to_physical_units():
    record = parse_isd_record(_fixed_width_isd_line() + "REMMET047METAR ZUCK 010300Z 28002MPS")

    assert record["station_id"] == "575160-99999"
    assert record["timestamp_utc"] == "2024-07-01T03:00:00Z"
    assert record["report_type"] == "FM-15"
    assert record["call_sign"] == "ZUCK"
    assert record["header_call_sign"] == "ZUCK"
    assert record["metar_call_sign"] == "ZUCK"
    assert record["latitude"] == 29.719
    assert record["longitude"] == 106.642
    assert record["wind_direction_degree"] == 280.0
    assert record["wind_speed_ms"] == 2.0
    assert record["visibility_m"] == 10000.0
    assert record["air_temperature_c"] == 25.0
    assert record["dew_point_c"] == 22.0
    assert record["sea_level_pressure_hpa"] == 1008.0


def test_build_noaa_isd_weather_proxy_filters_window_and_preserves_observed_boundary():
    lines = [
        _fixed_width_isd_line(date="20240630", temp="+0240"),
        _fixed_width_isd_line(date="20240701", time="0000", temp="+0250", slp="10080"),
        _fixed_width_isd_line(date="20240707", time="2300", temp="+0270", slp="10040"),
        _fixed_width_isd_line(date="20240708", temp="+0280"),
    ]

    proxy = build_noaa_isd_weather_proxy(
        lines,
        start_date="2024-07-01",
        end_date="2024-07-07",
        fetched_at="2026-07-05T10:00:00Z",
    )

    assert proxy["schema"] == NOAA_ISD_WEATHER_PROXY_SCHEMA
    assert proxy["source_dataset_ids"] == ["noaa_isd_chongqing_weather_observation_2024_07"]
    assert proxy["record_counts"]["raw_records_in_file"] == 4
    assert proxy["record_counts"]["records_in_time_window"] == 2
    assert proxy["summary"]["air_temperature_avg_c"] == 26.0
    assert proxy["summary"]["sea_level_pressure_avg_hpa"] == 1006.0
    assert proxy["quality_status"] == "observed_station_weather_holdout_ready"
    assert proxy["synthetic_flags"] == [
        {"dataset_id": "noaa_isd_chongqing_weather_observation_2024_07", "status": "public_proxy"}
    ]
    assert "observed_station_weather_not_reanalysis" in proxy["limitations"]
    assert proxy["empirical_superiority_claim"] is False


def test_write_noaa_isd_weather_proxy_snapshot_reads_gzip_and_writes_manifest(tmp_path):
    gz_path = tmp_path / "575160-99999-2024.gz"
    with gzip.open(gz_path, "wt", encoding="ascii") as handle:
        handle.write(_fixed_width_isd_line(date="20240701") + "\n")

    manifest = write_noaa_isd_weather_proxy_snapshot(
        gz_path=gz_path,
        output_dir=tmp_path / "out",
        start_date="2024-07-01",
        end_date="2024-07-07",
        fetched_at="2026-07-05T10:00:00Z",
    )

    assert manifest["schema"] == "uwm.public_proxy_snapshot_manifest.v1"
    assert manifest["dataset_id"] == "noaa_isd_chongqing_weather_observation_2024_07_snapshot"
    assert manifest["record_counts"]["records_in_time_window"] == 1
    assert (tmp_path / "out" / "noaa_isd_weather_proxy.json").exists()
    assert json.loads((tmp_path / "out" / "snapshot_manifest.json").read_text(encoding="utf-8")) == manifest
