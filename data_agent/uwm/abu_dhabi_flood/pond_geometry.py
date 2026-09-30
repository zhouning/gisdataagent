"""Explicit rectangular sloping-sided pond designs, not as-built measurements."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re


def finite(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"pond_geometry_{label}_invalid")
    return float(value)


@dataclass(frozen=True)
class RectangularPond:
    top_length_m: float
    top_width_m: float
    depth_m: float
    side_slope_h_over_v: float
    freeboard_m: float
    initial_water_depth_m: float

    def __post_init__(self):
        for key, value in asdict(self).items():
            object.__setattr__(self, key, finite(value, key))
        if not 0 < self.depth_m <= 10 or not 0 < self.top_length_m <= 10000 or not 0 < self.top_width_m <= 10000:
            raise ValueError("pond_geometry_dimensions_invalid")
        if not 0 <= self.side_slope_h_over_v <= 20:
            raise ValueError("pond_geometry_side_slope_invalid")
        if not 0 <= self.freeboard_m < self.depth_m or not 0 <= self.initial_water_depth_m <= self.depth_m:
            raise ValueError("pond_geometry_water_levels_invalid")
        if min(self.bottom_length_m, self.bottom_width_m) <= 0:
            raise ValueError("pond_geometry_bottom_collapsed")

    @property
    def bottom_length_m(self):
        return self.top_length_m - 2 * self.side_slope_h_over_v * self.depth_m

    @property
    def bottom_width_m(self):
        return self.top_width_m - 2 * self.side_slope_h_over_v * self.depth_m

    @property
    def safe_depth_m(self):
        return self.depth_m - self.freeboard_m

    def _water_depth(self, depth_m: float) -> float:
        depth = finite(depth_m, "water_depth")
        if not 0 <= depth <= self.depth_m:
            raise ValueError("pond_geometry_water_depth_outside_shape")
        return depth

    def area(self, depth_m: float) -> float:
        h = self._water_depth(depth_m); m = self.side_slope_h_over_v
        return (self.bottom_length_m + 2*m*h) * (self.bottom_width_m + 2*m*h)

    def volume(self, depth_m: float) -> float:
        h = self._water_depth(depth_m); m = self.side_slope_h_over_v
        length, width = self.bottom_length_m, self.bottom_width_m
        return length*width*h + m*(length+width)*h*h + (4/3)*m*m*h*h*h

    def water_depth_at_volume(self, volume_m3: float) -> float:
        volume = finite(volume_m3, "volume")
        if not 0 <= volume <= self.volume(self.depth_m):
            raise ValueError("pond_geometry_volume_outside_shape")
        lo, hi = 0.0, self.depth_m
        for _ in range(60):
            mid = (lo+hi)/2
            if self.volume(mid) < volume: lo = mid
            else: hi = mid
        return (lo+hi)/2

    def contract(self, *, stage_count: int = 101) -> dict:
        if type(stage_count) is not int or not 2 <= stage_count <= 1001:
            raise ValueError("pond_geometry_stage_count_invalid")
        total = self.volume(self.depth_m); initial = self.volume(self.initial_water_depth_m)
        safe = self.volume(self.safe_depth_m)
        return {"schema":"gwm.abu_dhabi_flood.pond_geometry.v1", "shape":"rectangular_flat_bottom_sloping_sides",
                "parameters":asdict(self), "slope_definition":"horizontal_run_per_one_vertical_rise",
                "bottom_length_m":self.bottom_length_m,"bottom_width_m":self.bottom_width_m,
                "top_area_m2":self.area(self.depth_m),"bottom_area_m2":self.area(0),
                "enclosed_geometric_volume_m3":total,"safe_depth_m":self.safe_depth_m,
                "volume_at_safe_depth_m3":safe,"initial_water_volume_m3":initial,
                "available_storage_under_assumptions_m3":max(0.0,safe-initial),
                "initial_state_above_safe_level":self.initial_water_depth_m>self.safe_depth_m,
                "reserved_freeboard_volume_m3":total-safe,
                "stage_area_volume":[{"water_depth_m":h,"surface_area_m2":self.area(h),"stored_volume_m3":self.volume(h)}
                    for h in (self.depth_m*i/(stage_count-1) for i in range(stage_count))],
                "evidence_class":"parameterized_design_not_as_built", "engineering_admitted":False,
                "available_storage_field_confirmed":False,"earthwork_quantity_from_dtm_computed":False,
                "limitations":["horizontal_level_rim_and_flat_bottom_assumed","no_sediment_or_unavailable_compartment_in_geometry",
                    "excavation_and_side_slope_stability_unverified","geometry_does_not_establish_inlet_or_emptying_capacity"]}

    def swmm_storage_line(self, node_id: str, *, invert_elevation_m: float, vertical_reference: str) -> str:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,30}", node_id):
            raise ValueError("pond_geometry_swmm_id_invalid")
        elevation = finite(invert_elevation_m, "invert_elevation")
        if not isinstance(vertical_reference, str) or not vertical_reference.strip():
            raise ValueError("pond_geometry_vertical_reference_required")
        # SWMM 5.2.4 PYRAMIDAL takes BOTTOM length, BOTTOM width and H/V.
        # The solver integrates its quadratic area relation analytically.
        return (f"{node_id} {elevation:.12g} {self.depth_m:.12g} {self.initial_water_depth_m:.12g} "
                f"PYRAMIDAL {self.bottom_length_m:.12g} {self.bottom_width_m:.12g} "
                f"{self.side_slope_h_over_v:.12g} 0 0")


def fit_rectangular_top(polygon, design: RectangularPond):
    """Bounded first-feasible layout search; no maximum-area or no-fit proof.

    Input is a planar metric screening polygon already inset by its stated
    screening setback. Holes and narrow strips are respected by covers().
    """
    from shapely.affinity import rotate, translate
    from shapely.geometry import box, Point
    if polygon.is_empty or not polygon.is_valid or polygon.geom_type not in {"Polygon","MultiPolygon"}:
        raise ValueError("pond_geometry_fit_polygon_invalid")
    if polygon.area < design.top_length_m*design.top_width_m:
        return None
    parts = [polygon] if polygon.geom_type == "Polygon" else sorted(polygon.geoms,key=lambda g:-g.area)
    template = box(-design.top_length_m/2,-design.top_width_m/2,design.top_length_m/2,design.top_width_m/2)
    for part in parts[:8]:
        if part.area < template.area: continue
        coords=list(part.minimum_rotated_rectangle.exterior.coords)
        angle=math.degrees(math.atan2(coords[1][1]-coords[0][1],coords[1][0]-coords[0][0])) % 180
        angles=list(dict.fromkeys([angle,*range(0,180,15)]))
        x0,y0,x1,y1=part.bounds
        centers=[part.representative_point(),part.centroid]
        centers.extend(Point(x0+(x1-x0)*i/8,y0+(y1-y0)*j/8) for i in range(1,8) for j in range(1,8))
        for center in centers:
            if not part.covers(center):continue
            for orientation in angles:
                footprint=translate(rotate(template,orientation,origin=(0,0)),center.x,center.y)
                if part.covers(footprint):
                    return {"geometry":footprint,"rotation_degrees":orientation,"center_xy":[center.x,center.y],
                            "method":"bounded_first_feasible_rectangle_search","construction_permission_confirmed":False}
    return None
