import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Map, RefreshCw, Shield, Target } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { formatNumber, getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;
function asArray<T = Row>(value: unknown): T[] { return Array.isArray(value) ? value as T[] : []; }
function isRecord(value: unknown): value is Row { return Boolean(value) && typeof value === 'object' && !Array.isArray(value); }
function fmtArea(value: unknown, unit: string): string {
  const number = Number(value);
  return Number.isFinite(number) ? `${formatNumber(number / 10000, { maximumFractionDigits: 2 })} ${unit}` : '-';
}

export default function TraditionalLivabilityS7Panel() {
  const { t } = useTranslation('common');
  const [result, setResult] = useState<Row | null>(null);
  const [gate, setGate] = useState<Row | null>(null);
  const [unavailable, setUnavailable] = useState<Row | null>(null);
  const [loading, setLoading] = useState(false);
  const [acknowledgement, setAcknowledgement] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [resultResponse, gateResponse] = await Promise.all([
        fetch('/api/uwm/traditional-livability/s7', { credentials: 'include', headers: getLocaleHeaders() }),
        fetch('/api/uwm/traditional-livability/s7/demand-gate', { credentials: 'include', headers: getLocaleHeaders() }),
      ]);
      const [resultPayload, gatePayload] = await Promise.all([resultResponse.json(), gateResponse.json()]);
      if (!resultResponse.ok || !gateResponse.ok) { setResult(null); setGate(gatePayload); setUnavailable(resultPayload); return; }
      setResult(resultPayload); setGate(gatePayload); setUnavailable(null);
    } catch (error: unknown) {
      setResult(null); setUnavailable({ blockers: [error instanceof Error ? error.message : 's7_request_failed'] });
    } finally { setLoading(false); }
  };

  const run = async (mode: 'authoritative' | 'conditional') => {
    setLoading(true);
    try {
      const response = await fetch('/api/uwm/traditional-livability/s7/run', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({ mode, acknowledgement: mode === 'conditional' ? acknowledgement : false }),
      });
      const payload = await response.json();
      if (!response.ok) { setUnavailable(payload); return; }
      setResult(payload); setUnavailable(null);
    } catch (error: unknown) {
      setUnavailable({ blockers: [error instanceof Error ? error.message : 's7_run_failed'] });
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);
  const funnel = isRecord(result?.candidate_filter_funnel) ? result.candidate_filter_funnel : {};
  const summary = isRecord(result?.demand_summary) ? result.demand_summary : {};
  const assumptions = isRecord(result?.assumptions) ? result.assumptions : {};
  const payload = isRecord(result?.geometry_payload) ? result.geometry_payload : {};
  const ranked = asArray<Row>(result?.ranked_candidates);
  const selected = asArray<Row>(result?.selected_sites);
  const blockers = asArray<string>(gate?.blockers || result?.production_blockers || unavailable?.blockers);
  const needConfirmed = gate?.state === 'authoritative_need_confirmed';
  const needUnresolved = gate?.state === 'need_unresolved';

  const mapUpdate = useMemo(() => {
    const pointFeatures = (sourceRows: Row[], color: string, label: string) => sourceRows.filter(row => isRecord(row.centroid)).map(row => ({
      type: 'Feature', properties: { label, color, parcel_id: row.parcel_id, planning_area_id: row.planning_area_id, exclusion_reason: row.exclusion_reason, not_a_site_recommendation: result?.not_a_site_recommendation === true },
      geometry: { type: 'Point', coordinates: [row.centroid.longitude, row.centroid.latitude] },
    }));
    return {
      schema: 'map_update.v1', summary: { title: t('s7.mapTitle') }, layers: [
        { name: t('s7.mapCandidateParcels'), type: 'geojson', geojsonData: { type: 'FeatureCollection', features: pointFeatures(asArray<Row>(payload.candidate_centroids), '#2563eb', t('s7.mapCandidateParcels')) } },
        { name: t('s7.mapResidentialDemand'), type: 'geojson', geojsonData: { type: 'FeatureCollection', features: pointFeatures(asArray<Row>(payload.demand_centroids), '#f97316', t('s7.mapResidentialAreaProxy')) } },
        { name: t('s7.mapDistanceCoverage'), type: 'geojson', geojsonData: { type: 'FeatureCollection', features: pointFeatures(asArray<Row>(payload.selected_candidate_centroids), '#059669', t('s7.mapDistanceCoverage')) } },
        { name: t('s7.mapExcludedParcels'), type: 'geojson', geojsonData: { type: 'FeatureCollection', features: pointFeatures(asArray<Row>(payload.excluded_candidates), '#94a3b8', t('s7.mapExcludedParcels')) } },
      ],
    };
  }, [payload, result?.not_a_site_recommendation, t]);

  return <div className="traditional-panel">
    <div className="traditional-panel-title"><Target size={15} /><strong>{t('s7.title')}</strong></div>
    <p>{t('s7.description')}</p>
    <button className="secondary-button" onClick={load} disabled={loading}><RefreshCw size={14} />{t('s7.refresh')}</button>
    {unavailable && <div className="traditional-message error"><AlertTriangle size={15} />{asArray<string>(unavailable.blockers).join(' / ') || unavailable.error || t('s7.unavailable')}</div>}
    <div className="traditional-two-col">
      <div className="traditional-panel">
        <h4>{t('s7.demandEvidence')}</h4>
        <div className="traditional-boundary-grid"><div><span>{t('s7.demandGate')}</span><strong>{gate?.state || '-'}</strong></div><div><span>{t('s7.s1Class')}</span><strong>{gate?.standard_class_id || '-'}</strong></div><div><span>{t('s7.authorityGap')}</span><strong>{gate?.gap?.gap_value ?? t('s7.unresolved')}</strong></div><div><span>{t('s7.recommendationPermission')}</span><strong>{needConfirmed ? t('s7.authoritativeAllowed') : t('s7.notAllowed')}</strong></div></div>
        {needUnresolved && <div className="traditional-message error"><Shield size={15} />{t('s7.unresolvedWarning')}</div>}
        <p>{t('s7.blockers')}: {blockers.join(' / ') || '-'}</p>
        <h4>{t('s7.runMode')}</h4>
        <button className="primary-button" disabled={!needConfirmed || loading} onClick={() => run('authoritative')}>{t('s7.authoritativeMode')}</button>
        <label><input type="checkbox" checked={acknowledgement} onChange={event => setAcknowledgement(event.target.checked)} />{t('s7.acknowledgement')}</label>
        <button className="secondary-button" disabled={!needUnresolved || !acknowledgement || loading} onClick={() => run('conditional')}>{t('s7.conditionalMode')}</button>
      </div>
      {result && <div className="traditional-panel">
        <div className="traditional-kpi-grid"><div className="traditional-kpi"><span>{t('s7.distanceThreshold')}</span><strong>{assumptions.coverage_distance_m || '-'} m</strong></div><div className="traditional-kpi"><span>{t('s7.candidateCount')}</span><strong>{formatNumber(ranked.length)}</strong></div><div className="traditional-kpi"><span>{t('s7.residentialAreaProxy')}</span><strong>{fmtArea(summary.total_proxy_area_m2, t('s7.hectares'))}</strong></div><div className="traditional-kpi"><span>{t('s7.unservedProxyArea')}</span><strong>{fmtArea(summary.unserved_proxy_area_m2, t('s7.hectares'))}</strong></div></div>
        <h4>{result.not_a_site_recommendation === true ? t('s7.conditionalRanking') : t('s7.authoritativeResult')}</h4>
        <div className="traditional-table-wrap"><table className="traditional-table"><thead><tr><th>{t('s7.order')}</th><th>{t('s7.parcel')}</th><th>{t('s7.newCoverage')}</th><th>{t('s7.overlapCoverage')}</th><th>{t('s7.evidenceBoundary')}</th></tr></thead><tbody>{ranked.slice(0, 8).map((row, index) => <tr key={`${row.planning_area_id}-${row.parcel_id}`}><td>{row.selection_round || index + 1}</td><td>{row.planning_area_id} · {row.parcel_id}</td><td>{fmtArea(row.newly_covered_proxy_area_m2, t('s7.hectares'))}</td><td>{fmtArea(row.overlap_proxy_area_m2, t('s7.hectares'))}</td><td>{row.not_a_site_recommendation === true ? t('s7.notRecommendation') : row.site_role || '-'}</td></tr>)}</tbody></table></div>
        <h4>{t('s7.filterFunnel')}</h4><p>{t('s7.excludedParcels', { count: funnel.excluded_candidate_count || 0 })}; {t('s7.noEligibleStatus')}: candidate_policy_no_eligible_parcels</p>
        <button className="primary-button" onClick={() => window.__handleMapUpdate?.(mapUpdate)} disabled={selected.length === 0}><Map size={14} />{t('s7.sendToMap')}</button>
        <p>{t('s7.capabilityBoundary')}</p>
      </div>}
    </div>
  </div>;
}
