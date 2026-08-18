import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, RefreshCw, Shield } from 'lucide-react';
import { formatNumber, getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;

export default function InfrastructureNetworkReadinessTab() {
  const { t, i18n } = useTranslation();
  const [overview, setOverview] = useState<Row | null>(null);
  const [assets, setAssets] = useState<Row[]>([]);
  const [channels, setChannels] = useState<Row>({});
  const [gate, setGate] = useState<Row>({});
  const [message, setMessage] = useState('');

  const load = async () => {
    try {
      setMessage('');
      const resources = ['overview', 'infrastructure-assets', 'utility-channels', 'kernel-gate'];
      const responses = await Promise.all(resources.map(resource => fetch('/api/uwm/infrastructure-network-readiness/' + resource, {
        credentials: 'include',
        headers: getLocaleHeaders(),
      })));
      const data = await Promise.all(responses.map(response => response.json()));
      if (responses.some(response => !response.ok)) {
        throw new Error(data.find(item => item.error)?.error || t('readinessPanels.infrastructure.errors.unavailable'));
      }
      setOverview(data[0]);
      setAssets(data[1].infrastructure_assets || []);
      setChannels(data[2].utility_channels || {});
      setGate(data[3].kernel_gate || {});
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : t('readinessPanels.infrastructure.errors.unavailable'));
    }
  };

  useEffect(() => { void load(); }, [i18n.resolvedLanguage]);
  const count = (value: unknown) => typeof value === 'number' ? formatNumber(value) : String(value ?? '-');

  return (
    <div className="traditional-livability-tab">
      <div className="traditional-panel">
        <div className="traditional-panel-title">
          <strong>{t('readinessPanels.infrastructure.title')}</strong>
          <button className="secondary-button" onClick={() => void load()}><RefreshCw size={14} />{t('readinessPanels.common.refresh')}</button>
        </div>
        <div className="traditional-message error"><Shield size={15} />{t('readinessPanels.infrastructure.warning')}</div>
        {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
        <div className="traditional-kpi-grid">
          <div className="traditional-kpi"><span>{t('readinessPanels.infrastructure.kpis.evidenceAssets')}</span><strong>{count(overview?.summary?.evidence_asset_count)}</strong></div>
          <div className="traditional-kpi"><span>{t('readinessPanels.infrastructure.kpis.roads')}</span><strong>{count(overview?.summary?.visible_road_feature_count)}</strong></div>
          <div className="traditional-kpi"><span>{t('readinessPanels.infrastructure.kpis.buildings')}</span><strong>{count(overview?.summary?.visible_building_feature_count)}</strong></div>
          <div className="traditional-kpi"><span>{t('readinessPanels.infrastructure.kpis.utilityNodes')}</span><strong>{count(overview?.summary?.materialized_utility_state_count)}</strong></div>
        </div>
        <h4>{t('readinessPanels.infrastructure.sections.assets')}</h4>
        <p>{assets.map(item => String(item.title) + ':' + String(item.asset_role) + ', ' + t('readinessPanels.common.countLabel') + '=' + String(item.feature_count ?? item.row_count ?? '-')).join(' · ') || '-'}</p>
        <h4>{t('readinessPanels.infrastructure.sections.channels')}</h4>
        <p>{Object.entries(channels).map(([key, value]: [string, any]) => key + ':' + String(value.status)).join(' · ') || '-'}</p>
        <h4>{t('readinessPanels.infrastructure.sections.kernel')}</h4>
        <p>{Object.entries(gate.mechanisms || {}).map(([key, value]) => key + ':' + String(value)).join(' · ') || '-'}</p>
        <div className="traditional-message error"><Shield size={15} />{t('readinessPanels.infrastructure.finalWarning')}</div>
      </div>
    </div>
  );
}
