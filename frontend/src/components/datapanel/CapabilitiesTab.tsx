import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { getLocaleHeaders, formatNumber } from '../../i18n';
import PlatformCapabilitiesPanel from './PlatformCapabilitiesPanel';

interface CapabilityItem {
  name: string;
  description: string;
  domain?: string;
  version?: string;
  intent_triggers?: string;
  type: string;
  id?: number;
  owner_username?: string;
  skill_name?: string;
  toolset_names?: string[];
  trigger_keywords?: string[];
  model_tier?: string;
  is_shared?: boolean;
  depends_on?: number[];
  author_username?: string;
  tags?: string[];
}

type CapFilter = 'all' | 'builtin_skill' | 'custom_skill' | 'toolset' | 'user_tool' | 'bundle' | 'template';

const TOOLSETS = [
  'ExplorationToolset', 'GeoProcessingToolset', 'LocationToolset', 'AnalysisToolset',
  'VisualizationToolset', 'DatabaseToolset', 'FileToolset', 'MemoryToolset',
  'AdminToolset', 'RemoteSensingToolset', 'SpatialStatisticsToolset',
  'SemanticLayerToolset', 'StreamingToolset', 'TeamToolset', 'DataLakeToolset',
  'McpHubToolset', 'FusionToolset', 'KnowledgeGraphToolset', 'KnowledgeBaseToolset',
  'AdvancedAnalysisToolset', 'SpatialAnalysisTier2Toolset', 'WatershedToolset',
  'UserToolset',
] as const;

const BUILTIN_TEMPLATE_KEYS: Array<{ key: string; tag: string }> = [
  { key: 'dataQualityAudit', tag: 'topology' },
  { key: 'landUsePlan', tag: 'fragmentation' },
  { key: 'landUseAnalysis', tag: 'land-use' },
  { key: 'spatialStatistics', tag: 'Moran' },
  { key: 'dataFusion', tag: 'fusion' },
  { key: 'changeDetection', tag: 'temporal' },
  { key: 'urbanHeatIsland', tag: 'heat-island' },
  { key: 'vegetationChange', tag: 'vegetation' },
];

const EMPTY_SKILL_FORM = {
  skill_name: '', instruction: '', description: '',
  toolset_names: [] as string[], trigger_keywords: '',
  model_tier: 'standard', is_shared: false,
};

