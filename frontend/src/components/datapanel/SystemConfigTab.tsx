/**
 * SystemConfigTab — 系统配置（系统管理组）
 *
 * 对接后端：
 * - GET /api/gateway/models — 模型列表
 * - GET /api/gateway/cost-summary — 成本汇总
 * - GET /api/admin/flags — 功能开关列表
 * - PUT /api/admin/flags — 设置功能开关
 * - DELETE /api/admin/flags/{name} — 删除功能开关
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Settings, Loader2, AlertCircle, Cpu, DollarSign,
  ToggleLeft, ToggleRight, Trash2, Plus, RefreshCw,
} from 'lucide-react';

interface ModelInfo {
  name?: string;
  model_id?: string;
  provider?: string;
  type?: string;
  capabilities?: string[];
  online?: boolean;
}

interface CostEntry {
  scenario: string;
  project_id: string;
  total_cost: number;
  call_count: number;
}

interface FeatureFlag {
  name: string;
  enabled: boolean;
}

type Section = 'models' | 'cost' | 'flags';

export default function SystemConfigTab() {
  const [section, setSection] = useState<Section>('models');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [models, setModels] = useState<ModelInfo[]>([]);
  const [costs, setCosts] = useState<CostEntry[]>([]);
  const [flags, setFlags] = useState<FeatureFlag[]>([]);
  const [newFlagName, setNewFlagName] = useState('');

  useEffect(() => {
    setError(null);
    if (section === 'models' && models.length === 0) loadModels();
    if (section === 'cost' && costs.length === 0) loadCosts();
    if (section === 'flags' && flags.length === 0) loadFlags();
  }, [section]);

  const loadModels = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/gateway/models', { credentials: 'include' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setModels(data.models ?? []);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const loadCosts = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/gateway/cost-summary?days=30', { credentials: 'include' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setCosts(data.summary ?? []);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const loadFlags = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/admin/flags', { credentials: 'include' });
      if (res.status === 403) { setError('需要管理员权限'); setLoading(false); return; }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const flagList: FeatureFlag[] = Object.entries(data.flags ?? {}).map(
        ([name, enabled]) => ({ name, enabled: Boolean(enabled) })
      );
      setFlags(flagList);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const handleToggleFlag = useCallback(async (name: string, enabled: boolean) => {
    try {
      const res = await fetch('/api/admin/flags', {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, enabled }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setFlags(prev => prev.map(f => f.name === name ? { ...f, enabled } : f));
    } catch (e: any) { setError(e.message); }
  }, []);

  const handleDeleteFlag = useCallback(async (name: string) => {
    try {
      const res = await fetch(`/api/admin/flags/${encodeURIComponent(name)}`, {
        method: 'DELETE', credentials: 'include',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setFlags(prev => prev.filter(f => f.name !== name));
    } catch (e: any) { setError(e.message); }
  }, []);

  const handleAddFlag = useCallback(async () => {
    if (!newFlagName.trim()) return;
    try {
      const res = await fetch('/api/admin/flags', {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newFlagName.trim(), enabled: false }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setFlags(prev => [...prev, { name: newFlagName.trim(), enabled: false }]);
      setNewFlagName('');
    } catch (e: any) { setError(e.message); }
  }, [newFlagName]);

  const sections: { key: Section; label: string; icon: any }[] = [
    { key: 'models', label: '模型配置', icon: <Cpu size={14} /> },
    { key: 'cost', label: '成本统计', icon: <DollarSign size={14} /> },
    { key: 'flags', label: '功能开关', icon: <ToggleLeft size={14} /> },
  ];

  return (
    <div className="sys-config-tab">
      <div className="km-tab__nav">
        {sections.map(s => (
          <button key={s.key} className={`km-nav-btn ${section === s.key ? 'active' : ''}`}
            onClick={() => setSection(s.key)}>
            {s.icon} {s.label}
          </button>
        ))}
      </div>

      {error && <div className="tab-error"><AlertCircle size={14} /> {error}</div>}

      <div className="sys-config-tab__content">
        {loading && <div className="tab-loading"><Loader2 size={20} className="spin" /> 加载中...</div>}

        {/* Models */}
        {!loading && section === 'models' && (
          <div className="model-list">
            {models.length === 0 ? (
              <div className="tab-empty">暂无已配置模型</div>
            ) : models.map((m, i) => (
              <div key={i} className="model-card">
                <div className="model-card__header">
                  <Cpu size={14} />
                  <span className="model-card__name">{m.name ?? m.model_id ?? `Model ${i}`}</span>
                  <span className={`model-card__status ${m.online ? 'online' : 'offline'}`}>
                    {m.online ? '在线' : '离线'}
                  </span>
                </div>
                <div className="model-card__meta">
                  {m.provider && <span>提供商: {m.provider}</span>}
                  {m.type && <span>类型: {m.type}</span>}
                </div>
                {m.capabilities && m.capabilities.length > 0 && (
                  <div className="model-card__caps">
                    {m.capabilities.map(c => <span key={c} className="field-tag">{c}</span>)}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Cost */}
        {!loading && section === 'cost' && (
          <div className="cost-section">
            {costs.length === 0 ? (
              <div className="tab-empty">暂无成本数据</div>
            ) : (
              <>
                <div className="cost-total">
                  <DollarSign size={16} />
                  总计: ${costs.reduce((a, c) => a + c.total_cost, 0).toFixed(4)}
                  <span className="cost-total__calls">
                    ({costs.reduce((a, c) => a + c.call_count, 0)} 次调用)
                  </span>
                </div>
                <div className="cost-table">
                  <div className="cost-table__header">
                    <span>场景</span>
                    <span>项目</span>
                    <span>费用 (USD)</span>
                    <span>调用次数</span>
                  </div>
                  {costs.map((c, i) => (
                    <div key={i} className="cost-table__row">
                      <span>{c.scenario || '-'}</span>
                      <span>{c.project_id || '-'}</span>
                      <span>${c.total_cost.toFixed(4)}</span>
                      <span>{c.call_count}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {/* Feature Flags */}
        {!loading && section === 'flags' && (
          <div className="flags-section">
            <div className="flags-create">
              <input placeholder="新功能开关名称" value={newFlagName}
                onChange={e => setNewFlagName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleAddFlag()} />
              <button onClick={handleAddFlag} disabled={!newFlagName.trim()}>
                <Plus size={14} /> 添加
              </button>
            </div>
            {flags.length === 0 ? (
              <div className="tab-empty">暂无功能开关</div>
            ) : (
              <div className="flags-list">
                {flags.map(f => (
                  <div key={f.name} className="flag-row">
                    <button className="flag-toggle" onClick={() => handleToggleFlag(f.name, !f.enabled)}>
                      {f.enabled
                        ? <ToggleRight size={18} className="flag-on" />
                        : <ToggleLeft size={18} className="flag-off" />}
                    </button>
                    <span className="flag-name">{f.name}</span>
                    <span className={`flag-status ${f.enabled ? 'on' : 'off'}`}>
                      {f.enabled ? '启用' : '禁用'}
                    </span>
                    <button className="btn-icon danger" onClick={() => handleDeleteFlag(f.name)}>
                      <Trash2 size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
