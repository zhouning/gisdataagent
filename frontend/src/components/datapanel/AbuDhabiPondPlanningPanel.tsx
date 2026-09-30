import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getLocaleHeaders } from '../../i18n';
import './AbuDhabiPondPlanningPanel.css';

type Catalog = {
  snapshot_id: string;
  counts: Record<string, number>;
  catchments: { source_fid: string; label: string; has_screening_inputs: boolean }[];
};
type Candidate = {
  candidate_id: string; source_fid: string; kind: string; screening_area_m2: number | null;
  minimum_distance_m: number; utility_overlap_count: number; construction_status?: string;
};
type Result = {
  snapshot_id: string; screening_id: string;
  summary: { hotspots: number; selected_candidates: number; connections: number; hotspots_without_candidate: number; existing_pond_references: number };
  candidates: Candidate[];
  connections: { connection_id: string; candidate_id: string; hotspot_id: string; distance_lower_bound_m: number; utility_intersections: number }[];
  required_data: string[];
  geojson: Record<string, unknown>;
  map_update: unknown;
};

export const pondRequirementLabels: Record<string, [string, string]> = {
  land_and_connection_permission: ['土地、连接及排水许可', 'Land, connection and discharge permissions'],
  surveyed_elevations_and_vertical_datum: ['实测高程与统一竖向基准', 'Surveyed elevations and vertical datum'],
  groundwater_and_geotechnics: ['地下水、土质和边坡条件', 'Groundwater, soil and slope conditions'],
  stage_area_storage_and_safe_overflow: ['水位—面积—库容曲线与安全溢流', 'Stage–area–storage curves and safe overflow'],
  inlet_and_connection_hydraulics: ['入口捕获、连接断面与流量能力', 'Inlet capture and connection hydraulics'],
  pump_curves_if_pumped: ['使用泵时的性能曲线和供能', 'Pump curves and power supply where required'],
  rainfall_tailwater_and_initial_state: ['降雨、尾水及初始水位', 'Rainfall, tailwater and initial water levels'],
  protection_targets_and_unit_costs: ['保护目标及分项工程单价', 'Protection targets and itemised unit costs'],
  independent_model_validation: ['独立事件与模型验证', 'Independent event and model validation'],
};

