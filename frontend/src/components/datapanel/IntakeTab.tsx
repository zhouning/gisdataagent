import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { formatNumber, getLocaleHeaders } from '../../i18n';

interface DatasetProfile {
  id: number;
  table_name: string;
  schema_name: string;
  row_count: number;
  geometry_type: string | null;
  status: string;
  created_at: string;
}

export default function IntakeTab() {
  const { t, i18n } = useTranslation();
  const [profiles, setProfiles] = useState<DatasetProfile[]>([]);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<any>(null);
  const [activating, setActivating] = useState(false);
  const [message, setMessage] = useState('');
  const [messageError, setMessageError] = useState(false);

  const feedback = (value: string, error = false) => { setMessage(value); setMessageError(error); };

  const fetchProfiles = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/intake/profiles?schema=public&latest=1', { credentials: 'include', headers: getLocaleHeaders() });
      if (response.ok) { const data = await response.json(); setProfiles(data.profiles || []); }
      else feedback(t('intakeTab.messages.requestException', { error: response.statusText }), true);
    } catch (error: any) { feedback(t('intakeTab.messages.requestException', { error: error?.message || t('intakeTab.unknownError') }), true); }
    finally { setLoading(false); }
  };

  useEffect(() => { void fetchProfiles(); }, [i18n.resolvedLanguage]);

  const handleScan = async () => {
    setScanning(true); setValidationResult(null); setMessage('');
    try {
      const response = await fetch('/api/intake/scan', { method: 'POST', credentials: 'include', headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ schema: 'public' }) });
      const data = await response.json();
      if (data.status === 'ok') { feedback(t('intakeTab.messages.scanComplete', { count: formatNumber(Number(data.tables_found || 0)) })); void fetchProfiles(); }
      else feedback(t('intakeTab.messages.scanFailed', { error: data.error || t('intakeTab.unknownError') }), true);
    } catch (error: any) { feedback(t('intakeTab.messages.scanException', { error: error?.message || t('intakeTab.unknownError') }), true); }
    finally { setScanning(false); }
  };

  const handleGenerateDraft = async (profileId: number) => {
    setMessage('');
    try {
      const response = await fetch(`/api/intake/${profileId}/draft`, { method: 'POST', credentials: 'include', headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ use_llm: true }) });
      const data = await response.json();
      if (data.status === 'ok') { feedback(t('intakeTab.messages.draftComplete', { table: data.table_name, version: data.version, confidence: formatNumber(Number(data.confidence || 0), { style: 'percent', maximumFractionDigits: 0 }) })); void fetchProfiles(); }
      else feedback(t('intakeTab.messages.draftFailed', { error: data.error || t('intakeTab.unknownError') }), true);
    } catch (error: any) { feedback(t('intakeTab.messages.requestException', { error: error?.message || t('intakeTab.unknownError') }), true); }
  };

  const handleValidate = async (profileId: number) => {
    setValidating(true); setValidationResult(null); setMessage('');
    try {
      const response = await fetch(`/api/intake/${profileId}/validate`, { method: 'POST', credentials: 'include', headers: getLocaleHeaders() });
      const data = await response.json(); setValidationResult(data);
      const score = formatNumber(Number(data.eval_score || 0), { style: 'percent', maximumFractionDigits: 0 });
      feedback(data.passed ? t('intakeTab.messages.validationPassed', { table: data.table_name, score }) : t('intakeTab.messages.validationFailed', { score }), !data.passed);
      void fetchProfiles();
    } catch (error: any) { feedback(t('intakeTab.messages.validationException', { error: error?.message || t('intakeTab.unknownError') }), true); }
    finally { setValidating(false); }
  };

  const handleActivate = async (draftId: number, evalScore: number) => {
    setActivating(true); setMessage('');
    try {
      const response = await fetch(`/api/intake/${draftId}/activate`, { method: 'POST', credentials: 'include', headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ eval_score: evalScore }) });
      const data = await response.json();
      if (data.status === 'ok') { feedback(t('intakeTab.messages.activated', { table: data.table_name, version: data.version })); void fetchProfiles(); }
      else feedback(t('intakeTab.messages.activateFailed', { error: data.error || t('intakeTab.unknownError') }), true);
    } catch (error: any) { feedback(t('intakeTab.messages.activateException', { error: error?.message || t('intakeTab.unknownError') }), true); }
    finally { setActivating(false); }
  };

  const handleRollback = async (datasetId: number) => {
    setMessage('');
    try {
      const response = await fetch(`/api/intake/${datasetId}/rollback`, { method: 'POST', credentials: 'include', headers: getLocaleHeaders() });
      const data = await response.json();
      if (data.status === 'ok') feedback(t('intakeTab.messages.rollbackComplete')); else feedback(t('intakeTab.messages.rollbackFailed', { error: data.error || t('intakeTab.unknownError') }), true);
      void fetchProfiles();
    } catch (error: any) { feedback(t('intakeTab.messages.rollbackException', { error: error?.message || t('intakeTab.unknownError') }), true); }
  };

  const activateValidated = async (profileId: number) => {
    try {
      const response = await fetch(`/api/intake/${profileId}/draft`, { credentials: 'include', headers: getLocaleHeaders() });
      if (!response.ok) { feedback(t('intakeTab.messages.draftFetchFailed'), true); return; }
      const draft = await response.json();
      await handleActivate(draft.id, validationResult?.eval_score ?? 0.85);
    } catch (error: any) { feedback(t('intakeTab.messages.activateException', { error: error?.message || t('intakeTab.unknownError') }), true); }
  };

  const statusColor = (status: string) => ({ active: '#22c55e', validated: '#3b82f6', reviewed: '#f59e0b', drafted: '#a78bfa' }[status] || '#94a3b8');
  const statusLabel = (status: string) => t(`intakeTab.statuses.${status}`, { defaultValue: status });

  return <div style={{ padding: '12px', fontSize: '13px' }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}><h3 style={{ margin: 0, fontSize: '14px' }}>{t('intakeTab.title')}</h3><button onClick={() => void handleScan()} disabled={scanning} style={{ padding: '4px 12px', fontSize: '12px', cursor: scanning ? 'wait' : 'pointer', background: '#3b82f6', color: '#fff', border: 'none', borderRadius: 4 }}>{scanning ? t('intakeTab.actions.scanning') : t('intakeTab.actions.scanNewTable')}</button></div>
    {message && <div style={{ padding: '6px 10px', marginBottom: 10, borderRadius: 4, background: messageError ? '#fef2f2' : '#f0fdf4', color: messageError ? '#dc2626' : '#16a34a', fontSize: '12px' }}>{message}</div>}
    {loading ? <div>{t('intakeTab.actions.loading')}</div> : <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}><thead><tr style={{ borderBottom: '1px solid #e2e8f0', textAlign: 'start' }}><th style={{ padding: '6px 4px' }}>{t('intakeTab.columns.schema')}</th><th style={{ padding: '6px 4px' }}>{t('intakeTab.columns.tableName')}</th><th style={{ padding: '6px 4px' }}>{t('intakeTab.columns.rows')}</th><th style={{ padding: '6px 4px' }}>{t('intakeTab.columns.geometry')}</th><th style={{ padding: '6px 4px' }}>{t('intakeTab.columns.status')}</th><th style={{ padding: '6px 4px' }}>{t('intakeTab.columns.actions')}</th></tr></thead><tbody>
      {profiles.map((profile) => <tr key={profile.id} style={{ borderBottom: '1px solid #f1f5f9' }}><td style={{ padding: '6px 4px', fontFamily: 'monospace', color: '#64748b' }}>{profile.schema_name}</td><td style={{ padding: '6px 4px', fontFamily: 'monospace' }}>{profile.table_name}</td><td style={{ padding: '6px 4px' }}>{formatNumber(Number(profile.row_count || 0))}</td><td style={{ padding: '6px 4px' }}>{profile.geometry_type || t('intakeTab.noValue')}</td><td style={{ padding: '6px 4px' }}><span style={{ padding: '2px 6px', borderRadius: 3, fontSize: '11px', background: `${statusColor(profile.status)}22`, color: statusColor(profile.status) }}>{statusLabel(profile.status)}</span></td><td style={{ padding: '6px 4px' }}>
        {profile.status === 'discovered' && <button onClick={() => void handleGenerateDraft(profile.id)} style={{ fontSize: '11px', padding: '2px 8px', cursor: 'pointer', background: '#a78bfa', color: '#fff', border: 'none', borderRadius: 3 }}>{t('intakeTab.actions.generateDraft')}</button>}
        {profile.status === 'drafted' && <button onClick={() => void handleValidate(profile.id)} disabled={validating} style={{ fontSize: '11px', padding: '2px 8px', cursor: 'pointer', background: '#f59e0b', color: '#fff', border: 'none', borderRadius: 3 }}>{validating ? t('intakeTab.actions.validating') : t('intakeTab.actions.validate')}</button>}
        {profile.status === 'reviewed' && <button onClick={() => void handleValidate(profile.id)} disabled={validating} style={{ fontSize: '11px', padding: '2px 8px', cursor: 'pointer', background: '#3b82f6', color: '#fff', border: 'none', borderRadius: 3 }}>{validating ? t('intakeTab.actions.validating') : t('intakeTab.actions.validateActivate')}</button>}
        {profile.status === 'validated' && <button onClick={() => void activateValidated(profile.id)} disabled={activating} style={{ fontSize: '11px', padding: '2px 8px', cursor: 'pointer', background: '#22c55e', color: '#fff', border: 'none', borderRadius: 3 }}>{activating ? t('intakeTab.actions.activating') : t('intakeTab.actions.activate')}</button>}
        {profile.status === 'active' && <button onClick={() => void handleRollback(profile.id)} style={{ fontSize: '11px', padding: '2px 8px', cursor: 'pointer', background: '#ef4444', color: '#fff', border: 'none', borderRadius: 3 }}>{t('intakeTab.actions.rollback')}</button>}
      </td></tr>)}
      {profiles.length === 0 && <tr><td colSpan={6} style={{ padding: 16, textAlign: 'center', color: '#94a3b8' }}>{t('intakeTab.empty')}</td></tr>}
    </tbody></table>}
    {validationResult && <div style={{ marginTop: 12, padding: 10, background: '#f8fafc', borderRadius: 4, fontSize: '12px' }}><strong>{t('intakeTab.validationResult', { table: validationResult.table_name })}</strong><span style={{ marginInlineStart: 8, color: validationResult.passed ? '#16a34a' : '#dc2626' }}>{formatNumber(Number(validationResult.eval_score || 0), { style: 'percent', maximumFractionDigits: 0 })} ({validationResult.passed_count}/{validationResult.total})</span><div style={{ marginTop: 6 }}><div style={{ fontWeight: 600, marginBottom: 4 }}>{t('intakeTab.details')}</div>{(validationResult.details || []).map((detail: any, index: number) => <div key={index} style={{ padding: '2px 0', color: detail.passed ? '#16a34a' : '#dc2626' }}>{detail.passed ? '✓' : '✗'} [{detail.type}] {detail.question?.substring(0, 60)}</div>)}</div></div>}
  </div>;
}
