import { useState, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, Pin, EyeOff, Eye, Plus, RefreshCw, Save, Send, CircleCheck, Ban, Archive, RotateCcw, FlaskConical, X } from 'lucide-react';
import { formatNumber, getLocaleHeaders } from '../../i18n';
import './AgentsTab.css';

interface MentionTarget {
  handle: string;
  label: string;
  display_name: string;
  aliases: string[];
  pinned: boolean;
  hidden: boolean;
  type: 'pipeline' | 'sub_agent' | 'adk_skill' | 'custom_skill';
  description: string;
  allowed: boolean;
  pipeline?: string;
}

type FilterKey = 'all' | 'pipeline' | 'sub_agent' | 'adk_skill' | 'custom_skill';

const TYPE_LABEL_KEYS: Record<MentionTarget['type'], string> = {
  pipeline: 'pipeline',
  sub_agent: 'subAgent',
  adk_skill: 'builtInSkill',
  custom_skill: 'customSkill',
};

const TYPE_COLORS: Record<string, string> = {
  pipeline: '#3b82f6',
  sub_agent: '#10b981',
  adk_skill: '#f59e0b',
  custom_skill: '#a855f7',
};

export default function AgentsTab() {
  const { t, i18n } = useTranslation();
  const [view, setView] = useState<'managed' | 'registry'>('managed');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: 12 }}>
      <div className="agent-management-tabs" role="tablist" aria-label={t('agentsTab.lifecycle.title')}>
        <button type="button" role="tab" aria-selected={view === 'managed'} className={view === 'managed' ? 'active' : ''}
          onClick={() => setView('managed')}>{t('agentsTab.lifecycle.title')}</button>
        <button type="button" role="tab" aria-selected={view === 'registry'} className={view === 'registry' ? 'active' : ''}
          onClick={() => setView('registry')}>{t('agentsTab.registry')}</button>
      </div>
      {view === 'managed' ? <ManagedAgentManager /> : <MentionRegistry />}
    </div>
  );
}

function MentionRegistry() {
  const { t, i18n } = useTranslation();
  const [targets, setTargets] = useState<MentionTarget[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterKey>('all');
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const fetchTargets = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetch('/api/agents/mention-targets?include_hidden=1', {
        credentials: 'include', headers: getLocaleHeaders(),
      });
      if (resp.ok) { const data = await resp.json(); setTargets(data.targets || []); }
    } finally { setLoading(false); }
  }, [i18n.resolvedLanguage]);
  useEffect(() => { fetchTargets(); }, [fetchTargets]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const typeOrder: Record<FilterKey, number> = { all: 99, pipeline: 0, sub_agent: 1, adk_skill: 2, custom_skill: 3 };
    return targets.filter(target => {
      if (filter !== 'all' && target.type !== filter) return false;
      if (!q) return true;
      return target.handle.toLowerCase().includes(q) || target.display_name.toLowerCase().includes(q) || target.aliases.some(a => a.toLowerCase().includes(q));
    }).sort((a, b) => {
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
      const at = typeOrder[a.type] ?? 99, bt = typeOrder[b.type] ?? 99;
      if (at !== bt) return at - bt;
      return (a.display_name || a.handle).localeCompare(b.display_name || b.handle, i18n.resolvedLanguage || i18n.language);
    });
  }, [targets, filter, search, i18n.resolvedLanguage, i18n.language]);

  if (loading) return <div className="empty-state">{t('agentsTab.common.loading')}</div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, flex: 1 }}>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
        <div style={{ position: 'relative', flex: 1 }}>
          <Search size={14} style={{ position: 'absolute', insetInlineStart: 8, top: 8, color: '#9ca3af' }} />
          <input
            type="text" placeholder={t('agentsTab.search.placeholder')}
            value={search} onChange={e => setSearch(e.target.value)}
            style={{
              width: '100%', paddingBlock: 6, paddingInlineEnd: 8, paddingInlineStart: 28, fontSize: 12,
              border: '1px solid #e5e7eb', borderRadius: 4,
            }}
          />
        </div>
        <span style={{ fontSize: 11, color: '#9ca3af' }}>
          {t('agentsTab.search.resultCount', {
            filtered: formatNumber(filtered.length),
            total: formatNumber(targets.length),
          })}
        </span>
      </div>

      <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
        {(['all', 'pipeline', 'sub_agent', 'adk_skill', 'custom_skill'] as FilterKey[]).map(k => (
          <button key={k} onClick={() => setFilter(k)}
            style={{
              padding: '3px 10px', fontSize: 11, border: '1px solid #e5e7eb',
              borderRadius: 12, cursor: 'pointer',
              background: filter === k ? '#3b82f6' : '#fff',
              color: filter === k ? '#fff' : '#374151',
            }}>
            {k === 'all' ? t('agentsTab.filters.all') : t(`agentsTab.types.${TYPE_LABEL_KEYS[k]}`)}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: 'auto' }}>
        {filtered.map(t => (
          <AgentCard
            key={t.handle} target={t}
            expanded={expanded === t.handle}
            onToggle={() => setExpanded(expanded === t.handle ? null : t.handle)}
            onChanged={fetchTargets}
          />
        ))}
        {filtered.length === 0 && (
          <div className="empty-state" style={{ padding: 24 }}>{t('agentsTab.empty.noMatches')}</div>
        )}
      </div>
    </div>
  );
}

