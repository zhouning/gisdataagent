import { useState, useEffect } from 'react';

export default function SuggestionsTab() {
  const [observations, setObservations] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSuggestions();
    const interval = setInterval(fetchSuggestions, 30000);
    return () => clearInterval(interval);
  }, []);

  const fetchSuggestions = async () => {
    try {
      const resp = await fetch('/api/suggestions', { credentials: 'include' });
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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, pipeline_type: pipelineType }),
      });
      alert('任务已提交到队列');
    } catch { alert('执行失败'); }
  };

  const dismissSuggestion = async (obsId: string) => {
    try {
      await fetch(`/api/suggestions/${obsId}/dismiss`, {
        method: 'POST', credentials: 'include',
      });
      setObservations(prev => prev.filter(o => o.observation_id !== obsId));
    } catch { /* ignore */ }
  };

  if (loading) return <div className="data-panel-empty">加载中...</div>;
  if (observations.length === 0) return <div className="data-panel-empty">暂无分析建议</div>;

  return (
    <div className="data-panel-list">
      {observations.map((obs: any) => (
        <div key={obs.observation_id} className="data-panel-card" style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>{obs.file_path?.split(/[/\\]/).pop()}</div>
          {(obs.suggestions || []).map((s: any, i: number) => (
            <div key={i} style={{ padding: '6px 0', borderTop: i > 0 ? '1px solid #333' : 'none' }}>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{s.title}</div>
              <div style={{ fontSize: 12, color: '#aaa', margin: '2px 0' }}>{s.description}</div>
              <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                <span className="data-panel-badge" style={{ background: '#0d9488' }}>{s.category}</span>
                <span style={{ fontSize: 11, color: '#888' }}>相关度: {'★'.repeat(Math.round((s.relevance_score || 0) * 5))}</span>
              </div>
              <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                <button className="data-panel-btn-sm" onClick={() => executeSuggestion(obs.observation_id, s.prompt_template, s.pipeline_type)}>执行</button>
                <button className="data-panel-btn-sm secondary" onClick={() => dismissSuggestion(obs.observation_id)}>忽略</button>
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
