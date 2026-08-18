import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { formatNumber, getLocaleHeaders } from '../../i18n';

export default function GeoJsonEditorTab() {
  const { t } = useTranslation();
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [saving, setSaving] = useState(false);

  const validate = () => {
    setError('');
    setInfo('');
    if (!text.trim()) { setError(t('geoJsonEditor.errors.empty')); return null; }
    try {
      const parsed = JSON.parse(text);
      if (!parsed.type) { setError(t('geoJsonEditor.errors.missingType')); return null; }
      if (parsed.type === 'FeatureCollection') {
        const n = parsed.features?.length || 0;
        setInfo(t('geoJsonEditor.info.featureCollection', { count: formatNumber(n) }));
      } else if (parsed.type === 'Feature') {
        setInfo(t('geoJsonEditor.info.singleFeature', {
          geometryType: parsed.geometry?.type || t('geoJsonEditor.common.unknown'),
        }));
      } else {
        setInfo(t('geoJsonEditor.info.type', { type: parsed.type }));
      }
      return parsed;
    } catch (e: any) {
      setError(t('geoJsonEditor.errors.parse', { error: e.message }));
      return null;
    }
  };

  const handleSave = async () => {
    const parsed = validate();
    if (!parsed) return;
    setSaving(true);
    try {
      const blob = new Blob([JSON.stringify(parsed, null, 2)], { type: 'application/json' });
      const formData = new FormData();
      const filename = `geojson_${Date.now()}.geojson`;
      formData.append('file', blob, filename);
      const r = await fetch('/api/user/upload', {
        method: 'POST',
        credentials: 'include',
        headers: getLocaleHeaders(),
        body: formData,
      });
      if (r.ok) {
        setInfo(t('geoJsonEditor.info.saved', { filename }));
        setError('');
      } else {
        setError(t('geoJsonEditor.errors.save'));
      }
    } catch (e: any) {
      setError(t('geoJsonEditor.errors.saveWithReason', { error: e.message }));
    } finally {
      setSaving(false);
    }
  };

  const handleFormat = () => {
    try {
      const parsed = JSON.parse(text);
      setText(JSON.stringify(parsed, null, 2));
      setError('');
    } catch (e: any) {
      setError(t('geoJsonEditor.errors.format', { error: e.message }));
    }
  };

  return (
    <div style={{ padding: '8px 12px', fontSize: 13, display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <span style={{ fontWeight: 600 }}>{t('geoJsonEditor.title')}</span>
        <div style={{ display: 'flex', gap: 6 }}>
          <button className="btn-secondary btn-sm" onClick={validate} style={{ fontSize: 11 }}>{t('geoJsonEditor.actions.validate')}</button>
          <button className="btn-secondary btn-sm" onClick={handleFormat} style={{ fontSize: 11 }}>{t('geoJsonEditor.actions.format')}</button>
          <button className="btn-primary btn-sm" onClick={handleSave} disabled={saving} style={{ fontSize: 11 }}>
            {saving ? t('geoJsonEditor.actions.saving') : t('geoJsonEditor.actions.save')}
          </button>
        </div>
      </div>
      {error && <div style={{ color: '#ef4444', fontSize: 12, marginBottom: 4 }}>{error}</div>}
      {info && <div style={{ color: '#10b981', fontSize: 12, marginBottom: 4 }}>{info}</div>}
      <textarea
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder={t('geoJsonEditor.placeholder')}
        dir="ltr"
        style={{
          flex: 1, minHeight: 200, background: '#0d1117', border: '1px solid #333',
          borderRadius: 6, padding: 8, color: '#e0e0e0', fontFamily: 'monospace',
          fontSize: 12, resize: 'vertical', lineHeight: 1.5, textAlign: 'left',
        }}
      />
    </div>
  );
}