type AgentState = 'draft' | 'testing' | 'pending_approval' | 'approved' | 'published' | 'disabled' | 'archived';
interface ManagedAgent {
  id: number | string;
  name: string;
  status: AgentState;
  current_version?: number | string | null;
  version_number?: number | string | null;
  spec?: AgentConfig;
  test_status?: string;
  updated_at?: string;
}
interface AgentConfig {
  description?: string;
  instruction?: string;
  model_tier?: string;
  skill_refs?: Array<{ skill_id: number | string; version?: number | string }>;
  allowed_toolsets?: string[];
  data_policy?: {
    mode?: string;
    allowed_resources?: string[];
    allow_mutations?: boolean;
    allow_discovery?: boolean;
  };
  budget_policy?: { max?: number | string; [key: string]: unknown };
}
interface SkillOption { id: number | string; skill_name: string; version?: number | string }
interface AgentForm {
  name: string; description: string; instruction: string; model_tier: string;
  skill_ids: string[]; allowed_toolsets: string[]; data_access_policy: string;
  allowed_resources: string; allow_mutations: boolean; allow_discovery: boolean; budget: string;
}
const EMPTY_AGENT_FORM: AgentForm = {
  name: '', description: '', instruction: '', model_tier: 'standard', skill_ids: [],
  allowed_toolsets: [], data_access_policy: 'inherit', allowed_resources: '',
  allow_mutations: false, allow_discovery: false, budget: '',
};

function parseAllowedResources(value: string): string[] {
  return [...new Set(value.split(/[\n,]/).map(item => item.trim()).filter(Boolean))];
}

