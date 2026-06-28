import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, RefreshCw, ShieldCheck } from 'lucide-react';

type MetricValue = string | number | null | undefined;
type MetricValueRecord = Record<string, MetricValue>;

interface Paper58Evidence {
  schema?: string;
  status?: 'missing' | 'supporting_evidence' | 'review' | 'blocked' | string;
  provided?: boolean;
  missing?: string[];
  read_errors?: Array<{ path?: string; error?: string }>;
  source_files?: Record<string, string | null | undefined>;
  metric_summary?: {
    best_paper58_method?: string | null;
    baseline_method?: string | null;
    area_count?: number | null;
    paper58_vs_baseline_wins?: number | null;
    best_paper58_metrics?: MetricValueRecord;
    baseline_metrics?: MetricValueRecord;
    deltas?: Record<string, number | null | undefined>;
  };
  manifest_summary?: Record<string, unknown>;
  claim_scope?: string;
  runtime_dependency?: string;
  geofm_runtime_allowed?: boolean;
  twm_generator_role?: string;
  primary_twm_route?: string;
  blocks_validation?: boolean;
  can_promote_claim_ladder?: boolean;
  claim_boundary?: string;
  error?: string;
}

const metricLabels: Record<string, string> = {
  mean_change_f1: 'Change F1',
  mean_fom: 'FoM',
  mean_transition_accuracy: 'Transition accuracy',
  mean_allocation_disagreement: 'Allocation disagreement',
};

const BOUNDARY_DEFAULTS: Paper58Evidence = {
  status: 'missing',
  claim_scope: 'external_benchmark_support_only',
  runtime_dependency: 'none',
  geofm_runtime_allowed: false,
  twm_generator_role: 'not_a_runtime_generator',
  primary_twm_route: 'twm_native_generation_and_planning',
  blocks_validation: false,
  can_promote_claim_ladder: false,
  claim_boundary: 'Paper58 is external benchmark support only.',
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function normalizedString(value: unknown) {
  return typeof value === 'string' ? value : undefined;
}

function normalizedNullableString(value: unknown) {
  if (typeof value === 'string' || value === null) return value;
  return undefined;
}

function normalizedBoolean(value: unknown) {
  return typeof value === 'boolean' ? value : undefined;
}

function normalizedNullableNumber(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (value === null) return null;
  return undefined;
}

function normalizeSourceFiles(value: unknown) {
  const sourceFiles: Record<string, string | null | undefined> = {};
  if (!isRecord(value)) return sourceFiles;

  Object.entries(value).forEach(([key, sourcePath]) => {
    if (typeof sourcePath === 'string' || sourcePath === null || typeof sourcePath === 'undefined') {
      sourceFiles[key] = sourcePath;
    }
  });

  return sourceFiles;
}

function normalizeDeltas(value: unknown) {
  const deltas: Record<string, number | null | undefined> = {};
  if (!isRecord(value)) return deltas;

  Object.entries(value).forEach(([key, delta]) => {
    if (typeof delta === 'number' && Number.isFinite(delta)) {
      deltas[key] = delta;
    } else if (delta === null || typeof delta === 'undefined') {
      deltas[key] = delta;
    }
  });

  return deltas;
}

function normalizeMetricValues(value: unknown) {
  const metrics: MetricValueRecord = {};
  if (!isRecord(value)) return metrics;

  Object.entries(value).forEach(([key, metricValue]) => {
    if (typeof metricValue === 'number' && Number.isFinite(metricValue)) {
      metrics[key] = metricValue;
    } else if (typeof metricValue === 'string' || metricValue === null || typeof metricValue === 'undefined') {
      metrics[key] = metricValue;
    }
  });

  return metrics;
}

function normalizeMetricSummary(value: unknown): Paper58Evidence['metric_summary'] | undefined {
  if (!isRecord(value)) return undefined;

  const summary: NonNullable<Paper58Evidence['metric_summary']> = {};
  const bestPaper58Method = normalizedNullableString(value.best_paper58_method);
  const baselineMethod = normalizedNullableString(value.baseline_method);
  const areaCount = normalizedNullableNumber(value.area_count);
  const wins = normalizedNullableNumber(value.paper58_vs_baseline_wins);
  const bestPaper58Metrics = normalizeMetricValues(value.best_paper58_metrics);
  const baselineMetrics = normalizeMetricValues(value.baseline_metrics);
  const deltas = normalizeDeltas(value.deltas);

  if (typeof bestPaper58Method !== 'undefined') summary.best_paper58_method = bestPaper58Method;
  if (typeof baselineMethod !== 'undefined') summary.baseline_method = baselineMethod;
  if (typeof areaCount !== 'undefined') summary.area_count = areaCount;
  if (typeof wins !== 'undefined') summary.paper58_vs_baseline_wins = wins;
  if (Object.keys(bestPaper58Metrics).length > 0) summary.best_paper58_metrics = bestPaper58Metrics;
  if (Object.keys(baselineMetrics).length > 0) summary.baseline_metrics = baselineMetrics;
  if (Object.keys(deltas).length > 0) summary.deltas = deltas;

  return summary;
}

function normalizeReadErrors(value: unknown): Array<{ path?: string; error?: string }> {
  if (!Array.isArray(value)) return [];

  return value
    .filter(isRecord)
    .map(item => ({
      path: normalizedString(item.path),
      error: normalizedString(item.error),
    }))
    .filter(item => item.path || item.error);
}

function normalizeEvidence(raw: unknown): Paper58Evidence {
  const evidence: Paper58Evidence = {
    ...BOUNDARY_DEFAULTS,
    missing: [],
    read_errors: [],
    source_files: {},
  };

  if (!isRecord(raw)) return evidence;

  const metricSummary = normalizeMetricSummary(raw.metric_summary);

  return {
    ...evidence,
    schema: normalizedString(raw.schema),
    status: normalizedString(raw.status) || evidence.status,
    provided: normalizedBoolean(raw.provided),
    missing: Array.isArray(raw.missing) ? raw.missing.filter((item): item is string => typeof item === 'string') : [],
    read_errors: normalizeReadErrors(raw.read_errors),
    source_files: normalizeSourceFiles(raw.source_files),
    metric_summary: metricSummary,
    manifest_summary: isRecord(raw.manifest_summary) ? raw.manifest_summary : undefined,
    claim_scope: BOUNDARY_DEFAULTS.claim_scope,
    runtime_dependency: BOUNDARY_DEFAULTS.runtime_dependency,
    geofm_runtime_allowed: BOUNDARY_DEFAULTS.geofm_runtime_allowed,
    twm_generator_role: BOUNDARY_DEFAULTS.twm_generator_role,
    primary_twm_route: BOUNDARY_DEFAULTS.primary_twm_route,
    blocks_validation: BOUNDARY_DEFAULTS.blocks_validation,
    can_promote_claim_ladder: BOUNDARY_DEFAULTS.can_promote_claim_ladder,
    claim_boundary: BOUNDARY_DEFAULTS.claim_boundary,
    error: normalizedString(raw.error),
  };
}

function formatValue(value: unknown) {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '-';
    return value.toFixed(4);
  }
  if (typeof value === 'boolean') return String(value);
  if (value === null || typeof value === 'undefined' || value === '') return '-';
  return String(value);
}