function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement('a');
  link.href = url; link.download = name; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function AbuDhabiPondPlanningPanel() {
  const { i18n } = useTranslation();
  const zh = i18n.language.startsWith('zh');
  const text = (cn: string, en: string) => zh ? cn : en;
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [catchment, setCatchment] = useState('');
  const [distance, setDistance] = useState(1500);
  const [area, setArea] = useState(500);
  const [setback, setSetback] = useState(3);
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [lastPayload, setLastPayload] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/abu-dhabi/flood/pond-planning/catalog', { credentials: 'include', headers: getLocaleHeaders(), signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(response.status === 503 ? 'not_provisioned' : 'load_failed');
        const data: Catalog = await response.json();
        setCatalog(data);
        const pilots = data.catchments.filter(row => row.has_screening_inputs);
        setCatchment(pilots.find(row => row.source_fid === '20')?.source_fid || pilots[0]?.source_fid || '');
      }).catch(reason => { if (reason.name !== 'AbortError') setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);
  const resetResult = () => { setResult(null); setLastPayload(null); setError(''); };
  const run = async () => {
    if (!catalog || !catchment) return;
    setBusy(true); setError(''); setResult(null); setLastPayload(null);
    const payload = { snapshot_id: catalog.snapshot_id, catchment_fid: catchment,
      policy: { maximum_distance_m: distance, minimum_area_m2: area, setback_m: setback } };
    try {
      const response = await fetch('/api/abu-dhabi/flood/pond-planning/screen', {
        method: 'POST', credentials: 'include', headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error('screen_failed');
      const value: Result = await response.json();
      setResult(value); setLastPayload(payload);
    } catch { setError('screen_failed'); }
    finally { setBusy(false); }
  };
  const exportCsv = async () => {
    if (!result || !lastPayload) return;
    setBusy(true); setError('');
    try {
      const response = await fetch('/api/abu-dhabi/flood/pond-planning/export.csv', {
        method: 'POST', credentials: 'include', headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify(lastPayload),
      });
      if (!response.ok) throw new Error('export_failed');
      download(`pond-screening-${result.screening_id}.csv`, await response.text(), 'text/csv;charset=utf-8');
    } catch { setError('export_failed'); }
    finally { setBusy(false); }
  };
  const showMap = () => {
    const handler = (window as unknown as { __handleMapUpdate?: (value: unknown) => void }).__handleMapUpdate;
    if (handler && result) handler(result.map_update);
    else setError('map_unavailable');
  };
  return (
    <section className="pond-planning-panel" aria-label={text('调蓄方案空间筛选', 'Pond planning spatial screening')}>
      <div className="pond-planning-heading"><div><span>POND PLANNING</span><h3>{text('调蓄方案 · 地块与连接初筛', 'Pond planning · land and connections')}</h3></div>
        <strong>{text('工程参数待核', 'Engineering data pending')}</strong></div>
      <p>{text('选择汇水区，筛选附近地块与现状塘，并检查设施冲突。连接线表示距离下界；重力可达性、可用库容与成本需补齐工程数据后计算。', 'Select a catchment to screen land and existing ponds and identify utility conflicts. Connection lines show distance lower bounds; gravity flow, available storage and cost require verified engineering inputs.')}</p>
      {loading && <p role="status">{text('正在读取试点数据…', 'Loading pilot data…')}</p>}
      {error && <p role="alert">{error === 'not_provisioned' ? text('尚未接入试点数据包。', 'No pilot snapshot is available.') : error === 'map_unavailable' ? text('当前地图尚未就绪，可先导出结果。', 'The map is not ready; you can export the results.') : text('操作未完成，请检查数据包或稍后重试。', 'The operation could not be completed. Check the snapshot or retry.')}</p>}
      {catalog && <>
        <div className="pond-planning-controls">
          <label>{text('汇水区（按唯一编号）', 'Catchment (unique source ID)')}<select value={catchment} disabled={busy} onChange={e => { setCatchment(e.target.value); resetResult(); }}>
            {catalog.catchments.filter(row => row.has_screening_inputs).map(row => <option key={row.source_fid} value={row.source_fid}>{row.label} · #{row.source_fid}</option>)}
          </select></label>
          <label>{text('最大筛选距离（米）', 'Maximum screening distance (m)')}<input type="number" min={10} max={1900} value={distance} disabled={busy} onChange={e => { setDistance(Number(e.target.value)); resetResult(); }} /></label>
          <label>{text('最小筛选面积（平方米）', 'Minimum screening area (m²)')}<input type="number" min={10} max={100000} value={area} disabled={busy} onChange={e => { setArea(Number(e.target.value)); resetResult(); }} /></label>
          <label>{text('暂定退界（米）', 'Assumed setback (m)')}<input type="number" min={0} max={30} value={setback} disabled={busy} onChange={e => { setSetback(Number(e.target.value)); resetResult(); }} /></label>
        </div>
        <p className="pond-planning-note">{text('按每个热点选取最近的 3 个空间候选；退界与 2 米设施缓冲均为初筛假设。地块存在不代表允许挖塘，零冲突不代表已完成地下设施核查。', 'Selects the 3 nearest spatial candidates per hotspot. Setback and the 2 m utility buffer are screening assumptions. Parcel presence does not grant excavation permission; zero conflicts do not establish utility clearance.')}</p>
        <button type="button" disabled={busy || !catchment || distance < 10 || distance > 1900 || area < 10 || area > 100000 || setback < 0 || setback > 30} onClick={run}>{busy ? text('处理中…', 'Processing…') : text('运行空间筛选', 'Run spatial screening')}</button>
      </>}
      {result && <>
        <div className="pond-planning-metrics">
          <span>{text('热点', 'Hotspots')} <b>{result.summary.hotspots}</b></span>
          <span>{text('待核候选', 'Candidates to verify')} <b>{result.summary.selected_candidates}</b></span>
          <span>{text('勘测连接', 'Survey connections')} <b>{result.summary.connections}</b></span>
          <span>{text('附近现状塘', 'Nearby existing pond assets')} <b>{result.summary.existing_pond_references}</b></span>
          <span>{text('无近邻候选热点', 'Hotspots without a candidate')} <b>{result.summary.hotspots_without_candidate}</b></span>
        </div>
        <div className="pond-planning-actions">
          <button type="button" onClick={showMap}>{text('在地图查看', 'Show on map')}</button>
          <button type="button" disabled={busy} onClick={exportCsv}>{text('导出连接清单 CSV', 'Export connections CSV')}</button>
          <button type="button" onClick={() => download(`pond-screening-${result.screening_id}.json`, JSON.stringify(result, null, 2), 'application/json')}>{text('导出完整结果 JSON', 'Export full results JSON')}</button>
          <button type="button" onClick={() => download(`pond-candidates-${result.screening_id}.geojson`, JSON.stringify(result.geojson.candidates), 'application/geo+json')}>{text('导出候选 GeoJSON', 'Export candidates GeoJSON')}</button>
        </div>
        <div className="pond-planning-table"><table><thead><tr>
          {[text('来源编号', 'Source ID'), text('类型', 'Type'), text('筛选面积 m²', 'Screening area m²'), text('最近距离 m', 'Nearest distance m'), text('设施重叠数', 'Utility overlaps')].map(value => <th key={value}>{value}</th>)}
        </tr></thead><tbody>{result.candidates.map(row => <tr key={row.candidate_id}>
          <td title={row.candidate_id}>{row.source_fid}</td><td>{row.kind === 'parcel' ? text('地块待核', 'Parcel to verify') : text('现状塘资产', 'Existing pond asset')}</td>
          <td>{row.screening_area_m2 === null ? '—' : row.screening_area_m2.toLocaleString()}</td><td>{row.minimum_distance_m.toLocaleString()}</td><td>{row.utility_overlap_count}</td>
        </tr>)}</tbody></table></div>
        <details><summary>{text('工程计算前需补齐的数据', 'Data required before engineering calculations')}</summary><ul>
          {result.required_data.map(key => <li key={key}>{pondRequirementLabels[key]?.[zh ? 0 : 1] || key}</li>)}
        </ul></details>
        <small>{text('数据版本', 'Snapshot')}: {result.snapshot_id} · {text('仅按距离初筛，尚未运行水动力或成本优化。', 'Distance screening only; hydraulics and cost optimization have not run.')}</small>
      </>}
    </section>
  );
}
