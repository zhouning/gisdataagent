import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, RefreshCw, Shield } from 'lucide-react';
import { getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;

export default function OperationsQualityTab() {
  const { t, i18n } = useTranslation();
  const [overview, setOverview] = useState<Row | null>(null);
  const [capabilities, setCapabilities] = useState<Row[]>([]);
  const [channels, setChannels] = useState<Row>({});
  const [gate, setGate] = useState<Row>({});
  const [message, setMessage] = useState('');

  const load = async () => {
    try {
      setMessage('');
      const resources = ['overview', 'platform-operations', 'customer-channels', 'uwm-gate'];
      const responses = await Promise.all(resources.map(resource => fetch('/api/uwm/operations-quality/' + resource, {
        credentials: 'include',
        headers: getLocaleHeaders(),
      })));
      const data = await Promise.all(responses.map(response => response.json()));
      if (responses.some(response => !response.ok)) {
        throw new Error(data.find(item => item.error)?.error || t('readinessPanels.operations.errors.unavailable'));
      }
      setOverview(data[0]);
      setCapabilities(data[1].platform_operations || []);
      setChannels(data[2].customer_channels || {});
      setGate(data[3].uwm_gate || {});
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : t('readinessPanels.operations.errors.unavailable'));
    }
  };

  useEffect(() => { void load(); }, [i18n.resolvedLanguage]);

  return (
    <div className="traditional-livability-tab">
      <div className="traditional-panel">
        <div className="traditional-panel-title">
          <strong>{t('readinessPanels.operations.title')}</strong>
          <button className="secondary-button" onClick={() => void load()}><RefreshCw size={14} />{t('readinessPanels.common.refresh')}</button>
        </div>
        <div className="traditional-message error"><Shield size={15} />{t('readinessPanels.operations.warning')}</div>
        {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
        <div className="traditional-kpi-grid">
          <div className="traditional-kpi"><span>{t('readinessPanels.operations.kpis.platform')}</span><strong>{overview?.summary?.platform_operation_capability_count ?? '-'}</strong></div>
          <div className="traditional-kpi"><span>{t('readinessPanels.operations.kpis.customerChannels')}</span><strong>{overview?.summary?.customer_channel_count ?? '-'}</strong></div>
          <div className="traditional-kpi"><span>{t('readinessPanels.operations.kpis.availableChannels')}</span><strong>{overview?.summary?.available_customer_channel_count ?? '-'}</strong></div>
          <div className="traditional-kpi"><span>{t('readinessPanels.operations.kpis.mechanisms')}</span><strong>{overview?.summary?.open_uwm_mechanism_count ?? '-'}</strong></div>
        </div>
        <h4>{t('readinessPanels.operations.sections.capabilities')}</h4>
        <p>{capabilities.map(item => item.capability_id).join(' · ') || '-'}</p>
        <h4>{t('readinessPanels.operations.sections.sla')}</h4>
        <p>{Object.entries(channels).map(([key, value]: [string, any]) => `${key}:${t(`statusLabels.${String(value.status)}`, { defaultValue: String(value.status) })}`).join(' · ') || '-'}</p>
        <h4>{t('readinessPanels.operations.sections.kernel')}</h4>
        <p>{Object.entries(gate.mechanisms || {}).map(([key, value]) => key + ':' + String(value)).join(' · ') || '-'}</p>
        <div className="traditional-message error"><Shield size={15} />{t('readinessPanels.operations.finalWarning')}</div>
      </div>
    </div>
  );
}