export default function CapabilitiesTab({ userRole }: { userRole?: string }) {
  const { t, i18n } = useTranslation('common');
  const [capabilityView, setCapabilityView] = useState<'platform' | 'skills'>('platform');
  const [items, setItems] = useState<CapabilityItem[]>([]);
  const [filter, setFilter] = useState<CapFilter>('all');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [counts, setCounts] = useState({ builtin: 0, custom: 0, toolset: 0 });

  // Skill form state
  const [showSkillForm, setShowSkillForm] = useState(false);
  const [editingSkill, setEditingSkill] = useState<CapabilityItem | null>(null);
  const [skillForm, setSkillForm] = useState({ ...EMPTY_SKILL_FORM });
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);

  // User tool form state
  const [showToolForm, setShowToolForm] = useState(false);
  const [editingTool, setEditingTool] = useState<any>(null);
  const [toolForm, setToolForm] = useState({
    tool_name: '', description: '', template_type: 'http_call',
    template_config: '{}', parameters: [] as {name: string; type: string; description: string; required: boolean; default?: string}[],
    is_shared: false,
  });
  const [toolError, setToolError] = useState('');
  const [savingTool, setSavingTool] = useState(false);

  // AI Skill Generator state (v23.0)
  const [showAiGen, setShowAiGen] = useState(false);
  const [aiDesc, setAiDesc] = useState('');
  const [aiGenerating, setAiGenerating] = useState(false);
  const [aiPreview, setAiPreview] = useState<any>(null);
  const [aiError, setAiError] = useState('');
  const [aiSaving, setAiSaving] = useState(false);

  // Bundle state
  const [bundles, setBundles] = useState<any[]>([]);
  const [showBundleForm, setShowBundleForm] = useState(false);
  const [editingBundle, setEditingBundle] = useState<any>(null);
  const [bundleForm, setBundleForm] = useState({ bundle_name: '', description: '', toolset_names: [] as string[], skill_names: [] as string[], intent_triggers: '', is_shared: false });
  const [bundleError, setBundleError] = useState('');
  const [savingBundle, setSavingBundle] = useState(false);
  const [availableTools, setAvailableTools] = useState<{ toolsets: string[]; skills: string[] }>({ toolsets: [], skills: [] });
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);

  const fetchCapabilities = async () => {
    setLoading(true);
    try {
      const localeHeaders = getLocaleHeaders();
      const [capResp, utResp, bundleResp, availResp, tmplResp] = await Promise.all([
        fetch('/api/capabilities', { credentials: 'include', headers: localeHeaders }),
        fetch('/api/user-tools', { credentials: 'include', headers: localeHeaders }),
        fetch('/api/bundles', { credentials: 'include', headers: localeHeaders }),
        fetch('/api/bundles/available-tools', { credentials: 'include', headers: localeHeaders }),
        fetch('/api/templates', { credentials: 'include', headers: localeHeaders }),
      ]);
      let builtin: CapabilityItem[] = [], custom: CapabilityItem[] = [], toolsets: CapabilityItem[] = [], userTools: CapabilityItem[] = [];
      if (capResp.ok) {
        const data = await capResp.json();
        builtin = data.builtin_skills || [];
        custom = (data.custom_skills || []).map((s: any) => ({
          ...s, name: s.skill_name, type: 'custom_skill',
          intent_triggers: (s.trigger_keywords || []).join(', '),
        }));
        toolsets = data.toolsets || [];
      }
      if (utResp.ok) {
        const utData = await utResp.json();
        userTools = (utData.tools || []).map((t: any) => ({
          ...t, name: t.tool_name, type: 'user_tool',
        }));
      }
      if (bundleResp.ok) {
        const bData = await bundleResp.json();
        setBundles(bData.bundles || []);
      }
      if (availResp.ok) {
        setAvailableTools(await availResp.json());
      }
      let templateItems: CapabilityItem[] = [];
      if (tmplResp.ok) {
        const tData = await tmplResp.json();
        templateItems = (tData.templates || []).map((t: any) => ({
          ...t, name: t.template_name, type: 'template' as const,
          description: t.description || '',
          domain: t.category,
        }));
      }
      setItems([...builtin, ...custom, ...toolsets, ...userTools, ...templateItems]);
      setCounts({ builtin: builtin.length, custom: custom.length, toolset: toolsets.length, userTool: userTools.length, template: templateItems.length } as any);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    if (capabilityView === 'skills') void fetchCapabilities();
  }, [capabilityView, i18n.resolvedLanguage]);

  const handleDeleteSkill = async (id: number) => {
    if (!confirm(t('capabilities.confirm.deleteSkill'))) return;
    try {
      const resp = await fetch(`/api/skills/${id}`, { method: 'DELETE', credentials: 'include', headers: getLocaleHeaders() });
      if (resp.ok) fetchCapabilities();
    } catch { /* ignore */ }
  };

  const handleEditSkill = (item: CapabilityItem) => {
    setEditingSkill(item);
    setSkillForm({
      skill_name: item.skill_name || item.name || '',
      instruction: (item as any).instruction || '',
      description: item.description || '',
      toolset_names: item.toolset_names || [],
      trigger_keywords: (item.trigger_keywords || []).join(', '),
      model_tier: item.model_tier || 'standard',
      is_shared: item.is_shared || false,
    });
    setFormError('');
    setShowSkillForm(true);
  };

  const handleNewSkill = () => {
    setEditingSkill(null);
    setSkillForm({ ...EMPTY_SKILL_FORM });
    setFormError('');
    setShowSkillForm(true);
  };

  const handleSaveSkill = async () => {
    setFormError('');
    if (!skillForm.skill_name.trim()) { setFormError(t('capabilities.errors.skillNameRequired')); return; }
    if (!skillForm.instruction.trim()) { setFormError(t('capabilities.errors.instructionRequired')); return; }
    setSaving(true);
    try {
      const body = {
        skill_name: skillForm.skill_name.trim(),
        instruction: skillForm.instruction.trim(),
        description: skillForm.description.trim(),
        toolset_names: skillForm.toolset_names,
        trigger_keywords: skillForm.trigger_keywords.split(',').map(s => s.trim()).filter(Boolean),
        model_tier: skillForm.model_tier,
        is_shared: skillForm.is_shared,
      };
      const url = editingSkill ? `/api/skills/${editingSkill.id}` : '/api/skills';
      const method = editingSkill ? 'PUT' : 'POST';
      const resp = await fetch(url, {
        method, credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (resp.ok) {
        setShowSkillForm(false);
        setEditingSkill(null);
        setSkillForm({ ...EMPTY_SKILL_FORM });
        fetchCapabilities();
      } else {
        setFormError(data.error || t('capabilities.errors.saveFailed'));
      }
    } catch { setFormError(t('capabilities.errors.network')); }
    finally { setSaving(false); }
  };

  const toggleToolset = (name: string) => {
    setSkillForm(f => ({
      ...f,
      toolset_names: f.toolset_names.includes(name)
        ? f.toolset_names.filter(n => n !== name)
        : [...f.toolset_names, name],
    }));
  };

  // --- User Tool handlers ---
  const handleNewTool = () => {
    setEditingTool(null);
    setToolForm({ tool_name: '', description: '', template_type: 'http_call', template_config: '{}', parameters: [], is_shared: false });
    setToolError(''); setTestResult(null);
    setShowToolForm(true); setShowSkillForm(false); setShowAiGen(false);
  };

  // --- AI Skill Generator handlers (v23.0) ---
  const handleOpenAiGen = () => {
    setShowAiGen(true); setShowSkillForm(false); setShowToolForm(false);
    setAiDesc(''); setAiPreview(null); setAiError(''); setAiSaving(false);
  };

  const handleAiGenerate = async () => {
    if (!aiDesc.trim()) { setAiError(t('capabilities.errors.aiDescriptionRequired')); return; }
    setAiGenerating(true); setAiError(''); setAiPreview(null);
    try {
      const resp = await fetch('/api/skills/generate', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({ description: aiDesc.trim() }),
      });
      const data = await resp.json();
      if (resp.ok && (data.config || data.skill)) {
        setAiPreview(data.config || data.skill);
      } else {
        setAiError(data.error || t('capabilities.errors.aiGenerateFailed'));
      }
    } catch { setAiError(t('capabilities.errors.network')); }
    finally { setAiGenerating(false); }
  };

  const handleAiSave = async () => {
    if (!aiPreview) return;
    setAiSaving(true); setAiError('');
    try {
      const resp = await fetch('/api/skills', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify(aiPreview),
      });
      const data = await resp.json();
      if (resp.ok) {
        setShowAiGen(false); setAiPreview(null); setAiDesc('');
        fetchCapabilities();
      } else {
        setAiError(data.error || t('capabilities.errors.saveFailed'));
      }
    } catch { setAiError(t('capabilities.errors.network')); }
    finally { setAiSaving(false); }
  };

  const handleAiEdit = () => {
    if (!aiPreview) return;
    // Transfer AI preview to manual skill form for fine-tuning
    setSkillForm({
      skill_name: aiPreview.skill_name || '',
      instruction: aiPreview.instruction || '',
      description: aiPreview.description || '',
      toolset_names: aiPreview.toolset_names || [],
      trigger_keywords: (aiPreview.trigger_keywords || []).join(', '),
      model_tier: aiPreview.model_tier || 'standard',
      is_shared: false,
    });
    setShowAiGen(false); setAiPreview(null);
    setEditingSkill(null); setShowSkillForm(true);
  };

  const handleEditTool = (item: any) => {
    setEditingTool(item);
    setToolForm({
      tool_name: item.tool_name || item.name || '',
      description: item.description || '',
      template_type: item.template_type || 'http_call',
      template_config: JSON.stringify(item.template_config || {}, null, 2),
      parameters: item.parameters || [],
      is_shared: item.is_shared || false,
    });
    setToolError(''); setTestResult(null);
    setShowToolForm(true); setShowSkillForm(false);
  };

  const handleDeleteTool = async (id: number) => {
    if (!confirm(t('capabilities.confirm.deleteTool'))) return;
    try {
      const resp = await fetch(`/api/user-tools/${id}`, { method: 'DELETE', credentials: 'include', headers: getLocaleHeaders() });
      if (resp.ok) fetchCapabilities();
    } catch { /* ignore */ }
  };

  const handleSaveTool = async () => {
    setToolError('');
    if (!toolForm.tool_name.trim()) { setToolError(t('capabilities.errors.toolNameRequired')); return; }
    let configObj: any;
    try { configObj = JSON.parse(toolForm.template_config); }
    catch { setToolError(t('capabilities.errors.templateJson')); return; }
    setSavingTool(true);
    try {
      const body = {
        tool_name: toolForm.tool_name.trim(),
        description: toolForm.description.trim(),
        template_type: toolForm.template_type,
        template_config: configObj,
        parameters: toolForm.parameters,
        is_shared: toolForm.is_shared,
      };
      const url = editingTool ? `/api/user-tools/${editingTool.id}` : '/api/user-tools';
      const method = editingTool ? 'PUT' : 'POST';
      const resp = await fetch(url, {
        method, credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (resp.ok) {
        setShowToolForm(false); setEditingTool(null);
        fetchCapabilities();
      } else { setToolError(data.error || t('capabilities.errors.saveFailed')); }
    } catch { setToolError(t('capabilities.errors.network')); }
    finally { setSavingTool(false); }
  };

  const handleTestTool = async () => {
    if (!editingTool?.id) return;
    setTesting(true); setTestResult(null);
    const testParams: Record<string, string> = {};
    toolForm.parameters.forEach(p => { testParams[p.name] = p.default || ''; });
    try {
      const resp = await fetch(`/api/user-tools/${editingTool.id}/test`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({ params: testParams }),
      });
      const data = await resp.json();
      setTestResult(data.result || data.message || JSON.stringify(data));
    } catch (e) { setTestResult(t('capabilities.errors.testFailed', { error: String(e) })); }
    finally { setTesting(false); }
  };

  const addParam = () => {
    setToolForm(f => ({
      ...f, parameters: [...f.parameters, { name: '', type: 'string', description: '', required: true }],
    }));
  };

  const updateParam = (idx: number, field: string, value: any) => {
    setToolForm(f => {
      const params = [...f.parameters];
      (params[idx] as any)[field] = value;
      return { ...f, parameters: params };
    });
  };

  const removeParam = (idx: number) => {
    setToolForm(f => ({ ...f, parameters: f.parameters.filter((_, i) => i !== idx) }));
  };

  const TEMPLATE_TYPES = ['http_call', 'sql_query', 'file_transform', 'chain', 'python_sandbox'] as const;

  const TEMPLATE_HINTS: Record<string, string> = {
    http_call: '{"method":"GET","url":"https://api.example.com/data","headers":{},"extract_path":"data.result"}',
    sql_query: '{"query":"SELECT * FROM parcels WHERE area > :min_area","readonly":true}',
    file_transform: '{"operations":[{"op":"filter","column":"area","condition":">","value":100}],"output_format":"geojson"}',
    chain: '{"steps":[{"tool_name":"my_query","param_map":{"x":"$input.x"}}]}',
    python_sandbox: '{"python_code":"def tool_function(params):\\n    # Add processing logic here\\n    return {\\\"result\\\": params.get(\\\"input\\\", \\\"hello\\\")}","timeout":30}',
  };

  const filtered = items.filter(item => {
    if (filter !== 'all' && item.type !== filter) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return (item.name || '').toLowerCase().includes(q)
      || (item.description || '').toLowerCase().includes(q)
      || (item.domain || '').toLowerCase().includes(q)
      || (item.intent_triggers || '').toLowerCase().includes(q);
  });

  const domainLabel = (domain: string) => t(`capabilities.domains.${domain}`, { defaultValue: domain });

  const typeLabel = (type: string) =>
    t(`capabilities.types.${type}`, { defaultValue: t('capabilities.types.toolset') });

  const typeClass = (t: string) =>
    t === 'builtin_skill' ? 'cap-type-builtin' : t === 'custom_skill' ? 'cap-type-custom' : t === 'user_tool' ? 'cap-type-usertool' : t === 'template' ? 'cap-type-template' : 'cap-type-toolset';

  const builtinTemplateKey = (item: CapabilityItem) => item.author_username === 'system'
    ? BUILTIN_TEMPLATE_KEYS.find(({ tag }) => item.tags?.includes(tag))?.key
    : undefined;

  const itemName = (item: CapabilityItem) => {
    const templateKey = builtinTemplateKey(item);
    return templateKey
      ? t(`capabilities.builtinTemplates.${templateKey}.name`, { defaultValue: item.name })
      : item.name;
  };

  const itemDescription = (item: CapabilityItem) => {
    if (item.type === 'toolset') {
      return t(`capabilities.toolsets.${item.name}.description`, { defaultValue: item.description });
    }
    if (item.type === 'builtin_skill') {
      return t(`capabilities.builtinSkills.${item.name}.description`, { defaultValue: item.description });
    }
    const templateKey = builtinTemplateKey(item);
    return templateKey
      ? t(`capabilities.builtinTemplates.${templateKey}.description`, { defaultValue: item.description })
      : item.description;
  };

  const itemDomain = (item: CapabilityItem) => {
    const templateKey = builtinTemplateKey(item);
    return templateKey
      ? t(`capabilities.builtinTemplates.${templateKey}.category`, { defaultValue: item.domain || '' })
      : domainLabel(item.domain || '');
  };

  return (
    <div className="capabilities-view">
      <div className="capability-view-switch" role="tablist" aria-label={t('capabilities.views.aria')}>
        <button
          type="button"
          role="tab"
          aria-selected={capabilityView === 'platform'}
          className={capabilityView === 'platform' ? 'active' : ''}
          onClick={() => setCapabilityView('platform')}
        >{t('capabilities.views.platform')}</button>
        <button
          type="button"
          role="tab"
          aria-selected={capabilityView === 'skills'}
          className={capabilityView === 'skills' ? 'active' : ''}
          onClick={() => setCapabilityView('skills')}
        >{t('capabilities.views.skills')}</button>
      </div>
      {capabilityView === 'platform' ? (
        <PlatformCapabilitiesPanel userRole={userRole} />
      ) : (
        <>
      <div className="capabilities-summary">
        <span>{t('capabilities.summary.builtin', { count: formatNumber((counts as any).builtin) })}</span>
        <span className="cap-sep">/</span>
        <span>{t('capabilities.summary.custom', { count: formatNumber((counts as any).custom) })}</span>
        <span className="cap-sep">/</span>
        <span>{t('capabilities.summary.toolset', { count: formatNumber((counts as any).toolset) })}</span>
        <span className="cap-sep">/</span>
        <span>{t('capabilities.summary.userTool', { count: formatNumber((counts as any).userTool || 0) })}</span>
        <button className="btn-add-server" onClick={() => showSkillForm ? setShowSkillForm(false) : handleNewSkill()} title={t('capabilities.actions.newSkillTitle')}>{t('capabilities.actions.newSkill')}</button>
        <button className="btn-add-server" onClick={handleOpenAiGen} title={t('capabilities.actions.aiGenerateTitle')} style={{ background: '#8b5cf6' }}>{t('capabilities.actions.aiGenerate')}</button>
        <button className="btn-add-server" onClick={() => showToolForm ? setShowToolForm(false) : handleNewTool()} title={t('capabilities.actions.newToolTitle')}>{t('capabilities.actions.newTool')}</button>
      </div>

      {/* AI Skill Generator Panel (v23.0) */}
      {showAiGen && (
        <div className="skill-add-form" style={{ borderColor: '#8b5cf6' }}>
          <div className="skill-add-form-title" style={{ color: '#8b5cf6' }}>{t('capabilities.ai.title')}</div>
          {!aiPreview ? (
            <>
              <textarea
                placeholder={t('capabilities.ai.placeholder')}
                rows={4} maxLength={2000}
                value={aiDesc} onChange={e => setAiDesc(e.target.value)}
                style={{ fontSize: 13, lineHeight: 1.6 }}
              />
              {aiError && <div className="skill-add-error">{aiError}</div>}
              <div className="skill-add-actions">
                <button className="btn-secondary btn-sm" onClick={() => setShowAiGen(false)}>{t('capabilities.actions.cancel')}</button>
                <button className="btn-primary btn-sm" disabled={aiGenerating || !aiDesc.trim()}
                  onClick={handleAiGenerate}
                  style={{ background: '#8b5cf6' }}>
                  {aiGenerating ? t('capabilities.actions.generating') : t('capabilities.actions.generateConfig')}
                </button>
              </div>
            </>
          ) : (
            <>
              <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>{t('capabilities.ai.generated')}</div>
              <div style={{ background: '#f8fafc', borderRadius: 6, padding: 10, fontSize: 12, lineHeight: 1.7 }}>
                <div><b>{t('capabilities.ai.fields.name')}:</b> {aiPreview.skill_name}</div>
                <div><b>{t('capabilities.ai.fields.description')}:</b> {aiPreview.description}</div>
                <div><b>{t('capabilities.ai.fields.modelTier')}:</b> {aiPreview.model_tier}</div>
                <div><b>{t('capabilities.ai.fields.toolsets')}:</b> {(aiPreview.toolset_names || []).join(', ') || t('capabilities.common.none')}</div>
                <div><b>{t('capabilities.ai.fields.triggers')}:</b> {(aiPreview.trigger_keywords || []).join(', ') || t('capabilities.common.none')}</div>
                <div style={{ marginTop: 6 }}><b>{t('capabilities.ai.fields.instruction')}:</b></div>
                <pre style={{ whiteSpace: 'pre-wrap', fontSize: 11, color: '#374151', maxHeight: 150, overflow: 'auto',
                  background: '#fff', padding: 8, borderRadius: 4, border: '1px solid #e5e7eb' }}>
                  {aiPreview.instruction}
                </pre>
              </div>
              {aiError && <div className="skill-add-error">{aiError}</div>}
              <div className="skill-add-actions">
                <button className="btn-secondary btn-sm" onClick={() => { setAiPreview(null); setAiDesc(''); }}>{t('capabilities.actions.regenerate')}</button>
                <button className="btn-secondary btn-sm" onClick={handleAiEdit}>{t('capabilities.actions.editBeforeSave')}</button>
                <button className="btn-primary btn-sm" disabled={aiSaving} onClick={handleAiSave}
                  style={{ background: '#8b5cf6' }}>
                  {aiSaving ? t('capabilities.actions.saving') : t('capabilities.actions.saveDirectly')}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {showSkillForm && (
        <div className="skill-add-form">
          <div className="skill-add-form-title">{editingSkill ? t('capabilities.skillForm.editTitle', { name: editingSkill.name }) : t('capabilities.skillForm.newTitle')}</div>
          <input placeholder={t('capabilities.skillForm.namePlaceholder')} maxLength={100}
            value={skillForm.skill_name} onChange={e => setSkillForm({ ...skillForm, skill_name: e.target.value })} />
          <textarea placeholder={t('capabilities.skillForm.instructionPlaceholder')} rows={4} maxLength={10000}
            value={skillForm.instruction} onChange={e => setSkillForm({ ...skillForm, instruction: e.target.value })} />
          <input placeholder={t('capabilities.skillForm.descriptionPlaceholder')} value={skillForm.description}
            onChange={e => setSkillForm({ ...skillForm, description: e.target.value })} />
          <div className="skill-section-label">{t('capabilities.skillForm.selectToolsets')}</div>
          <div className="skill-toolset-grid">
            {TOOLSETS.map(toolset => (
              <label key={toolset} className="skill-toolset-item">
                <input type="checkbox" checked={skillForm.toolset_names.includes(toolset)}
                  onChange={() => toggleToolset(toolset)} />
                <span>{t(`capabilities.toolsets.${toolset}.label`, { defaultValue: toolset })}</span>
              </label>
            ))}
          </div>
          <input placeholder={t('capabilities.skillForm.triggersPlaceholder')} value={skillForm.trigger_keywords}
            onChange={e => setSkillForm({ ...skillForm, trigger_keywords: e.target.value })} />
          <div className="skill-row">
            <select value={skillForm.model_tier} onChange={e => setSkillForm({ ...skillForm, model_tier: e.target.value })}>
              <option value="fast">{t('capabilities.modelTiers.fast')}</option>
              <option value="standard">{t('capabilities.modelTiers.standard')}</option>
              <option value="premium">{t('capabilities.modelTiers.premium')}</option>
            </select>
            <label className="skill-checkbox">
              <input type="checkbox" checked={skillForm.is_shared}
                onChange={e => setSkillForm({ ...skillForm, is_shared: e.target.checked })} />
              {t('capabilities.skillForm.share')}
            </label>
          </div>
          {formError && <div className="skill-add-error">{formError}</div>}
          <div className="skill-add-actions">
            <button className="btn-secondary btn-sm" onClick={() => { setShowSkillForm(false); setEditingSkill(null); }}>{t('capabilities.actions.cancel')}</button>
            <button className="btn-primary btn-sm" disabled={saving} onClick={handleSaveSkill}>
              {saving ? t('capabilities.actions.saving') : editingSkill ? t('capabilities.actions.save') : t('capabilities.actions.create')}
            </button>
          </div>
        </div>
      )}

      {showToolForm && (
        <div className="skill-add-form">
          <div className="skill-add-form-title">{editingTool ? t('capabilities.toolForm.editTitle', { name: editingTool.name }) : t('capabilities.toolForm.newTitle')}</div>
          <input placeholder={t('capabilities.toolForm.namePlaceholder')} maxLength={100}
            value={toolForm.tool_name} onChange={e => setToolForm({ ...toolForm, tool_name: e.target.value })} />
          <input placeholder={t('capabilities.toolForm.descriptionPlaceholder')} value={toolForm.description}
            onChange={e => setToolForm({ ...toolForm, description: e.target.value })} />
          <div className="skill-row">
            <select value={toolForm.template_type} onChange={e => {
              const tt = e.target.value;
              setToolForm({ ...toolForm, template_type: tt, template_config: TEMPLATE_HINTS[tt] || '{}' });
            }}>
              {TEMPLATE_TYPES.map(templateType => <option key={templateType} value={templateType}>{t(`capabilities.templateTypes.${templateType}`)}</option>)}
            </select>
            <label className="skill-checkbox">
              <input type="checkbox" checked={toolForm.is_shared}
                onChange={e => setToolForm({ ...toolForm, is_shared: e.target.checked })} />
              {t('capabilities.common.shared')}
            </label>
          </div>

          <div className="skill-section-label">{t('capabilities.toolForm.parameters')} <button className="param-add-btn" onClick={addParam}>{t('capabilities.actions.addParameter')}</button></div>
          {toolForm.parameters.map((p, idx) => (
            <div key={idx} className="param-row">
              <input placeholder={t('capabilities.toolForm.parameterName')} value={p.name} className="param-name"
                onChange={e => updateParam(idx, 'name', e.target.value)} />
              <select value={p.type} onChange={e => updateParam(idx, 'type', e.target.value)}>
                <option value="string">string</option>
                <option value="number">number</option>
                <option value="integer">integer</option>
                <option value="boolean">boolean</option>
              </select>
              <input placeholder={t('capabilities.toolForm.parameterDescription')} value={p.description} className="param-desc"
                onChange={e => updateParam(idx, 'description', e.target.value)} />
              <button className="param-remove-btn" onClick={() => removeParam(idx)} title={t('capabilities.actions.removeParameter')} aria-label={t('capabilities.actions.removeParameter')}>×</button>
            </div>
          ))}

          <div className="skill-section-label">{t('capabilities.toolForm.templateConfig')}</div>
          <textarea className="tool-config-editor" rows={5} value={toolForm.template_config}
            onChange={e => setToolForm({ ...toolForm, template_config: e.target.value })}
            placeholder={TEMPLATE_HINTS[toolForm.template_type] || '{}'} />

          {toolError && <div className="skill-add-error">{toolError}</div>}
          {testResult && <div className="tool-test-result">{testResult}</div>}
          <div className="skill-add-actions">
            <button className="btn-secondary btn-sm" onClick={() => { setShowToolForm(false); setEditingTool(null); }}>{t('capabilities.actions.cancel')}</button>
            {editingTool?.id && <button className="btn-secondary btn-sm" disabled={testing} onClick={handleTestTool}>{testing ? t('capabilities.actions.testing') : t('capabilities.actions.test')}</button>}
            <button className="btn-primary btn-sm" disabled={savingTool} onClick={handleSaveTool}>
              {savingTool ? t('capabilities.actions.saving') : editingTool ? t('capabilities.actions.save') : t('capabilities.actions.create')}
            </button>
          </div>
        </div>
      )}

      <input className="capabilities-search" placeholder={t('capabilities.search.placeholder')}
        value={search} onChange={e => setSearch(e.target.value)} />

      <div className="capabilities-filters">
        {(['all', 'builtin_skill', 'custom_skill', 'toolset', 'user_tool', 'bundle', 'template'] as CapFilter[]).map(f => (
          <button key={f} className={`cap-filter-btn ${filter === f ? 'active' : ''}`}
            onClick={() => setFilter(f)}>
            {f === 'bundle'
              ? t('capabilities.filters.bundle', { count: formatNumber(bundles.length) })
              : t(`capabilities.filters.${f}`)}
          </button>
        ))}
      </div>

      {loading && items.length === 0 ? (
        <div className="empty-state">{t('capabilities.states.loading')}</div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">{t('capabilities.states.empty')}</div>
      ) : (
        <div className="capabilities-list">
          {filtered.map((item, i) => (
            <div key={`${item.type}-${item.id || item.name}-${i}`} className="capability-card">
              <div className="cap-card-header">
                <span className="cap-card-name">{itemName(item)}</span>
                <span className={`cap-badge ${typeClass(item.type)}`}>{typeLabel(item.type)}</span>
                {item.domain && <span className="cap-badge cap-domain">{itemDomain(item)}</span>}
              </div>
              {item.description && <div className="cap-card-desc">{itemDescription(item)}</div>}
              {item.intent_triggers && (
                <div className="cap-card-triggers">
                  {item.intent_triggers.split(',').map((t, j) => (
                    <span key={j} className="cap-trigger-tag">{t.trim()}</span>
                  ))}
                </div>
              )}
              {item.type === 'custom_skill' && (
                <div className="cap-card-footer">
                  {item.owner_username && <span className="cap-owner">{t('capabilities.cards.by', { name: item.owner_username })}</span>}
                  {item.is_shared && <span className="cap-badge cap-shared">{t('capabilities.common.shared')}</span>}
                  {item.depends_on && item.depends_on.length > 0 && (
                    <span className="cap-badge cap-domain" title={t('capabilities.cards.dependenciesTitle')}>
                      {t('capabilities.cards.dependencies', { ids: item.depends_on.map((d: number) => `#${d}`).join(', ') })}
                    </span>
                  )}
                  {item.id && (
                    <>
                      <button className="cap-edit-btn" onClick={() => handleEditSkill(item)}>{t('capabilities.actions.edit')}</button>
                      <button className="cap-delete-btn" onClick={() => handleDeleteSkill(item.id!)}>{t('capabilities.actions.delete')}</button>
                    </>
                  )}
                </div>
              )}
              {item.type === 'user_tool' && (
                <div className="cap-card-footer">
                  <span className="cap-badge cap-template-type">{(item as any).template_type}</span>
                  {item.owner_username && <span className="cap-owner">{t('capabilities.cards.by', { name: item.owner_username })}</span>}
                  {item.is_shared && <span className="cap-badge cap-shared">{t('capabilities.common.shared')}</span>}
                  {item.id && (
                    <>
                      <button className="cap-edit-btn" onClick={() => handleEditTool(item)}>{t('capabilities.actions.edit')}</button>
                      <button className="cap-delete-btn" onClick={() => handleDeleteTool(item.id!)}>{t('capabilities.actions.delete')}</button>
                    </>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Skill Bundles Section ── */}
      {filter === 'bundle' && (
        <div className="capabilities-list">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontSize: 12, color: '#6b7280' }}>{t('capabilities.bundles.description')}</span>
            <button className="cap-add-btn" onClick={() => { setEditingBundle(null); setBundleForm({ bundle_name: '', description: '', toolset_names: [], skill_names: [], intent_triggers: '', is_shared: false }); setShowBundleForm(true); }}>{t('capabilities.actions.newBundle')}</button>
          </div>

          {showBundleForm && (
            <div className="cap-skill-form" style={{ marginBottom: 12 }}>
              <h4>{editingBundle ? t('capabilities.bundles.editTitle') : t('capabilities.bundles.createTitle')}</h4>
              {bundleError && <div className="cap-form-error">{bundleError}</div>}
              <input placeholder={t('capabilities.bundles.namePlaceholder')} value={bundleForm.bundle_name} onChange={e => setBundleForm(f => ({ ...f, bundle_name: e.target.value }))} />
              <input placeholder={t('capabilities.bundles.descriptionPlaceholder')} value={bundleForm.description} onChange={e => setBundleForm(f => ({ ...f, description: e.target.value }))} />
              <input placeholder={t('capabilities.bundles.triggersPlaceholder')} value={bundleForm.intent_triggers} onChange={e => setBundleForm(f => ({ ...f, intent_triggers: e.target.value }))} />

              <div style={{ fontSize: 11, fontWeight: 600, marginTop: 8 }}>{t('capabilities.bundles.toolsets')}</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
                {(availableTools.toolsets || []).map(ts => (
                  <label key={ts} style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 2 }}>
                    <input type="checkbox" checked={bundleForm.toolset_names.includes(ts)}
                      onChange={e => {
                        const names = e.target.checked ? [...bundleForm.toolset_names, ts] : bundleForm.toolset_names.filter(n => n !== ts);
                        setBundleForm(f => ({ ...f, toolset_names: names }));
                      }} />
                    {ts}
                  </label>
                ))}
              </div>

              <div style={{ fontSize: 11, fontWeight: 600 }}>{t('capabilities.bundles.skills')}</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
                {(availableTools.skills || []).map(sk => (
                  <label key={sk} style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 2 }}>
                    <input type="checkbox" checked={bundleForm.skill_names.includes(sk)}
                      onChange={e => {
                        const names = e.target.checked ? [...bundleForm.skill_names, sk] : bundleForm.skill_names.filter(n => n !== sk);
                        setBundleForm(f => ({ ...f, skill_names: names }));
                      }} />
                    {sk}
                  </label>
                ))}
              </div>

              <label style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
                <input type="checkbox" checked={bundleForm.is_shared} onChange={e => setBundleForm(f => ({ ...f, is_shared: e.target.checked }))} />
                {t('capabilities.skillForm.share')}
              </label>

              <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                <button className="cap-save-btn" disabled={savingBundle} onClick={async () => {
                  if (!bundleForm.bundle_name.trim()) { setBundleError(t('capabilities.errors.bundleNameRequired')); return; }
                  if (bundleForm.toolset_names.length === 0 && bundleForm.skill_names.length === 0) { setBundleError(t('capabilities.errors.bundleSelectionRequired')); return; }
                  setSavingBundle(true); setBundleError('');
                  try {
                    const url = editingBundle ? `/api/bundles/${editingBundle.id}` : '/api/bundles';
                    const method = editingBundle ? 'PUT' : 'POST';
                    const resp = await fetch(url, { method, credentials: 'include', headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() }, body: JSON.stringify(bundleForm) });
                    if (!resp.ok) { const d = await resp.json(); setBundleError(d.error || t('capabilities.errors.saveFailed')); return; }
                    setShowBundleForm(false); fetchCapabilities();
                  } catch { setBundleError(t('capabilities.errors.network')); }
                  finally { setSavingBundle(false); }
                }}>{savingBundle ? t('capabilities.actions.saving') : t('capabilities.actions.save')}</button>
                <button className="cap-cancel-btn" onClick={() => setShowBundleForm(false)}>{t('capabilities.actions.cancel')}</button>
              </div>
            </div>
          )}

          {bundles.map(b => (
            <div key={b.id} className="capability-card">
              <div className="cap-card-header">
                <span className="cap-type-badge cap-type-custom">{t('capabilities.types.bundle')}</span>
                <span className="cap-name">{b.bundle_name}</span>
              </div>
              {b.description && <div className="cap-description">{b.description}</div>}
              <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>
                {t('capabilities.bundles.contents', {
                  toolsets: (b.toolset_names || []).join(', ') || t('capabilities.common.none'),
                  skills: (b.skill_names || []).join(', ') || t('capabilities.common.none'),
                })}
              </div>
              {b.intent_triggers && <div style={{ fontSize: 11, color: '#9ca3af' }}>{t('capabilities.bundles.triggers', { triggers: b.intent_triggers })}</div>}
              <div className="cap-card-actions">
                {b.owner_username && <span className="cap-owner">{t('capabilities.cards.by', { name: b.owner_username })}</span>}
                {b.is_shared && <span className="cap-badge cap-shared">{t('capabilities.common.shared')}</span>}
                <button className="cap-edit-btn" onClick={() => { setEditingBundle(b); setBundleForm({ bundle_name: b.bundle_name, description: b.description || '', toolset_names: b.toolset_names || [], skill_names: b.skill_names || [], intent_triggers: b.intent_triggers || '', is_shared: b.is_shared || false }); setShowBundleForm(true); }}>{t('capabilities.actions.edit')}</button>
                <button className="cap-delete-btn" onClick={async () => {
                  if (!confirm(t('capabilities.confirm.deleteBundle', { name: b.bundle_name }))) return;
                  await fetch(`/api/bundles/${b.id}`, { method: 'DELETE', credentials: 'include', headers: getLocaleHeaders() });
                  fetchCapabilities();
                }}>{t('capabilities.actions.delete')}</button>
              </div>
            </div>
          ))}
          {bundles.length === 0 && !showBundleForm && (
            <div style={{ textAlign: 'center', color: '#9ca3af', padding: 20, fontSize: 12 }}>
              {t('capabilities.bundles.empty')}
            </div>
          )}
        </div>
      )}
        </>
      )}
    </div>
  );
}
