import { useCallback, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Database,
  ExternalLink,
  FlaskConical,
  Gauge,
  GitCompareArrows,
  Layers3,
  Map,
  Maximize2,
  Minimize2,
  Network,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Workflow,
  XCircle,
} from 'lucide-react';

type TwmDestination = 'overview' | 'operate' | 'data';
type TwmMapStage = 'locate' | 'risk' | 'plan';
type Row = Record<string, any>;

interface TwmExecutiveDemoPanelProps {
  onNavigate: (destination: TwmDestination) => void;
  onMapStage: (stage: TwmMapStage) => void;
}

const rows = <T = Row,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];

const signed = (value: unknown, digits = 3) => {
  const number = Number(value || 0);
  return `${number > 0 ? '+' : ''}${number.toFixed(digits)}`;
};

const compactNumber = (value: unknown) => new Intl.NumberFormat('zh-CN').format(Number(value || 0));

const statusLabel = (value: unknown) => {
  const status = String(value || 'review');
  if (status === 'verified_offline_run') return '已验证';
  if (status === 'engineering_ready') return '工程可用';
  if (status === 'compiled_not_admitted') return '已编译 / 未准入';
  if (status === 'not_admitted') return '诊断完成 / 未准入';
  return '待复核';
};

const statusTone = (value: unknown) => {
  const status = String(value || 'review');
  if (status === 'verified_offline_run') return 'verified';
  if (status === 'engineering_ready') return 'ready';
  if (status === 'compiled_not_admitted' || status === 'not_admitted') return 'blocked';
  return 'review';
};

