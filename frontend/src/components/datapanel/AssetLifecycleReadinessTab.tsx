import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, RefreshCw, Shield } from 'lucide-react';
import { formatNumber, getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;

export default function AssetLifecycleReadinessTab() {
  const { t, i18n } = useTranslation();
  const [overview, setOverview] = useState<Row | null>(null);
  const [products, setProducts] = useState<Row[]>([]);
  const [channels, setChannels] = useState<Row>({});
  const [gate, setGate] = useState<Row>({});
  const [message, setMessage] = useState('');

  const load = async () => {
    try {
      setMessage('');
      const resources = ['overview', 'source-products', 'lifecycle-channels', 'lifecycle-gate'];
      const responses = await Promise.all(resources.map(resource => fetch('/api/uwm/asset-lifecycle-readiness/' + resource, {
        credentials: 'include',
        headers: getLocaleHeaders(),
      })));
      const data = await Promise.all(responses.map(response => response.json()));
      if (responses.some(response => !response.ok)) {
        throw new Error(data.find(item => item.error)?.error || t('readinessPanels.assetLifecycle.errors.unavailable'));
      }
      setOverview(data[0]);
      setProducts(data[1].source_products || []);
      setChannels(data[2].lifecycle_channels || {});
      setGate(data[3].lifecycle_gate || {});
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : t('readinessPanels.assetLifecycle.errors.unavailable'));
    }
  };

  useEffect(() => { void load(); }, [i18n.resolvedLanguage]);
  const count = (value: unknown) => typeof value === 'number' ? formatNumber(value) : String(value ?? '-');

  return (
    <div className="traditional-livability-tab">
      <div className="traditional-panel">
        <div className="traditional-panel-title">
          <strong>{t('readinessPanels.assetLifecycle.title')}</strong>
          <button className="secondary-button" onClick={() => void load()}><RefreshCw size={14} />{t('readinessPanels.common.refresh')}</button>
        </div>
        <div className="traditional-message error"><Shield size={15} />{t('readinessPanels.assetLifecycle.warning')}</div>
        {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
        <div className="traditional-kpi-grid">
          <div className="traditional-kpi"><span>{t('readinessPanels.assetLifecycle.kpis.sourceProducts')}</span><strong>{count(overview?.summary?.source_product_count)}</strong></div>
          <div className="traditional-kpi"><span>{t('readinessPanels.assetLifecycle.kpis.uniqueAssets')}</span><strong>{count(overview?.summary?.unique_asset_count ?? t('readinessPanels.common.unavailable'))}</strong></div>
          <div className="traditional-kpi"><span>{t('readinessPanels.assetLifecycle.kpis.stateNodes')}</span><strong>{count(overview?.summary?.materialized_asset_state_count)}</strong></div>
          <div className="traditional-kpi"><span>{t('readinessPanels.assetLifecycle.kpis.events')}</span><strong>{count(overview?.summary?.observed_lifecycle_event_count)}</strong></div>
        </div>
        <h4>{t('readinessPanels.assetLifecycle.sections.catalog')}</h4>
        <p>{products.map(item => String(item.product_id) + ':' + String(item.record_count) + ' (' + String(item.record_semantics) + ')').join(' · ') || '-'}</p>
        <h4>{t('readinessPanels.assetLifecycle.sections.channels')}</h4>
        <p>{Object.entries(channels).map(([key, value]: [string, any]) => `${key}:${t(`statusLabels.${String(value.status)}`, { defaultValue: String(value.status) })}`).join(' · ') || '-'}</p>
        <h4>{t('readinessPanels.assetLifecycle.sections.kernel')}</h4>
        <p>{Object.entries(gate.mechanisms || {}).map(([key, value]) => key + ':' + String(value)).join(' · ') || '-'}</p>
        <div className="traditional-message error"><Shield size={15} />{t('readinessPanels.assetLifecycle.finalWarning')}</div>
      </div>
    </div>
  );
}
