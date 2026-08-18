import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Map, RefreshCw, Route, Shield } from 'lucide-react';
import { formatNumber, getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;
const arrayOf = <T,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];

export default function TraditionalLivabilityMobilityPanel() {
  const { t, i18n } = useTranslation();
  const [overview, setOverview] = useState<Row | null>(null);
  const [units, setUnits] = useState<Row[]>([]);
  const [mapPayload, setMapPayload] = useState<Row | null>(null);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    setMessage('');
    try {
      const urls = [
        '/api/uwm/traditional-livability/mobility/overview',
        '/api/uwm/traditional-livability/mobility/admin-units',
        '/api/uwm/traditional-livability/mobility/map',
      ];
      const responses = await Promise.all(urls.map(url => fetch(url, { credentials: 'include', headers: getLocaleHeaders() })));
      const data = await Promise.all(responses.map(response => response.json()));
      if (responses.some(response => !response.ok)) {
        throw new Error(data.find(item => item.error)?.error || t('traditionalPanels.mobility.errors.unavailable'));
      }
      setOverview(data[0]);
      setUnits(arrayOf<Row>(data[1].admin_units));
      setMapPayload(data[2]);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : t('traditionalPanels.mobility.errors.unavailable'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [i18n.resolvedLanguage]);
  const channels = overview?.channel_readiness || {};
  const channelRows = Object.entries(channels) as [string, Row][];
  const ranked = [...units].filter(row => row.accessibility_gap_rank != null).sort((a, b) => Number(a.accessibility_gap_rank) - Number(b.accessibility_gap_rank)).slice(0, 10);
  const loadDetail = async (id: string) => {
    const response = await fetch('/api/uwm/traditional-livability/mobility/admin-units/' + encodeURIComponent(id), { credentials: 'include', headers: getLocaleHeaders() });
    const data = await response.json();
    setMessage(response.ok
      ? t('traditionalPanels.mobility.detail', { id: data.admin_unit_id, value: String(data.network_proxy_not_observed_walk_time) })
      : (data.error || t('traditionalPanels.mobility.errors.unitUnavailable')));
  };
  const count = (value: unknown) => typeof value === 'number' ? formatNumber(value) : String(value ?? '-');
  const channelStatus = (value: unknown) => {
    const raw = String(value ?? '-');
    return t(`traditionalPanels.common.statuses.${raw}`, { defaultValue: raw });
  };

  return (
    <div className="traditional-panel">
      <div className="traditional-panel-title"><Route size={15} /><strong>{t('traditionalPanels.mobility.title')}</strong><button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={14} />{t('traditionalPanels.common.refresh')}</button></div>
      <p>{t('traditionalPanels.mobility.subtitle')}</p>
      {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
      <div className="traditional-kpi-grid">
        <div className="traditional-kpi"><span>{t('traditionalPanels.mobility.kpis.units')}</span><strong>{count(overview?.summary?.admin_unit_count)}</strong></div>
        <div className="traditional-kpi"><span>{t('traditionalPanels.mobility.kpis.roads')}</span><strong>{count(overview?.summary?.road_segment_count)}</strong></div>
        <div className="traditional-kpi"><span>{t('traditionalPanels.mobility.kpis.edges')}</span><strong>{count(overview?.summary?.mobility_graph_edge_count)}</strong></div>
        <div className="traditional-kpi"><span>{t('traditionalPanels.mobility.kpis.claim')}</span><strong>{overview?.claim_boundary?.max_claim_level || '-'}</strong></div>
      </div>
      <h4>{t('traditionalPanels.mobility.sections.channels')}</h4>
      <div className="traditional-source-grid">{channelRows.map(([name, row]) => <div key={name}><span>{name}</span><strong>{channelStatus(row.status)}</strong><small>{arrayOf<string>(row.blockers).join(' / ') || '-'}</small></div>)}</div>
      <div className="traditional-message error"><Shield size={15} />{t('traditionalPanels.mobility.warning')}</div>
      <h4>{t('traditionalPanels.mobility.sections.gapRanking')}</h4>
      <div className="traditional-table-wrap"><table className="traditional-table"><thead><tr><th>{t('traditionalPanels.mobility.table.rank')}</th><th>{t('traditionalPanels.mobility.table.unit')}</th><th>{t('traditionalPanels.mobility.table.accessibility')}</th><th>{t('traditionalPanels.mobility.table.distance')}</th><th>{t('traditionalPanels.mobility.table.reasons')}</th></tr></thead><tbody>{ranked.map(row => <tr key={row.admin_unit_id} onClick={() => void loadDetail(row.admin_unit_id)}><td>{row.accessibility_gap_rank}</td><td>{row.county}{row.township}</td><td>{row.service_accessibility_score ?? '-'}</td><td>{row.nearest_essential_service_distance_m ?? '-'} m</td><td>{arrayOf<string>(row.review_priority_reasons).join(' / ') || '-'}</td></tr>)}</tbody></table></div>
      <button className="primary-button" disabled={!mapPayload} onClick={() => window.__handleMapUpdate?.(mapPayload)}><Map size={14} />{t('traditionalPanels.mobility.actions.sendToMap')}</button>
      <p>{t('traditionalPanels.mobility.footer')}</p>
    </div>
  );
}