export default function TwmExecutiveDemoPanel({ onNavigate, onMapStage }: TwmExecutiveDemoPanelProps) {
  const [report, setReport] = useState<Row | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [presentationMode, setPresentationMode] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/twm/executive-demo-report', { credentials: 'include' });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || '汇报证据接口不可用');
      setReport(payload);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : '汇报证据接口不可用');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPresentationMode(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const positioning = report?.positioning || {};
  const gwmDefinition = report?.gwm_definition || {};
  const simulator = report?.simulator || {};
  const architecture = report?.architecture || {};
  const paper9 = report?.paper9v2 || {};
  const foundation = report?.twm_foundation || {};
  const eventCompilation = report?.natural_resource_event_compilation || {};
  const benchmark = report?.gwm_benchmark || {};
  const claimBoundary = report?.claim_boundary || {};
  const geososComparison = report?.geosos_flus_comparison || {};
  const generatedAt = useMemo(() => {
    if (!report?.generated_at) return '-';
    const value = new Date(report.generated_at);
    return Number.isNaN(value.getTime()) ? '-' : value.toLocaleString('zh-CN', { hour12: false });
  }, [report?.generated_at]);

  const openMapStory = () => {
    onNavigate('overview');
    onMapStage('locate');
  };

  if (loading && !report) {
    return <div className="twm-briefing-loading" aria-live="polite"><RefreshCw size={17} className="spin" />正在核验演示证据...</div>;
  }

  const content = (
    <div className={`twm-briefing ${presentationMode ? 'presentation' : ''}`} data-testid="twm-executive-demo">
      <section className="twm-briefing-verdict">
        <div className="twm-briefing-verdict-icon"><ShieldCheck size={22} /></div>
        <div>
          <span className="twm-briefing-eyebrow">现场演示证据状态</span>
          <h3>{positioning.verdict || '演示证据待核验'}</h3>
          <p>{positioning.title || 'TWM 汇报演示'}</p>
        </div>
        <div className="twm-briefing-verdict-meta">
          <span className="twm-briefing-status controlled">受控演示</span>
          <span className="twm-briefing-status production-blocked">生产主张未开放</span>
          <small>证据刷新：{generatedAt}</small>
          <button type="button" className="twm-briefing-icon-button" onClick={load} disabled={loading} title="重新核验汇报证据">
            <RefreshCw size={14} className={loading ? 'spin' : ''} />
          </button>
          <button
            type="button"
            className="twm-briefing-icon-button"
            onClick={() => setPresentationMode(value => !value)}
            title={presentationMode ? '退出全宽演示' : '进入全宽演示'}
            aria-label={presentationMode ? '退出全宽演示' : '进入全宽演示'}
          >
            {presentationMode ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        </div>
      </section>

      {error && <div className="twm-briefing-message error"><AlertTriangle size={16} />{error}</div>}

      <section className="twm-briefing-section twm-briefing-opening">
        <div className="twm-briefing-section-head">
          <Workflow size={17} />
          <div><h4>从一张图走向可推演的治理闭环</h4><p>系统不是替代法定决策，而是把数据、规则、行动、方案和证据放进同一个可计算过程。</p></div>
        </div>
        <div className="twm-briefing-story" aria-label="TWM 决策闭环">
          {rows(report?.decision_story).map((item, index, items) => (
            <div className="twm-briefing-story-step" key={item.id}>
              <span>{index + 1}</span>
              <strong>{item.label}</strong>
              <small>{item.detail}</small>
              {index < items.length - 1 && <ArrowRight size={15} aria-hidden="true" />}
            </div>
          ))}
        </div>
      </section>

      <section className="twm-briefing-section">
        <div className="twm-briefing-section-head">
          <Sparkles size={17} />
          <div><h4>GWM 在世界模型谱系中的位置</h4><p>独特价值不在生成更逼真的画面，而在空间状态、行动和治理约束的统一计算。</p></div>
        </div>
        <div className="twm-briefing-world-grid">
          {rows(report?.world_model_positioning).map(item => (
            <div key={item.family}>
              <strong>{item.family}</strong>
              <span>{item.focus}</span>
              <p>{item.gwm_difference}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="twm-briefing-section" data-testid="twm-gwm-definition">
        <div className="twm-briefing-section-head">
          <Network size={17} />
          <div><h4>地理空间世界模型的正式定义</h4><p>{gwmDefinition.formal_definition}</p></div>
        </div>
        <p className="twm-briefing-boundary"><ShieldAlert size={14} />{gwmDefinition.not_coordinate_appendage}</p>
        <div className="twm-briefing-world-grid">
          {rows(gwmDefinition.fusion_dimensions).map(item => (
            <div key={item.dimension}>
              <strong>{item.dimension}</strong>
              <span>{item.geospatial_capability}</span>
              <p>{item.runtime_effect}</p>
            </div>
          ))}
        </div>
        <p className="twm-briefing-boundary"><CheckCircle2 size={14} />{gwmDefinition.distinctive_value}</p>
      </section>

      <section className="twm-briefing-section" data-testid="twm-simulator-mechanism">
        <div className="twm-briefing-section-head">
          <Workflow size={17} />
          <div><h4>GWM Simulator 如何实现推演</h4><p>{simulator.definition}</p></div>
          <code>{simulator.transition_equation}</code>
        </div>
        <div className="twm-briefing-story" aria-label="GWM Simulator 组合转移与状态写回">
          {rows(simulator.pipeline).map((item, index, items) => (
            <div className="twm-briefing-story-step" key={item.id}>
              <span>{index + 1}</span>
              <strong>{item.label}</strong>
              <small>{item.detail}</small>
              {index < items.length - 1 && <ArrowRight size={15} aria-hidden="true" />}
            </div>
          ))}
        </div>
        <div className="twm-briefing-case-table-wrap">
          <table className="twm-briefing-table comparison">
            <thead><tr><th>组合转移来源</th><th>适用变量</th><th>必须保留的 trace</th></tr></thead>
            <tbody>{rows(simulator.transition_sources).map(item => <tr key={item.source}><td><strong>{item.source}</strong></td><td>{item.use_for}</td><td>{item.trace}</td></tr>)}</tbody>
          </table>
        </div>
        <div className="twm-briefing-section-head">
          <GitCompareArrows size={17} />
          <div><h4>与其他 Simulator 的区别</h4><p>差别不在是否使用神经网络，而在模拟状态、行动语义、关系写回和验证责任。</p></div>
        </div>
        <div className="twm-briefing-case-table-wrap">
          <table className="twm-briefing-table comparison">
            <thead><tr><th>Simulator</th><th>状态</th><th>行动</th><th>输出</th><th>相对 GWM 的边界</th></tr></thead>
            <tbody>{rows(simulator.comparison).map(item => <tr key={item.family}><td><strong>{item.family}</strong></td><td>{item.state}</td><td>{item.action}</td><td>{item.output}</td><td>{item.gwm_difference}</td></tr>)}</tbody>
          </table>
        </div>
        <p className="twm-briefing-boundary"><ShieldAlert size={14} />{simulator.claim_boundary}</p>
      </section>

      <section className="twm-briefing-section">
        <div className="twm-briefing-section-head">
          <Network size={17} />
          <div><h4>GWM 技术架构与 TWM 领域实例</h4><p>算法内核负责学习空间动力学，运行内核负责让推演在规则、证据和审计约束下工作。</p></div>
        </div>
        <div className="twm-briefing-architecture">
          <div className="twm-briefing-architecture-lane kernel">
            <span>Geospatial Kernel</span>
            <strong>DAM-GK</strong>
            <p>{architecture.dam_definition}</p>
            <div>{rows<string>(architecture.geospatial_kernel).map(item => <small key={item}>{item}</small>)}</div>
          </div>
          <ArrowRight size={22} className="twm-briefing-architecture-arrow" />
          <div className="twm-briefing-architecture-lane runtime">
            <span>GWM Runtime Kernel</span>
            <strong>状态 · 推演 · 规划 · 评价</strong>
            <p>{architecture.boundary}</p>
            <div>{rows<string>(architecture.runtime_kernel).map(item => <small key={item}>{item}</small>)}</div>
          </div>
          <ArrowRight size={22} className="twm-briefing-architecture-arrow" />
          <div className="twm-briefing-architecture-lane domain">
            <span>自然资源领域实例</span>
            <strong>TWM</strong>
            <p>{positioning.gwm_twm_relationship}</p>
            <div>{rows<string>(foundation.supported_chain).map(item => <small key={item}>{item}</small>)}</div>
          </div>
        </div>
      </section>

      <section className="twm-briefing-section" data-testid="twm-paper9-evidence">
        <div className="twm-briefing-section-head">
          <Gauge size={17} />
          <div><h4>耕地空间布局优化：从静态评分到多步方案搜索</h4><p>部级离线环境适配的双县全流程结果，三项硬门槛均通过；这不是生产验收结论。</p></div>
          <div className="twm-briefing-source-status">
            <span className={`twm-briefing-status ${statusTone(paper9.status)}`}>{statusLabel(paper9.status)}</span>
            <small>{paper9.source_mode === 'live_offline_artifacts' ? '离线产物实时核验' : `${paper9.source_date || '2026-06-27'} 验证快照`}</small>
          </div>
        </div>
        <div className="twm-briefing-paper9-layout">
          <div className="twm-briefing-problem">
            <strong>为什么常规方法不够</strong>
            <p>{paper9.question}</p>
            <ul>{rows<string>(paper9.why_conventional_methods_are_insufficient).map(item => <li key={item}>{item}</li>)}</ul>
            <div className="twm-briefing-gates">
              {rows(paper9.hard_gates).map(gate => <span className={gate.passed ? 'pass' : 'fail'} key={gate.id}>{gate.passed ? <CheckCircle2 size={14} /> : <XCircle size={14} />}{gate.label}</span>)}
            </div>
          </div>
          <div className="twm-briefing-case-table-wrap">
            <table className="twm-briefing-table">
              <thead><tr><th>离线案例</th><th>耕地面积</th><th>坡度</th><th>连片度</th><th>置换</th></tr></thead>
              <tbody>{rows(paper9.cases).map(item => (
                <tr key={item.id}>
                  <td><strong>{item.label}</strong><small>{item.hard_constraint_passed ? '硬约束通过' : '待复核'}</small></td>
                  <td className="positive">{signed(item.cultivated_area_change_ha)} ha</td>
                  <td className="positive">{signed(item.slope_change_pct)}%</td>
                  <td className="positive">{signed(item.contiguity_change, 4)}</td>
                  <td>{compactNumber(item.swaps_completed)} 次</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </div>
        <p className="twm-briefing-boundary"><ShieldAlert size={14} />{paper9.claim_boundary}</p>
      </section>

      <section className="twm-briefing-section">
        <div className="twm-briefing-section-head">
          <GitCompareArrows size={17} />
          <div><h4>为什么要与 GeoSOS-FLUS 对标</h4><p>{geososComparison.benchmark_role}</p></div>
        </div>
        <div className="twm-briefing-case-table-wrap">
          <table className="twm-briefing-table comparison">
            <thead><tr><th>比较维度</th><th>GeoSOS-FLUS</th><th>TWM / GWM</th></tr></thead>
            <tbody>{rows(geososComparison.dimensions).map(item => <tr key={item.dimension}><td><strong>{item.dimension}</strong></td><td>{item.geosos_flus}</td><td>{item.twm}</td></tr>)}</tbody>
          </table>
        </div>
        <p className="twm-briefing-boundary"><ShieldAlert size={14} />{geososComparison.verdict}</p>
      </section>

      <section className="twm-briefing-section" data-testid="twm-foundation-evidence">
        <div className="twm-briefing-section-head">
          <Database size={17} />
          <div><h4>TWM 当前数据基础</h4><p>工程链路有足够规模做受控演示，但真实业务时序仍是明确缺口。</p></div>
          <span className={`twm-briefing-status ${statusTone(foundation.status)}`}>{statusLabel(foundation.status)}</span>
        </div>
        <div className="twm-briefing-kpis">
          <div><span>受控数据记录</span><strong>{compactNumber(foundation.record_count)}</strong><small>{foundation.dataset_id}</small></div>
          <div><span>空间要素</span><strong>{compactNumber(foundation.spatial_feature_count)}</strong><small>对象与管控关系底板</small></div>
          <div><span>合成时序实验</span><strong>{compactNumber(foundation.synthetic_experiment?.row_count)}</strong><small>{foundation.synthetic_experiment?.pair_count || 0} 对 / {foundation.synthetic_experiment?.region_count || 0} 区域</small></div>
          <div className="blocked"><span>生产观测历史</span><strong>{compactNumber(foundation.production_observed_history_rows)}</strong><small>必须由省级试点补齐</small></div>
          <div className="blocked"><span>生产政策动作历史</span><strong>{compactNumber(foundation.production_policy_history_rows)}</strong><small>Action 条件校准阻断项</small></div>
        </div>
        <p className="twm-briefing-boundary"><ShieldAlert size={14} />{foundation.claim_boundary}</p>
      </section>

      <section className="twm-briefing-section" data-testid="twm-event-compilation">
        <div className="twm-briefing-section-head">
          <Layers3 size={17} />
          <div><h4>真实自然资源事件如何进入 Geospatial Kernel</h4><p>上海供地事件链展示“官方事件到训练候选”的数据编译，不展示政策效果数字。</p></div>
          <span className={`twm-briefing-status ${statusTone(eventCompilation.status)}`}>{statusLabel(eventCompilation.status)}</span>
        </div>
        <div className="twm-briefing-event-chain">
          {rows(eventCompilation.pipeline).map((item, index, items) => <div key={item.id}><span>{item.label}</span><strong>{compactNumber(item.count)}</strong>{index < items.length - 1 && <ArrowRight size={15} />}</div>)}
        </div>
        <div className="twm-briefing-gate-strip">
          <span className={eventCompilation.spatial_sampling_ready ? 'pass' : 'fail'}>{eventCompilation.spatial_sampling_ready ? <CheckCircle2 size={14} /> : <XCircle size={14} />}空间采样协议</span>
          <span className={eventCompilation.comparison_candidate_ready ? 'pass' : 'fail'}>{eventCompilation.comparison_candidate_ready ? <CheckCircle2 size={14} /> : <XCircle size={14} />}对照候选构建</span>
          <span className={eventCompilation.comparison_design_complete ? 'pass' : 'fail'}>{eventCompilation.comparison_design_complete ? <CheckCircle2 size={14} /> : <XCircle size={14} />}对照设计完成</span>
          <span className={eventCompilation.training_admission ? 'pass' : 'fail'}>{eventCompilation.training_admission ? <CheckCircle2 size={14} /> : <XCircle size={14} />}训练准入</span>
        </div>
        <p className="twm-briefing-boundary"><ShieldAlert size={14} />{eventCompilation.claim_boundary}</p>
      </section>

      <section className="twm-briefing-section" data-testid="twm-benchmark-evidence">
        <div className="twm-briefing-section-head">
          <FlaskConical size={17} />
          <div><h4>GWM-Bench：允许基准否定 Kernel</h4><p>真正可信的系统必须主动展示失败门禁，而不是只展示最好的一次运行。</p></div>
          <span className={`twm-briefing-status ${statusTone(benchmark.status)}`}>{statusLabel(benchmark.status)}</span>
        </div>
        <div className="twm-briefing-benchmark-layout">
          <div className="twm-briefing-benchmark-matrix">
            {rows(benchmark.matrix).map(item => <div key={item.id} className={item.passed ? 'pass' : 'fail'}><span>{item.direction}</span><strong>{item.label}</strong><em>{item.pass_count}/{item.seed_count}</em></div>)}
          </div>
          <div className="twm-briefing-v03">
            <span>v0.3 数据准入快照</span>
            <strong>{benchmark.candidate_v03?.status === 'synchronized_snapshot_incomplete' ? '同步快照尚不完整' : benchmark.candidate_v03?.status || '待核验'}</strong>
            <dl>
              <div><dt>已编译对象</dt><dd>{compactNumber(benchmark.candidate_v03?.compiled_object_count)}</dd></div>
              <div><dt>Forcing 证书</dt><dd className="fail">{benchmark.candidate_v03?.forcing_certificate || '-'}</dd></div>
              <div><dt>Topology 证书</dt><dd className="fail">{benchmark.candidate_v03?.topology_certificate || '-'}</dd></div>
              <div><dt>训练输入准入</dt><dd className="fail">{benchmark.candidate_v03?.training_input_admitted ? '通过' : '未通过'}</dd></div>
            </dl>
          </div>
        </div>
        <p className="twm-briefing-boundary"><ShieldAlert size={14} />{benchmark.claim_boundary}</p>
      </section>

      <section className="twm-briefing-section">
        <div className="twm-briefing-section-head">
          <ShieldCheck size={17} />
          <div><h4>当前主张边界</h4><p>现场演示以“能证明什么、不能证明什么”作为结论，不把研究路线图当成已交付能力。</p></div>
        </div>
        <div className="twm-briefing-claim-grid">
          <div className="can"><strong><CheckCircle2 size={16} />当前可以演示</strong>{rows<string>(claimBoundary.can_demonstrate).map(item => <p key={item}>{item}</p>)}</div>
          <div className="cannot"><strong><XCircle size={16} />当前不能宣称</strong>{rows<string>(claimBoundary.cannot_claim).map(item => <p key={item}>{item}</p>)}</div>
        </div>
      </section>

      <section className="twm-briefing-section">
        <div className="twm-briefing-section-head">
          <Database size={17} />
          <div><h4>省级试点的最小数据闭环</h4><p>不是先要全省所有数据，而是先选一个真实业务闭环，补齐可验证的状态、动作和结果。</p></div>
        </div>
        <div className="twm-briefing-case-table-wrap">
          <table className="twm-briefing-table pilot">
            <thead><tr><th>优先级</th><th>数据</th><th>最小范围</th><th>解锁能力</th></tr></thead>
            <tbody>{rows(report?.pilot_data_requirements).map(item => <tr key={`${item.priority}-${item.data}`}><td><strong>{item.priority}</strong></td><td>{item.data}</td><td>{item.minimum}</td><td>{item.unlocks}</td></tr>)}</tbody>
          </table>
        </div>
      </section>

      <section className="twm-briefing-conclusion">
        <div><strong>下一代智能体平台 = LLM + World Model + Evidence Gate</strong><p>{positioning.llm_wm_relationship}</p></div>
        <div className="twm-briefing-actions">
          <button type="button" onClick={openMapStory}><Map size={15} />进入地图联动</button>
          <button type="button" onClick={() => onNavigate('operate')}><ExternalLink size={15} />进入操作推演</button>
          <button type="button" onClick={() => onNavigate('data')}><Database size={15} />查看数据依据</button>
        </div>
      </section>
    </div>
  );
  return presentationMode ? createPortal(content, document.body) : content;
}
