"""Overpass query builders for UWM public OSM proxy downloads."""

from __future__ import annotations

from typing import Any


def build_osm_amenity_overpass_query(bbox: list[Any], *, timeout_seconds: int = 180) -> str:
    """Build an Overpass query for all amenity nodes/ways/relations in a bbox."""

    bbox_text = _bbox_text(bbox)
    return (
        f"[out:json][timeout:{int(timeout_seconds)}];"
        "("
        f'node["amenity"]({bbox_text});'
        f'way["amenity"]({bbox_text});'
        f'relation["amenity"]({bbox_text});'
        ");"
        "out center tags;"
    )


def build_osm_highway_overpass_query(bbox: list[Any], *, timeout_seconds: int = 240) -> str:
    """Build an Overpass query for highway ways and their coordinate nodes."""

    bbox_text = _bbox_text(bbox)
    return (
        f"[out:json][timeout:{int(timeout_seconds)}];"
        "("
        f'way["highway"]({bbox_text});'
        ");"
        "(._;>;);"
        "out body;"
    )


def _bbox_text(bbox: list[Any]) -> str:
    if len(bbox) != 4:
        raise ValueError("bbox must be [lat_min, lon_min, lat_max, lon_max]")
    values = []
    for value in bbox:
        try:
            values.append(float(value))
        except (TypeError, ValueError) as exc:
            raise ValueError("bbox values must be numeric") from exc
    lat_min, lon_min, lat_max, lon_max = values
    if not (lat_min < lat_max and lon_min < lon_max):
        raise ValueError("bbox min values must be smaller than max values")
    return ",".join(str(round(value, 6)) for value in values)
