import { useState, useEffect } from 'react';

interface ClassifiedAsset {
  id: number;
  name: string;
  sensitivity: string;
  category: string;
  description: string;
  feature_count: string | null;
  crs: string | null;
  derived_from: string | null;
  source_tables: string[] | null;
}

const SENS_LABEL: Record<string, string> = {
  secret: '绝密', restricted: '限制', confidential: '机密',
  internal: '内部', public: '公开', unclassified: '未分级',
};
const SENS_COLOR: Record<string, string> = {
  secret: '#991b1b', restricted: '#ef4444', confidential: '#f59e0b',
  internal: '#3b82f6', public: '#22c55e', unclassified: '#6b7280',
};

export default function ClassificationTab() {
  const [assets, setAssets] = useState<ClassifiedAsset[]>([]);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState('');
  const [showAnon, setShowAnon] = useState(false);
  const [anonForm, setAnonForm] = useState({
    source_table: '', output_table: '', level: 'L3',
    data_type: 'polygon', keep_attrs: 'dlmc,tbmj',
    category_column: '类型', k_anonymity: 5,
  });
  const [anonResult, setAnonResult] = useState<any>(null);
  const [anonLoading, setAnonLoading] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    try {
      const resp = await fetch('/api/classification/summary', { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setAssets(data.assets || []);
        setSummary(data.summary || {});
      }
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  useEffect(() => { fetchData(); }, []);

  const runAnonymize = async () => {
    setAnonLoading(true);
    setAnonResult(null);
    try {
      const body: any = {
        source_table: anonForm.source_table,
        output_table: anonForm.output_table,
        level: anonForm.level,
        data_type: anonForm.data_type,
        k_anonymity: anonForm.k_anonymity,
      };
      if (anonForm.data_type === 'polygon') {
        body.keep_attrs = anonForm.keep_attrs.split(',').map((s: string) => s.trim());
      } else {
        body.category_column = anonForm.category_column;
      }
      const resp = await fetch('/api/classification/anonymize', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      setAnonResult(data);
      if (data.status === 'ok') fetchData();
    } catch (e: any) { setAnonResult({ status: 'error', message: e.message }); }
    setAnonLoading(false);
  };

  const filtered = filter
    ? assets.filter(a => a.sensitivity === filter)
    : assets;

  return (
    <div style={{ padding: '12px', fontSize: '13px', height: '100%', overflow: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ fontWeight: 600 }}>数据分级总览</span>
        <button onClick={fetchData} disabled={loading}
          style={{ fontSize: 12, padding: '2px 8px', cursor: 'pointer' }}>
          {loading ? '加载中...' : '刷新'}
        </button>
        <button onClick={() => setShowAnon(!showAnon)}
          style={{ fontSize: 12, padding: '2px 8px', cursor: 'pointer',
                   background: showAnon ? '#3b82f6' : '#f3f4f6',
                   color: showAnon ? '#fff' : '#333', border: 'none', borderRadius: 3 }}>
          {showAnon ? '收起脱密' : '一键脱密'}
        </button>
      </div>

      {/* Anonymize panel */}
      {showAnon && (
        <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 6,
                      padding: 10, marginBottom: 12, fontSize: 12 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6, marginBottom: 8 }}>
            <label>源表<br/>
              <input value={anonForm.source_table} style={{ width: '100%', fontSize: 12 }}
                onChange={e => setAnonForm({...anonForm, source_table: e.target.value})}
                placeholder="cq_dltb" />
            </label>
            <label>输出表<br/>
              <input value={anonForm.output_table} style={{ width: '100%', fontSize: 12 }}
                onChange={e => setAnonForm({...anonForm, output_table: e.target.value})}
                placeholder="cq_dltb_grid_l3_public" />
            </label>
            <label>等级<br/>
              <select value={anonForm.level} style={{ width: '100%', fontSize: 12 }}
                onChange={e => setAnonForm({...anonForm, level: e.target.value})}>
                <option value="L1">L1 (25m 内部)</option>
                <option value="L2">L2 (100m 内部)</option>
                <option value="L3">L3 (250m 共享)</option>
                <option value="L4">L4 (1000m 公开)</option>
              </select>
            </label>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6, marginBottom: 8 }}>
            <label>数据类型<br/>
              <select value={anonForm.data_type} style={{ width: '100%', fontSize: 12 }}
                onChange={e => setAnonForm({...anonForm, data_type: e.target.value})}>
                <option value="polygon">面数据 (图斑)</option>
                <option value="point">点数据 (POI)</option>
              </select>
            </label>
            {anonForm.data_type === 'polygon' ? (
              <label>保留字段<br/>
                <input value={anonForm.keep_attrs} style={{ width: '100%', fontSize: 12 }}
                  onChange={e => setAnonForm({...anonForm, keep_attrs: e.target.value})}
                  placeholder="dlmc,tbmj" />
              </label>
            ) : (
              <label>分类字段<br/>
                <input value={anonForm.category_column} style={{ width: '100%', fontSize: 12 }}
                  onChange={e => setAnonForm({...anonForm, category_column: e.target.value})}
                  placeholder="类型" />
              </label>
            )}
            <label>k-匿名<br/>
              <input type="number" value={anonForm.k_anonymity} style={{ width: '100%', fontSize: 12 }}
                onChange={e => setAnonForm({...anonForm, k_anonymity: parseInt(e.target.value) || 5})} />
            </label>
          </div>
          <button onClick={runAnonymize} disabled={anonLoading || !anonForm.source_table}
            style={{ fontSize: 12, padding: '4px 12px', background: '#3b82f6', color: '#fff',
                     border: 'none', borderRadius: 3, cursor: 'pointer' }}>
            {anonLoading ? '执行中...' : '执行脱密'}
          </button>
          {anonResult && (
            <div style={{ marginTop: 8, padding: 6, borderRadius: 4, fontSize: 11,
                          background: anonResult.status === 'ok' ? '#dcfce7' : '#fee2e2' }}>
              {anonResult.status === 'ok'
                ? `完成: ${anonResult.output_row_count || anonResult.output_table} 格网, 等级=${anonResult.level}`
                : `错误: ${anonResult.message || anonResult.error}`}
            </div>
          )}
        </div>
      )}

      {/* Summary badges */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
        <span onClick={() => setFilter('')}
          style={{ padding: '2px 8px', borderRadius: 4, cursor: 'pointer',
                   background: !filter ? '#e5e7eb' : 'transparent', fontSize: 12 }}>
          全部 ({assets.length})
        </span>
        {Object.entries(SENS_LABEL).map(([key, label]) => {
          const count = summary[key] || 0;
          if (!count) return null;
          return (
            <span key={key} onClick={() => setFilter(filter === key ? '' : key)}
              style={{ padding: '2px 8px', borderRadius: 4, cursor: 'pointer',
                       background: filter === key ? SENS_COLOR[key] + '22' : 'transparent',
                       border: `1px solid ${SENS_COLOR[key]}`, color: SENS_COLOR[key], fontSize: 12 }}>
              {label} ({count})
            </span>
          );
        })}
      </div>

      {/* Asset table */}
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid #e5e7eb', textAlign: 'left' }}>
            <th style={{ padding: '4px 6px' }}>等级</th>
            <th style={{ padding: '4px 6px' }}>表名</th>
            <th style={{ padding: '4px 6px' }}>说明</th>
            <th style={{ padding: '4px 6px' }}>来源</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map(a => (
            <tr key={a.id} style={{ borderBottom: '1px solid #f3f4f6' }}>
              <td style={{ padding: '4px 6px' }}>
                <span style={{ display: 'inline-block', padding: '1px 6px', borderRadius: 3,
                               background: SENS_COLOR[a.sensitivity] + '18',
                               color: SENS_COLOR[a.sensitivity], fontWeight: 500, fontSize: 11 }}>
                  {SENS_LABEL[a.sensitivity] || a.sensitivity}
                </span>
              </td>
              <td style={{ padding: '4px 6px', fontFamily: 'monospace' }}>{a.name}</td>
              <td style={{ padding: '4px 6px', color: '#6b7280', maxWidth: 200,
                           overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {a.description}
              </td>
              <td style={{ padding: '4px 6px', color: '#9ca3af', fontSize: 11 }}>
                {a.derived_from ? `← ${a.derived_from}` : '原始'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {filtered.length === 0 && !loading && (
        <div style={{ textAlign: 'center', color: '#9ca3af', padding: 20 }}>暂无数据</div>
      )}
    </div>
  );
}
