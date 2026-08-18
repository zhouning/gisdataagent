import { useState, useEffect, useCallback } from 'react';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';
import { formatDate, formatNumber, getLocaleHeaders } from '../../i18n';

/* ------------------------------------------------------------------
   Types
   ------------------------------------------------------------------ */

interface FusionOperation {
  id: number;
  username: string;
  strategy: string;
  quality_score: number | null;
  duration_s: number | null;
  created_at: string;
  v2_features: {
    temporal: boolean;
    conflict: boolean;
    explainability: boolean;
  };
}

interface QualityDetail {
  operation_id: number;
  quality_score: number | null;
  quality_report: Record<string, unknown>;
  explainability: Record<string, unknown>;
}

interface DiagnosticCheck {
  check_id: string;
  label_zh: string;
  status: 'pass' | 'warn' | 'fail' | string;
  severity: string;
  message_zh: string;
  evidence: Record<string, unknown>;
}

interface MmfeReadiness {
  product_id: string;
  summary: {
    readiness_score: number;
    validation_ready: boolean;
    production_ready: boolean;
    status: string;
    pass_count: number;
    warn_count: number;
    fail_count: number;
  };
  capabilities: {
    layer_count: number;
    field_semantic_count: number;
    semantic_relation_count: number;
    semantic_graph_node_count: number;
    semantic_graph_edge_count: number;
    trace_card_count: number;
    objective_count: number;
  };
  core_surfaces: DiagnosticCheck[];
  production_gates: DiagnosticCheck[];
  recommendations_zh: string[];
}

/* ------------------------------------------------------------------
   Helpers
   ------------------------------------------------------------------ */

function confidenceBadge(score: number | null, t: TFunction): { label: string; color: string } {
  if (score === null) return { label: '—', color: '#888' };
  if (score >= 0.7) return { label: t('fusionQuality.confidence.high'), color: '#10b981' };
  if (score >= 0.3) return { label: t('fusionQuality.confidence.medium'), color: '#f59e0b' };
  return { label: t('fusionQuality.confidence.low'), color: '#ef4444' };
}

function statusBadge(status: string, t: TFunction): { label: string; color: string; background: string } {
  if (status === 'pass') return { label: t('fusionQuality.status.pass'), color: '#047857', background: '#d1fae5' };
  if (status === 'warn') return { label: t('fusionQuality.status.warn'), color: '#b45309', background: '#fef3c7' };
  return { label: t('fusionQuality.status.fail'), color: '#b91c1c', background: '#fee2e2' };
}

function formatEvidenceValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number') return formatNumber(value, { maximumFractionDigits: 4 });
  if (Array.isArray(value)) return value.map(formatEvidenceValue).join(', ');
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function compactEvidence(check: DiagnosticCheck): string {
  const keys = [
    'source_count',
    'official_verified_count',
    'audit_count',
    'requires_review_count',
    'node_count',
    'edge_count',
    'trace_card_count',
    'standard_source_path_count',
    'schema',
    'role_count',
    'component_count',
    'total_relation_count',
    'objective_count',
    'blocked_source_count',
    'missing_field_count',
    'pending_standard_gap_count',
  ];
  return keys
    .filter((key) => Object.prototype.hasOwnProperty.call(check.evidence, key))
    .slice(0, 3)
    .map((key) => `${key}: ${formatEvidenceValue(check.evidence[key])}`)
    .join(' / ');
}

/* ------------------------------------------------------------------
   Component
   ------------------------------------------------------------------ */

