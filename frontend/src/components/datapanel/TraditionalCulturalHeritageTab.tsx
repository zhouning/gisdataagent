import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Map, RefreshCw, Shield } from 'lucide-react';
import { formatNumber, getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;
type Tier = 'confirmed_cultural_place_evidence' | 'heritage_candidate_leads' | 'excluded_ambiguous_records';
const arrayOf = <T,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];

export default function TraditionalCulturalHeritageTab() {
  const { t, i18n } = useTranslation();
  const [tier, setTier] = useState<Tier>('confirmed_cultural_place_evidence');
  const [overview, setOverview] = useState<Row | null>(null);
  const [places, setPlaces] = useState<Row[]>([]);
  const [admins, setAdmins] = useState<Row[]>([]);
  const [mapPayload, setMapPayload] = useState<Row | null>(null);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    setMessage('');
    try {
      const suffix = '?tier=' + tier;
      const urls = [
        '/api/uwm/traditional-livability/cultural-heritage/overview',
        '/api/uwm/traditional-livability/cultural-heritage/places' + suffix,
        '/api/uwm/traditional-livability/cultural-heritage/admin-units',
        '/api/uwm/traditional-livability/cultural-heritage/map' + suffix,
      ];
      const responses = await Promise.all(urls.map(url => fetch(url, { credentials: 'include', headers: getLocaleHeaders() })));
      const data = await Promise.all(responses.map(response => response.json()));
      if (responses.some(response => !response.ok)) {
        throw new Error(data.find(item => item.error)?.error || t('traditionalPanels.cultural.errors.unavailable'));
      }
      setOverview(data[0]);
      setPlaces(arrayOf<Row>(data[1].places));
      setAdmins(arrayOf<Row>(data[2].admin_units));
      setMapPayload(data[3]);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : t('traditionalPanels.cultural.errors.unavailable'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [tier, i18n.resolvedLanguage]);
  const ranked = useMemo(() => [...admins].sort((a, b) => Number(a.relative_cultural_heritage_evidence_gap_rank) - Number(b.relative_cultural_heritage_evidence_gap_rank)).slice(0, 12), [admins]);
  const count = (value: unknown) => typeof value === 'number' ? formatNumber(value) : String(value ?? '-');

  return (
    <div className="traditional-livability-tab">
      <div className="traditional-panel">
        <div className="traditional-panel-title"><strong>{t('traditionalPanels.cultural.title')}</strong><button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={14} />{t('traditionalPanels.common.refresh')}</button></div>
        <div className="traditional-tag-list">{(['confirmed_cultural_place_evidence', 'heritage_candidate_leads', 'excluded_ambiguous_records'] as Tier[]).map(item => <button key={item} className={tier === item ? 'primary-button' : 'secondary-button'} onClick={() => setTier(item)}>{t('traditionalPanels.cultural.tiers.' + item)}</button>)}</div>
        <div className="traditional-message error"><Shield size={15} />{t('traditionalPanels.cultural.warning')}</div>
        {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
        <div className="traditional-kpi-grid">
          <div className="traditional-kpi"><span>{t('traditionalPanels.cultural.kpis.currentTier')}</span><strong>{formatNumber(places.length)}</strong></div>
          <div className="traditional-kpi"><span>{t('traditionalPanels.cultural.kpis.confirmed')}</span><strong>{count(overview?.summary?.confirmed_place_count)}</strong></div>
          <div className="traditional-kpi"><span>{t('traditionalPanels.cultural.kpis.candidates')}</span><strong>{count(overview?.summary?.candidate_lead_count)}</strong></div>
          <div className="traditional-kpi"><span>{t('traditionalPanels.cultural.kpis.excluded')}</span><strong>{count(overview?.summary?.excluded_ambiguous_count)}</strong></div>
        </div>
        <p>{t('traditionalPanels.cultural.confirmedCategories')}: {Object.entries(overview?.summary?.confirmed_category_counts || {}).map(([key, value]) => key + ':' + String(value)).join(' / ') || '-'}</p>
        <div className="traditional-message error"><Shield size={15} />{t('traditionalPanels.cultural.finalWarning')}</div>
        <h4>{t('traditionalPanels.cultural.sections.gap')}</h4>
        <div className="traditional-table-wrap"><table className="traditional-table"><thead><tr><th>{t('traditionalPanels.cultural.table.rank')}</th><th>{t('traditionalPanels.cultural.table.unit')}</th><th>{t('traditionalPanels.cultural.table.confirmed')}</th><th>{t('traditionalPanels.cultural.table.candidates')}</th><th>{t('traditionalPanels.cultural.table.categories')}</th></tr></thead><tbody>{ranked.map(item => <tr key={item.admin_unit_id}><td>{item.relative_cultural_heritage_evidence_gap_rank}</td><td>{item.admin_name || item.admin_unit_id}</td><td>{item.confirmed_place_count}</td><td>{item.candidate_lead_count}</td><td>{item.confirmed_category_count}</td></tr>)}</tbody></table></div>
        <button className="primary-button" disabled={!mapPayload} onClick={() => window.__handleMapUpdate?.(mapPayload)}><Map size={14} />{t('traditionalPanels.cultural.actions.sendToMap')}</button>
      </div>
    </div>
  );
}
