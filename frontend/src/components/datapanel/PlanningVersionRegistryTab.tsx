import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, RefreshCw, Shield } from 'lucide-react';
import { getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;

export default function PlanningVersionRegistryTab() {
  const { t, i18n } = useTranslation();
  const [overview, setOverview] = useState<Row | null>(null);
  const [assets, setAssets] = useState<Row[]>([]);
  const [channels, setChannels] = useState<Row>({});
  const [gate, setGate] = useState<Row>({});
  const [message, setMessage] = useState('');

  const load = async () => {
    try {
      setMessage('');
      const resources = ['overview', 'version-assets', 'version-channels', 'temporal-gate'];
      const responses = await Promise.all(resources.map(resource => fetch('/api/uwm/planning-version-registry/' + resource, { credentials: 'include', headers: getLocaleHeaders() })));
      const data = await Promise.all(responses.map(response => response.json()));
      if (responses.some(response => !response.ok)) {
        throw new Error(data.find(item => item.error)?.error || t('readinessPanels.planningVersion.errors.unavailable'));
      }
      setOverview(data[0]);
      setAssets(data[1].version_assets || []);
      setChannels(data[2].version_channels || {});
      setGate(data[3].temporal_gate || {});
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : t('readinessPanels.planningVersion.errors.unavailable'));
    }
  };

  useEffect(() => { void load(); }, [i18n.resolvedLanguage]);
  return (
    <div className="traditional-livability-tab">
      <div className="traditional-panel">
        <div className="traditional-panel-title"><strong>{t('readinessPanels.planningVersion.title')}</strong><button className="secondary-button" onClick={() => void load()}><RefreshCw size={14} />{t('readinessPanels.common.refresh')}</button></div>
        <div className="traditional-message error"><Shield size={15} />{t('readinessPanels.planningVersion.warning')}</div>
        {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
        <div className="traditional-kpi-grid">
          <div className="traditional-kpi"><span>{t('readinessPanels.planningVersion.kpis.assets')}</span><strong>{overview?.summary?.version_asset_count ?? '-'}</strong></div>
          <div className="traditional-kpi"><span>{t('readinessPanels.planningVersion.kpis.verified')}</span><strong>{overview?.summary?.verified_approval_asset_count ?? '-'}</strong></div>
          <div className="traditional-kpi"><span>{t('readinessPanels.planningVersion.kpis.authoritative')}</span><strong>{overview?.summary?.authoritative_current_version_count ?? '-'}</strong></div>
          <div className="traditional-kpi"><span>{t('readinessPanels.planningVersion.kpis.temporal')}</span><strong>{overview?.summary?.open_temporal_mechanism_count ?? '-'}</strong></div>
        </div>
        <h4>{t('readinessPanels.planningVersion.sections.assets')}</h4>
        <p>{assets.map(item => String(item.title) + ':' + String(item.feature_count ?? item.row_count ?? '-') + (item.layer_count ? '/' + String(item.layer_count) + ' ' + t('readinessPanels.planningVersion.layers') : '') + ', ' + t('readinessPanels.planningVersion.approval') + '=' + String(item.approval_status)).join(' · ') || '-'}</p>
        <h4>{t('readinessPanels.planningVersion.sections.channels')}</h4><p>{Object.entries(channels).map(([key, value]: [string, any]) => key + ':' + String(value.status)).join(' · ') || '-'}</p>
        <h4>{t('readinessPanels.planningVersion.sections.kernel')}</h4><p>{Object.entries(gate.mechanisms || {}).map(([key, value]) => key + ':' + String(value)).join(' · ') || '-'}</p>
        <div className="traditional-message error"><Shield size={15} />{t('readinessPanels.planningVersion.finalWarning')}</div>
      </div>
    </div>
  );
}
