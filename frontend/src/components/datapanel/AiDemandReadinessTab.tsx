import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw, Route, ShieldAlert } from 'lucide-react';

type RequirementRow = {
  id: string;
  title: string;
  primary_route: string;
  required_method: string;
  implementation_level: string;
  data_support: string;
  route_availability: 'existing' | 'planned';
  implemented_outputs: string[];
  production_blockers: string[];
};

type RouteRow = {
  route: string;
  availability: 'existing' | 'planned';
};

type ReadinessPayload = {
  schema: "uwm.ai_demand_readiness_api.v2";
  source_documents: string[];
  livability_scenarios: RequirementRow[];
  customer_ai_demands: RequirementRow[];
  primary_routes: RouteRow[];
  summary: {
    registered_requirement_count: number;
    existing_route_count: number;
    planned_route_count: number;
    production_complete_count: number;
  };
  claim_boundary: {
    registration_is_not_implementation: boolean;
    observed_policy_outcome_superiority_claim: boolean;
  };
};

const ROUTE_LABELS: Record<string, string> = {
  traditional_livability: '城市宜居性（传统方法）',
  uwm_livability: '城市宜居性（UWM）',
  planning_land: '城市规划与土地',
  infrastructure_assets: '基础设施与资产',
  population_demand: '人口与需求',
  economy_investment: '经济与投资',
  impact_implementation: '影响与实施决策',
};

const cellStyle = { verticalAlign: 'top' as const, whiteSpace: 'normal' as const };
const routeListStyle = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
  gap: 10,
  listStyle: 'none',
  margin: 0,
  padding: 0,
};
const routeCardStyle = {
  display: 'flex',
  gap: 8,
  alignItems: 'flex-start',
  padding: 10,
  border: '1px solid var(--border-color, #d1d5db)',
  borderRadius: 8,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(item => typeof item === 'string');
}

function isAvailability(value: unknown): value is 'existing' | 'planned' {
  return value === 'existing' || value === 'planned';
}

function isRequirementRow(value: unknown): value is RequirementRow {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === 'string'
    && typeof value.title === 'string'
    && typeof value.primary_route === 'string'
    && typeof value.required_method === 'string'
    && typeof value.implementation_level === 'string'
    && typeof value.data_support === 'string'
    && isAvailability(value.route_availability)
    && isStringArray(value.implemented_outputs)
    && isStringArray(value.production_blockers)
  );
}

function isRouteRow(value: unknown): value is RouteRow {
  return (
    isRecord(value)
    && typeof value.route === 'string'
    && isAvailability(value.availability)
  );
}

function isReadinessPayload(value: unknown): value is ReadinessPayload {
  if (!isRecord(value) || value.schema !== 'uwm.ai_demand_readiness_api.v2') return false;
  if (!isStringArray(value.source_documents)) return false;
  if (!Array.isArray(value.livability_scenarios)
    || !value.livability_scenarios.every(isRequirementRow)) return false;
  if (!Array.isArray(value.customer_ai_demands)
    || !value.customer_ai_demands.every(isRequirementRow)) return false;
  if (!Array.isArray(value.primary_routes) || !value.primary_routes.every(isRouteRow)) return false;
  if (!isRecord(value.summary)
    || typeof value.summary.registered_requirement_count !== 'number'
    || typeof value.summary.existing_route_count !== 'number'
    || typeof value.summary.planned_route_count !== 'number'
    || typeof value.summary.production_complete_count !== 'number') return false;
  return (
    isRecord(value.claim_boundary)
    && typeof value.claim_boundary.registration_is_not_implementation === 'boolean'
    && typeof value.claim_boundary.observed_policy_outcome_superiority_claim === 'boolean'
  );
}

async function parseReadinessResponse(response: Response): Promise<unknown> {
  const responseBody = await response.text();
  let data: unknown = null;
  if (responseBody) {
    try {
      data = JSON.parse(responseBody) as unknown;
    } catch {
      throw new Error(`HTTP ${response.status}: 响应不是有效 JSON`);
    }
  }
  if (!response.ok) {
    const serverMessage = isRecord(data) && typeof data.error === 'string'
      ? data.error
      : response.statusText || '请求失败';
    throw new Error(`HTTP ${response.status}: ${serverMessage}`);
  }
  return data;
}