function ManagedAgentManager() {
  const { t, i18n } = useTranslation();
  const [agents, setAgents] = useState<ManagedAgent[]>([]);
  const [skills, setSkills] = useState<SkillOption[]>([]);
  const [toolsets, setToolsets] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [editing, setEditing] = useState<ManagedAgent | null>(null);
  const [form, setForm] = useState<AgentForm>({ ...EMPTY_AGENT_FORM });

  const request = useCallback(async (url: string, init?: RequestInit) => {
    const response = await fetch(url, {
      ...init, credentials: 'include',
      headers: { ...getLocaleHeaders(), ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || data.message || `${response.status}`);
    return data;
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [agentData, skillData] = await Promise.all([
        request('/api/managed-agents'), request('/api/skills'),
      ]);
      setAgents(Array.isArray(agentData.agents) ? agentData.agents : []);
      setSkills(Array.isArray(skillData.skills) ? skillData.skills : []);
      try {
        const toolData = await request('/api/bundles/available-tools');
        const availableToolsets = toolData.toolsets || toolData.toolset_names;
        setToolsets(Array.isArray(availableToolsets) ? availableToolsets : []);
      } catch { setToolsets([]); }
    } catch (e) { setError(e instanceof Error ? e.message : t('agentsTab.lifecycle.errors.load')); }
    finally { setLoading(false); }
  }, [request, t, i18n.resolvedLanguage]);

  useEffect(() => { void refresh(); }, [refresh]);

  const startNew = () => { setEditing(null); setForm({ ...EMPTY_AGENT_FORM }); setError(''); setNotice(''); };
  const startEdit = (agent: ManagedAgent) => {
    const config = agent.spec || {};
    const policy = config.data_policy || {};
    setEditing(agent); setError(''); setNotice('');
    setForm({
      name: agent.name || '', description: config.description || '', instruction: config.instruction || '',
      model_tier: config.model_tier || 'standard',
      skill_ids: (config.skill_refs || []).map(reference => String(reference.skill_id)),
      allowed_toolsets: config.allowed_toolsets || [],
      data_access_policy: policy.mode || 'inherit',
      allowed_resources: (policy.allowed_resources || []).join('\n'),
      allow_mutations: policy.allow_mutations === true,
      allow_discovery: policy.allow_discovery === true,
      budget: config.budget_policy?.max == null ? '' : String(config.budget_policy.max),
    });
  };
  const save = async () => {
    setError(''); setNotice('');
    if (!form.name.trim() || !form.instruction.trim()) { setError(t('agentsTab.lifecycle.errors.required')); return; }
    if (form.budget.trim() && (!Number.isFinite(Number(form.budget)) || Number(form.budget) < 0)) {
      setError(t('agentsTab.lifecycle.errors.budget')); return;
    }
    const allowedResources = parseAllowedResources(form.allowed_resources);
    if (form.data_access_policy === 'restricted' && allowedResources.length === 0) {
      setError(t('agentsTab.lifecycle.errors.resources')); return;
    }
    setBusy(true);
    try {
      const config: AgentConfig = {
        description: form.description.trim(), instruction: form.instruction.trim(), model_tier: form.model_tier,
        skill_refs: skills.filter(skill => form.skill_ids.includes(String(skill.id))).map(skill => ({
          skill_id: Number(skill.id), version: Number(skill.version || 1),
        })),
        allowed_toolsets: form.allowed_toolsets,
        data_policy: {
          mode: form.data_access_policy,
          allowed_resources: allowedResources,
          allow_mutations: form.allow_mutations,
          allow_discovery: form.allow_discovery,
        },
        budget_policy: form.budget.trim() ? { max: Number(form.budget) } : {},
      };
      const url = editing ? `/api/managed-agents/${encodeURIComponent(String(editing.id))}` : '/api/managed-agents';
      const result = await request(url, { method: editing ? 'PUT' : 'POST', body: JSON.stringify({ name: form.name.trim(), ...config }) });
      setNotice(t('agentsTab.lifecycle.notices.saved'));
      if (result.agent) setAgents(current => [result.agent, ...current.filter(a => a.id !== result.agent.id)]);
      await refresh();
      if (!editing && result.agent) startEdit(result.agent);
    } catch (e) { setError(e instanceof Error ? e.message : t('agentsTab.lifecycle.errors.save')); }
    finally { setBusy(false); }
  };
  const transition = async (
    agent: ManagedAgent,
    action: 'test' | 'submit' | 'approve' | 'publish' | 'disable' | 'archive' | 'rollback',
    approve?: boolean,
  ) => {
    setBusy(true); setError(''); setNotice('');
    try {
      const body = action === 'approve' && approve === false ? { approve: false } : {};
      const result = await request(`/api/managed-agents/${encodeURIComponent(String(agent.id))}/${action}`, { method: 'POST', body: JSON.stringify(body) });
      setNotice(result.message || t(`agentsTab.lifecycle.notices.${approve === false ? 'reject' : action}`));
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : t('agentsTab.lifecycle.errors.transition')); }
    finally { setBusy(false); }
  };

  return (
    <div className="agent-lifecycle">
      <div className="agent-lifecycle-toolbar">
        <div><h3>{t('agentsTab.lifecycle.heading')}</h3><p>{t('agentsTab.lifecycle.relationship')}</p></div>
        <button type="button" className="agent-icon-button" title={t('agentsTab.lifecycle.refresh')} onClick={() => void refresh()} disabled={loading}>
          <RefreshCw size={15} />
        </button>
        <button type="button" className="agent-primary-button" onClick={startNew}><Plus size={15} />{t('agentsTab.lifecycle.create')}</button>
      </div>
      {error && <div className="agent-form-error" role="alert">{error}</div>}
      {notice && <div className="agent-form-notice" role="status">{notice}</div>}
      {loading ? <div className="empty-state">{t('agentsTab.common.loading')}</div> : (
        <div className="agent-lifecycle-grid">
          <section className="agent-lifecycle-list" aria-label={t('agentsTab.lifecycle.heading')}>
            {agents.map(agent => {
              const cfg = agent.spec || {};
              return <article key={agent.id} className={`agent-lifecycle-item ${editing?.id === agent.id ? 'selected' : ''}`}>
                <button type="button" className="agent-lifecycle-item-main" onClick={() => startEdit(agent)}>
                  <span className={`agent-state state-${agent.status}`}>{t(`agentsTab.lifecycle.states.${agent.status}`, { defaultValue: agent.status })}</span>
                  <strong>{agent.name}</strong>
                  <small>{t('agentsTab.lifecycle.version', { version: agent.current_version || agent.version_number || '-' })}</small>
                  <span className="agent-lifecycle-description">{cfg.description || t('agentsTab.empty.noDescription')}</span>
                </button>
                <div className="agent-lifecycle-actions">
                  {agent.status === 'draft' && <button type="button" title={t('agentsTab.lifecycle.test')} onClick={() => void transition(agent, 'test')} disabled={busy}><FlaskConical size={14} /></button>}
                  {agent.status === 'testing' && <button type="button" title={t('agentsTab.lifecycle.submit')} onClick={() => void transition(agent, 'submit')} disabled={busy}><Send size={14} /></button>}
                  {agent.status === 'pending_approval' && <button type="button" title={t('agentsTab.lifecycle.approve')} onClick={() => void transition(agent, 'approve', true)} disabled={busy}><CircleCheck size={14} /></button>}
                  {agent.status === 'pending_approval' && <button type="button" title={t('agentsTab.lifecycle.reject')} onClick={() => void transition(agent, 'approve', false)} disabled={busy}><Ban size={14} /></button>}
                  {agent.status === 'approved' && <button type="button" title={t('agentsTab.lifecycle.publish')} onClick={() => void transition(agent, 'publish')} disabled={busy}><CircleCheck size={14} /></button>}
                  {agent.status === 'published' && <button type="button" title={t('agentsTab.lifecycle.disable')} onClick={() => void transition(agent, 'disable')} disabled={busy}><Ban size={14} /></button>}
                  {agent.status === 'disabled' && <button type="button" title={t('agentsTab.lifecycle.rollback')} onClick={() => void transition(agent, 'rollback')} disabled={busy}><RotateCcw size={14} /></button>}
                  {agent.status !== 'archived' && <button type="button" title={t('agentsTab.lifecycle.archive')} onClick={() => void transition(agent, 'archive')} disabled={busy}><Archive size={14} /></button>}
                </div>
              </article>;
            })}
            {agents.length === 0 && <div className="empty-state agent-lifecycle-empty">{t('agentsTab.lifecycle.empty')}</div>}
          </section>
          <section className="agent-lifecycle-editor">
            <div className="agent-editor-heading">
              <strong>{editing ? t('agentsTab.lifecycle.edit') : t('agentsTab.lifecycle.new')}</strong>
              {editing && <button type="button" className="agent-icon-button" title={t('agentsTab.lifecycle.close')} onClick={startNew}><X size={15} /></button>}
            </div>
            <label>{t('agentsTab.lifecycle.fields.name')}<input value={form.name} maxLength={100} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
            <label>{t('agentsTab.lifecycle.fields.description')}<input value={form.description} maxLength={500} onChange={e => setForm({ ...form, description: e.target.value })} /></label>
            <label>{t('agentsTab.lifecycle.fields.instruction')}<textarea rows={5} value={form.instruction} onChange={e => setForm({ ...form, instruction: e.target.value })} /></label>
            <div className="agent-editor-row">
              <label>{t('agentsTab.lifecycle.fields.model')}<select value={form.model_tier} onChange={e => setForm({ ...form, model_tier: e.target.value })}><option value="fast">fast</option><option value="standard">standard</option><option value="premium">premium</option></select></label>
            </div>
            <fieldset className="agent-toolset-picker">
              <legend>{t('agentsTab.lifecycle.fields.skills')}</legend>
              {skills.length === 0 ? <span>{t('agentsTab.lifecycle.noSkill')}</span> : skills.map(skill => (
                <label key={skill.id}>
                  <input type="checkbox" checked={form.skill_ids.includes(String(skill.id))}
                    onChange={e => setForm({ ...form, skill_ids: e.target.checked
                      ? [...form.skill_ids, String(skill.id)]
                      : form.skill_ids.filter(value => value !== String(skill.id)) })} />
                  {skill.skill_name}{skill.version ? ` · v${skill.version}` : ''}
                </label>
              ))}
            </fieldset>
            <fieldset className="agent-toolset-picker">
              <legend>{t('agentsTab.lifecycle.fields.tools')}</legend>
              {toolsets.length === 0 ? <span>{t('agentsTab.lifecycle.noTools')}</span> : toolsets.map(toolset => (
                <label key={toolset}>
                  <input type="checkbox" checked={form.allowed_toolsets.includes(toolset)}
                    onChange={e => setForm({ ...form, allowed_toolsets: e.target.checked
                      ? [...form.allowed_toolsets, toolset]
                      : form.allowed_toolsets.filter(value => value !== toolset) })} />
                  {toolset}
                </label>
              ))}
            </fieldset>
            <div className="agent-editor-row">
              <label>{t('agentsTab.lifecycle.fields.dataPolicy')}<select value={form.data_access_policy} onChange={e => setForm({ ...form, data_access_policy: e.target.value })}><option value="inherit">{t('agentsTab.lifecycle.policies.inherit')}</option><option value="read_only">{t('agentsTab.lifecycle.policies.readOnly')}</option><option value="restricted">{t('agentsTab.lifecycle.policies.restricted')}</option></select></label>
              <label>{t('agentsTab.lifecycle.fields.budget')}<input type="number" min="0" value={form.budget} onChange={e => setForm({ ...form, budget: e.target.value })} /></label>
            </div>
            <label>{t('agentsTab.lifecycle.fields.allowedResources')}<textarea rows={3} value={form.allowed_resources} placeholder={t('agentsTab.lifecycle.resourcesPlaceholder')} onChange={e => setForm({ ...form, allowed_resources: e.target.value })} /></label>
            <div className="agent-editor-row agent-policy-flags">
              <label><input type="checkbox" checked={form.allow_mutations} disabled={form.data_access_policy !== 'restricted'} onChange={e => setForm({ ...form, allow_mutations: e.target.checked })} />{t('agentsTab.lifecycle.fields.allowMutations')}</label>
              <label><input type="checkbox" checked={form.allow_discovery} disabled={form.data_access_policy !== 'restricted'} onChange={e => setForm({ ...form, allow_discovery: e.target.checked })} />{t('agentsTab.lifecycle.fields.allowDiscovery')}</label>
            </div>
            <div className="agent-form-hint">{t('agentsTab.lifecycle.relationHint')}</div>
            <button type="button" className="agent-primary-button" onClick={() => void save()} disabled={busy}><Save size={14} />{busy ? t('agentsTab.actions.saving') : t('agentsTab.lifecycle.saveDraft')}</button>
          </section>
        </div>
      )}
    </div>
  );
}

