import { useEffect, useState } from 'react';
import { AlertTriangle, Map, RefreshCw, Shield } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;

export default function BusinessLicenceTab() {
  const { t, i18n } = useTranslation();
  const [overview, setOverview] = useState<Row | null>(null);
  const [admins, setAdmins] = useState<Row[]>([]);
  const [channels, setChannels] = useState<Row>({});
  const [gate, setGate] = useState<Row>({});
  const [map, setMap] = useState<Row | null>(null);
  const [message, setMessage] = useState('');

  const load = async () => {
    try {
      setMessage('');
      const headers = getLocaleHeaders();
      const responses = await Promise.all(['overview', 'admin-units', 'licence-channels', 'uwm-gate', 'map'].map((part) => fetch(`/api/uwm/business-licence/${part}`, { credentials: 'include', headers })));
      const data = await Promise.all(responses.map((response) => response.json()));
      if (responses.some((response) => !response.ok)) throw new Error(data.find((item) => item.error)?.error || t('readinessPanels.businessLicence.errors.unavailable'));
      setOverview(data[0]); setAdmins(data[1].admin_units || []); setChannels(data[2].licence_channels || {}); setGate(data[3].uwm_gate || {}); setMap(data[4]);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : t('readinessPanels.businessLicence.errors.unavailable'));
    }
  };

  useEffect(() => { void load(); }, [i18n.resolvedLanguage]);
  const list = (value: Row, key = 'status') => Object.entries(value).map(([name, item]) => `${name}:${String((item as Row)?.[key] ?? item)}`).join(' · ') || t('readinessPanels.common.none');

  return <div className="traditional-livability-tab"><div className="traditional-panel">
    <div className="traditional-panel-title"><strong>{t('readinessPanels.businessLicence.title')}</strong><button className="secondary-button" onClick={() => void load()}><RefreshCw size={14} />{t('readinessPanels.common.refresh')}</button></div>
    <div className="traditional-message error"><Shield size={15} />{t('readinessPanels.businessLicence.warning')}</div>
    {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
    <div className="traditional-kpi-grid"><div className="traditional-kpi"><span>{t('readinessPanels.businessLicence.kpis.poi')}</span><strong>{overview?.summary?.business_poi_count ?? '-'}</strong></div><div className="traditional-kpi"><span>{t('readinessPanels.businessLicence.kpis.districts')}</span><strong>{overview?.summary?.admin_unit_count ?? '-'}</strong></div><div className="traditional-kpi"><span>{t('readinessPanels.businessLicence.kpis.channels')}</span><strong>{overview?.summary?.available_licence_channel_count ?? '-'}</strong></div><div className="traditional-kpi"><span>{t('readinessPanels.businessLicence.kpis.mechanisms')}</span><strong>{overview?.summary?.open_lifecycle_mechanism_count ?? '-'}</strong></div></div>
    <h4>{t('readinessPanels.businessLicence.sections.admin')}</h4><p>{admins.slice(0, 12).map((item) => `${item.admin_name}:${item.business_poi_count}`).join(' · ') || t('readinessPanels.businessLicence.emptyAssets')}</p>
    <h4>{t('readinessPanels.businessLicence.sections.channels')}</h4><p>{list(channels)}</p>
    <h4>{t('readinessPanels.businessLicence.sections.gate')}</h4><p>{list(gate.mechanisms || {})}</p>
    <div className="traditional-message error"><Shield size={15} />{t('readinessPanels.businessLicence.finalWarning')}</div>
    <button className="primary-button" disabled={!map} onClick={() => window.__handleMapUpdate?.(map)}><Map size={14} />{t('readinessPanels.businessLicence.sendToMap')}</button>
  </div></div>;
}
