import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  Database,
  Gauge,
  ListOrdered,
  Map,
  RefreshCw,
  Shield,
} from 'lucide-react';
import TraditionalLivabilityS7Panel from './TraditionalLivabilityS7Panel';
import TraditionalLivabilityS6Panel from './TraditionalLivabilityS6Panel';
import TraditionalLivabilityS4Panel from './TraditionalLivabilityS4Panel';
import TraditionalLivabilityMobilityPanel from './TraditionalLivabilityMobilityPanel';
import TraditionalLivabilitySocialPublicServicePanel from './TraditionalLivabilitySocialPublicServicePanel';
import TraditionalLivabilityPublicSpacePanel from './TraditionalLivabilityPublicSpacePanel';
import TraditionalLivabilitySafetyComfortPanel from './TraditionalLivabilitySafetyComfortPanel';
import TraditionalLivabilityDailyConveniencePanel from './TraditionalLivabilityDailyConveniencePanel';
import TraditionalLivabilityHousingCommunityPanel from './TraditionalLivabilityHousingCommunityPanel';
import { useTranslation } from 'react-i18next';
import { formatNumber, getLocaleHeaders } from '../../i18n';

declare global {
  interface Window {
    __handleMapUpdate?: (payload: any) => void;
    __uwmTraditionalLastMapUpdate?: any;
  }
}

type AnyRecord = Record<string, any>;

function isRecord(value: unknown): value is AnyRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function asArray<T = AnyRecord>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function fmtScore(value: unknown): string {
  const num = Number(value);
  return Number.isFinite(num) ? formatNumber(num, { maximumFractionDigits: 3 }) : '-';
}

function fmtPercent(value: unknown): string {
  const num = Number(value);
  return Number.isFinite(num) ? `${formatNumber(num * 100, { maximumFractionDigits: 0 })}%` : '-';
}

function gradeClass(grade: unknown): string {
  const text = String(grade || '').toLowerCase();
  return ['a', 'b', 'c', 'd', 'e'].includes(text) ? text : 'unknown';
}

function coverageText(source: AnyRecord, nodeLabel: string, edgeLabel: string): string {
  if ('matched_admin_units' in source && 'requested_admin_units' in source) {
    return `${source.matched_admin_units}/${source.requested_admin_units}`;
  }
  if ('node_count' in source || 'edge_count' in source) {
    return `${formatNumber(source.node_count || 0)} ${nodeLabel} / ${formatNumber(source.edge_count || 0)} ${edgeLabel}`;
  }
  return source.unit_projection || '-';
}

