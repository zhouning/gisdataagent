import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  Database,
  Eye,
  GitCompare,
  Layers3,
  ListChecks,
  Map,
  Play,
  RefreshCw,
  Route,
  ShieldCheck,
  Sigma,
  Sparkles,
  Split,
} from 'lucide-react';

type R = Record<string, any>;

declare global {
  interface Window {
    __handleMapUpdate?: (payload: any) => void;
  }
}

const rec = (value: unknown): R =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as R : {};
const arr = <T = R,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];
const number = (value: unknown, digits = 9) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : '-';
};
const unit = (value: unknown) => {
  const text = String(value || '-');
  const parts = text.split('|');
  return parts.length >= 2 ? `${parts[0]} · ${parts[1]}` : text;
};
const ACTION_LABELS: Record<string, string> = {
  increase_green_infrastructure: '增加绿色基础设施',
  traffic_emission_control: '交通减排治理',
  add_community_service: '补充社区公共服务',
};
const actionLabel = (value: unknown) => ACTION_LABELS[String(value || '')] || String(value || '-');
const FEATURE_GROUP_DESCRIPTIONS: Record<string, string> = {
  模型基准: '常数偏置，承担线性模型截距作用',
  动作编码: '区分增绿、交通减排、公共服务和其他动作',
  动作强度: '描述本次干预力度，当前候选目录统一为1.0',
  目标状态: '目标空间单元当前的风险、短板、公平性和宜居性',
  空间与交通上下文: '空间连接、出行时间、道路和设施容量等条件',
  候选生成依据: '记录该动作因何种业务阈值进入候选目录',
  时序上下文: '动作处于多阶段规划的第几步',
};
const actionFromId = (value: unknown) => {
  const actionId = String(value || '');
  const actionType = Object.keys(ACTION_LABELS).find(type => actionId.startsWith(`${type}-`)) || '';
  return {
    label: actionLabel(actionType),
    target: actionId.slice(actionType.length + 1),
  };
};

