import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CircleDot, RefreshCw, Route, ShieldAlert } from 'lucide-react';
import { formatNumber, getLocaleHeaders } from '../../i18n';

type EvidenceLevel = 'observed' | 'proxy' | 'simulated' | 'contract_only' | 'unsupported';
type UncertaintyLevel = 'low' | 'medium' | 'high' | 'not_assessed';
type MaxClaimLevel =
  | 'descriptive_observed'
  | 'proxy_diagnostic'
  | 'model_counterfactual'
  | 'requirement_registered'
  | 'unsupported';

type RequirementRow = {
  id: string;
  title: string;
  primary_route: string;
  required_method: string;
  implementation_level: string;
  data_support: string;
  evidence_level: EvidenceLevel;
  uncertainty: UncertaintyLevel;
  max_claim_level: MaxClaimLevel;
  route_availability: 'existing' | 'planned';
  implemented_outputs: string[];
  production_blockers: string[];
  implementation_status: 'production_verified' | 'implemented_evidence_bounded' | 'data_query_only' | 'contract_only' | 'not_implemented';
  status_basis: string;
  evidence_artifacts: string[];
  evidence_artifact_checks: { path: string; exists: boolean }[];
  max_supported_claim: string;
  next_actions: string[];
};

type RouteRow = {
  route: string;
  availability: 'existing' | 'planned';
};

type ReadinessPayload = {
  schema: "uwm.ai_demand_readiness_api.v2";
  source_documents: string[];
  source_provenance_server_side: true;
  livability_scenarios: RequirementRow[];
  customer_ai_demands: RequirementRow[];
  primary_routes: RouteRow[];
  summary: {
    registered_requirement_count: number;
    existing_route_count: number;
    planned_route_count: number;
    production_complete_count: number;
    implementation_status_counts: Record<RequirementRow['implementation_status'], number>;
    verified_or_bounded_count: number;
  };
  claim_boundary: {
    registration_is_not_implementation: boolean;
    observed_policy_outcome_superiority_claim: boolean;
    product_presence_is_not_full_requirement_completion: boolean;
  };
};