export default function TraditionalLivabilityTab() {
  const { t } = useTranslation();
  const [analysis, setAnalysis] = useState<AnyRecord | null>(null);
  const [s1, setS1] = useState<AnyRecord | null>(null);
  const [s1Unavailable, setS1Unavailable] = useState<AnyRecord | null>(null);
  const [topN, setTopN] = useState(8);
  const [loading, setLoading] = useState(false);
  const [pushingMap, setPushingMap] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const loadTraditionalAnalysis = async () => {
    setLoading(true);
    setError('');
    try {
      const resp = await fetch(`/api/uwm/traditional-livability?top_n=${topN}`, {
        credentials: 'include',
        headers: getLocaleHeaders(),
      });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        setError(data.error || t('traditionalLivability.overview.errors.load'));
        return;
      }
      setAnalysis(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t('traditionalLivability.overview.errors.load'));
    } finally {
      setLoading(false);
    }
  };

  const loadS1Assessment = async () => {
    try {
      const resp = await fetch('/api/uwm/traditional-livability/s1', { credentials: 'include', headers: getLocaleHeaders() });
      const data = await resp.json();
      if (!resp.ok || data.ready === false) {
        setS1(null);
        setS1Unavailable(data);
        return;
      }
      setS1(data);
      setS1Unavailable(null);
    } catch (err: unknown) {
      setS1(null);
      setS1Unavailable({ blockers: [err instanceof Error ? err.message : 's1_request_failed'] });
    }
  };

  const pushTraditionalLayerToMap = async () => {
    setPushingMap(true);
    setError('');
    setMessage('');
    try {
      const resp = await fetch('/api/uwm/traditional-livability/map', {
        method: 'POST',
        credentials: 'include',
        headers: { ...getLocaleHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ top_n: topN }),
      });
      const data = await resp.json();
      if (!resp.ok || data.error || data.map_update_queued === false) {
        setError(data.error || t('traditionalLivability.overview.errors.map'));
        return;
      }
      const mapResp = await fetch('/api/map/pending', { credentials: 'include', headers: getLocaleHeaders() });
      const mapData = await mapResp.json();
      const mapUpdate = mapData.map_update || data.map_update;
      window.__uwmTraditionalLastMapUpdate = mapUpdate;
      if (mapUpdate && window.__handleMapUpdate) {
        window.__handleMapUpdate(mapUpdate);
      }
      setMessage(t('traditionalLivability.overview.messages.mapSent'));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t('traditionalLivability.overview.errors.map'));
    } finally {
      setPushingMap(false);
    }
  };

  useEffect(() => {
    loadTraditionalAnalysis();
    loadS1Assessment();
  }, [topN]);

  const summary = isRecord(analysis?.summary) ? analysis.summary : {};
  const dataBasis = isRecord(analysis?.data_basis) ? analysis.data_basis : {};
  const indicatorSystem = isRecord(analysis?.indicator_system) ? analysis.indicator_system : {};
  const methodBoundary = isRecord(analysis?.method_boundary) ? analysis.method_boundary : {};
  const rankedUnits = asArray<AnyRecord>(analysis?.ranked_admin_units);
  const priorityDiagnosis = asArray<AnyRecord>(analysis?.priority_diagnosis);
  const dimensions = asArray<AnyRecord>(analysis?.dimension_summary);
  const sourceCoverage = isRecord(dataBasis.source_coverage) ? dataBasis.source_coverage : {};
  const sourceRows = useMemo(
    () => Object.entries(sourceCoverage).map(([name, value]) => ({
      name,
      value: isRecord(value) ? value : {},
    })),
    [sourceCoverage],
  );
  const actionPlan = isRecord(analysis?.static_action_plan) ? analysis.static_action_plan : {};
  const actions = asArray<AnyRecord>(actionPlan.actions);
  const indicatorDimensions = asArray<AnyRecord>(indicatorSystem.dimensions);
  const s1Summary = isRecord(s1?.summary) ? s1.summary : {};
  const s1DataSupport = isRecord(s1?.data_support) ? s1.data_support : {};
  const s1Metrics = asArray<AnyRecord>(s1?.supply_metrics);
  const s1Blockers = asArray<string>(s1?.production_blockers || s1Unavailable?.blockers);

  return (
    <div className="traditional-livability-tab">
      <TraditionalLivabilityMobilityPanel />
      <TraditionalLivabilitySocialPublicServicePanel />
      <TraditionalLivabilityPublicSpacePanel />
      <TraditionalLivabilitySafetyComfortPanel />
      <TraditionalLivabilityDailyConveniencePanel />
      <TraditionalLivabilityHousingCommunityPanel />
      <div className="datapanel-section-header">
        <div>
          <h3>{t('traditionalLivability.overview.title')}</h3>
          <p>{t('traditionalLivability.overview.description')}</p>
        </div>
        <div className="traditional-header-actions">
          <label className="traditional-control">
            <span>{t('traditionalLivability.overview.controls.topUnits')}</span>
            <select value={topN} onChange={(event) => setTopN(Number(event.target.value))}>
              {[5, 8, 12, 16, 20].map(value => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>
          <button className="secondary-button" onClick={loadTraditionalAnalysis} disabled={loading}>
            <RefreshCw size={14} />
            {t('traditionalLivability.overview.actions.refresh')}
          </button>
          <button className="primary-button" onClick={pushTraditionalLayerToMap} disabled={pushingMap || !analysis}>
            <Map size={14} />
            {t('traditionalLivability.overview.actions.sendMap')}
          </button>
        </div>
      </div>

      {error && <div className="traditional-message error"><AlertTriangle size={15} />{error}</div>}
      {message && <div className="traditional-message success"><Shield size={15} />{message}</div>}
      {loading && !analysis && <div className="traditional-empty">{t('traditionalLivability.overview.loading')}</div>}

      <TraditionalLivabilityS6Panel />
      <TraditionalLivabilityS4Panel />
      <TraditionalLivabilityS7Panel />

      <div className="traditional-panel">
        <div className="traditional-panel-title">
          <Database size={15} />
          <strong>{t('traditionalLivability.overview.s1.title')}</strong>
        </div>
        {s1Unavailable && (
          <div className="traditional-empty">
            {t('traditionalLivability.overview.s1.unavailable', { blockers: s1Blockers.join(' / ') || '-' })}
          </div>
        )}
        {s1 && (
          <>
            <div className="traditional-kpi-grid">
              <div className="traditional-kpi"><span>{t('traditionalLivability.overview.s1.region')}</span><strong>{t('traditionalLivability.overview.s1.chongqing')}</strong></div>
              <div className="traditional-kpi"><span>{s1DataSupport.complete_inventory ? t('traditionalLivability.overview.s1.completeInventory') : t('traditionalLivability.overview.s1.sampledInventory')}</span><strong>{formatNumber(s1Summary.facility_count || 0)}</strong></div>
              <div className="traditional-kpi"><span>{t('traditionalLivability.overview.s1.matchedPopulation')}</span><strong>{formatNumber(s1Summary.population_unit_count || 0)}</strong></div>
              <div className="traditional-kpi"><span>{t('traditionalLivability.overview.s1.unmatchedFacilities')}</span><strong>{formatNumber(s1Summary.unmatched_facility_count || 0)}</strong></div>
            </div>
            <div className="traditional-message error">
              <AlertTriangle size={15} />{t('traditionalLivability.overview.s1.noStandard')}
            </div>
            <div className="traditional-table-wrap">
              <table className="traditional-table">
                <thead><tr><th>{t('traditionalLivability.overview.table.adminUnit')}</th><th>{t('traditionalLivability.overview.table.facilityClass')}</th><th>{t('traditionalLivability.overview.table.facilityCount')}</th><th>{t('traditionalLivability.overview.table.perTenThousand')}</th><th>{t('traditionalLivability.overview.table.compliance')}</th></tr></thead>
                <tbody>
                  {s1Metrics.slice(0, 30).map(row => (
                    <tr key={`${row.admin_code}-${row.canonical_class}`}>
                      <td>{row.admin_name || row.admin_code}</td><td>{row.canonical_class}</td><td>{formatNumber(row.facility_count || 0)}</td>
                      <td>{fmtScore(row.facilities_per_10000_residents)}</td><td>{t(`traditionalLivability.overview.compliance.${String(row.compliance_status)}`, { defaultValue: t('traditionalLivability.overview.compliance.not_assessed') })}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="traditional-boundary-grid">
              <div><span>{t('traditionalLivability.overview.s1.productionBlockers')}</span><strong>{s1Blockers.join(' / ') || '-'}</strong></div>
              <div><span>{t('traditionalLivability.overview.boundary.title')}</span><strong>{t('traditionalLivability.overview.s1.boundary')}</strong></div>
            </div>
          </>
        )}
      </div>

      {analysis && (
        <>
          <div className="traditional-kpi-grid">
            <div className="traditional-kpi">
              <span>{t('traditionalLivability.overview.kpis.score')}</span>
              <strong>{fmtScore(summary.city_livability_score)}</strong>
            </div>
            <div className={`traditional-kpi grade ${gradeClass(summary.grade)}`}>
              <span>{t('traditionalLivability.overview.kpis.grade')}</span>
              <strong>{summary.grade || '-'}</strong>
            </div>
            <div className="traditional-kpi">
              <span>{t('traditionalLivability.overview.kpis.adminUnits')}</span>
              <strong>{formatNumber(summary.admin_unit_count || 0)}</strong>
            </div>
            <div className="traditional-kpi">
              <span>{t('traditionalLivability.overview.kpis.dataSources')}</span>
              <strong>{formatNumber(summary.data_source_count || 0)}</strong>
            </div>
          </div>

          <div className="traditional-panel">
            <div className="traditional-panel-title">
              <BarChart3 size={15} />
              <strong>{t('traditionalLivability.overview.sections.dimensions')}</strong>
            </div>
            <div className="traditional-bar-list">
              {dimensions.map(item => (
                <div key={item.dimension_id} className="traditional-bar-row">
                  <div>
                    <strong>{item.label}</strong>
                    <span>{t('traditionalLivability.overview.dimensions.meta', { weight: fmtPercent(item.weight), count: formatNumber(item.low_score_unit_count || 0) })}</span>
                  </div>
                  <div className="traditional-bar-track">
                    <div style={{ width: fmtPercent(item.mean_score) }} />
                  </div>
                  <b>{fmtScore(item.mean_score)}</b>
                </div>
              ))}
            </div>
            <div className="traditional-indicator-grid">
              {indicatorDimensions.map(item => (
                <div key={item.dimension_id}>
                  <span>{item.label}</span>
                  <strong>{asArray<string>(item.indicator_fields).join(' / ')}</strong>
                </div>
              ))}
            </div>
          </div>

          <div className="traditional-panel">
            <div className="traditional-panel-title">
              <ListOrdered size={15} />
              <strong>{t('traditionalLivability.overview.sections.ranking')}</strong>
            </div>
            <div className="traditional-table-wrap">
              <table className="traditional-table">
                <thead>
                  <tr>
                    <th>{t('traditionalLivability.overview.table.rank')}</th>
                    <th>{t('traditionalLivability.overview.table.adminUnit')}</th>
                    <th>{t('traditionalLivability.overview.table.score')}</th>
                    <th>{t('traditionalLivability.overview.table.gaps')}</th>
                    <th>{t('traditionalLivability.overview.table.recommendation')}</th>
                  </tr>
                </thead>
                <tbody>
                  {rankedUnits.slice(0, 12).map(row => (
                    <tr key={row.admin_unit_id}>
                      <td>{row.static_rank}</td>
                      <td>{row.county}{row.township}</td>
                      <td>{fmtScore(row.traditional_livability_score)}</td>
                      <td>
                        <div className="traditional-tag-list">
                          {asArray<string>(row.issue_tags).map(tag => (
                            <span key={tag} className="traditional-tag">{tag}</span>
                          ))}
                        </div>
                      </td>
                      <td>{asArray<string>(row.recommended_static_actions).slice(0, 2).join('；') || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="traditional-two-col">
            <div className="traditional-panel">
              <div className="traditional-panel-title">
                <Gauge size={15} />
                <strong>{t('traditionalLivability.overview.sections.diagnosis')}</strong>
              </div>
              <div className="traditional-diagnosis-list">
                {priorityDiagnosis.map(row => (
                  <div key={row.admin_unit_id} className="traditional-diagnosis-item">
                    <div>
                      <strong>{row.static_rank}. {row.county}{row.township}</strong>
                      <span>{t('traditionalLivability.overview.diagnosis.score', { score: fmtScore(row.traditional_livability_score) })}</span>
                    </div>
                    <div className="traditional-tag-list">
                      {asArray<string>(row.issue_tags).map(tag => (
                        <span key={tag} className="traditional-tag">{tag}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="traditional-panel">
              <div className="traditional-panel-title">
                <Shield size={15} />
                <strong>{t('traditionalLivability.overview.boundary.title')}</strong>
              </div>
              <div className="traditional-boundary-grid">
                <div>
                  <span>{t('traditionalLivability.overview.boundary.canOutput')}</span>
                  <strong>{asArray<string>(methodBoundary.can_output).join(' / ')}</strong>
                </div>
                <div>
                  <span>{t('traditionalLivability.overview.boundary.cannotOutput')}</span>
                  <strong>{t('traditionalLivability.overview.boundary.unsupported')}</strong>
                </div>
              </div>
            </div>
          </div>

          <div className="traditional-panel">
            <div className="traditional-panel-title">
              <AlertTriangle size={15} />
              <strong>{t('traditionalLivability.overview.sections.actions')}</strong>
            </div>
            <div className="traditional-action-list">
              {actions.map(action => (
                <div key={action.action_type}>
                  <strong>{action.action_name}</strong>
                  <span>{t('traditionalLivability.overview.actions.targetUnits', { count: formatNumber(asArray<string>(action.target_units).length), basis: action.basis })}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="traditional-panel">
            <div className="traditional-panel-title">
              <Database size={15} />
              <strong>{t('traditionalLivability.overview.sections.dataBasis')}</strong>
            </div>
            <div className="traditional-source-grid">
              {sourceRows.map(row => (
                <div key={row.name}>
                  <span>{row.name}</span>
                  <strong>{coverageText(row.value, t('traditionalLivability.overview.data.nodes'), t('traditionalLivability.overview.data.edges'))}</strong>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