function documentName(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

function listText(values: string[], emptyText: string): string {
  return values.length ? values.join('；') : emptyText;
}

function RequirementTable({ title, rows }: { title: string; rows: RequirementRow[] }) {
  return (
    <section className="uwm-livability-panel">
      <div className="uwm-livability-panel-title">{title}</div>
      <div className="uwm-priority-table-wrap">
        <table className="uwm-priority-table">
          <caption>{title}的技术归属、实施状态与生产阻塞项</caption>
          <thead>
            <tr>
              <th scope="col">ID / 需求</th>
              <th scope="col">主技术路线</th>
              <th scope="col">实施与数据状态</th>
              <th scope="col">已实现产出</th>
              <th scope="col">生产阻塞项</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr key={row.id}>
                <td style={cellStyle}>
                  <strong>{row.id} · {row.title}</strong>
                  <div>{row.required_method}</div>
                </td>
                <td style={cellStyle}>
                  <strong>{ROUTE_LABELS[row.primary_route] || row.primary_route}</strong>
                  <div>primary_route: {row.primary_route}</div>
                  <div>route_availability: {row.route_availability}</div>
                </td>
                <td style={cellStyle}>
                  <div>implementation_level: {row.implementation_level}</div>
                  <div>data_support: {row.data_support}</div>
                </td>
                <td style={cellStyle}>{listText(row.implemented_outputs, '尚无已验证产出')}</td>
                <td style={cellStyle}>{listText(row.production_blockers, '当前 registry 未登记 blocker')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function AiDemandReadinessTab() {
  const [payload, setPayload] = useState<ReadinessPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const requestIdRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  const loadReadiness = useCallback(async () => {
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/uwm/ai-demand-readiness', {
        credentials: 'include',
        signal: controller.signal,
      });
      const data = await parseReadinessResponse(response);
      if (requestId !== requestIdRef.current) return;
      if (!isReadinessPayload(data)) {
        throw new Error(`HTTP ${response.status}: 响应结构不符合 readiness contract`);
      }
      setPayload(data);
    } catch (loadError: unknown) {
      if (loadError instanceof Error && loadError.name === 'AbortError') return;
      if (requestId !== requestIdRef.current) return;
      setPayload(null);
      setError(loadError instanceof Error ? loadError.message : 'AI 应用需求矩阵加载失败');
    } finally {
      if (requestId === requestIdRef.current) {
        setLoading(false);
        if (abortControllerRef.current === controller) abortControllerRef.current = null;
      }
    }
  }, []);

  useEffect(() => {
    loadReadiness();
    return () => {
      requestIdRef.current += 1;
      abortControllerRef.current?.abort();
    };
  }, [loadReadiness]);

  const summary = payload?.summary;
  const claimBoundary = payload?.claim_boundary;

  return (
    <div className="uwm-livability-tab" aria-live="polite" aria-busy={loading}>
      <div className="datapanel-section-header">
        <div>
          <h3>AI应用需求矩阵</h3>
          <p>两份客户需求文档的唯一技术归属、实施状态、数据基础与生产阻塞项。</p>
        </div>
        <button className="secondary-button" onClick={loadReadiness} disabled={loading}>
          <RefreshCw size={14} /> {loading ? '加载中' : '刷新'}
        </button>
      </div>

      {error && <div role="alert" className="uwm-livability-message error">{error}</div>}

      {claimBoundary?.registration_is_not_implementation && (
        <div
          role="alert"
          style={{
            display: 'flex',
            gap: 10,
            alignItems: 'flex-start',
            padding: 12,
            marginBottom: 12,
            border: '1px solid #f59e0b',
            borderRadius: 8,
            background: 'rgba(245, 158, 11, 0.12)',
          }}
        >
          <AlertTriangle size={18} />
          <div>
            <strong>注册不等于实现。</strong>
            <div>
              本页只声明需求所有权与 readiness；observed_policy_outcome_superiority_claim =
              {' '}{String(claimBoundary.observed_policy_outcome_superiority_claim)}。
            </div>
          </div>
        </div>
      )}

      {payload && summary ? (
        <>
          <div className="uwm-livability-kpi-grid">
            <div className="uwm-livability-kpi">
              <span>宜居性专项</span>
              <strong>{payload.livability_scenarios.length} 个宜居性场景</strong>
            </div>
            <div className="uwm-livability-kpi">
              <span>客户应用</span>
              <strong>{payload.customer_ai_demands.length} 项客户需求</strong>
            </div>
            <div className="uwm-livability-kpi">
              <span>唯一归属</span>
              <strong>{payload.primary_routes.length} 条主技术路线</strong>
            </div>
            <div className="uwm-livability-kpi">
              <span>production_complete_count</span>
              <strong>{summary.production_complete_count}</strong>
            </div>
          </div>

          <section className="uwm-livability-panel">
            <div className="uwm-livability-panel-title"><Route size={16} /> 主技术路线</div>
            <ul className="ai-demand-route-list" style={routeListStyle}>
              {payload.primary_routes.map(routeRow => (
                <li className="ai-demand-route-card" style={routeCardStyle} key={routeRow.route}>
                  {routeRow.availability === 'existing'
                    ? <CheckCircle2 size={15} />
                    : <ShieldAlert size={15} />}
                  <div>
                    <strong>{ROUTE_LABELS[routeRow.route] || routeRow.route}</strong>
                    <div>{routeRow.route} · {routeRow.availability}</div>
                  </div>
                </li>
              ))}
            </ul>
          </section>

          <section className="uwm-livability-panel">
            <div className="uwm-livability-panel-title">需求来源</div>
            <div className="uwm-capability-tags">
              {payload.source_documents.map(path => (
                <span key={path}>{documentName(path)}</span>
              ))}
            </div>
          </section>

          <RequirementTable
            title={`${payload.livability_scenarios.length} 个宜居性场景`}
            rows={payload.livability_scenarios}
          />
          <RequirementTable
            title={`${payload.customer_ai_demands.length} 项客户需求`}
            rows={payload.customer_ai_demands}
          />
        </>
      ) : !loading && !error ? (
        <div className="uwm-livability-empty">暂无 AI 应用需求 readiness 数据。</div>
      ) : null}
    </div>
  );
}