const ROUTE_LABELS: Record<string, string> = {
  traditional_livability: 'traditional_livability',
  uwm_livability: 'uwm_livability',
  planning_land: 'planning_land',
  infrastructure_assets: 'infrastructure_assets',
  population_demand: 'population_demand',
  economy_investment: 'economy_investment',
  impact_implementation: 'impact_implementation',
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

function isEvidenceLevel(value: unknown): value is EvidenceLevel {
  return ['observed', 'proxy', 'simulated', 'contract_only', 'unsupported'].includes(String(value));
}

function isUncertaintyLevel(value: unknown): value is UncertaintyLevel {
  return ['low', 'medium', 'high', 'not_assessed'].includes(String(value));
}

function isMaxClaimLevel(value: unknown): value is MaxClaimLevel {
  return [
    'descriptive_observed',
    'proxy_diagnostic',
    'model_counterfactual',
    'requirement_registered',
    'unsupported',
  ].includes(String(value));
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
    && isEvidenceLevel(value.evidence_level)
    && isUncertaintyLevel(value.uncertainty)
    && isMaxClaimLevel(value.max_claim_level)
    && isAvailability(value.route_availability)
    && isStringArray(value.implemented_outputs)
    && isStringArray(value.production_blockers)
    && ['production_verified', 'implemented_evidence_bounded', 'data_query_only', 'contract_only', 'not_implemented'].includes(String(value.implementation_status))
    && typeof value.status_basis === 'string'
    && isStringArray(value.evidence_artifacts)
    && Array.isArray(value.evidence_artifact_checks)
    && typeof value.max_supported_claim === 'string'
    && isStringArray(value.next_actions)
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
  if (value.source_provenance_server_side !== true) return false;
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
  if (!isRecord(value.summary.implementation_status_counts)
    || typeof value.summary.verified_or_bounded_count !== 'number') return false;
  return (
    isRecord(value.claim_boundary)
    && typeof value.claim_boundary.registration_is_not_implementation === 'boolean'
    && typeof value.claim_boundary.observed_policy_outcome_superiority_claim === 'boolean'
    && typeof value.claim_boundary.product_presence_is_not_full_requirement_completion === 'boolean'
  );
}

async function parseReadinessResponse(response: Response): Promise<unknown> {
  const responseBody = await response.text();
  let data: unknown = null;
  if (responseBody) {
    try {
      data = JSON.parse(responseBody) as unknown;
    } catch {
      throw new Error(`HTTP ${response.status}: Invalid JSON response`);
    }
  }
  if (!response.ok) {
    const serverMessage = isRecord(data) && typeof data.error === 'string'
      ? data.error
      : response.statusText || 'Request failed';
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
  const { t } = useTranslation();
  return (
    <section className="uwm-livability-panel">
      <div className="uwm-livability-panel-title">{title}</div>
      <div className="uwm-priority-table-wrap">
        <table className="uwm-priority-table">
          <caption>{t('aiDemandReadiness.table.caption', { title })}</caption>
          <thead>
            <tr>
              <th scope="col">{t('aiDemandReadiness.table.requirement')}</th>
              <th scope="col">{t('aiDemandReadiness.table.route')}</th>
              <th scope="col">{t('aiDemandReadiness.table.implementation')}</th>
              <th scope="col">{t('aiDemandReadiness.table.status')}</th>
              <th scope="col">{t('aiDemandReadiness.table.evidence')}</th>
              <th scope="col">{t('aiDemandReadiness.table.outputs')}</th>
              <th scope="col">{t('aiDemandReadiness.table.blockers')}</th>
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
                    <strong>{t(`aiDemandReadiness.routeLabels.${ROUTE_LABELS[row.primary_route] || row.primary_route}`, { defaultValue: row.primary_route })}</strong>
                  <div>primary_route: {row.primary_route}</div>
                  <div>{t('aiDemandReadiness.labels.routeAvailability')}: {row.route_availability}</div>
                </td>
                <td style={cellStyle}>
                  <div>{t('aiDemandReadiness.labels.implementationLevel')}: {row.implementation_level}</div>
                  <div>{t('aiDemandReadiness.labels.dataSupport')}: {row.data_support}</div>
                </td>
                <td style={cellStyle}>
                  <strong>{t(`statusLabels.${row.implementation_status}`, { defaultValue: row.implementation_status })}</strong>
                  <div>{t('aiDemandReadiness.labels.statusBasis')}: {row.status_basis}</div>
                </td>
                <td style={cellStyle}>
                  <div>{t('aiDemandReadiness.labels.evidenceLevel')}: {row.evidence_level}</div>
                  <div>{t('aiDemandReadiness.labels.uncertainty')}: {row.uncertainty}</div>
                  <div>{t('aiDemandReadiness.labels.maxClaimLevel')}: {row.max_claim_level}</div>
                  <div>{t('aiDemandReadiness.labels.maxSupportedClaim')}: {row.max_supported_claim}</div>
                  <div>{t('aiDemandReadiness.labels.evidenceArtifacts')}: {listText(row.evidence_artifacts, t('aiDemandReadiness.empty.noVerifiedArtifacts'))}</div>
                </td>
                <td style={cellStyle}>{listText(row.implemented_outputs, t('aiDemandReadiness.empty.noVerifiedOutputs'))}</td>
                <td style={cellStyle}>
                  <div>{listText(row.production_blockers, t('aiDemandReadiness.empty.noBlockers'))}</div>
                  <div>{t('aiDemandReadiness.labels.nextActions')}: {listText(row.next_actions, t('aiDemandReadiness.empty.none'))}</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function AiDemandReadinessTab() {
  const { t, i18n } = useTranslation();
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
        headers: getLocaleHeaders(),
        signal: controller.signal,
      });
      const data = await parseReadinessResponse(response);
      if (requestId !== requestIdRef.current) return;
      if (!isReadinessPayload(data)) {
        throw new Error(`HTTP ${response.status}: ${t('aiDemandReadiness.errors.invalidContract')}`);
      }
      setPayload(data);
    } catch (loadError: unknown) {
      if (loadError instanceof Error && loadError.name === 'AbortError') return;
      if (requestId !== requestIdRef.current) return;
      setPayload(null);
      setError(loadError instanceof Error ? loadError.message : t('aiDemandReadiness.errors.load'));
    } finally {
      if (requestId === requestIdRef.current) {
        setLoading(false);
        if (abortControllerRef.current === controller) abortControllerRef.current = null;
      }
    }
  }, [t, i18n.resolvedLanguage]);

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
          <h3>{t('aiDemandReadiness.title')}</h3>
          <p>{t('aiDemandReadiness.subtitle')}</p>
        </div>
        <button className="secondary-button" onClick={loadReadiness} disabled={loading}>
          <RefreshCw size={14} /> {loading ? t('aiDemandReadiness.actions.loading') : t('aiDemandReadiness.actions.refresh')}
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
            <strong>{t('aiDemandReadiness.claimBoundary.title')}</strong>
            <div>
              {t('aiDemandReadiness.claimBoundary.description')} observed_policy_outcome_superiority_claim =
              {' '}{String(claimBoundary.observed_policy_outcome_superiority_claim)}。
            </div>
          </div>
        </div>
      )}

      {payload && summary ? (
        <>
          <div className="uwm-livability-kpi-grid">
            <div className="uwm-livability-kpi">
              <span>{t('aiDemandReadiness.kpis.livability')}</span>
              <strong>{t('aiDemandReadiness.kpis.livabilityValue', { count: formatNumber(payload.livability_scenarios.length) })}</strong>
            </div>
            <div className="uwm-livability-kpi">
              <span>{t('aiDemandReadiness.kpis.customer')}</span>
              <strong>{t('aiDemandReadiness.kpis.customerValue', { count: formatNumber(payload.customer_ai_demands.length) })}</strong>
            </div>
            <div className="uwm-livability-kpi">
              <span>{t('aiDemandReadiness.kpis.routes')}</span>
              <strong>{t('aiDemandReadiness.kpis.routesValue', { count: formatNumber(payload.primary_routes.length) })}</strong>
            </div>
            <div className="uwm-livability-kpi">
              <span>{t('aiDemandReadiness.kpis.verified')}</span>
              <strong>{formatNumber(summary.verified_or_bounded_count)}</strong>
            </div>
          </div>

          <section className="uwm-livability-panel">
            <div className="uwm-livability-panel-title">{t('aiDemandReadiness.status.title')}</div>
            <div>production_verified：{formatNumber(summary.implementation_status_counts.production_verified)}</div>
            <div>implemented_evidence_bounded：{formatNumber(summary.implementation_status_counts.implemented_evidence_bounded)}</div>
            <div>data_query_only：{formatNumber(summary.implementation_status_counts.data_query_only)}</div>
            <div>contract_only：{formatNumber(summary.implementation_status_counts.contract_only)}</div>
            <div>not_implemented：{formatNumber(summary.implementation_status_counts.not_implemented)}</div>
          </section>

          <section className="uwm-livability-panel">
            <div className="uwm-livability-panel-title"><Route size={16} /> {t('aiDemandReadiness.routes.title')}</div>
            <ul className="ai-demand-route-list" style={routeListStyle}>
              {payload.primary_routes.map(routeRow => (
                <li className="ai-demand-route-card" style={routeCardStyle} key={routeRow.route}>
                  {routeRow.availability === 'existing'
                    ? <CircleDot size={15} />
                    : <ShieldAlert size={15} />}
                  <div>
                    <strong>{t(`aiDemandReadiness.routeLabels.${ROUTE_LABELS[routeRow.route] || routeRow.route}`, { defaultValue: routeRow.route })}</strong>
                    <div>
                      {routeRow.route} · {routeRow.availability === 'existing'
                        ? t('aiDemandReadiness.routes.existing')
                        : t('aiDemandReadiness.routes.planned')}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </section>

          <section className="uwm-livability-panel">
            <div className="uwm-livability-panel-title">{t('aiDemandReadiness.sources.title')}</div>
            <div className="uwm-capability-tags">
              {payload.source_documents.map(documentId => (
                <span key={documentId}>{documentName(documentId)}</span>
              ))}
            </div>
            <div>{t('aiDemandReadiness.sources.description')}</div>
          </section>

          <RequirementTable
            title={t('aiDemandReadiness.kpis.livabilityValue', { count: formatNumber(payload.livability_scenarios.length) })}
            rows={payload.livability_scenarios}
          />
          <RequirementTable
            title={t('aiDemandReadiness.kpis.customerValue', { count: formatNumber(payload.customer_ai_demands.length) })}
            rows={payload.customer_ai_demands}
          />
        </>
      ) : !loading && !error ? (
        <div className="uwm-livability-empty">{t('aiDemandReadiness.empty.data')}</div>
      ) : null}
    </div>
  );
}
