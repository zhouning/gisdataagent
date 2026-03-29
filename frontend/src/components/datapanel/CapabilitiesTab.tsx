import { useState, useEffect } from 'react';

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
}

type CapFilter = 'all' | 'builtin_skill' | 'custom_skill' | 'toolset' | 'user_tool' | 'bundle' | 'template';

const TOOLSETS = [
  { name: 'ExplorationToolset', label: '数据探查与质量审计' },
  { name: 'GeoProcessingToolset', label: '缓冲区、叠加、裁剪' },
  { name: 'LocationToolset', label: '地理编码、POI搜索' },
  { name: 'AnalysisToolset', label: '空间统计与属性分析' },
  { name: 'VisualizationToolset', label: '地图渲染、3D可视化' },
  { name: 'DatabaseToolset', label: 'PostGIS查询与管理' },
  { name: 'FileToolset', label: '文件读写与格式转换' },
  { name: 'MemoryToolset', label: '空间记忆存储与检索' },
  { name: 'AdminToolset', label: '用户管理与系统配置' },
  { name: 'RemoteSensingToolset', label: '遥感影像与DEM下载' },
  { name: 'SpatialStatisticsToolset', label: '空间自相关与热点' },
  { name: 'SemanticLayerToolset', label: '语义目录浏览' },
  { name: 'StreamingToolset', label: '流式输出与进度推送' },
  { name: 'TeamToolset', label: '团队协作与资产共享' },
  { name: 'DataLakeToolset', label: '数据湖资产注册' },
  { name: 'McpHubToolset', label: 'MCP外部工具集成' },
  { name: 'FusionToolset', label: '多源数据融合' },
  { name: 'KnowledgeGraphToolset', label: '知识图谱构建' },
  { name: 'KnowledgeBaseToolset', label: '知识库与RAG检索' },
  { name: 'AdvancedAnalysisToolset', label: '时序、网络、假设分析' },
  { name: 'SpatialAnalysisTier2Toolset', label: '高级空间分析' },
  { name: 'WatershedToolset', label: '流域提取与水文分析' },
  { name: 'UserToolset', label: '用户自定义工具' },
];

const EMPTY_SKILL_FORM = {
  skill_name: '', instruction: '', description: '',
  toolset_names: [] as string[], trigger_keywords: '',
  model_tier: 'standard', is_shared: false,
};

