import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Map, RefreshCw, Shield } from 'lucide-react';
import { formatNumber, getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;
const arrayOf = <T,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];

export default function TraditionalLivabilitySafetyComfortPanel() {
  const { t, i18n } = useTranslation();
  const [overview, setOverview] = useState<Row | null>(null);
  const [admins, setAdmins] = useState<Row[]>([]);
  const [sources, setSources] = useState<Row[]>([]);
  const [mapPayload, setMapPayload] = useState<Row | null>(null);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    setMessage('');
    try {
      const urls = [
        '/api/uwm/traditional-livability/safety-comfort/overview',
        '/api/uwm/traditional-livability/safety-comfort/admin-units',
        '/api/uwm/traditional-livability/safety-comfort/evidence-sources',
        '/api/uwm/traditional-livability/safety-comfort/map',
      ];
      const responses = await Promise.all(urls.map(url => fetch(url, { credentials: 'include', headers: getLocaleHeaders() })));
      const data = await Promise.all(responses.map(response => response.json()));
      if (responses.some(response => !response.ok)) {
        throw new Error(data.find(item => item.error)?.error || t('traditionalPanels.safety.errors.unavailable'));
      }
      setOverview(data[0]);
      setAdmins(arrayOf<Row>(data[1].admin_units));
      setSources(arrayOf<Row>(data[2].evidence_sources));
      setMapPayload(data[3]);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : t('traditionalPanels.safety.errors.unavailable'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [i18n.resolvedLanguage]);
  const ranked = useMemo(() => [...admins].sort((a, b) => Number(a.relative_safety_comfort_evidence_gap_rank) - Number(b.relative_safety_comfort_evidence_gap_rank)).slice(0, 10), [admins]);
  const count = (value: unknown) => typeof value === 'number' ? formatNumber(value) : String(value ?? '-');
  const statusLabel = (value: unknown) => {
    const raw = String(value ?? '-');
    return t(`statusLabels.${raw}`, { defaultValue: raw });
  };

  return (
    <div className="traditional-panel">
      <div className="traditional-panel-title"><strong>{t('traditionalPanels.safety.title')}</strong><button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={14} />{t('traditionalPanels.common.refresh')}</button></div>
      <div className="traditional-message error"><Shield size={15} />{t('traditionalPanels.safety.warning')}</div>
      {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
      <div className="traditional-kpi-grid">
        <div className="traditional-kpi"><span>{t('traditionalPanels.safety.kpis.units')}</span><strong>{count(overview?.summary?.admin_unit_count)}</strong></div>
        <div className="traditional-kpi"><span>{t('traditionalPanels.safety.kpis.environmentRows')}</span><strong>{count(overview?.summary?.environment_reference_row_count)}</strong></div>
        <div className="traditional-kpi"><span>{t('traditionalPanels.safety.kpis.joinedRows')}</span><strong>{count(overview?.summary?.joined_environment_row_count)}</strong></div>
        <div className="traditional-kpi"><span>{t('traditionalPanels.safety.kpis.fabricated')}</span><strong>{count(overview?.fabricated_value_count)}</strong></div>
      </div>
      <h4>{t('traditionalPanels.safety.sections.sources')}</h4>
      <div className="traditional-source-grid">{sources.map(source => <div key={source.source_id}><span>{source.source_id}</span><strong>{statusLabel(source.join_status)}</strong><small>{source.source_spatial_unit} · {source.source_spatial_unit_count}</small></div>)}</div>
      <p>{t('traditionalPanels.safety.referenceOnly')}</p>
      <div className="traditional-message error"><Shield size={15} />{t('traditionalPanels.safety.finalWarning')}</div>
      <h4>{t('traditionalPanels.safety.sections.gap')}</h4>
      <div className="traditional-table-wrap"><table className="traditional-table"><thead><tr><th>{t('traditionalPanels.safety.table.rank')}</th><th>{t('traditionalPanels.safety.table.unit')}</th><th>{t('traditionalPanels.safety.table.road')}</th><th>{t('traditionalPanels.safety.table.environment')}</th><th>{t('traditionalPanels.safety.table.priorities')}</th></tr></thead><tbody>{ranked.map(item => <tr key={item.admin_unit_id}><td>{item.relative_safety_comfort_evidence_gap_rank}</td><td>{item.county}{item.township}</td><td>{String(item.evidence_coverage?.mobility_present)}</td><td>{String(item.evidence_coverage?.meteorology_present)}</td><td>{arrayOf<string>(item.field_collection_priorities).slice(0, 3).join(' / ')}</td></tr>)}</tbody></table></div>
      <button className="primary-button" disabled={!mapPayload} onClick={() => window.__handleMapUpdate?.(mapPayload)}><Map size={14} />{t('traditionalPanels.safety.actions.sendToMap')}</button>
    </div>
  );
}