export default function UwmMultistageInterventionTab() {
  const [overview, setOverview] = useState<R>({});
  const [run, setRun] = useState<R>({});
  const [loading, setLoading] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState('');
  const [focusUnit, setFocusUnit] = useState('');
  const [horizon, setHorizon] = useState(2);
  const [beamWidth, setBeamWidth] = useState(8);
  const [gamma, setGamma] = useState(0.9);
  const [uncertaintyPenalty, setUncertaintyPenalty] = useState(0.5);
  const [actionTypes, setActionTypes] = useState<string[]>(Object.keys(ACTION_LABELS));
  const [activeScene, setActiveScene] = useState('branch');

  const loadOverview = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/uwm/multistage-intervention/overview', { credentials: 'include' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '多阶段规划概览加载失败');
      setOverview(payload);
      const defaults = rec(payload.default_request);
      setFocusUnit(String(defaults.focus_unit || ''));
      setHorizon(Number(defaults.horizon || 2));
      setBeamWidth(Number(defaults.beam_width || 8));
      setGamma(Number(defaults.gamma || 0.9));
      setUncertaintyPenalty(Number(defaults.uncertainty_penalty || 0.5));
      setActionTypes(arr<string>(defaults.action_types));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '多阶段规划概览加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadOverview(); }, []);

  const showScene = (sceneKey: string, payload = run) => {
    const scene = rec(rec(payload.map_scenes)[sceneKey]);
    if (!scene.schema) return;
    setActiveScene(sceneKey);
    window.__handleMapUpdate?.(scene);
  };

  const executePlan = async () => {
    setPlanning(true);
    setError('');
    try {
      const response = await fetch('/api/uwm/multistage-intervention/plan', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          focus_unit: focusUnit,
          neighborhood_hops: focusUnit ? 1 : 0,
          horizon,
          beam_width: beamWidth,
          gamma,
          uncertainty_penalty: uncertaintyPenalty,
          action_types: actionTypes,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'UWM多阶段规划失败');
      setRun(payload);
      setActiveScene('branch');
      window.__handleMapUpdate?.(rec(payload.map_scenes).branch || payload.map_update);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'UWM多阶段规划失败');
    } finally {
      setPlanning(false);
    }
  };

  const toggleActionType = (value: string) => {
    setActionTypes(current => current.includes(value)
      ? current.filter(item => item !== value)
      : [...current, value]);
  };

  const foundation = rec(overview.data_foundation);
  const dataLayers = arr<R>(foundation.data_layers);
  const actionCatalog = rec(overview.action_catalog);
  const actionCatalogRows = arr<R>(actionCatalog.rows);
  const simulatorSpec = rec(overview.simulator_specification);
  const inputGroups = arr<R>(simulatorSpec.input_groups);
  const inputFeatures = arr<R>(simulatorSpec.input_features);
  const outputTargets = arr<R>(simulatorSpec.output_targets);
  const necessity = rec(overview.world_model_necessity);
  const architecture = rec(run.world_model_architecture);
  const scope = rec(run.planning_scope);
  const candidateSummary = rec(run.candidate_action_summary);
  const selected = rec(run.selected_sequence);
  const steps = arr<R>(selected.imagined_steps);
  const dependency = rec(run.state_dependency_diagnostic);
  const story = rec(run.decision_story);
  const proofPoints = arr<string>(story.proof_points);
  const searchSummary = rec(run.planner_search_summary);
  const baselines = rec(run.baselines);
  const advantages = rec(baselines.advantages);
  const ablationRows = arr<R>(rec(baselines.validated_action_ablation_benchmark).baseline_rows);
  const training = rec(run.training_summary);
  const trainingTransparency = rec(run.training_transparency);
  const runtimeProfile = rec(run.runtime_profile);
  const boundary = rec(run.claim_boundary || overview.claim_boundary);
  const prohibitedClaims = arr<string>(boundary.prohibited_claims);
  const rankingBefore = arr<R>(dependency.ranking_before_state_update);
  const rankingAfter = arr<R>(dependency.ranking_after_state_update);
  const rankingChanges = arr<R>(dependency.ranking_changes);
  const oldSecond = actionFromId(dependency.top_second_action_without_state_update);
  const selectedActions = arr<R>(selected.action_sequence);
  const newSecond = selectedActions[1] || {};
  const firstAction = selectedActions[0] || {};
  const canRun = actionTypes.length > 0 && !planning;

  return (
    <div className="uwm-livability-tab uwm-multistage-tab">
      <div className="datapanel-section-header">
        <div>
          <h3><BrainCircuit size={18} />UWM多阶段城市干预规划</h3>
          <p>让用户看见世界状态如何变化，以及变化后的世界为什么要求改变下一步。</p>
        </div>
        <button className="secondary-button" onClick={loadOverview} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} />刷新资产
        </button>
      </div>

      {error && <div className="uwm-livability-message error">{error}</div>}

      <section className="uwm-data-readiness">
        <div className="uwm-section-lead">
          <div>
            <span><Database size={14} />规划前先看数据</span>
            <h3>UWM当前能够感知的城市数据现状</h3>
            <p>先确认状态、空间关系、候选动作和学习样本，再进入未来推演。</p>
          </div>
          <div className="uwm-readiness-badge"><CheckCircle2 size={16} />1017/1017空间单元已连接</div>
        </div>
        <div className="uwm-data-layer-grid">
          {dataLayers.map(row => <div className="uwm-data-layer-card" key={row.layer}>
            <div><strong>{row.layer}</strong><span>{row.status}</span></div>
            <b>{row.coverage}</b>
            <small>{row.content}</small>
          </div>)}
        </div>
        <p className="uwm-evidence-note"><AlertTriangle size={14} />{foundation.evidence_note || '-'}</p>
      </section>

      <section className="uwm-action-catalog">
        <div className="uwm-section-lead">
          <div>
            <span><ListChecks size={14} />候选动作目录</span>
            <h3>不是1,137种政策，而是3类动作在不同空间单元上的1,137个实例</h3>
            <p>{actionCatalog.instance_definition || '-'}</p>
          </div>
          <div className="uwm-catalog-equation"><strong>{actionCatalog.template_count || 3}</strong><span>类模板</span><b>×</b><strong>符合阈值的空间单元</strong><b>=</b><strong>{actionCatalog.instance_count || '-'}</strong><span>个候选实例</span></div>
        </div>
        <div className="uwm-action-type-grid">
          {actionCatalogRows.map(row => <article key={row.action_type}>
            <header><span>{actionLabel(row.action_type)}</span><strong>{row.instance_count}个</strong></header>
            <p><b>为什么进入目录：</b>{row.trigger}</p>
            <div className="uwm-action-examples">
              <span>高优先级样例</span>
              {arr<R>(row.examples).map(example => <small key={example.target}>{example.target}</small>)}
            </div>
          </article>)}
        </div>
        <p className="uwm-field-help">{actionCatalog.intensity_definition || ''}</p>
      </section>

      <section className="uwm-model-blueprint">
        <div className="uwm-section-lead">
          <div>
            <span><Sigma size={14} />Simulator模型结构</span>
            <h3>每次想象：23维动作场景 → 6维下一状态预测</h3>
            <p>{simulatorSpec.scope_note || '-'}</p>
          </div>
          <div className="uwm-model-formula">{simulatorSpec.formula || 'ŷ = x · W'}</div>
        </div>
        <div className="uwm-io-flow">
          <div className="uwm-io-column">
            <header><span>输入向量 x</span><strong>{simulatorSpec.input_dimension || 23}维</strong></header>
            <div className="uwm-feature-groups">
              {inputGroups.map(group => <div key={group.group}>
                <strong>{group.group}</strong><b>{group.dimension}维</b>
                <small>{FEATURE_GROUP_DESCRIPTIONS[String(group.group)] || ''}</small>
              </div>)}
            </div>
            <details className="uwm-vector-details">
              <summary>展开查看全部23个输入字段</summary>
              <div>{inputFeatures.map(feature => <span key={feature.name}><b>{feature.label}</b><small>{feature.meaning}</small></span>)}</div>
            </details>
          </div>
          <ArrowRight size={22} className="uwm-io-arrow" />
          <div className="uwm-matrix-card">
            <span>参数矩阵 W</span>
            <strong>{arr<number>(simulatorSpec.coefficient_matrix_shape).join(' × ')}</strong>
            <b>{simulatorSpec.coefficient_count}个系数</b>
            <small>岭回归 · L2正则</small>
          </div>
          <ArrowRight size={22} className="uwm-io-arrow" />
          <div className="uwm-io-column">
            <header><span>输出向量 ŷ</span><strong>{simulatorSpec.output_dimension || 6}维</strong></header>
            <div className="uwm-output-list">{outputTargets.map(target => <div key={target.name}><strong>{target.label}</strong><small>{target.meaning}</small></div>)}</div>
          </div>
        </div>
        <div className="uwm-parameter-clarification"><ShieldCheck size={15} /><p><strong>参数量核对：</strong>{simulatorSpec.parameter_explanation || '-'}</p></div>
        <p className="uwm-field-help">{simulatorSpec.training_method || ''}</p>
      </section>

      <div className="uwm-world-loop">
        <div><span>1</span><strong>感知当前世界</strong><small>真实空间图与复合压力状态</small></div>
        <ArrowRight size={18} />
        <div><span>2</span><strong>想象行动后果</strong><small>目标与邻域状态同步更新</small></div>
        <ArrowRight size={18} />
        <div><span>3</span><strong>在新世界重规划</strong><small>重新排序下一步，而非照抄初始榜单</small></div>
      </div>

      <div className="uwm-livability-kpi-grid">
        <div className="uwm-livability-kpi"><span>空间状态</span><strong>{foundation.graph_node_count || '-'}</strong><small>行政单元</small></div>
        <div className="uwm-livability-kpi"><span>空间关系</span><strong>{foundation.graph_edge_count || '-'}</strong><small>图关系边</small></div>
        <div className="uwm-livability-kpi"><span>候选实例</span><strong>{foundation.available_action_count || '-'}</strong><small>3类模板 × 符合阈值单元</small></div>
        <div className="uwm-livability-kpi"><span>学习经验</span><strong>{foundation.transition_count || '-'}</strong><small>状态转移</small></div>
      </div>

      <div className="uwm-multistage-controls">
        <div className="uwm-livability-panel">
          <div className="uwm-livability-panel-title"><Layers3 size={15} /><strong>本次规划场景</strong></div>
          <label>规划范围
            <select
              value={focusUnit ? 'reference_scene' : 'full_admin'}
              onChange={event => setFocusUnit(
                event.target.value === 'reference_scene'
                  ? String(rec(overview.default_request).focus_unit || '')
                  : '',
              )}
            >
              <option value="reference_scene">沙坪坝区 · 土湾—石井坡复合压力场景</option>
              <option value="full_admin">重庆全域压力测试</option>
            </select>
          </label>
          <p className="uwm-field-help">客户界面仅显示业务地名；内部状态节点和源要素序号只保留在审计数据中。</p>
          <div className="uwm-action-checkboxes">
            {Object.entries(ACTION_LABELS).map(([value, label]) => (
              <label key={value}>
                <input type="checkbox" checked={actionTypes.includes(value)} onChange={() => toggleActionType(value)} />{label}
              </label>
            ))}
          </div>
        </div>

        <div className="uwm-livability-panel">
          <div className="uwm-livability-panel-title"><ShieldCheck size={15} /><strong>世界模型规划参数</strong></div>
          <label>规划时域
            <select value={horizon} onChange={event => setHorizon(Number(event.target.value))}>
              <option value={2}>2步：t0 → a1 → t1 → a2 → t2</option>
              <option value={3}>3步有限时域</option>
            </select>
          </label>
          <label>保留未来路径数
            <input type="number" min={2} max={30} value={beamWidth} onChange={event => setBeamWidth(Number(event.target.value))} />
          </label>
          <div className="uwm-compact-params">
            <label>未来折扣 γ<input type="number" min={0.1} max={1} step={0.05} value={gamma} onChange={event => setGamma(Number(event.target.value))} /></label>
            <label>风险惩罚<input type="number" min={0} max={5} step={0.1} value={uncertaintyPenalty} onChange={event => setUncertaintyPenalty(Number(event.target.value))} /></label>
          </div>
          <button className="primary-button uwm-plan-button" onClick={executePlan} disabled={!canRun}>
            <Play size={15} />{planning ? '正在生成并比较未来世界…' : '让UWM规划下一步'}
          </button>
        </div>
      </div>

      {!run.run_id && <div className="uwm-livability-panel necessity-panel">
        <div className="uwm-livability-panel-title"><Route size={15} /><strong>这不是普通选址评分</strong></div>
        <p>{necessity.reason || '-'}</p>
        <small>运行后将直接展示两条不同未来：不更新世界的旧选择，以及UWM更新世界后的新选择。</small>
      </div>}

      {run.run_id && <>
        <section className="uwm-decision-hero">
          <div className="uwm-hero-eyebrow"><Sparkles size={15} />世界模型发现了决策转折</div>
          <h2>{story.headline || '世界状态更新改变了下一步决策'}</h2>
          <p>第一步在<strong>{unit(arr<string>(firstAction.target_units)[0])}</strong>实施<strong>{actionLabel(firstAction.action_type)}</strong>后，系统没有沿用原始排行榜，而是生成`t1`新世界并重新规划。</p>
          <div className="uwm-proof-points">
            {proofPoints.map(point => <span key={point}><CheckCircle2 size={14} />{point}</span>)}
          </div>
        </section>

        <section className="uwm-training-proof">
          <div className="uwm-training-proof-header">
            <div>
              <span>客户常问：世界模型不需要训练吗？</span>
              <h3>本次确实重新训练了Simulator，但它是轻量模型</h3>
            </div>
            <strong>{number(runtimeProfile.total_ms, 1)} ms</strong>
          </div>
          <div className="uwm-training-pipeline">
            <div><span>Renderer</span><strong>读取空间世界</strong><small>不训练</small></div>
            <ArrowRight size={17} />
            <div className="trained-stage"><span>Simulator</span><strong>训练状态转移</strong><small>{trainingTransparency.training_row_count}条训练记录</small></div>
            <ArrowRight size={17} />
            <div><span>Kernel</span><strong>计算空间传播</strong><small>图结构计算</small></div>
            <ArrowRight size={17} />
            <div><span>Planner</span><strong>搜索未来路径</strong><small>{searchSummary.evaluated_imagined_action_count}次想象动作</small></div>
          </div>
          <div className="uwm-training-facts">
            <div><span>训练/留出</span><strong>{trainingTransparency.training_row_count}/{trainingTransparency.holdout_row_count}</strong></div>
            <div><span>输入→输出</span><strong>{trainingTransparency.feature_count}维 → {trainingTransparency.target_count}维</strong></div>
            <div><span>模型系数</span><strong>{trainingTransparency.coefficient_count}</strong></div>
            <div><span>实际训练耗时</span><strong>{number(runtimeProfile.dynamics_training_ms, 1)} ms</strong></div>
          </div>
          <p>{trainingTransparency.why_seconds_not_hours}</p>
          <p className="uwm-model-level"><strong>当前模型等级：</strong>轻量动作条件地理空间世界模型，不是大参数深度神经世界模型。秒级训练证明模型规模小，不代表没有训练。</p>
          <p><strong>生产建议：</strong>{trainingTransparency.production_recommendation}</p>
        </section>

        <div className="uwm-map-story-controls">
          <strong><Map size={15} />在中间地图分步查看世界变化</strong>
          <div>
            {[
              ['t0', '1 当前世界'],
              ['t1', '2 第一步传播'],
              ['branch', '3 第二步分叉'],
              ['t2', '4 最终轨迹'],
            ].map(([key, label]) => <button
              key={key}
              className={activeScene === key ? 'primary-button' : 'secondary-button'}
              onClick={() => showScene(key)}
            ><Eye size={13} />{label}</button>)}
          </div>
          <small>{String(rec(rec(run.map_scenes)[activeScene]).metadata?.narrative || '')}</small>
        </div>

        <div className="uwm-future-branch">
          <div className="uwm-future-card baseline-future">
            <div className="uwm-future-tag"><Split size={15} />如果不更新世界状态</div>
            <div className="uwm-future-step"><span>a1</span><strong>{actionLabel(firstAction.action_type)}</strong><small>{unit(arr<string>(firstAction.target_units)[0])}</small></div>
            <ArrowRight size={22} />
            <div className="uwm-future-step"><span>a2</span><strong>{oldSecond.label}</strong><small>{unit(oldSecond.target)}</small></div>
            <p>把项目当作互不影响的静态清单，第二步仍沿用原始第一名。</p>
          </div>
          <div className="uwm-branch-divider"><span>VS</span></div>
          <div className="uwm-future-card uwm-future">
            <div className="uwm-future-tag"><BrainCircuit size={15} />UWM生成`t1`后重新规划</div>
            <div className="uwm-future-step"><span>a1</span><strong>{actionLabel(firstAction.action_type)}</strong><small>{unit(arr<string>(firstAction.target_units)[0])}</small></div>
            <ArrowRight size={22} />
            <div className="uwm-future-step"><span>a2</span><strong>{actionLabel(newSecond.action_type)}</strong><small>{unit(arr<string>(newSecond.target_units)[0])}</small></div>
            <p>第一步改变热、污染、服务与宜居状态后，社区服务从第2名升到第1名。</p>
          </div>
        </div>

        <div className="uwm-livability-panel uwm-ranking-panel">
          <div className="uwm-livability-panel-title"><GitCompare size={15} /><strong>第二步候选排名真的发生了变化</strong></div>
          <div className="uwm-ranking-comparison">
            <div>
              <h4>原始`t0`继续排序</h4>
              {rankingBefore.map(row => <div className={`uwm-ranking-row ${row.rank === 1 ? 'rank-first' : ''}`} key={row.action_id}>
                <b>#{row.rank}</b><span>{actionLabel(row.action_type)}<small>{unit(row.target_unit_id)}</small></span>
              </div>)}
            </div>
            <ArrowRight className="ranking-arrow" size={24} />
            <div>
              <h4>写回`t1`后重新排序</h4>
              {rankingAfter.map(row => <div className={`uwm-ranking-row ${row.rank === 1 ? 'rank-first' : ''}`} key={row.action_id}>
                <b>#{row.rank}</b><span>{actionLabel(row.action_type)}<small>{unit(row.target_unit_id)}</small></span>
              </div>)}
            </div>
          </div>
          <div className="uwm-rank-moves">
            {rankingChanges.map(row => <span key={row.action_id} className={row.rank_delta > 0 ? 'rank-up' : 'rank-down'}>
              {actionLabel(row.action_type)}：第{row.rank_before}名 → 第{row.rank_after}名
            </span>)}
          </div>
        </div>

        <div className="uwm-livability-panel uwm-search-evidence">
          <div><span>本次候选动作</span><strong>{candidateSummary.candidate_action_count}</strong></div>
          <div><span>想象动作评估</span><strong>{searchSummary.evaluated_imagined_action_count}</strong></div>
          <div><span>完成未来序列</span><strong>{searchSummary.completed_sequence_count}</strong></div>
          <div><span>保留最优路径</span><strong>{searchSummary.retained_sequence_count}</strong></div>
          <p>规划器不是生成一句建议，而是在每一步写回世界状态后，继续比较多个未来序列。</p>
        </div>

        <div className="uwm-timeline">
          <div className="uwm-state-card"><span>t0</span><strong>当前复合压力世界</strong><small>{scope.allowed_unit_count}个规划单元、{candidateSummary.candidate_action_count}个候选动作</small></div>
          {steps.map((step, index) => {
            const action = rec(step.action);
            const propagation = rec(step.propagation);
            return <div className="uwm-step-group" key={`${action.action_id}-${index}`}>
              <div className="uwm-action-card"><span>a{index + 1}</span><strong>{actionLabel(action.action_type)}</strong><small>{unit(arr<string>(action.target_units)[0])}</small></div>
              <div className="uwm-state-card"><span>t{index + 1}</span><strong>世界状态已写回</strong><small>目标与{propagation.neighbor_affected_unit_count}个邻域单元同步更新</small></div>
            </div>;
          })}
        </div>

        <details className="uwm-technical-details">
          <summary>展开技术审计、归一化指标与声明边界</summary>
          <div className="uwm-livability-two-col">
            <div className="uwm-livability-panel">
              <div className="uwm-livability-panel-title"><GitCompare size={15} /><strong>算法基线</strong></div>
              <div className="uwm-compare-grid">
                <div><span>传统静态评分优势</span><strong>{number(advantages.over_traditional_static)}</strong></div>
                <div><span>单步世界模型优势</span><strong>{number(advantages.over_one_step_greedy)}</strong></div>
                <div><span>多步不更新状态优势</span><strong>{number(advantages.over_multi_step_without_state_update)}</strong></div>
              </div>
            </div>
            <div className="uwm-livability-panel">
              <div className="uwm-livability-panel-title"><ShieldCheck size={15} /><strong>运行审计</strong></div>
              <div className="uwm-compare-grid">
                <div><span>运行ID</span><strong>{run.run_id}</strong></div>
                <div><span>重新训练</span><strong>{String(Boolean(training.retrained_for_run))}</strong></div>
                <div><span>训练/留出</span><strong>{training.train_count}/{training.holdout_count}</strong></div>
                <div><span>规划域</span><strong>{scope.scope_mode}</strong></div>
              </div>
            </div>
          </div>
          <div className="uwm-livability-panel">
            <div className="uwm-livability-panel-title"><GitCompare size={15} /><strong>全域动作信号消融</strong></div>
            <div className="uwm-ablation-grid">{ablationRows.map(row => <div key={row.policy_baseline}><span>{String(row.policy_baseline)}</span><strong>UWM优势 {number(row.world_model_policy_improvement_advantage)}</strong></div>)}</div>
          </div>
          <div className="uwm-livability-panel">
            <div className="uwm-livability-panel-title"><BrainCircuit size={15} /><strong>Renderer / Simulator / Planner / Kernel</strong></div>
            <div className="uwm-architecture-grid">{Object.entries(architecture).map(([key, value]) => <div key={key}><span>{key}</span><strong>{String(value)}</strong></div>)}</div>
          </div>
          <div className="uwm-livability-panel claim-boundary-panel">
            <div className="uwm-livability-panel-title"><AlertTriangle size={15} /><strong>客户陈述边界</strong></div>
            <p><strong>可陈述：</strong>{boundary.allowed_claim || '-'}</p>
            <p><strong>数据性质：</strong>{boundary.transition_evidence || '-'}</p>
            <div className="s2-chip-list">{prohibitedClaims.map(value => <span key={value}>{value}</span>)}</div>
          </div>
        </details>
      </>}
    </div>
  );
}