export default function FusionQualityTab() {
  const { t } = useTranslation();
  const [operations, setOperations] = useState<FusionOperation[]>([]);
  const [selected, setSelected] = useState<QualityDetail | null>(null);
  const [readiness, setReadiness] = useState<MmfeReadiness | null>(null);
  const [loading, setLoading] = useState(false);
  const [readinessLoading, setReadinessLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchReadiness = useCallback(async () => {
    setReadinessLoading(true);
    setError(null);
    try {
      const resp = await fetch('/api/fusion/mmfe/readiness', { credentials: 'include', headers: getLocaleHeaders() });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setReadiness(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setReadinessLoading(false);
    }
  }, []);

  /* Fetch operations list */
  const fetchOperations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch('/api/fusion/operations?limit=50', { credentials: 'include', headers: getLocaleHeaders() });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setOperations(data.items ?? []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchReadiness();
    fetchOperations();
  }, [fetchReadiness, fetchOperations]);

  /* Fetch quality detail for a specific operation */
  const fetchDetail = useCallback(async (opId: number) => {
    try {
      const resp = await fetch(`/api/fusion/quality/${opId}`, { credentials: 'include', headers: getLocaleHeaders() });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data: QualityDetail = await resp.json();
      setSelected(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const checkLabel = (check: DiagnosticCheck) => t(`fusionQuality.checks.${check.check_id}`, { defaultValue: check.label_zh });
  const readinessStatus = (status: string) => t(`fusionQuality.readinessStatus.${status}`, { defaultValue: status });

  /* ----------------------------------------------------------------
     Render
     ---------------------------------------------------------------- */

  return (
    <div style={{ padding: 12, height: '100%', overflow: 'auto', fontSize: 13 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>{t('fusionQuality.title')}</h3>
        <button
          onClick={() => { fetchReadiness(); fetchOperations(); }}
          style={{ padding: '4px 12px', cursor: 'pointer', borderRadius: 4, border: '1px solid #ccc' }}
        >
          {t('fusionQuality.actions.refresh')}
        </button>
      </div>

      {loading && <p>{t('fusionQuality.loading.operations')}</p>}
      {readinessLoading && <p>{t('fusionQuality.loading.readiness')}</p>}
      {error && <p style={{ color: '#ef4444' }}>{t('fusionQuality.error', { error })}</p>}

      {readiness && (
        <div style={{
          border: '1px solid #d1d5db',
          borderRadius: 8,
          padding: 12,
          marginBottom: 14,
          background: '#ffffff',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
            <div>
              <h4 style={{ margin: '0 0 6px' }}>{t('fusionQuality.readiness.title')}</h4>
              <div style={{ color: '#4b5563', fontSize: 12 }}>
                {readiness.product_id} / {readinessStatus(readiness.summary.status)}
              </div>
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              <span style={{
                padding: '3px 8px',
                borderRadius: 999,
                color: '#047857',
                background: '#d1fae5',
                fontWeight: 600,
              }}>
                {t('fusionQuality.readiness.validation', { value: t(readiness.summary.validation_ready ? 'fusionQuality.common.yes' : 'fusionQuality.common.no') })}
              </span>
              <span style={{
                padding: '3px 8px',
                borderRadius: 999,
                color: readiness.summary.production_ready ? '#047857' : '#b45309',
                background: readiness.summary.production_ready ? '#d1fae5' : '#fef3c7',
                fontWeight: 600,
              }}>
                {t('fusionQuality.readiness.production', { value: t(readiness.summary.production_ready ? 'fusionQuality.common.yes' : 'fusionQuality.common.no') })}
              </span>
              <span style={{
                padding: '3px 8px',
                borderRadius: 999,
                color: '#1f2937',
                background: '#f3f4f6',
                fontWeight: 600,
              }}>
                {formatNumber(readiness.summary.readiness_score, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </div>
          </div>

          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
            gap: 8,
            marginTop: 10,
            marginBottom: 10,
          }}>
            <div><strong>{t('fusionQuality.capabilities.layers')}</strong><br />{formatNumber(readiness.capabilities.layer_count)}</div>
            <div><strong>{t('fusionQuality.capabilities.fieldSemantics')}</strong><br />{formatNumber(readiness.capabilities.field_semantic_count)}</div>
            <div><strong>{t('fusionQuality.capabilities.relations')}</strong><br />{formatNumber(readiness.capabilities.semantic_relation_count)}</div>
            <div><strong>{t('fusionQuality.capabilities.graphNodes')}</strong><br />{formatNumber(readiness.capabilities.semantic_graph_node_count)}</div>
            <div><strong>{t('fusionQuality.capabilities.graphEdges')}</strong><br />{formatNumber(readiness.capabilities.semantic_graph_edge_count)}</div>
            <div><strong>{t('fusionQuality.capabilities.objectives')}</strong><br />{formatNumber(readiness.capabilities.objective_count)}</div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8 }}>
            {readiness.core_surfaces.map((check) => {
              const badge = statusBadge(check.status, t);
              return (
                <div key={check.check_id} style={{ border: '1px solid #e5e7eb', borderRadius: 6, padding: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                    <strong>{checkLabel(check)}</strong>
                    <span style={{
                      padding: '1px 6px',
                      borderRadius: 999,
                      color: badge.color,
                      background: badge.background,
                      fontSize: 12,
                      fontWeight: 600,
                    }}>
                      {badge.label}
                    </span>
                  </div>
                  <div style={{ color: '#6b7280', fontSize: 11, marginTop: 4 }}>
                    {compactEvidence(check)}
                  </div>
                </div>
              );
            })}
          </div>

          <div style={{ marginTop: 10 }}>
            <strong>{t('fusionQuality.readiness.productionBlockers')}:</strong>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
              {readiness.production_gates.map((check) => {
                const badge = statusBadge(check.status, t);
                return (
                  <span
                    key={check.check_id}
                    title={t('fusionQuality.readiness.gateTitle', { label: checkLabel(check), status: badge.label })}
                    style={{
                      padding: '3px 8px',
                      borderRadius: 999,
                      color: badge.color,
                      background: badge.background,
                      fontWeight: 600,
                    }}
                  >
                    {checkLabel(check)}: {badge.label}
                  </span>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Operations Table */}
      <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 16 }}>
        <thead>
          <tr style={{ borderBottom: '2px solid #e5e7eb', textAlign: 'start' }}>
            <th style={{ padding: '6px 8px' }}>ID</th>
            <th style={{ padding: '6px 8px' }}>{t('fusionQuality.table.strategy')}</th>
            <th style={{ padding: '6px 8px' }}>{t('fusionQuality.table.quality')}</th>
            <th style={{ padding: '6px 8px' }}>{t('fusionQuality.table.duration')}</th>
            <th style={{ padding: '6px 8px' }}>{t('fusionQuality.table.features')}</th>
            <th style={{ padding: '6px 8px' }}>{t('fusionQuality.table.time')}</th>
          </tr>
        </thead>
        <tbody>
          {operations.map((op) => {
            const badge = confidenceBadge(op.quality_score, t);
            return (
              <tr
                key={op.id}
                onClick={() => fetchDetail(op.id)}
                style={{
                  borderBottom: '1px solid #f3f4f6',
                  cursor: 'pointer',
                  background: selected?.operation_id === op.id ? '#eff6ff' : 'transparent',
                }}
              >
                <td style={{ padding: '6px 8px' }}>#{op.id}</td>
                <td style={{ padding: '6px 8px' }}>{op.strategy}</td>
                <td style={{ padding: '6px 8px' }}>
                  <span style={{
                    display: 'inline-block', padding: '2px 8px', borderRadius: 10,
                    background: badge.color + '20', color: badge.color, fontWeight: 600,
                  }}>
                    {op.quality_score !== null ? formatNumber(op.quality_score, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'} {badge.label}
                  </span>
                </td>
                <td style={{ padding: '6px 8px' }}>{op.duration_s == null ? '—' : t('fusionQuality.durationSeconds', { value: formatNumber(op.duration_s, { maximumFractionDigits: 1 }) })}</td>
                <td style={{ padding: '6px 8px' }}>
                  {op.v2_features.temporal && <span title={t('fusionQuality.features.temporal')}>⏱</span>}
                  {op.v2_features.conflict && <span title={t('fusionQuality.features.conflict')}>⚡</span>}
                  {op.v2_features.explainability && <span title={t('fusionQuality.features.explainability')}>🔍</span>}
                  {!op.v2_features.temporal && !op.v2_features.conflict && !op.v2_features.explainability && '—'}
                </td>
                <td style={{ padding: '6px 8px', fontSize: 11, color: '#6b7280' }}>
                  {formatDate(op.created_at, { dateStyle: 'medium', timeStyle: 'short' })}
                </td>
              </tr>
            );
          })}
          {operations.length === 0 && !loading && (
            <tr><td colSpan={6} style={{ padding: 16, textAlign: 'center', color: '#9ca3af' }}>
              {t('fusionQuality.empty.operations')}
            </td></tr>
          )}
        </tbody>
      </table>

      {/* Detail Panel */}
      {selected && (
        <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: 12 }}>
          <h4 style={{ margin: '0 0 8px' }}>{t('fusionQuality.details.title', { id: formatNumber(selected.operation_id) })}</h4>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <div>
              <strong>{t('fusionQuality.details.qualityScore')}:</strong>{' '}
              {selected.quality_score !== null ? formatNumber(selected.quality_score, { minimumFractionDigits: 4, maximumFractionDigits: 4 }) : '—'}
            </div>
            <div>
              <strong>{t('fusionQuality.details.qualityReport')}:</strong>{' '}
              {JSON.stringify(selected.quality_report?.warnings ?? [], null, 0).slice(0, 100)}
            </div>
          </div>
          {selected.explainability && Object.keys(selected.explainability).length > 0 && (
            <div style={{ marginTop: 8 }}>
              <strong>{t('fusionQuality.details.explainability')}:</strong>
              <pre style={{ background: '#f9fafb', padding: 8, borderRadius: 4, fontSize: 11, overflow: 'auto', maxHeight: 200 }}>
                {JSON.stringify(selected.explainability, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
