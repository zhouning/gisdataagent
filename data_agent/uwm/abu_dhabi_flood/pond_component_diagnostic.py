"""Run an isolated pond in real EPA SWMM using explicitly synthetic forcing.

This verifies storage compilation and routing, not any customer's capture
capacity, pump, tailwater, network coupling or flood-reduction performance.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import math
import re

from .pond_geometry import RectangularPond, finite
from .pond_planning import canonical, private_root, write_json
from .swmm_saved_results import execute_swmm_saved_results


def triangular_source(*, peak_m3s: float = 1.0, event_seconds: int = 7200, total_seconds: int = 21600, step_seconds: int = 60):
    if type(event_seconds) is not int or type(total_seconds) is not int or type(step_seconds) is not int or not 0 < step_seconds <= event_seconds <= total_seconds:
        raise ValueError("pond_component_source_time_invalid")
    if finite(peak_m3s,"source_peak") < 0:
        raise ValueError("pond_component_source_peak_invalid")
    if event_seconds % (2*step_seconds) or total_seconds % step_seconds:
        raise ValueError("pond_component_source_time_alignment_required")
    return [(t, max(0.0, peak_m3s*(1-abs(2*t/event_seconds-1)))) for t in range(0,total_seconds+1,step_seconds)]


def render_component(geometry: RectangularPond, source_points: list, *, capture_limit_m3s: float,
                     emptying_coefficient: float, spillway_crest_m: float, spillway_width_m: float,
                     tailwater_m: float = 0.0, report_seconds: int = 10, routing_seconds: int = 2) -> tuple[str, dict]:
    import numpy as np
    values = {k:finite(v,k) for k,v in dict(capture_limit_m3s=capture_limit_m3s,emptying_coefficient=emptying_coefficient,
        spillway_crest_m=spillway_crest_m,spillway_width_m=spillway_width_m,tailwater_m=tailwater_m).items()}
    if min(values['capture_limit_m3s'],values['emptying_coefficient'],values['tailwater_m']) < 0 or not 0 < spillway_width_m <= 100:
        raise ValueError("pond_component_controls_invalid")
    if not 0 <= spillway_crest_m < geometry.depth_m:
        raise ValueError("pond_component_spillway_crest_invalid")
    if any(type(v) is not int for v in (report_seconds,routing_seconds)) or not 1 <= routing_seconds <= report_seconds <= 60 or report_seconds % routing_seconds:
        raise ValueError("pond_component_time_steps_invalid")
    if not 2 <= len(source_points) <= 10001:
        raise ValueError("pond_component_source_length_invalid")
    times = [p[0] for p in source_points]
    source = [finite(p[1],"source_flow") for p in source_points]
    if any(type(t) is not int for t in times) or times[0] != 0 or not 0 < times[-1] <= 7*86400 or any(b<=a for a,b in zip(times,times[1:])) or min(source)<0:
        raise ValueError("pond_component_source_invalid")
    if times[-1] % report_seconds:
        raise ValueError("pond_component_reporting_end_must_align")
    captured = np.minimum(source,capture_limit_m3s).tolist()
    origin=datetime(2020,1,1); end=origin+timedelta(seconds=times[-1])
    series=[]
    for sec,flow in zip(times,captured,strict=True):
        stamp=origin+timedelta(seconds=sec)
        series.append(f"TIN {stamp:%m/%d/%Y} {stamp:%H:%M:%S} {flow:.12g}")
    storage=geometry.swmm_storage_line('POND',invert_elevation_m=0,vertical_reference='synthetic_local_relative_datum')
    text=f'''[TITLE]
Synthetic pond component test; not an Abu Dhabi event or network simulation.

[OPTIONS]
FLOW_UNITS CMS
FLOW_ROUTING DYNWAVE
LINK_OFFSETS DEPTH
ALLOW_PONDING NO
SKIP_STEADY_STATE NO
START_DATE 01/01/2020
START_TIME 00:00:00
REPORT_START_DATE 01/01/2020
REPORT_START_TIME 00:00:00
END_DATE {end:%m/%d/%Y}
END_TIME {end:%H:%M:%S}
REPORT_STEP 00:{report_seconds//60:02d}:{report_seconds%60:02d}
ROUTING_STEP 00:{routing_seconds//60:02d}:{routing_seconds%60:02d}
WET_STEP 00:01:00
DRY_STEP 01:00:00
VARIABLE_STEP 0
MIN_SURFAREA 0.01

[EVAPORATION]
CONSTANT 0

[STORAGE]
{storage}

[OUTFALLS]
OUT_EMPTY 0 FIXED {tailwater_m:.12g} YES
OUT_SPILL 0 FIXED {tailwater_m:.12g} YES

[OUTLETS]
EMPTY POND OUT_EMPTY 0 FUNCTIONAL/HEAD {emptying_coefficient:.12g} 0.5 YES

[WEIRS]
SPILL POND OUT_SPILL TRANSVERSE {spillway_crest_m:.12g} 1.7 YES 0 0 NO

[XSECTIONS]
SPILL RECT_OPEN {geometry.depth_m-spillway_crest_m:.12g} {spillway_width_m:.12g} 0 0

[INFLOWS]
POND FLOW TIN FLOW 1 1 0

[TIMESERIES]
{chr(10).join(series)}

[REPORT]
INPUT YES
CONTROLS NO
NODES ALL
LINKS ALL
'''
    contract={"evidence_class":"synthetic_component_forcing_not_customer_event","geometry":geometry.contract(),
              "controls":{**values,"spillway_coefficient_assumed":1.7,"emptying_law":"q=k*sqrt(positive_head_difference)",
                          "no_pump_curve_or_pipe_design_implied":True},
              "source_points":[list(p) for p in source_points],"captured_points":list(map(list,zip(times,captured))),
              "capture_sampling":"piecewise_linear_of_clipped_samples",
              "source_volume_m3":float(np.trapezoid(source,times)),"captured_volume_m3":float(np.trapezoid(captured,times)),
              "bypass_volume_m3":float(np.trapezoid(np.asarray(source)-captured,times)),
              "vertical_reference":"synthetic_local_relative_datum","report_seconds":report_seconds,
              "routing_seconds":routing_seconds,"full_source_sha256":hashlib.sha256(canonical(source_points)).hexdigest(),
              "rainfall_runoff_or_network_exchange_simulated":False,"engineering_admitted":False}
    return text,contract


def run_component(geometry: RectangularPond, source_points: list, *, output_dir: Path, library_path: Path, **controls) -> dict:
    import numpy as np
    output=private_root(output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError("pond_component_output_must_be_empty")
    text,contract=render_component(geometry,source_points,**controls)
    output.mkdir(parents=True,exist_ok=True)
    path=output/'component.inp';path.write_text(text)
    result=execute_swmm_saved_results(library_path=library_path,model_input_path=path,node_names=('POND','OUT_EMPTY','OUT_SPILL'),link_names=('EMPTY','SPILL'))
    report=result['report_text'];(output/'component.rpt').write_text(report)
    times=result['timestamp_seconds_since_model_start'];states=result['node_state'];links=result['link_state']
    depth=states[:,0,0].astype(float);storage=states[:,0,2].astype(float)
    # Saved-rate integration is independent of the solver's internal continuity
    # ledger and is labelled as reporting-grid approximation.
    tt=np.r_[0,times]
    def integrate(series): return float(np.trapezoid(np.r_[series[0],series],tt))
    def volume_through_report_end(points):
        xp=np.asarray([p[0] for p in points],dtype=float)
        qp=np.asarray([p[1] for p in points],dtype=float)
        within=xp<times[-1]
        clipped_times=np.r_[xp[within],times[-1]]
        clipped_values=np.r_[qp[within],np.interp(times[-1],xp,qp)]
        return float(np.trapezoid(clipped_values,clipped_times))
    source_through_report=volume_through_report_end(contract['source_points'])
    captured_through_report=volume_through_report_end(contract['captured_points'])
    emptying=integrate(links[:,0,0].astype(float));spill=integrate(links[:,1,0].astype(float))
    flooding=integrate(states[:,0,5].astype(float))
    initial=geometry.volume(geometry.initial_water_depth_m)
    residual=initial+captured_through_report-float(storage[-1])-emptying-spill-flooding
    expected=np.array([geometry.volume(min(geometry.depth_m,max(0,float(h)))) for h in depth])
    curve_error=float(np.max(np.abs(expected-storage)))
    number=r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
    match=re.search(r'Flow Routing Continuity.*?Continuity Error \(%\)\s*\.{2,}\s*('+number+')',report,re.S)
    if match is None:raise ValueError('pond_component_routing_continuity_missing')
    continuity=float(match.group(1))
    convergence=re.search(r'% of Steps Not Converging\s*:\s*('+number+')',report)
    if convergence is None:raise ValueError('pond_component_convergence_missing')
    nonconverging=float(convergence.group(1))
    errors=len(re.findall(r'^\s*ERROR\s+\d+',report,re.M))
    denominator=max(initial+captured_through_report,1)
    passed=(errors==0 and nonconverging<=0.1 and abs(continuity)<=0.5 and abs(residual)<=max(2,0.005*denominator) and curve_error<=0.02)
    metrics={"source_volume_m3":source_through_report,"captured_volume_m3":captured_through_report,
        "bypass_volume_m3":source_through_report-captured_through_report,"initial_storage_m3":initial,
        "last_report_seconds":int(times[-1]),"requested_end_seconds":contract['source_points'][-1][0],
        "unreported_tail_seconds":int(contract['source_points'][-1][0]-times[-1]),
        "available_storage_at_start_m3":geometry.contract()['available_storage_under_assumptions_m3'],
        "maximum_depth_on_report_grid_m":float(depth.max()),"maximum_storage_on_report_grid_m3":float(storage.max()),
        "safe_depth_m":geometry.safe_depth_m,"safe_depth_exceeded":bool(depth.max()>geometry.safe_depth_m+1e-5),
        "safe_depth_exceedance_report_grid_seconds":int(np.sum(depth>geometry.safe_depth_m+1e-5)*contract['report_seconds']),
        "final_reported_storage_m3":float(storage[-1]),"emptying_outflow_approx_m3":emptying,
        "spillway_outflow_approx_m3":spill,"node_flooding_loss_approx_m3":flooding,
        "sampled_mass_balance_residual_m3":residual,"solver_routing_continuity_error_percent":continuity,
        "solver_nonconverging_steps_percent":nonconverging,
        "maximum_analytic_vs_solver_storage_difference_m3":curve_error,"numerical_quality_passed":passed}
    np.savez_compressed(output/'states.npz',elapsed_seconds=times,node_state=states,link_state=links)
    receipt={"schema":"gwm.abu_dhabi_flood.pond_component_diagnostic.v1","contract":contract,"metrics":metrics,
        "solver_version":result['solver_version'],"solver_runtime_sha256":result['runtime_sha256'],
        "input_sha256":result['model_input_sha256'],"implementation_sha256":hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name('pond_geometry.py').read_bytes()).hexdigest(),
        "engineering_admitted":False,"city_or_catchment_flood_benefit_estimated":False,
        "hydraulic_component_executed":True,"customer_network_simulation_executed":False}
    write_json(output/'receipt.json',receipt)
    if not passed:raise ValueError('pond_component_numerical_quality_failed')
    return receipt
