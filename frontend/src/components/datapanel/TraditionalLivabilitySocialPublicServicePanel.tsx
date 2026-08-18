import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Map, RefreshCw, Shield } from 'lucide-react';
import { formatNumber, getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;
type View = 'social_infrastructure' | 'government_public_service';
const arrayOf = <T,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];

export default function TraditionalLivabilitySocialPublicServicePanel() {
  const { t, i18n } = useTranslation();
  const [view, setView] = useState<View>('social_infrastructure');
  const [overview, setOverview] = useState<Row | null>(null);
  const [facilities, setFacilities] = useState<Row[]>([]);
  const [admins, setAdmins] = useState<Row[]>([]);
  const [mapPayload, setMapPayload] = useState<Row | null>(null);
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    setMessage('');
    try {
      const suffix = '?view=' + view;
      const urls = [
        '/api/uwm/traditional-livability/social-public-service/overview',
        '/api/uwm/traditional-livability/social-public-service/facilities' + suffix,
        '/api/uwm/traditional-livability/social-public-service/admin-units' + suffix,
        '/api/uwm/traditional-livability/social-public-service/map' + suffix,
      ];
      const responses = await Promise.all(urls.map(url => fetch(url, { credentials: 'include', headers: getLocaleHeaders() })));
      const data = await Promise.all(responses.map(response => response.json()));
      if (responses.some(response => !response.ok)) {
        throw new Error(data.find(item => item.error)?.error || t('traditionalPanels.socialService.errors.unavailable'));
      }
      setOverview(data[0]);
      setFacilities(arrayOf<Row>(data[1].facilities));
      setAdmins(arrayOf<Row>(data[2].admin_units));
      setMapPayload(data[3]);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : t('traditionalPanels.socialService.errors.unavailable'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [view, i18n.resolvedLanguage]);
  const ranked = useMemo(() => [...admins].sort((a, b) => Number(a.view?.relative_gap_rank || 9999) - Number(b.view?.relative_gap_rank || 9999)).slice(0, 12), [admins]);
  const readiness = overview?.channel_readiness?.[view] || {};
  const unavailable = Object.entries(readiness).filter(([, row]: [string, any]) => row.status === 'unavailable').map(([name]) => name);
  const count = (value: unknown) => typeof value === 'number' ? formatNumber(value) : String(value ?? '-');

  return (
    <div className="traditional-panel">
      <div className="traditional-panel-title"><strong>{t('traditionalPanels.socialService.title')}</strong><button className="secondary-button" onClick={() => void load()} disabled={loading}><RefreshCw size={14} />{t('traditionalPanels.common.refresh')}</button></div>
      <div className="traditional-tag-list"><button className={view === 'social_infrastructure' ? 'primary-button' : 'secondary-button'} onClick={() => setView('social_infrastructure')}>{t('traditionalPanels.socialService.views.social')}</button><button className={view === 'government_public_service' ? 'primary-button' : 'secondary-button'} onClick={() => setView('government_public_service')}>{t('traditionalPanels.socialService.views.government')}</button></div>
      <p>{t('traditionalPanels.socialService.subtitle')}</p>
      {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
      <div className="traditional-kpi-grid">
        <div className="traditional-kpi"><span>{t('traditionalPanels.socialService.kpis.facilities')}</span><strong>{formatNumber(facilities.length)}</strong></div>
        <div className="traditional-kpi"><span>{t('traditionalPanels.socialService.kpis.districts')}</span><strong>{formatNumber(admins.length)}</strong></div>
        <div className="traditional-kpi"><span>{t('traditionalPanels.socialService.kpis.fabricated')}</span><strong>{count(overview?.fabricated_value_count)}</strong></div>
        <div className="traditional-kpi"><span>{t('traditionalPanels.socialService.kpis.claim')}</span><strong>{overview?.claim_boundary?.max_claim_level || '-'}</strong></div>
      </div>
      <div className="traditional-message error"><Shield size={15} />{t('traditionalPanels.socialService.warning')}</div>
      <h4>{t('traditionalPanels.socialService.sections.unavailable')}</h4><p>{unavailable.join(' / ') || '-'}</p>
      <h4>{t('traditionalPanels.socialService.sections.ranking')}</h4>
      <div className="traditional-table-wrap"><table className="traditional-table"><thead><tr><th>{t('traditionalPanels.socialService.table.rank')}</th><th>{t('traditionalPanels.socialService.table.district')}</th><th>{t('traditionalPanels.socialService.table.facilities')}</th><th>{t('traditionalPanels.socialService.table.categories')}</th><th>{t('traditionalPanels.socialService.table.reasons')}</th></tr></thead><tbody>{ranked.map(row => <tr key={row.admin_unit_id}><td>{row.view?.relative_gap_rank}</td><td>{row.county || row.admin_unit_id}</td><td>{row.view?.facility_count}</td><td>{row.view?.category_count}</td><td>{arrayOf<string>(row.view?.relative_gap_reasons).join(' / ') || '-'}</td></tr>)}</tbody></table></div>
      <button className="primary-button" disabled={!mapPayload} onClick={() => window.__handleMapUpdate?.(mapPayload)}><Map size={14} />{t('traditionalPanels.socialService.actions.sendToMap')}</button>
    </div>
  );
}
