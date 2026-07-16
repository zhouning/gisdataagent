import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  GitCompare,
  LocateFixed,
  Map,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react';

type R = Record<string, any>;
type BusinessAction = 'change_land_use' | 'add_facility' | 'remove_facility';

declare global {
  interface Window {
    __handleMapUpdate?: (payload: any) => void;
  }
}

const rec = (value: unknown): R =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as R) : {};
const arr = <T = R,>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : []);
const text = (value: unknown) => String(value ?? '-');
const percent = (value: unknown) =>
  typeof value === 'number' ? `${value.toFixed(2)}%` : '-';

const RECOMMENDATIONS: Record<string, string> = {
  agree: '同意',
  conditional_agree: '有条件同意',
  disagree: '不同意',
  evidence_insufficient: '证据不足',
};

const RULE_LABELS: Record<string, string> = {
  coverage_not_decreased: '设施覆盖代理未下降',
  coverage_decreased: '设施覆盖代理下降',
  land_use_transition_resolved: '用途转换规则已解析',
  land_use_transition_requires_review: '用途转换仍需人工复核',
  incomplete_facility_inventory_blocks_formal_agreement: '设施清单不完整，阻止正式同意',
  scenario_radius_blocks_statutory_claim: '服务半径是情景假设，不能作法定标准',
  critical_facility_coverage_proxy_decreases: '关键设施覆盖下降，触发不同意',
  required_evidence_missing_fail_closed: '关键证据缺失，系统关闭结论',
};

const CASES = [
  {
    name: '和平村：新增学校（500米情景）',
    parcelId: 'parcel_79bb3178da33949459fc',
    target: 'village_public_service_land',
    actionType: 'add_facility' as BusinessAction,
    facilityClass: 'education.school',
    radius: '500',
    rationale: '评估在目标地块新增学校后，和平村真实地块覆盖代理的前后变化。',
  },
  {
    name: '和平村：仅变更用途',
    parcelId: 'parcel_79bb3178da33949459fc',
    target: 'village_independent_construction_land',
    actionType: 'change_land_use' as BusinessAction,
    facilityClass: '',
    radius: '',
    rationale: '仅验证用途变更的状态、传播和证据边界，不虚构设施覆盖变化。',
  },
  {
    name: '斑竹村：住宅 → 公共服务',
    parcelId: 'parcel_21fc78d2bdc55c84a859',
    target: 'village_public_service_land',
    actionType: 'change_land_use' as BusinessAction,
    facilityClass: '',
    radius: '',
    rationale: '验证斑竹村公共服务用途变更后的直接状态、邻域传播和无行动基线。',
  },
];

