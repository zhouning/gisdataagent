import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, RefreshCw, Shield } from 'lucide-react';
import { getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;

export default function PublicFeedbackReadinessTab() {
  const { t, i18n } = useTranslation();
  const [overview, setOverview] = useState<Row | null>(null);
  const [capabilities, setCapabilities] = useState<Row[]>([]);
  const [channels, setChannels] = useState<Row>({});
  const [gate, setGate] = useState<Row>({});
  const [message, setMessage] = useState('');

  const load = async () => {
    try {
      setMessage('');
      const resources = ['overview', 'capabilities', 'feedback-channels', 'analysis-gate'];
      const responses = await Promise.all(resources.map(resource => fetch('/api/uwm/public-feedback-readiness/' + resource, { credentials: 'include', headers: getLocaleHeaders() })));
      const data = await Promise.all(responses.map(response => response.json()));
      if (responses.some(response => !response.ok)) {
        throw new Error(data.find(item => item.error)?.error || t('readinessPanels.publicFeedback.errors.unavailable'));
      }
      setOverview(data[0]);
      setCapabilities(data[1].capabilities || []);
      setChannels(data[2].feedback_channels || {});
      setGate(data[3].analysis_gate || {});
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : t('readinessPanels.publicFeedback.errors.unavailable'));
    }
  };

  useEffect(() => { void load(); }, [i18n.resolvedLanguage]);

  return (
    <div className="traditional-livability-tab">
      <div className="traditional-panel">
        <div className="traditional-panel-title"><strong>{t('readinessPanels.publicFeedback.title')}</strong><button className="secondary-button" onClick={() => void load()}><RefreshCw size={14} />{t('readinessPanels.common.refresh')}</button></div>
        <div className="traditional-message error"><Shield size={15} />{t('readinessPanels.publicFeedback.warning')}</div>
        {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
        <div className="traditional-kpi-grid">
          <div className="traditional-kpi"><span>{t('readinessPanels.publicFeedback.kpis.capabilities')}</span><strong>{overview?.summary?.capability_count ?? '-'}</strong></div>
          <div className="traditional-kpi"><span>{t('readinessPanels.publicFeedback.kpis.channels')}</span><strong>{overview?.summary?.feedback_channel_count ?? '-'}</strong></div>
          <div className="traditional-kpi"><span>{t('readinessPanels.publicFeedback.kpis.available')}</span><strong>{overview?.summary?.available_feedback_channel_count ?? '-'}</strong></div>
          <div className="traditional-kpi"><span>{t('readinessPanels.publicFeedback.kpis.published')}</span><strong>{overview?.summary?.published_feedback_observation_count ?? '-'}</strong></div>
        </div>
        <h4>{t('readinessPanels.publicFeedback.sections.capabilities')}</h4><p>{capabilities.map(item => String(item.title) + ':' + String(item.capability_type)).join(' · ') || '-'}</p>
        <h4>{t('readinessPanels.publicFeedback.sections.channels')}</h4><p>{Object.entries(channels).map(([key, value]: [string, any]) => key + ':' + String(value.status)).join(' · ') || '-'}</p>
        <h4>{t('readinessPanels.publicFeedback.sections.gate')}</h4><p>{Object.entries(gate.mechanisms || {}).map(([key, value]) => key + ':' + String(value)).join(' · ') || '-'}</p>
        <div className="traditional-message error"><Shield size={15} />{t('readinessPanels.publicFeedback.finalWarning')}</div>
      </div>
    </div>
  );
}
