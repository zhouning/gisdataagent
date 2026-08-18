import { useEffect, useState } from 'react';
import { AlertTriangle, RefreshCw, Shield } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;

export default function DevelopmentControlTab() {
  const { t, i18n } = useTranslation();
  const [overview, setOverview] = useState<Row | null>(null);
  const [assets, setAssets] = useState<Row[]>([]);
  const [channels, setChannels] = useState<Row>({});
  const [gate, setGate] = useState<Row>({});
  const [message, setMessage] = useState('');
  const load = async () => {
    try {
      setMessage('');
      const headers = getLocaleHeaders();
      const responses = await Promise.all(['overview', 'rule-assets', 'dcr-channels', 'execution-gate'].map((part) => fetch(`/api/uwm/development-control/${part}`, { credentials: 'include', headers })));
      const data = await Promise.all(responses.map((response) => response.json()));
      if (responses.some((response) => !response.ok)) throw new Error(data.find((item) => item.error)?.error || t('readinessPanels.developmentControl.errors.unavailable'));
      setOverview(data[0]); setAssets(data[1].rule_assets || []); setChannels(data[2].dcr_channels || {}); setGate(data[3].execution_gate || {});
    } catch (error: unknown) { setMessage(error instanceof Error ? error.message : t('readinessPanels.developmentControl.errors.unavailable')); }
  };
  useEffect(() => { void load(); }, [i18n.resolvedLanguage]);
  const list = (value: Row) => Object.entries(value).map(([name, item]) => `${name}:${String((item as Row)?.status ?? item)}`).join(' · ') || t('readinessPanels.common.none');
  return <div className="traditional-livability-tab"><div className="traditional-panel">
    <div className="traditional-panel-title"><strong>{t('readinessPanels.developmentControl.title')}</strong><button className="secondary-button" onClick={() => void load()}><RefreshCw size={14} />{t('readinessPanels.common.refresh')}</button></div>
    <div className="traditional-message error"><Shield size={15} />{t('readinessPanels.developmentControl.warning')}</div>
    {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
    <div className="traditional-kpi-grid"><div className="traditional-kpi"><span>{t('readinessPanels.developmentControl.kpis.assets')}</span><strong>{overview?.summary?.rule_asset_count ?? '-'}</strong></div><div className="traditional-kpi"><span>{t('readinessPanels.developmentControl.kpis.executable')}</span><strong>{overview?.summary?.executable_site_rule_count ?? '-'}</strong></div><div className="traditional-kpi"><span>{t('readinessPanels.developmentControl.kpis.channels')}</span><strong>{overview?.summary?.dcr_channel_count ?? '-'}</strong></div><div className="traditional-kpi"><span>{t('readinessPanels.developmentControl.kpis.available')}</span><strong>{overview?.summary?.available_dcr_channel_count ?? '-'}</strong></div></div>
    <h4>{t('readinessPanels.developmentControl.sections.assets')}</h4><p>{assets.map((item) => `${item.title}:${item.rule_asset_class}/${item.execution_status}`).join(' · ') || t('readinessPanels.developmentControl.emptyAssets')}</p>
    <h4>{t('readinessPanels.developmentControl.sections.channels')}</h4><p>{list(channels)}</p>
    <h4>{t('readinessPanels.developmentControl.sections.gate')}</h4><p>{list(gate.mechanisms || {})}</p>
    <div className="traditional-message error"><Shield size={15} />{t('readinessPanels.developmentControl.finalWarning')}</div>
  </div></div>;
}