interface AgentCardProps {
  target: MentionTarget;
  expanded: boolean;
  onToggle: () => void;
  onChanged: () => void;
}

function AgentCard({ target, expanded, onToggle, onChanged }: AgentCardProps) {
  const { t } = useTranslation();
  const [aliasInput, setAliasInput] = useState(target.aliases.join(', '));
  const [displayName, setDisplayName] = useState(target.display_name);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      const aliases = aliasInput.split(',').map(a => a.trim()).filter(Boolean);
      await fetch(`/api/agents/${encodeURIComponent(target.handle)}/alias`, {
        method: 'PUT', credentials: 'include',
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ aliases, display_name: displayName }),
      });
      onChanged();
    } finally { setSaving(false); }
  };

  const togglePin = async () => {
    await fetch(`/api/agents/${encodeURIComponent(target.handle)}/pin`, {
      method: 'PUT', credentials: 'include',
      headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ pinned: !target.pinned }),
    });
    onChanged();
  };

  const toggleHide = async () => {
    await fetch(`/api/agents/${encodeURIComponent(target.handle)}/hide`, {
      method: 'PUT', credentials: 'include',
      headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ hidden: !target.hidden }),
    });
    onChanged();
  };

  const color = TYPE_COLORS[target.type] || '#6b7280';

  return (
    <div style={{
      border: '1px solid #e5e7eb', borderRadius: 6, marginBottom: 8,
      background: target.hidden ? '#f9fafb' : '#fff',
      opacity: target.hidden ? 0.6 : 1,
    }}>
      <div onClick={onToggle} style={{
        padding: '8px 12px', cursor: 'pointer',
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        {target.pinned && <Pin size={12} color="#f59e0b" />}
        <span style={{
          background: color, color: '#fff', fontSize: 9, fontWeight: 600,
          padding: '1px 6px', borderRadius: 3,
        }}>{t(`agentsTab.types.${TYPE_LABEL_KEYS[target.type]}`)}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, fontWeight: 600 }}>
            {target.display_name || target.handle}
          </div>
          <div style={{ fontSize: 10, color: '#9ca3af' }}>
            @{target.handle}
            {target.aliases.length > 0 && ` · ${t('agentsTab.card.aliases', { aliases: target.aliases.join(', ') })}`}
          </div>
        </div>
        <button onClick={e => { e.stopPropagation(); togglePin(); }}
          title={target.pinned ? t('agentsTab.actions.unpin') : t('agentsTab.actions.pin')}
          aria-label={target.pinned ? t('agentsTab.actions.unpin') : t('agentsTab.actions.pin')}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>
          <Pin size={14} color={target.pinned ? '#f59e0b' : '#9ca3af'} />
        </button>
        <button onClick={e => { e.stopPropagation(); toggleHide(); }}
          title={target.hidden ? t('agentsTab.actions.show') : t('agentsTab.actions.hide')}
          aria-label={target.hidden ? t('agentsTab.actions.show') : t('agentsTab.actions.hide')}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>
          {target.hidden ? <EyeOff size={14} color="#9ca3af" /> : <Eye size={14} color="#9ca3af" />}
        </button>
      </div>

      {expanded && (
        <div style={{ borderTop: '1px solid #f3f4f6', padding: '8px 12px', background: '#fafafa' }}>
          <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 6 }}>
            {target.description || t('agentsTab.empty.noDescription')}
          </div>
          <label style={{ fontSize: 10, color: '#374151', display: 'block', marginTop: 6 }}>
            {t('agentsTab.form.displayName')}
          </label>
          <input value={displayName} onChange={e => setDisplayName(e.target.value)}
            placeholder={t('agentsTab.form.displayNamePlaceholder')}
            style={{ width: '100%', padding: '4px 6px', fontSize: 11,
                     border: '1px solid #e5e7eb', borderRadius: 3 }} />
          <label style={{ fontSize: 10, color: '#374151', display: 'block', marginTop: 6 }}>
            {t('agentsTab.form.aliases')}
          </label>
          <input value={aliasInput} onChange={e => setAliasInput(e.target.value)}
            placeholder={t('agentsTab.form.aliasesPlaceholder')}
            style={{ width: '100%', padding: '4px 6px', fontSize: 11,
                     border: '1px solid #e5e7eb', borderRadius: 3 }} />
          <button onClick={handleSave} disabled={saving}
            style={{ marginTop: 8, padding: '4px 12px', fontSize: 11,
                     background: '#3b82f6', color: '#fff', border: 'none',
                     borderRadius: 3, cursor: 'pointer' }}>
            {saving ? t('agentsTab.actions.saving') : t('agentsTab.actions.save')}
          </button>
        </div>
      )}
    </div>
  );
}
