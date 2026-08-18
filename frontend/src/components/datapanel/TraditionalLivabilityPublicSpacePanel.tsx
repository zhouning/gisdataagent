import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Map, RefreshCw, Shield } from 'lucide-react';
import { formatNumber, getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;
const arrayOf = <T,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];

export default function TraditionalLivabilityPublicSpacePanel() {
  const { t, i18n } = useTranslation();
  const [overview, setOverview] = useState<Row | null>(null);
  const [spaces, setSpaces] = useState<Row[]>([]);
  const [admins, setAdmins] = useState<Row[]>([]);
  const [mapPayload, setMapPayload] = useState<Row | null>(null);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    setMessage('');
    try {
      const urls = [
        '/api/uwm/traditional-livability/public-space/overview',
        '/api/uwm/traditional-livability/public-space/spaces',
        '/api/uwm/traditional-livability/public-space/admin-units',
        '/api/uwm/traditional-livability/public-space/map',
      ];
      const responses = await Promise.all(urls.map(url => fetch(url, {
        credentials: 'include',
        headers: getLocaleHeaders(),
      })));
      const data = await Promise.all(responses.map(response => response.json()));
      if (responses.some(response => !response.ok)) {
        throw new Error(data.find(item => item.error)?.error || t('traditionalPanels.publicSpace.errors.unavailable'));
      }
      setOverview(data[0]);
      setSpaces(arrayOf<Row>(data[1].spaces));
      setAdmins(arrayOf<Row>(data[2].admin_units));
      setMapPayload(data[3]);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : t('traditionalPanels.publicSpace.errors.unavailable'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [i18n.resolvedLanguage]);
  const ranked = useMemo(
    () => [...admins].sort((a, b) => Number(a.relative_public_space_evidence_gap_rank) - Number(b.relative_public_space_evidence_gap_rank)).slice(0, 12),
    [admins],
  );
  const counts = overview?.summary?.eligible_category_counts || {};
  const count = (value: unknown) => typeof value === 'number' ? formatNumber(value) : String(value ?? '-');

  return (
    <div className="traditional-panel">
      <div className="traditional-panel-title">
        <strong>{t('traditionalPanels.publicSpace.title')}</strong>
        <button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={14} />{t('traditionalPanels.common.refresh')}</button>
      </div>
      <p>{t('traditionalPanels.publicSpace.subtitle')}</p>
      {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
      <div className="traditional-kpi-grid">
        <div className="traditional-kpi"><span>{t('traditionalPanels.publicSpace.kpis.included')}</span><strong>{formatNumber(spaces.length)}</strong></div>
        <div className="traditional-kpi"><span>{t('traditionalPanels.publicSpace.kpis.excluded')}</span><strong>{count(overview?.summary?.excluded_record_count)}</strong></div>
        <div className="traditional-kpi"><span>{t('traditionalPanels.publicSpace.kpis.districts')}</span><strong>{formatNumber(admins.length)}</strong></div>
        <div className="traditional-kpi"><span>{t('traditionalPanels.publicSpace.kpis.fabricated')}</span><strong>{count(overview?.fabricated_value_count)}</strong></div>
      </div>
      <h4>{t('traditionalPanels.publicSpace.sections.categories')}</h4>
      <div className="traditional-source-grid">
        <div><span>core_open_space</span><strong>{count(counts.core_open_space)}</strong></div>
        <div><span>civic_cultural_space</span><strong>{count(counts.civic_cultural_space)}</strong></div>
        <div><span>public_recreation_space</span><strong>{count(counts.public_recreation_space)}</strong></div>
      </div>
      <div className="traditional-message error"><Shield size={15} />{t('traditionalPanels.publicSpace.warning')}</div>
      <h4>{t('traditionalPanels.publicSpace.sections.evidenceGap')}</h4>
      <div className="traditional-table-wrap">
        <table className="traditional-table">
          <thead><tr><th>{t('traditionalPanels.publicSpace.table.rank')}</th><th>{t('traditionalPanels.publicSpace.table.district')}</th><th>{t('traditionalPanels.publicSpace.table.openSpace')}</th><th>{t('traditionalPanels.publicSpace.table.categories')}</th><th>{t('traditionalPanels.publicSpace.table.reason')}</th></tr></thead>
          <tbody>{ranked.map(item => (
            <tr key={item.admin_unit_id}>
              <td>{item.relative_public_space_evidence_gap_rank}</td>
              <td>{item.county || item.admin_unit_id}</td>
              <td>{item.core_open_space_count}</td>
              <td>{item.space_category_count}</td>
              <td>{arrayOf<string>(item.relative_gap_reasons).join(' / ') || '-'}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <button className="primary-button" disabled={!mapPayload} onClick={() => window.__handleMapUpdate?.(mapPayload)}>
        <Map size={14} />{t('traditionalPanels.publicSpace.actions.sendToMap')}
      </button>
    </div>
  );
}