function formatCount(value: unknown) {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '-';
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  return formatValue(value);
}

function statusBadgeClass(status?: string) {
  if (status === 'supporting_evidence') return 'status-badge success';
  if (status === 'review') return 'status-badge warning';
  if (status === 'blocked') return 'status-badge error';
  return 'status-badge dismissed';
}

export default function WorldModelV11Tab() {
  const [evidence, setEvidence] = useState<Paper58Evidence>(() => normalizeEvidence(null));
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');

  const metricRows = useMemo(() => {
    const metricSummary = isRecord(evidence.metric_summary) ? evidence.metric_summary : {};
    const paper58Metrics = isRecord(metricSummary.best_paper58_metrics) ? metricSummary.best_paper58_metrics : {};
    const baselineMetrics = isRecord(metricSummary.baseline_metrics) ? metricSummary.baseline_metrics : {};
    const deltas = isRecord(metricSummary.deltas) ? metricSummary.deltas : {};
    return Object.keys(metricLabels).map(key => ({
      key,
      label: metricLabels[key],
      paper58: paper58Metrics[key],
      baseline: baselineMetrics[key],
      delta: deltas[key],
    }));
  }, [evidence]);

  const loadEvidence = async () => {
    setLoading(true);
    setError('');
    try {
      const resp = await fetch('/api/twm/paper58-benchmark', { credentials: 'include' });
      const data = normalizeEvidence(await resp.json());
      if (!resp.ok || data.error) {
        const message = data.error || 'Paper58 evidence load failed';
        setEvidence(normalizeEvidence({ error: message }));
        setError(message);
        return;
      }
      setEvidence(data);
    } catch (err: unknown) {
      setEvidence(normalizeEvidence(null));
      setError(err instanceof Error ? err.message : 'Paper58 evidence load failed');
    } finally {
      setLoading(false);
    }
  };

  const refreshEvidence = async () => {
    setRefreshing(true);
    setError('');
    try {
      const resp = await fetch('/api/twm/paper58-benchmark/refresh', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const data = normalizeEvidence(await resp.json());
      if (!resp.ok || data.error) {
        const message = data.error || 'Paper58 evidence refresh failed';
        setEvidence(normalizeEvidence({ error: message }));
        setError(message);
        return;
      }
      setEvidence(data);
    } catch (err: unknown) {
      setEvidence(normalizeEvidence(null));
      setError(err instanceof Error ? err.message : 'Paper58 evidence refresh failed');
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadEvidence();
  }, []);

  const status = evidence.status || BOUNDARY_DEFAULTS.status || 'missing';
  const sourceFiles = isRecord(evidence.source_files) ? evidence.source_files : {};
  const metricSummary = isRecord(evidence.metric_summary) ? evidence.metric_summary : {};
  const missing = Array.isArray(evidence.missing) ? evidence.missing : [];
  const readErrors = Array.isArray(evidence.read_errors) ? evidence.read_errors : [];

  return (
    <div className="datapanel-section world-model-v11-tab">
      <div className="datapanel-section-header">
        <div>
          <h3>世界模型 v1.1</h3>
          <p>Paper58 is external benchmark support only. TWM-native generation and planning remain the runtime route.</p>
        </div>
        <button className="secondary-button" type="button" onClick={refreshEvidence} disabled={refreshing || loading}>
          <RefreshCw size={14} />
          {refreshing ? '刷新中' : '刷新证据'}
        </button>
      </div>

      {error && (
        <div className="datapanel-card">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      <div className="datapanel-card">
        <div className="datapanel-card-header">
          <ShieldCheck size={16} />
          <strong>Paper58 boundary</strong>
          <span className={statusBadgeClass(status)}>{status}</span>
        </div>
        <div className="metric-grid compact">
          <div><span>Claim scope</span><strong>{formatValue(evidence.claim_scope)}</strong></div>
          <div><span>runtime_dependency=none</span><strong>{formatValue(evidence.runtime_dependency)}</strong></div>
          <div><span>geofm_runtime_allowed=false</span><strong>{formatValue(evidence.geofm_runtime_allowed)}</strong></div>
          <div><span>Generator role</span><strong>{formatValue(evidence.twm_generator_role || 'not_a_runtime_generator')}</strong></div>
          <div><span>Primary route</span><strong>{formatValue(evidence.primary_twm_route)}</strong></div>
          <div><span>Can promote claim ladder</span><strong>{formatValue(evidence.can_promote_claim_ladder)}</strong></div>
        </div>
        <p className="muted-text">{evidence.claim_boundary || BOUNDARY_DEFAULTS.claim_boundary}</p>
      </div>

      <div className="datapanel-card">
        <div className="datapanel-card-header">
          <CheckCircle2 size={16} />
          <strong>Paper58 vs GeoSOS-FLUS</strong>
        </div>
        <div className="metric-grid compact">
          <div><span>Paper58 method</span><strong>{formatValue(metricSummary.best_paper58_method)}</strong></div>
          <div><span>Baseline</span><strong>{formatValue(metricSummary.baseline_method)}</strong></div>
          <div><span>Area count</span><strong>{formatCount(metricSummary.area_count)}</strong></div>
          <div><span>Wins</span><strong>{formatCount(metricSummary.paper58_vs_baseline_wins)}</strong></div>
        </div>
        <table className="data-table compact-table">
          <thead>
            <tr><th>Metric</th><th>Paper58</th><th>GeoSOS-FLUS</th><th>Delta</th></tr>
          </thead>
          <tbody>
            {metricRows.map(row => (
              <tr key={row.key}>
                <td>{row.label}</td>
                <td>{formatValue(row.paper58)}</td>
                <td>{formatValue(row.baseline)}</td>
                <td>{formatValue(row.delta)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="datapanel-card">
        <div className="datapanel-card-header"><strong>Evidence source</strong></div>
        <div className="metric-grid compact">
          <div><span>paper58_benchmark_dir</span><strong>{formatValue(sourceFiles.paper58_benchmark_dir)}</strong></div>
          <div><span>metric_summary_by_method.csv</span><strong>{formatValue(sourceFiles.metric_summary_by_method)}</strong></div>
          <div><span>metrics_by_method.csv</span><strong>{formatValue(sourceFiles.metrics_by_method)}</strong></div>
          <div><span>manifest.json</span><strong>{formatValue(sourceFiles.manifest)}</strong></div>
        </div>
        {missing.length > 0 && <p className="muted-text">Missing: {missing.join(', ')}</p>}
        {readErrors.length > 0 && <p className="muted-text">Read errors: {readErrors.map(item => item.error || item.path).join('; ')}</p>}
      </div>
    </div>
  );
}
