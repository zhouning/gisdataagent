"""Public evidence contract for the April 2024 flood-event reconstruction.

This is deliberately a non-spatial evidence product.  It gives the user
interface an auditable event narrative and a clearly labelled reconstructed
hyetograph without leaking customer data or presenting illustrative geometry
as a surveyed flood layer.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


APRIL_2024_EVENT_EVIDENCE_SCHEMA = "gwm.abu_dhabi_flood.april_2024_evidence.v1"


def _sha256_json(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _source(title: str, url: str) -> dict[str, str]:
    return {"title": title, "url": url}


def build_april_2024_event_evidence() -> dict[str, object]:
    """Build the public, non-spatial 2024 event evidence payload.

    The 139-hour event replay profile is based on the released demonstration
    research pack.  It is intentionally limited here to the 40-hour rainfall
    window: the later recovery timeline is documented evidence, not rainfall.
    """

    rainfall_profile_mmph = [
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.09,
        1.32,
        8.13,
        20.13,
        20.25,
        9.68,
        7.4,
        7.8,
        8.32,
        18.0,
        22.82,
        13.14,
        6.18,
        13.35,
        27.99,
        30.32,
        17.12,
        6.21,
        3.22,
        3.11,
        3.08,
        2.65,
        1.97,
        1.27,
        0.70,
        0.33,
        0.14,
        0.05,
        0.01,
        0.0,
    ]
    rain_source = _source(
        "Hussein et al. (2025), Natural Hazards; NCM record cited in Table 1",
        "https://doi.org/10.1007/s11069-025-07156-9",
    )
    live_source = _source(
        "Khaleej Times live coverage, 16 April 2024",
        "https://www.khaleejtimes.com/uae/emergencies/live-heavy-rains-hail-batter-uae-as-residents-wake-up-to-thunderstorm",
    )
    payload: dict[str, object] = {
        "schema": APRIL_2024_EVENT_EVIDENCE_SCHEMA,
        "event_id": "uae-april-2024-extreme-rainfall",
        "status": "public_evidence_and_reconstructed_forcing_not_calibrated",
        "data_class": "public_evidence_non_spatial",
        "map_behavior": "does_not_publish_any_map_layer",
        "provenance": {
            "research_pack": "nabd_flood_devpack_v1.5",
            "research_pack_release_date": "2026-09-05",
            "event_evidence_reference": "devpack/data/p3_replay_2024/p3_documented_2024.json",
            "reconstruction_reference": "devpack/data/p3_replay_2024/p3.json",
            "customer_data_included": False,
        },
        "fidelity": {
            "title_zh": "公开事实与重构雨型分开呈现",
            "title_en": "Public evidence and reconstructed rainfall are shown separately",
            "body_zh": "本页的逐时雨型是为演示物理模型闭环而做的三波次重构，不是阿布扎比市或岛内雨量站实测。它以公开事件时刻锚点组织，以艾因 Khatm Al Shakla 站 254.8 mm 为总量锚点；只能用于原型敏感性演示，不能用于校准或城市级预测声明。",
            "body_en": "The hourly hyetograph is a three-burst reconstruction for demonstrating the physical-model loop, not an observation from Abu Dhabi city or island gauges. It is structured around public event-time anchors and uses the 254.8 mm Khatm Al Shakla (Al Ain) total as an anchor. It is for prototype sensitivity demonstrations only, never calibration or a citywide prediction claim.",
        },
        "key_facts": [
            {
                "label_zh": "国家级极端事件记录",
                "label_en": "National extreme-rainfall record",
                "value": "254.8 mm / 24 h",
                "detail_zh": "Khatm Al Shakla，艾因；截至 2024-04-16 21:00 当地时间。不是阿布扎比市雨量。",
                "detail_en": "Khatm Al Shakla, Al Ain; through 21:00 local time on 16 Apr 2024. It is not Abu Dhabi city rainfall.",
                "source": rain_source,
            },
            {
                "label_zh": "阿布扎比市本地 24 h 雨量",
                "label_en": "Abu Dhabi city local 24-hour rainfall",
                "value": "待客户或站网数据补充",
                "detail_zh": "公开资料未找到可准入的市内逐时/24 h 实测序列，不能用艾因站值替代。",
                "detail_en": "No admissible public hourly or 24-hour city observation has been identified; the Al Ain station total cannot substitute for it.",
                "source": rain_source,
            },
            {
                "label_zh": "公开恢复记录",
                "label_en": "Documented recovery",
                "value": "2024-04-21 09:12 GST",
                "detail_zh": "DMT 及合作单位报告阿布扎比大部分积水和杂物已清除；这不是逐街道退水完成时间。",
                "detail_en": "DMT and partners reported that most pooling and debris in Abu Dhabi had been cleared; this is not a per-street drainage-completion time.",
                "source": _source(
                    "Gulf News report, 21 April 2024",
                    "https://gulfnews.com/uae/abu-dhabi-clears-most-of-the-water-pooling-debris-after-uaes-heaviest-rains-1.102255666",
                ),
            },
        ],
        "reconstruction": {
            "label_zh": "三波次重构雨型（40 h 雨量窗口）",
            "label_en": "Three-burst reconstructed hyetograph (40-hour rainfall window)",
            "series_start_gst": "2024-04-15T20:00:00+04:00",
            "interval_minutes": 60,
            "rainfall_profile_mmph": rainfall_profile_mmph,
            "reconstructed_total_mm": round(sum(rainfall_profile_mmph), 2),
            "peak_mmph": max(rainfall_profile_mmph),
            "admission": "prototype_sensitivity_only",
            "assumptions_zh": [
                "09:00 左右显著增强、午后第二波、傍晚至夜间峰值、22:50 预警降级来自公开时刻锚点。",
                "254.8 mm 只作为艾因站总量锚点，不能表述为阿布扎比市实测或全市均匀雨量。",
                "替换为客户本地雨量站/雷达 QPE 与统一时标后，才可进入事件校准。",
            ],
            "assumptions_en": [
                "Sharp intensification around 09:00, an afternoon second burst, an evening peak, and the 22:50 warning downgrade are anchored to public event timing.",
                "The 254.8 mm total is an Al Ain station anchor only; it must not be described as an Abu Dhabi city observation or uniform city rainfall.",
                "Only customer local gauges/radar QPE on one time standard can admit this event to calibration.",
            ],
        },
        "phases": [
            {
                "id": "T0",
                "window": "15 Apr 20:00 - 16 Apr 09:00 GST",
                "title_zh": "风暴抵达与前置准备",
                "title_en": "Storm arrival and pre-positioning",
                "evidence_class": "public timing anchor",
            },
            {
                "id": "T1",
                "window": "16 Apr 09:00 - 11:00 GST",
                "title_zh": "早高峰强降雨",
                "title_en": "Morning downpour",
                "evidence_class": "public timing anchor",
            },
            {
                "id": "T3",
                "window": "16 Apr 15:00 - 20:00 GST",
                "title_zh": "第二波与红色预警",
                "title_en": "Second burst and red alert",
                "evidence_class": "public record",
            },
            {
                "id": "T4",
                "window": "16 Apr 20:00 - 23:00 GST",
                "title_zh": "事件峰值窗口",
                "title_en": "Event peak window",
                "evidence_class": "reconstructed timing",
            },
            {
                "id": "T5",
                "window": "16 Apr 23:00 - 17 Apr 19:00 GST",
                "title_zh": "预警降级与交通响应",
                "title_en": "Warning downgrade and traffic response",
                "evidence_class": "public record",
            },
            {
                "id": "T6-T7",
                "window": "17 Apr 19:00 - 21 Apr 14:00 GST",
                "title_zh": "郊区残余积水至基本恢复",
                "title_en": "Suburban residual ponding to broad recovery",
                "evidence_class": "public record",
            },
        ],
        "timeline": [
            {
                "time": "16 Apr 09:00 GST",
                "area_zh": "阿联酋全国",
                "area_en": "UAE",
                "event_zh": "公开直播记录暴雨显著加强。",
                "event_en": "Public live coverage records a marked intensification of rainfall.",
                "kind_zh": "媒体",
                "kind_en": "Media",
                "source": live_source,
            },
            {
                "time": "16 Apr 16:28 GST",
                "area_zh": "阿布扎比岛与 Al Muroor",
                "area_en": "Abu Dhabi Island and Al Muroor",
                "event_zh": "超过 1 小时停电及供水中断记录；不是具名积水水深记录。",
                "event_en": "Power interruption for more than an hour and water-supply disruption were reported; this is not a named flood-depth observation.",
                "kind_zh": "媒体",
                "kind_en": "Media",
                "source": live_source,
            },
            {
                "time": "16 Apr 18:50 GST",
                "area_zh": "阿联酋全国",
                "area_en": "UAE",
                "event_zh": "NCM 红色预警覆盖多个地区。",
                "event_en": "An NCM red alert covered many areas.",
                "kind_zh": "官方记录",
                "kind_en": "Official record",
                "source": live_source,
            },
            {
                "time": "16 Apr 22:50 GST",
                "area_zh": "阿联酋全国",
                "area_en": "UAE",
                "event_zh": "预警从红色降为橙色，覆盖范围缩小。",
                "event_en": "The alert was downgraded from red to orange and its coverage reduced.",
                "kind_zh": "官方记录",
                "kind_en": "Official record",
                "source": live_source,
            },
            {
                "time": "17 Apr 09:41 GST",
                "area_zh": "Al Khaleej Al Arabi Street",
                "area_en": "Al Khaleej Al Arabi Street",
                "event_zh": "警方因暴雨后拥堵实施交通分流；并非封路或水深测量。",
                "event_en": "Police diverted traffic because of post-rain congestion; it is neither a road-closure nor flood-depth measurement.",
                "kind_zh": "官方记录",
                "kind_en": "Official record",
                "source": _source(
                    "Gulf News live coverage, 17 April 2024",
                    "https://gulfnews.com/uae/weather/unstable-weather-in-uae-here-are-the-updates-1.1713332487792",
                ),
            },
            {
                "time": "19 Apr",
                "area_zh": "Khalifa City 与 Zayed City",
                "area_en": "Khalifa City and Zayed City",
                "event_zh": "Landsat 9 图像显示成片积水；这是遥感证据，不提供逐时水深。",
                "event_en": "A Landsat 9 image shows flooded patches; this is remote-sensing evidence, not hourly water depth.",
                "kind_zh": "遥感",
                "kind_en": "Remote sensing",
                "source": _source(
                    "NASA Earth Observatory, 20 April 2024",
                    "https://science.nasa.gov/earth/earth-observatory/deluge-in-the-united-arab-emirates-152703/",
                ),
            },
            {
                "time": "20 Apr",
                "area_zh": "阿布扎比酋长国",
                "area_en": "Abu Dhabi Emirate",
                "event_zh": "DMT 表示应急队伍持续通宵处置。",
                "event_en": "DMT reported emergency teams continuing their overnight response.",
                "kind_zh": "官方记录",
                "kind_en": "Official record",
                "source": _source(
                    "Abu Dhabi Media Office, 20 April 2024",
                    "https://www.mediaoffice.abudhabi/en/infrastructure/department-of-municipalities-and-transport-continuing-to-mitigate-impact-of-weather-conditions-across-the-emirate/",
                ),
            },
            {
                "time": "21 Apr 09:12 GST",
                "area_zh": "阿布扎比酋长国",
                "area_en": "Abu Dhabi Emirate",
                "event_zh": "DMT 及合作单位报告“大部分积水与杂物已清除”。",
                "event_en": "DMT and partners reported that most water pooling and debris had been cleared.",
                "kind_zh": "官方 / 媒体",
                "kind_en": "Official / media",
                "source": _source(
                    "Gulf News report, 21 April 2024",
                    "https://gulfnews.com/uae/abu-dhabi-clears-most-of-the-water-pooling-debris-after-uaes-heaviest-rains-1.102255666",
                ),
            },
        ],
        "validation_gaps": [
            {
                "title_zh": "阿布扎比市内的逐时雨量与雷达 QPE",
                "title_en": "Hourly Abu Dhabi city rain gauges and radar QPE",
                "use_zh": "替换重构强迫并对齐统一时标。",
                "use_en": "Replace reconstructed forcing and align one time standard.",
            },
            {
                "title_zh": "潮位、出水口边界和泵闸运行日志",
                "title_en": "Tide, outfall boundary, and pump/gate operating logs",
                "use_zh": "约束 SWMM 和二维模型的事件边界。",
                "use_en": "Constrain event boundaries for SWMM and the 2D model.",
            },
            {
                "title_zh": "带时间戳的积水深度、范围、退水与道路影响观测",
                "title_en": "Time-stamped inundation depth, extent, recession, and road-impact observations",
                "use_zh": "校准、盲测和影响模型验证。",
                "use_en": "Calibrate, blind-test, and validate impact models.",
            },
        ],
    }
    payload["evidence_sha256"] = _sha256_json(payload)
    return payload


def _contains_spatial_geometry(value: object) -> bool:
    if isinstance(value, dict):
        prohibited = {"geometry", "coordinates", "latitude", "longitude", "lat", "lon"}
        if prohibited.intersection(value):
            return True
        return any(_contains_spatial_geometry(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_spatial_geometry(item) for item in value)
    return False


def verify_april_2024_event_evidence(payload: dict[str, Any]) -> None:
    """Validate the no-geometry and no-false-observation presentation boundary."""

    if payload.get("schema") != APRIL_2024_EVENT_EVIDENCE_SCHEMA:
        raise ValueError("april_2024_event_evidence_schema_invalid")
    claimed = payload.get("evidence_sha256")
    content = dict(payload)
    content.pop("evidence_sha256", None)
    if not isinstance(claimed, str) or claimed != _sha256_json(content):
        raise ValueError("april_2024_event_evidence_sha256_invalid")
    if payload.get("data_class") != "public_evidence_non_spatial":
        raise ValueError("april_2024_event_evidence_data_class_invalid")
    if payload.get("map_behavior") != "does_not_publish_any_map_layer":
        raise ValueError("april_2024_event_evidence_map_boundary_invalid")
    if _contains_spatial_geometry(content):
        raise ValueError("april_2024_event_evidence_must_not_contain_geometry")
    reconstruction = payload.get("reconstruction")
    if not isinstance(reconstruction, dict) or reconstruction.get("admission") != "prototype_sensitivity_only":
        raise ValueError("april_2024_event_evidence_reconstruction_boundary_invalid")
    profile = reconstruction.get("rainfall_profile_mmph")
    if not isinstance(profile, list) or len(profile) != 40 or max(profile, default=-1.0) != 30.32:
        raise ValueError("april_2024_event_evidence_profile_invalid")