export default function UwmLivabilityS2Panel() {
  const [catalog, setCatalog] = useState<R>({});
  const [parcels, setParcels] = useState<R[]>([]);
  const [facilities, setFacilities] = useState<R[]>([]);
  const [planningProjects, setPlanningProjects] = useState<R[]>([]);
  const [parcelId, setParcelId] = useState('');
  const [search, setSearch] = useState('');
  const [villageFilter, setVillageFilter] = useState('');
  const [landUseFilter, setLandUseFilter] = useState('');
  const [targetClass, setTargetClass] = useState('');
  const [alternativeClass, setAlternativeClass] = useState('');
  const [actionType, setActionType] = useState<BusinessAction>('change_land_use');
  const [facilityClass, setFacilityClass] = useState('');
  const [facilityId, setFacilityId] = useState('');
  const [planningProjectId, setPlanningProjectId] = useState('');
  const [serviceRadius, setServiceRadius] = useState('500');
  const [radiusEvidenceSource, setRadiusEvidenceSource] = useState('user_scenario_assumption');
  const [criticalFacility, setCriticalFacility] = useState(true);
  const [rationale, setRationale] = useState('比较业务动作前后的覆盖、直接状态和邻域传播。');
  const [confirmed, setConfirmed] = useState(false);
  const [validation, setValidation] = useState<R | null>(null);
  const [run, setRun] = useState<R | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [auditOpen, setAuditOpen] = useState(false);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const [catalogResponse, parcelsResponse, facilitiesResponse, projectsResponse] = await Promise.all([
        fetch('/api/uwm/livability/s2/catalog', { credentials: 'include' }),
        fetch('/api/uwm/livability/s2/parcels', { credentials: 'include' }),
        fetch('/api/uwm/livability/s2/facilities', { credentials: 'include' }),
        fetch('/api/uwm/livability/s2/planning-projects', { credentials: 'include' }),
      ]);
      const [catalogPayload, parcelsPayload, facilitiesPayload, projectsPayload] = await Promise.all([
        catalogResponse.json(),
        parcelsResponse.json(),
        facilitiesResponse.json(),
        projectsResponse.json(),
      ]);
      if (!catalogResponse.ok || !parcelsResponse.ok || !facilitiesResponse.ok || !projectsResponse.ok) {
        throw new Error(
          catalogPayload.error || parcelsPayload.error || facilitiesPayload.error || projectsPayload.error || 'S2 快照加载失败',
        );
      }
      setCatalog(catalogPayload);
      setParcels(arr(parcelsPayload.features));
      setFacilities(arr(facilitiesPayload.features));
      setPlanningProjects(arr(projectsPayload.projects));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'S2 快照加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const selected = useMemo(
    () => parcels.find((parcel) => String(parcel.id) === parcelId),
    [parcels, parcelId],
  );
  const properties = rec(selected?.properties);
  const villages = useMemo(
    () => Array.from(new Set(parcels.map((parcel) => text(rec(parcel.properties).planning_area_id)))).sort(),
    [parcels],
  );
  const classes = useMemo(
    () => Array.from(new Set(parcels.map((parcel) => text(rec(parcel.properties).current_land_use_class)))).sort(),
    [parcels],
  );
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return parcels
      .filter((parcel) => {
        const item = rec(parcel.properties);
        const id = text(parcel.id);
        const village = text(item.planning_area_id);
        const source = text(item.source_land_use_name);
        const current = text(item.current_land_use_class);
        return (
          (!query || `${id} ${village} ${source} ${current}`.toLowerCase().includes(query)) &&
          (!villageFilter || village === villageFilter) &&
          (!landUseFilter || current === landUseFilter)
        );
      })
      .slice(0, 30);
  }, [parcels, search, villageFilter, landUseFilter]);
  const removableFacilities = useMemo(
    () =>
      facilities.filter((facility) => {
        const item = rec(facility.properties);
        const areas = arr<string>(item.matching_planning_area_ids);
        const belongs = item.planning_area_id === properties.planning_area_id || areas.includes(properties.planning_area_id);
        return belongs && (!facilityClass || item.canonical_class === facilityClass);
      }),
    [facilities, facilityClass, properties.planning_area_id],
  );
  const availablePlanningProjects = useMemo(
    () => planningProjects.filter((project) => project.planning_area_id === properties.planning_area_id && project.canonical_facility_class),
    [planningProjects, properties.planning_area_id],
  );

  const reset = () => {
    setValidation(null);
    setRun(null);
    setConfirmed(false);
  };
  const select = (id: string) => {
    setParcelId(id);
    reset();
  };
  const loadCase = (scenario: (typeof CASES)[number]) => {
    setSearch(scenario.parcelId);
    setVillageFilter('');
    setLandUseFilter('');
    select(scenario.parcelId);
    setTargetClass(scenario.target);
    setActionType(scenario.actionType);
    setFacilityClass(scenario.facilityClass);
    setFacilityId('');
    setPlanningProjectId('');
    setServiceRadius(scenario.radius);
    setAlternativeClass('');
    setRationale(scenario.rationale);
  };
  const body = () => ({
    parcel_id: parcelId,
    from_land_use_class: properties.current_land_use_class,
    to_land_use_class: targetClass,
    snapshot_digest: catalog.snapshot_digest,
    rationale,
    requested_at: new Date().toISOString(),
    alternative_land_use_class: alternativeClass || undefined,
    action_type: actionType,
    facility_class: actionType === 'change_land_use' ? undefined : facilityClass || undefined,
    facility_id: actionType === 'remove_facility' ? facilityId || undefined : undefined,
    service_radius_m:
      actionType === 'change_land_use' || !serviceRadius ? undefined : Number(serviceRadius),
    radius_evidence_source:
      actionType === 'change_land_use' ? undefined : radiusEvidenceSource,
    critical_facility: actionType === 'change_land_use' ? false : criticalFacility,
    planning_project_id: actionType === 'change_land_use' ? undefined : planningProjectId || undefined,
  });

  const validate = async () => {
    setError('');
    setValidation(null);
    if (!parcelId || !targetClass || !rationale.trim()) {
      setError('请先选择真实地块、目标用途并填写行动理由。');
      return;
    }
    if (actionType !== 'change_land_use' && (!facilityClass || Number(serviceRadius) <= 0)) {
      setError('设施动作必须填写设施类别和正数服务半径。');
      return;
    }
    if (actionType === 'remove_facility' && !facilityId) {
      setError('移除设施必须选择真实设施记录。');
      return;
    }
    const response = await fetch('/api/uwm/livability/s2/validate-action', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body()),
    });
    const payload = await response.json();
    setValidation(payload);
    if (!response.ok) {
      setError(payload.error || arr(payload.validation?.errors).join(' / ') || '动作验证失败');
    }
  };

  const rollout = async () => {
    if (!confirmed) {
      setError('请先完成人工确认。');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/uwm/livability/s2/rollout', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body()),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'S2 推演失败');
      setRun(payload);
      pushMap(payload);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'S2 推演失败');
    } finally {
      setLoading(false);
    }
  };

  const MAP_STYLES: Record<string, R> = {
    target: { color: '#f59e0b', weight: 4, opacity: 1, fillColor: '#fbbf24', fillOpacity: 0.34 },
    affected: { color: '#64748b', weight: 1, opacity: 0.7, fillColor: '#94a3b8', fillOpacity: 0.12 },
    baseline: { color: '#475569', weight: 2, opacity: 0.85, fillColor: '#cbd5e1', fillOpacity: 0.10, dashArray: '7 5' },
    intervention: { color: '#ea580c', weight: 3, opacity: 0.95, fillColor: '#fb923c', fillOpacity: 0.20 },
    newlyCovered: { color: '#15803d', weight: 2, opacity: 0.95, fillColor: '#22c55e', fillOpacity: 0.46 },
    newlyUncovered: { color: '#b91c1c', weight: 2, opacity: 0.95, fillColor: '#ef4444', fillOpacity: 0.46 },
    planningResource: { color: '#7e22ce', weight: 2, opacity: 0.9, fillColor: '#c084fc', fillOpacity: 0.18 },
    facility: { color: '#0f766e', weight: 2, opacity: 1, fillColor: '#14b8a6', fillOpacity: 0.86, radius: 7 },
  };
  const layer = (name: string, geojsonData: unknown, style: R) => ({ name, type: 'geojson', geojsonData, style });
  const send = (layers: any[], metadata: R = {}) =>
    window.__handleMapUpdate?.({
      schema: 'map_update.v1',
      summary: { title: 'S2 用地性质变更与设施覆盖评估' },
      layers,
      metadata,
    });
  const locate = () =>
    selected &&
    send([layer('S2 目标真实地块', { type: 'FeatureCollection', features: [selected] }, MAP_STYLES.target)], {
      evidence_only: true,
      selected_parcel_id: parcelId,
    });
  const pushMap = (payload = run) => {
    if (!selected || !payload) return;
    const rolloutPayload = rec(payload.rollout);
    const evidence = rec(payload.map_evidence);
    const messages = arr(rec(rec(rolloutPayload.intervention).t2).messages);
    send(
      [
        layer('S2 目标真实地块', evidence.target_parcel || { type: 'FeatureCollection', features: [selected] }, MAP_STYLES.target),
        layer('S2 受影响地块', evidence.affected_parcels || { type: 'FeatureCollection', features: [] }, MAP_STYLES.affected),
        layer('S2 基线服务范围', evidence.baseline_service_areas || { type: 'FeatureCollection', features: [] }, MAP_STYLES.baseline),
        layer('S2 干预服务范围', evidence.intervention_service_areas || { type: 'FeatureCollection', features: [] }, MAP_STYLES.intervention),
        layer('S2 新增覆盖地块', evidence.newly_covered_parcels || { type: 'FeatureCollection', features: [] }, MAP_STYLES.newlyCovered),
        layer('S2 失去覆盖地块', evidence.newly_uncovered_parcels || { type: 'FeatureCollection', features: [] }, MAP_STYLES.newlyUncovered),
        layer('S2 规划资源证据', evidence.planning_resources || { type: 'FeatureCollection', features: [] }, MAP_STYLES.planningResource),
        layer('S2 设施证据', evidence.facilities || { type: 'FeatureCollection', features: [] }, MAP_STYLES.facility),
      ],
      {
        evidence_only: true,
        proxy_distance_bands_m: [50, 150, 300],
        assessment_digest: rec(payload.business_assessment).assessment_digest,
        affected_node_ids: messages.map((message) => message.target_node_id),
      },
    );
  };

  const validationPayload = rec(validation?.validation);
  const transition = rec(validationPayload.transition);
  const preview = rec(validation?.business_assessment_preview);
  const validationReady = Boolean(validationPayload.valid);
  const rolloutPayload = rec(run?.rollout);
  const intervention = rec(rolloutPayload.intervention);
  const t1 = rec(intervention.t1);
  const t2 = rec(intervention.t2);
  const execution = rec(run?.execution_scope);
  const assessment = rec(run?.business_assessment);
  const technicalAudit = rec(run?.technical_audit);
  const baselineCoverage = rec(assessment.baseline);
  const interventionCoverage = rec(assessment.intervention);
  const resultReady = Boolean(run?.run_id);
  const recommendation = RECOMMENDATIONS[text(assessment.recommendation)] || text(assessment.recommendation);

  return (
    <section className="traditional-workspace s2-workspace">
      <div className="traditional-panel s2-header">
        <div>
          <h3>S2 用地性质变更推演</h3>
          <p>真实地块 + 确定性GIS覆盖 + UWM状态行动反事实 Kernel。</p>
        </div>
        <button className="secondary-button" onClick={load} disabled={loading}>
          <RefreshCw size={14} />刷新真实快照
        </button>
      </div>

      <div className="traditional-panel s2-boundary">
        <AlertTriangle size={18} />
        <div>
          <strong>当前证据边界</strong>
          <p>
            设施清单完整性：{catalog.facility_inventory_complete ? '完整' : '不完整'}。情景半径结果是地块空间覆盖代理，
            不是人口覆盖、步行网络可达范围、法定服务半径或规划许可。
          </p>
        </div>
      </div>

      {error && <div className="traditional-error">{error}</div>}

      <div className="s2-case-row">
        {CASES.map((scenario) => (
          <button className="secondary-button" key={scenario.name} onClick={() => loadCase(scenario)}>
            {scenario.name}
          </button>
        ))}
      </div>

      <div className="s2-grid">
        <div className="traditional-panel">
          <h4>步骤 1：选择真实地块</h4>
          <label className="s2-search-label">
            <Search size={14} />
            地块 ID / 村庄 / 地类
            <input
              value={search}
              disabled={loading && !parcels.length}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="例如 parcel_79bb3178da33949459fc"
            />
          </label>
          <div className="s2-filter-row">
            <select value={villageFilter} onChange={(event) => setVillageFilter(event.target.value)}>
              <option value="">全部村庄</option>
              {villages.map((village) => <option key={village}>{village}</option>)}
            </select>
            <select value={landUseFilter} onChange={(event) => setLandUseFilter(event.target.value)}>
              <option value="">全部当前用途</option>
              {classes.map((item) => <option key={item}>{item}</option>)}
            </select>
          </div>
          <p>{loading && !parcels.length ? '正在加载真实地块…' : `匹配 ${filtered.length}${filtered.length === 30 ? '+' : ''} / 总计 ${parcels.length}`}</p>
          <div className="s2-parcel-results">
            {filtered.map((parcel) => {
              const item = rec(parcel.properties);
              return (
                <button
                  aria-label={`选择地块 ${parcel.id}`}
                  className={parcel.id === parcelId ? 's2-parcel-result active' : 's2-parcel-result'}
                  key={parcel.id}
                  onClick={() => select(String(parcel.id))}
                >
                  <strong>{text(parcel.id)}</strong>
                  <span>{text(item.planning_area_id)} · {text(item.source_land_use_name)}</span>
                  <small>{text(item.current_land_use_class)}</small>
                </button>
              );
            })}
            {!loading && !filtered.length && <p>未找到匹配地块，请调整关键词或筛选条件。</p>}
          </div>
        </div>

        <div className="traditional-panel">
          <h4>步骤 2：定义业务动作</h4>
          {selected ? (
            <>
              <div className="s2-parcel-card">
                <span>地块 ID</span><strong>{parcelId}</strong>
                <span>村庄</span><strong>{text(properties.planning_area_id)}</strong>
                <span>原始地类</span><strong>{text(properties.source_land_use_name)}</strong>
                <span>当前用途</span><strong>{text(properties.current_land_use_class)}</strong>
                <span>规划用途</span><strong>{text(properties.planned_land_use_class)}</strong>
              </div>
              <button className="secondary-button" onClick={locate}><LocateFixed size={14} />定位地块到地图</button>
            </>
          ) : <p>请先选择一个真实地块。</p>}

          <label>业务动作
            <select value={actionType} disabled={!selected} onChange={(event) => { setActionType(event.target.value as BusinessAction); reset(); }}>
              <option value="change_land_use">仅变更用地性质</option>
              <option value="add_facility">变更用地并新增设施</option>
              <option value="remove_facility">变更用地并移除设施</option>
            </select>
          </label>
          <label>目标用途
            <select value={targetClass} disabled={!selected} onChange={(event) => { setTargetClass(event.target.value); reset(); }}>
              <option value="">请选择</option>
              {arr<string>(catalog.land_use_classes).map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
          <label>替代用途
            <select value={alternativeClass} disabled={!selected} onChange={(event) => { setAlternativeClass(event.target.value); reset(); }}>
              <option value="">不设置</option>
              {arr<string>(catalog.land_use_classes).map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>

          {actionType !== 'change_land_use' && (
            <div className="s2-facility-action">
              <label>设施类别
                <input
                  list="s2-facility-classes"
                  value={facilityClass}
                  onChange={(event) => { setFacilityClass(event.target.value); setFacilityId(''); reset(); }}
                  placeholder="例如 education.school"
                />
                <datalist id="s2-facility-classes">
                  {arr<string>(catalog.observed_facility_classes).map((value) => <option key={value} value={value} />)}
                  <option value="education.school" />
                  <option value="healthcare.primary" />
                  <option value="park.public" />
                </datalist>
              </label>
              <label>规划项目证据（可选）
                <select
                  value={planningProjectId}
                  onChange={(event) => {
                    const projectId = event.target.value;
                    const project = planningProjects.find((item) => item.project_id === projectId);
                    setPlanningProjectId(projectId);
                    if (project?.canonical_facility_class) setFacilityClass(project.canonical_facility_class);
                    if (project?.project_name) setRationale(`依据重点项目清单“${project.project_name}”构建业务情景；项目表仅作为动作来源证据，目标地块仍由本次分析明确指定。`);
                    reset();
                  }}
                >
                  <option value="">不关联规划项目</option>
                  {availablePlanningProjects.map((project) => (
                    <option key={project.project_id} value={project.project_id}>
                      {text(project.project_name)} · {text(project.canonical_facility_class)}
                    </option>
                  ))}
                </select>
              </label>
              {actionType === 'remove_facility' && (
                <label>真实设施记录
                  <select value={facilityId} onChange={(event) => { setFacilityId(event.target.value); reset(); }}>
                    <option value="">请选择</option>
                    {removableFacilities.map((facility) => (
                      <option key={facility.id} value={facility.id}>
                        {text(rec(facility.properties).name)} · {text(facility.id)}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label>服务半径（米）
                <input type="number" min="1" step="50" value={serviceRadius} onChange={(event) => { setServiceRadius(event.target.value); reset(); }} />
              </label>
              <label>半径证据来源
                <select value={radiusEvidenceSource} onChange={(event) => { setRadiusEvidenceSource(event.target.value); reset(); }}>
                  <option value="user_scenario_assumption">用户情景假设</option>
                  <option value="authoritative_profile">权威标准配置</option>
                </select>
              </label>
              <label className="s2-confirm">
                <input type="checkbox" checked={criticalFacility} onChange={(event) => { setCriticalFacility(event.target.checked); reset(); }} />
                关键设施（覆盖下降时执行保守规则）
              </label>
            </div>
          )}

          <label>行动理由
            <textarea value={rationale} disabled={!selected} onChange={(event) => { setRationale(event.target.value); reset(); }} />
          </label>
          <p><strong>数据快照：</strong>{text(catalog.snapshot_digest)}</p>
        </div>

        <div className="traditional-panel">
          <h4>步骤 3：验证与人工确认</h4>
          <button className="secondary-button" disabled={!selected || !targetClass || !rationale.trim()} onClick={validate}>
            <ShieldCheck size={14} />验证动作与覆盖输入
          </button>
          {validation && (
            <div className="s2-validation-summary">
              <span>动作有效</span><strong>{text(validationPayload.valid)}</strong>
              <span>转换状态</span><strong>{text(transition.status)}</strong>
              <span>业务预判</span><strong>{RECOMMENDATIONS[text(preview.recommendation)] || text(preview.recommendation)}</strong>
              <span>需要人工复核</span><strong>{text(validationPayload.review_required)}</strong>
              {arr<string>(preview.blockers).length > 0 && <p>阻断项：{arr<string>(preview.blockers).join(' / ')}</p>}
              <p>{transition.status === 'unresolved' ? '权威转换规则不足，系统保持 fail-closed；这不是规划许可。' : '转换规则已解析，仍需按业务流程复核。'}</p>
            </div>
          )}
          <label className="s2-confirm">
            <input type="checkbox" disabled={!validationReady} checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
            人工确认：理解覆盖结果的证据等级、设施清单完整性和非许可边界。
          </label>
          <button className="primary-button" disabled={loading || !validationReady || !confirmed} onClick={rollout}>
            <Play size={14} />{loading ? '推演中…' : '执行反事实推演'}
          </button>
        </div>

        <div className="traditional-panel s2-business-result">
          <h4>步骤 4：业务结论与覆盖变化</h4>
          {!resultReady ? <p>完成动作验证和人工确认后执行推演。</p> : (
            <>
              <div className={`s2-recommendation ${text(assessment.recommendation)}`}>
                <span>建议</span>
                <strong>{recommendation}</strong>
                <small>{text(assessment.evidence_level)}</small>
              </div>
              <div className="traditional-kpi-grid">
                <div className="traditional-kpi"><span>基线覆盖代理</span><strong>{percent(baselineCoverage.coverage_percent)}</strong></div>
                <div className="traditional-kpi"><span>干预覆盖代理</span><strong>{percent(interventionCoverage.coverage_percent)}</strong></div>
                <div className="traditional-kpi"><span>变化百分点</span><strong>{assessment.coverage_delta_percentage_points == null ? '-' : Number(assessment.coverage_delta_percentage_points).toFixed(2)}</strong></div>
                <div className="traditional-kpi"><span>新增覆盖地块</span><strong>{arr(assessment.newly_covered_parcel_ids).length}</strong></div>
              </div>
              <h5>为什么</h5>
              <ol className="s2-explanation-chain">
                <li>在快照 <code>{text(run?.snapshot_digest)}</code> 中锁定目标真实地块和同村需求地块。</li>
                <li>按 {text(assessment.parameters?.service_radius_m)} 米半径重算基线与干预服务范围。</li>
                <li>以地块内部代表点等权判断覆盖，得到 {text(assessment.coverage_delta_percentage_points)} 个百分点变化。</li>
                <li>执行业务规则：{arr<string>(assessment.triggered_rules).map((rule) => RULE_LABELS[rule] || rule).join('；')}。</li>
                <li>UWM提供 t0 状态、t1 情景变更和 t2 空间关系信号；“有条件同意”由独立的覆盖代理和版本化业务规则共同得出，不把空间信号伪称为政策效果。</li>
              </ol>
              {arr<string>(assessment.blockers).length > 0 && <p><strong>阻断项：</strong>{arr<string>(assessment.blockers).join(' / ')}</p>}
              {arr<string>(assessment.completeness_warnings).length > 0 && <p><strong>完整性警告：</strong>{arr<string>(assessment.completeness_warnings).join(' / ')}</p>}
              <p><strong>声明边界：</strong>{text(assessment.claim_boundary)}</p>
              {assessment.planning_project_evidence && (
                <div className="s2-project-evidence">
                  <h5>规划项目来源证据</h5>
                  <p><strong>{text(assessment.planning_project_evidence.project_name)}</strong> · {text(assessment.planning_project_evidence.project_category)}</p>
                  <p>建设地点：{text(assessment.planning_project_evidence.location_text)}；空间证据：{text(assessment.planning_project_evidence.spatial_evidence_status)}</p>
                  <p>原表：{text(assessment.planning_project_evidence.source_ref?.source_file)}，第 {text(assessment.planning_project_evidence.source_ref?.excel_row)} 行。</p>
                  <p>该证据用于证明动作来源，不作为现状设施坐标或覆盖计算输入。</p>
                </div>
              )}
              <button className="secondary-button" onClick={() => pushMap()}><Map size={14} />发送覆盖与证据图层到地图</button>
            </>
          )}
        </div>
      </div>

      {resultReady && (
        <div className="traditional-panel">
          <h4><GitCompare size={16} /> UWM内部实现机制</h4>
          <div className="s2-timeline">
            <span>t0 当前状态<br /><strong>{text(properties.current_land_use_class)}</strong></span>
            <ChevronRight />
            <span>行动<br /><strong>{text(assessment.action?.action_type)}</strong></span>
            <ChevronRight />
            <span>t1 情景变更<br /><strong>{text(rec(t1.direct_state_delta).to_land_use_class)}</strong></span>
            <ChevronRight />
            <span>t2 邻域适应<br /><strong>{arr(t2.messages).length} 条空间传播信号</strong></span>
            <ChevronRight />
            <span>覆盖代理差异<br /><strong>{text(assessment.coverage_delta_percentage_points)} pp</strong></span>
          </div>
          <div className="traditional-kpi-grid">
            <div className="traditional-kpi"><span>局部状态节点</span><strong>{text(execution.rollout_node_count)}</strong></div>
            <div className="traditional-kpi"><span>局部空间关系边</span><strong>{text(execution.rollout_edge_count)} 条边</strong></div>
            <div className="traditional-kpi"><span>村域聚合</span><strong>{text(execution.cross_scale_edge_count)} 条跨尺度边</strong></div>
            <div className="traditional-kpi"><span>运行 ID</span><strong>{text(run?.run_id)}</strong></div>
          </div>
          <p>50 米、150 米、300 米仅用于Kernel空间传播代理；业务覆盖使用用户明确输入的服务半径，两者不混用。</p>
          <p>技术归因：本次运行的状态、动作、传播、覆盖代理和证据门已写入审计账本；其中 t1 是情景状态，不是已发生的观测结果。</p>
          <h5>不可预测效果</h5>
          <div className="s2-chip-list">{arr<string>(rolloutPayload.unavailable_effects).map((value) => <span key={value}>{value}</span>)}</div>
        </div>
      )}

      {resultReady && (
        <div className="traditional-panel">
          <button className="s2-audit-toggle" onClick={() => setAuditOpen((value) => !value)}>
            {auditOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}高级审计信息
          </button>
          {auditOpen && (
            <div className="s2-audit-grid">
              <div><h5>直接状态变化</h5><pre>{JSON.stringify(rolloutPayload.direct_state_delta || {}, null, 2)}</pre></div>
              <div><h5>覆盖业务评估</h5><pre>{JSON.stringify(assessment, null, 2)}</pre></div>
              <div><h5>不确定性</h5><pre>{JSON.stringify(rolloutPayload.uncertainty || {}, null, 2)}</pre></div>
              <div><h5>执行范围</h5><pre>{JSON.stringify(run?.execution_scope || {}, null, 2)}</pre></div>
              <div><h5>技术归因账本</h5><pre>{JSON.stringify(technicalAudit, null, 2)}</pre></div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