export default function CapabilitiesTab({ userRole }: { userRole?: string }) {
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
      const [capResp, utResp, bundleResp, availResp, tmplResp] = await Promise.all([
        fetch('/api/capabilities', { credentials: 'include' }),
        fetch('/api/user-tools', { credentials: 'include' }),
        fetch('/api/bundles', { credentials: 'include' }),
        fetch('/api/bundles/available-tools', { credentials: 'include' }),
        fetch('/api/templates', { credentials: 'include' }),
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
          description: `[${t.category || '通用'}] ${t.description || ''}`,
          domain: t.category,
        }));
      }
      setItems([...builtin, ...custom, ...toolsets, ...userTools, ...templateItems]);
      setCounts({ builtin: builtin.length, custom: custom.length, toolset: toolsets.length, userTool: userTools.length, template: templateItems.length } as any);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchCapabilities(); }, []);

  const handleDeleteSkill = async (id: number) => {
    if (!confirm('确定删除此自定义技能？')) return;
    try {
      const resp = await fetch(`/api/skills/${id}`, { method: 'DELETE', credentials: 'include' });
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
    if (!skillForm.skill_name.trim()) { setFormError('技能名称必填'); return; }
    if (!skillForm.instruction.trim()) { setFormError('指令必填'); return; }
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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (resp.ok) {
        setShowSkillForm(false);
        setEditingSkill(null);
        setSkillForm({ ...EMPTY_SKILL_FORM });
        fetchCapabilities();
      } else {
        setFormError(data.error || '保存失败');
      }
    } catch { setFormError('网络错误'); }
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
    setShowToolForm(true); setShowSkillForm(false);
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
    if (!confirm('确定删除此自定义工具？')) return;
    try {
      const resp = await fetch(`/api/user-tools/${id}`, { method: 'DELETE', credentials: 'include' });
      if (resp.ok) fetchCapabilities();
    } catch { /* ignore */ }
  };

  const handleSaveTool = async () => {
    setToolError('');
    if (!toolForm.tool_name.trim()) { setToolError('工具名称必填'); return; }
    let configObj: any;
    try { configObj = JSON.parse(toolForm.template_config); }
    catch { setToolError('模板配置必须是有效 JSON'); return; }
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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (resp.ok) {
        setShowToolForm(false); setEditingTool(null);
        fetchCapabilities();
      } else { setToolError(data.error || '保存失败'); }
    } catch { setToolError('网络错误'); }
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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ params: testParams }),
      });
      const data = await resp.json();
      setTestResult(data.result || data.message || JSON.stringify(data));
    } catch (e) { setTestResult('测试失败: ' + e); }
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

  const TEMPLATE_TYPES = [
    { value: 'http_call', label: 'HTTP 调用' },
    { value: 'sql_query', label: 'SQL 查询' },
    { value: 'file_transform', label: '文件转换' },
    { value: 'chain', label: '链式组合' },
    { value: 'python_sandbox', label: 'Python 沙箱' },
  ];

  const TEMPLATE_HINTS: Record<string, string> = {
    http_call: '{"method":"GET","url":"https://api.example.com/data","headers":{},"extract_path":"data.result"}',
    sql_query: '{"query":"SELECT * FROM parcels WHERE area > :min_area","readonly":true}',
    file_transform: '{"operations":[{"op":"filter","column":"area","condition":">","value":100}],"output_format":"geojson"}',
    chain: '{"steps":[{"tool_name":"my_query","param_map":{"x":"$input.x"}}]}',
    python_sandbox: '{"python_code":"def tool_function(params):\\n    # 在此编写处理逻辑\\n    return {\\\"result\\\": params.get(\\\"input\\\", \\\"hello\\\")}","timeout":30}',
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

  const domainMap: Record<string, string> = {
    gis: 'GIS', governance: '治理', visualization: '可视化',
    analysis: '分析', database: '数据库', fusion: '融合',
    collaboration: '协作', general: '通用',
  };

  const typeLabel = (t: string) =>
    t === 'builtin_skill' ? '内置技能' : t === 'custom_skill' ? '自定义技能' : t === 'user_tool' ? '自定义工具' : t === 'template' ? '行业模板' : '工具集';

  const typeClass = (t: string) =>
    t === 'builtin_skill' ? 'cap-type-builtin' : t === 'custom_skill' ? 'cap-type-custom' : t === 'user_tool' ? 'cap-type-usertool' : t === 'template' ? 'cap-type-template' : 'cap-type-toolset';

  return (
    <div className="capabilities-view">
      <div className="capabilities-summary">
        <span>{(counts as any).builtin} 内置技能</span>
        <span className="cap-sep">/</span>
        <span>{(counts as any).custom} 自定义</span>
        <span className="cap-sep">/</span>
        <span>{(counts as any).toolset} 工具集</span>
        <span className="cap-sep">/</span>
        <span>{(counts as any).userTool || 0} 自建工具</span>
        <button className="btn-add-server" onClick={() => showSkillForm ? setShowSkillForm(false) : handleNewSkill()} title="新建自定义技能">+技能</button>
        <button className="btn-add-server" onClick={() => showToolForm ? setShowToolForm(false) : handleNewTool()} title="新建自定义工具">+工具</button>
      </div>

      {showSkillForm && (
        <div className="skill-add-form">
          <div className="skill-add-form-title">{editingSkill ? `编辑: ${editingSkill.name}` : '新建自定义技能'}</div>
          <input placeholder="技能名称 (必填，如: 土壤分析专家)" maxLength={100}
            value={skillForm.skill_name} onChange={e => setSkillForm({ ...skillForm, skill_name: e.target.value })} />
          <textarea placeholder="指令 (必填，描述技能的行为和专业知识，最多10000字)" rows={4} maxLength={10000}
            value={skillForm.instruction} onChange={e => setSkillForm({ ...skillForm, instruction: e.target.value })} />
          <input placeholder="描述 (可选)" value={skillForm.description}
            onChange={e => setSkillForm({ ...skillForm, description: e.target.value })} />
          <div className="skill-section-label">选择工具集</div>
          <div className="skill-toolset-grid">
            {TOOLSETS.map(t => (
              <label key={t.name} className="skill-toolset-item">
                <input type="checkbox" checked={skillForm.toolset_names.includes(t.name)}
                  onChange={() => toggleToolset(t.name)} />
                <span>{t.label}</span>
              </label>
            ))}
          </div>
          <input placeholder="触发关键词 (逗号分隔，如: 土壤, 地质)" value={skillForm.trigger_keywords}
            onChange={e => setSkillForm({ ...skillForm, trigger_keywords: e.target.value })} />
          <div className="skill-row">
            <select value={skillForm.model_tier} onChange={e => setSkillForm({ ...skillForm, model_tier: e.target.value })}>
              <option value="fast">快速 (fast)</option>
              <option value="standard">标准 (standard)</option>
              <option value="premium">高级 (premium)</option>
            </select>
            <label className="skill-checkbox">
              <input type="checkbox" checked={skillForm.is_shared}
                onChange={e => setSkillForm({ ...skillForm, is_shared: e.target.checked })} />
              共享给其他用户
            </label>
          </div>
          {formError && <div className="skill-add-error">{formError}</div>}
          <div className="skill-add-actions">
            <button className="btn-secondary btn-sm" onClick={() => { setShowSkillForm(false); setEditingSkill(null); }}>取消</button>
            <button className="btn-primary btn-sm" disabled={saving} onClick={handleSaveSkill}>
              {saving ? '保存中...' : editingSkill ? '保存' : '创建'}
            </button>
          </div>
        </div>
      )}

      {showToolForm && (
        <div className="skill-add-form">
          <div className="skill-add-form-title">{editingTool ? `编辑工具: ${editingTool.name}` : '新建自定义工具'}</div>
          <input placeholder="工具名称 (必填，如: query_weather)" maxLength={100}
            value={toolForm.tool_name} onChange={e => setToolForm({ ...toolForm, tool_name: e.target.value })} />
          <input placeholder="描述 (给 LLM 看的工具说明)" value={toolForm.description}
            onChange={e => setToolForm({ ...toolForm, description: e.target.value })} />
          <div className="skill-row">
            <select value={toolForm.template_type} onChange={e => {
              const tt = e.target.value;
              setToolForm({ ...toolForm, template_type: tt, template_config: TEMPLATE_HINTS[tt] || '{}' });
            }}>
              {TEMPLATE_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
            <label className="skill-checkbox">
              <input type="checkbox" checked={toolForm.is_shared}
                onChange={e => setToolForm({ ...toolForm, is_shared: e.target.checked })} />
              共享
            </label>
          </div>

          <div className="skill-section-label">参数定义 <button className="param-add-btn" onClick={addParam}>+ 添加参数</button></div>
          {toolForm.parameters.map((p, idx) => (
            <div key={idx} className="param-row">
              <input placeholder="参数名" value={p.name} className="param-name"
                onChange={e => updateParam(idx, 'name', e.target.value)} />
              <select value={p.type} onChange={e => updateParam(idx, 'type', e.target.value)}>
                <option value="string">string</option>
                <option value="number">number</option>
                <option value="integer">integer</option>
                <option value="boolean">boolean</option>
              </select>
              <input placeholder="说明" value={p.description} className="param-desc"
                onChange={e => updateParam(idx, 'description', e.target.value)} />
              <button className="param-remove-btn" onClick={() => removeParam(idx)}>×</button>
            </div>
          ))}

          <div className="skill-section-label">模板配置 (JSON)</div>
          <textarea className="tool-config-editor" rows={5} value={toolForm.template_config}
            onChange={e => setToolForm({ ...toolForm, template_config: e.target.value })}
            placeholder={TEMPLATE_HINTS[toolForm.template_type] || '{}'} />

          {toolError && <div className="skill-add-error">{toolError}</div>}
          {testResult && <div className="tool-test-result">{testResult}</div>}
          <div className="skill-add-actions">
            <button className="btn-secondary btn-sm" onClick={() => { setShowToolForm(false); setEditingTool(null); }}>取消</button>
            {editingTool?.id && <button className="btn-secondary btn-sm" disabled={testing} onClick={handleTestTool}>{testing ? '测试中...' : '测试'}</button>}
            <button className="btn-primary btn-sm" disabled={savingTool} onClick={handleSaveTool}>
              {savingTool ? '保存中...' : editingTool ? '保存' : '创建'}
            </button>
          </div>
        </div>
      )}

      <input className="capabilities-search" placeholder="搜索技能或工具集..."
        value={search} onChange={e => setSearch(e.target.value)} />

      <div className="capabilities-filters">
        {(['all', 'builtin_skill', 'custom_skill', 'toolset', 'user_tool', 'bundle', 'template'] as CapFilter[]).map(f => (
          <button key={f} className={`cap-filter-btn ${filter === f ? 'active' : ''}`}
            onClick={() => setFilter(f)}>
            {f === 'all' ? '全部' : f === 'builtin_skill' ? '内置技能' : f === 'custom_skill' ? '自定义' : f === 'user_tool' ? '自建工具' : f === 'bundle' ? `技能包(${bundles.length})` : f === 'template' ? '行业模板' : '工具集'}
          </button>
        ))}
      </div>

      {loading && items.length === 0 ? (
        <div className="empty-state">加载中...</div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">暂无匹配项</div>
      ) : (
        <div className="capabilities-list">
          {filtered.map((item, i) => (
            <div key={`${item.type}-${item.id || item.name}-${i}`} className="capability-card">
              <div className="cap-card-header">
                <span className="cap-card-name">{item.name}</span>
                <span className={`cap-badge ${typeClass(item.type)}`}>{typeLabel(item.type)}</span>
                {item.domain && <span className="cap-badge cap-domain">{domainMap[item.domain] || item.domain}</span>}
              </div>
              {item.description && <div className="cap-card-desc">{item.description}</div>}
              {item.intent_triggers && (
                <div className="cap-card-triggers">
                  {item.intent_triggers.split(',').map((t, j) => (
                    <span key={j} className="cap-trigger-tag">{t.trim()}</span>
                  ))}
                </div>
              )}
              {item.type === 'custom_skill' && (
                <div className="cap-card-footer">
                  {item.owner_username && <span className="cap-owner">by {item.owner_username}</span>}
                  {item.is_shared && <span className="cap-badge cap-shared">共享</span>}
                  {item.depends_on && item.depends_on.length > 0 && (
                    <span className="cap-badge cap-domain" title="依赖技能 ID">
                      依赖: {item.depends_on.map((d: number) => `#${d}`).join(', ')}
                    </span>
                  )}
                  {item.id && (
                    <>
                      <button className="cap-edit-btn" onClick={() => handleEditSkill(item)}>编辑</button>
                      <button className="cap-delete-btn" onClick={() => handleDeleteSkill(item.id!)}>删除</button>
                    </>
                  )}
                </div>
              )}
              {item.type === 'user_tool' && (
                <div className="cap-card-footer">
                  <span className="cap-badge cap-template-type">{(item as any).template_type}</span>
                  {item.owner_username && <span className="cap-owner">by {item.owner_username}</span>}
                  {item.is_shared && <span className="cap-badge cap-shared">共享</span>}
                  {item.id && (
                    <>
                      <button className="cap-edit-btn" onClick={() => handleEditTool(item)}>编辑</button>
                      <button className="cap-delete-btn" onClick={() => handleDeleteTool(item.id!)}>删除</button>
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
            <span style={{ fontSize: 12, color: '#6b7280' }}>组合多个工具集+技能为可复用的技能包</span>
            <button className="cap-add-btn" onClick={() => { setEditingBundle(null); setBundleForm({ bundle_name: '', description: '', toolset_names: [], skill_names: [], intent_triggers: '', is_shared: false }); setShowBundleForm(true); }}>+ 技能包</button>
          </div>

          {showBundleForm && (
            <div className="cap-skill-form" style={{ marginBottom: 12 }}>
              <h4>{editingBundle ? '编辑技能包' : '创建技能包'}</h4>
              {bundleError && <div className="cap-form-error">{bundleError}</div>}
              <input placeholder="技能包名称" value={bundleForm.bundle_name} onChange={e => setBundleForm(f => ({ ...f, bundle_name: e.target.value }))} />
              <input placeholder="描述（可选）" value={bundleForm.description} onChange={e => setBundleForm(f => ({ ...f, description: e.target.value }))} />
              <input placeholder="触发关键词（逗号分隔）" value={bundleForm.intent_triggers} onChange={e => setBundleForm(f => ({ ...f, intent_triggers: e.target.value }))} />

              <div style={{ fontSize: 11, fontWeight: 600, marginTop: 8 }}>工具集</div>
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

              <div style={{ fontSize: 11, fontWeight: 600 }}>技能</div>
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
                共享给其他用户
              </label>

              <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                <button className="cap-save-btn" disabled={savingBundle} onClick={async () => {
                  if (!bundleForm.bundle_name.trim()) { setBundleError('名称不能为空'); return; }
                  if (bundleForm.toolset_names.length === 0 && bundleForm.skill_names.length === 0) { setBundleError('至少选择一个工具集或技能'); return; }
                  setSavingBundle(true); setBundleError('');
                  try {
                    const url = editingBundle ? `/api/bundles/${editingBundle.id}` : '/api/bundles';
                    const method = editingBundle ? 'PUT' : 'POST';
                    const resp = await fetch(url, { method, credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(bundleForm) });
                    if (!resp.ok) { const d = await resp.json(); setBundleError(d.error || '保存失败'); return; }
                    setShowBundleForm(false); fetchCapabilities();
                  } catch { setBundleError('网络错误'); }
                  finally { setSavingBundle(false); }
                }}>{savingBundle ? '保存中...' : '保存'}</button>
                <button className="cap-cancel-btn" onClick={() => setShowBundleForm(false)}>取消</button>
              </div>
            </div>
          )}

          {bundles.map(b => (
            <div key={b.id} className="capability-card">
              <div className="cap-card-header">
                <span className="cap-type-badge cap-type-custom">技能包</span>
                <span className="cap-name">{b.bundle_name}</span>
              </div>
              {b.description && <div className="cap-description">{b.description}</div>}
              <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>
                工具集: {(b.toolset_names || []).join(', ') || '无'} | 技能: {(b.skill_names || []).join(', ') || '无'}
              </div>
              {b.intent_triggers && <div style={{ fontSize: 11, color: '#9ca3af' }}>触发: {b.intent_triggers}</div>}
              <div className="cap-card-actions">
                {b.owner_username && <span className="cap-owner">by {b.owner_username}</span>}
                {b.is_shared && <span className="cap-badge cap-shared">共享</span>}
                <button className="cap-edit-btn" onClick={() => { setEditingBundle(b); setBundleForm({ bundle_name: b.bundle_name, description: b.description || '', toolset_names: b.toolset_names || [], skill_names: b.skill_names || [], intent_triggers: b.intent_triggers || '', is_shared: b.is_shared || false }); setShowBundleForm(true); }}>编辑</button>
                <button className="cap-delete-btn" onClick={async () => {
                  if (!confirm(`确定删除技能包 "${b.bundle_name}"？`)) return;
                  await fetch(`/api/bundles/${b.id}`, { method: 'DELETE', credentials: 'include' });
                  fetchCapabilities();
                }}>删除</button>
              </div>
            </div>
          ))}
          {bundles.length === 0 && !showBundleForm && (
            <div style={{ textAlign: 'center', color: '#9ca3af', padding: 20, fontSize: 12 }}>
              暂无技能包，点击 "+ 技能包" 创建
            </div>
          )}
        </div>
      )}
    </div>
  );
}