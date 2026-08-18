import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { getLocaleHeaders } from '../../i18n';

const LEGACY_SUGGESTION_KEYS: Record<string, string> = {
  '\u7a7a\u95f4\u81ea\u76f8\u5173\u5206\u6790': 'spatialAutocorrelation',
  '\u70ed\u70b9\u5206\u6790': 'hotspotAnalysis',
  '\u6570\u636e\u8d28\u91cf\u5ba1\u8ba1': 'dataQualityAudit',
  '\u7a7a\u95f4\u53ef\u89c6\u5316': 'spatialVisualization',
  'IDW \u7a7a\u95f4\u63d2\u503c': 'idwInterpolation',
};

const CATEGORY_KEYS: Record<string, string> = {
  pattern: 'pattern',
  quality: 'quality',
  visualization: 'visualization',
  analysis: 'analysis',
};

export default function SuggestionsTab() {
  const { t, i18n } = useTranslation();
  const [observations, setObservations] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSuggestions();
    const interval = setInterval(fetchSuggestions, 30000);
    return () => clearInterval(interval);
  }, [i18n.resolvedLanguage]);

  const fetchSuggestions = async () => {
    try {
      const resp = await fetch('/api/suggestions', { credentials: 'include', headers: getLocaleHeaders() });
      if (resp.ok) {
        const data = await resp.json();
        setObservations(data.suggestions || []);
      }
    } catch { /* ignore */ }
    setLoading(false);
  };

  const executeSuggestion = async (obsId: string, prompt: string, pipelineType: string) => {
    try {
      await fetch(`/api/suggestions/${obsId}/execute`, {
        method: 'POST', credentials: 'include',
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, pipeline_type: pipelineType }),
      });
      alert(t('suggestionsTab.messages.submitted'));
    } catch { alert(t('suggestionsTab.errors.execute')); }
  };

  const dismissSuggestion = async (obsId: string) => {
    try {
      await fetch(`/api/suggestions/${obsId}/dismiss`, {
        method: 'POST', credentials: 'include',
        headers: getLocaleHeaders(),
      });
      setObservations(prev => prev.filter(o => o.observation_id !== obsId));
    } catch { /* ignore */ }
  };

  const categoryLabel = (category: string) => {
    const key = CATEGORY_KEYS[category];
    return key ? t(`suggestionsTab.categories.${key}`) : category;
  };

  if (loading) return <div className="data-panel-empty">{t('suggestionsTab.common.loading')}</div>;
  if (observations.length === 0) return <div className="data-panel-empty">{t('suggestionsTab.empty.suggestions')}</div>;

  return (
    <div className="data-panel-list">
      {observations.map((obs: any) => {
        const fileName = obs.file_path?.split(/[/\\]/).pop() || '';
        return (
          <div key={obs.observation_id} className="data-panel-card" style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>{fileName}</div>
            {(obs.suggestions || []).map((suggestion: any, index: number) => {
              const suggestionKey = suggestion.template_key || LEGACY_SUGGESTION_KEYS[suggestion.title];
              const title = suggestionKey
                ? t(`suggestionsTab.builtIns.${suggestionKey}.title`)
                : suggestion.title;
              const description = suggestionKey
                ? t(`suggestionsTab.builtIns.${suggestionKey}.description`)
                : suggestion.description;
              const prompt = suggestionKey
                ? t(`suggestionsTab.builtIns.${suggestionKey}.prompt`, { file: fileName })
                : suggestion.prompt_template;
              return (
                <div key={suggestion.suggestion_id || index} style={{ padding: '6px 0', borderTop: index > 0 ? '1px solid #333' : 'none' }}>
                  <div style={{ fontWeight: 600, fontSize: 13 }}>{title}</div>
                  <div style={{ fontSize: 12, color: '#aaa', margin: '2px 0' }}>{description}</div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                    <span className="data-panel-badge" style={{ background: '#0d9488' }}>{categoryLabel(suggestion.category)}</span>
                    <span style={{ fontSize: 11, color: '#888' }}>
                      {t('suggestionsTab.details.relevance', { rating: '★'.repeat(Math.round((suggestion.relevance_score || 0) * 5)) })}
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                    <button className="data-panel-btn-sm" onClick={() => executeSuggestion(obs.observation_id, prompt, suggestion.pipeline_type)}>{t('suggestionsTab.actions.execute')}</button>
                    <button className="data-panel-btn-sm secondary" onClick={() => dismissSuggestion(obs.observation_id)}>{t('suggestionsTab.actions.dismiss')}</button>
                  </div>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
