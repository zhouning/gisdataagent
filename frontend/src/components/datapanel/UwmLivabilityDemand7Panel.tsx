import { useEffect, useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { AlertTriangle, Map, RefreshCw, Search, ShieldCheck, Target } from 'lucide-react';
import { formatNumber, getLocaleHeaders } from '../../i18n';

type Row = Record<string, any>;

const TARGET_UNIT = '\u6daa\u9675\u533a|\u853a\u5e02\u9547|498';
const INDICATORS = [
  ['heat_risk', true],
  ['air_pollution_exposure', true],
  ['service_accessibility', false],
  ['equity', false],
  ['livability', false],
] as const;
const PROFILE_IDS = [
  'balanced',
  'community_service',
  'environmental_comfort',
  'equitable_livability',
] as const;

const arr = <T = Row,>(value: unknown): T[] => Array.isArray(value) ? value as T[] : [];
const number = (value: unknown, digits = 6) => {
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? formatNumber(parsed, { minimumFractionDigits: digits, maximumFractionDigits: digits })
    : '-';
};

export default function UwmLivabilityDemand7Panel() {
  const { t, i18n } = useTranslation('common');
  const isChinese = (i18n.resolvedLanguage || i18n.language).startsWith('zh');
  const [overview, setOverview] = useState<Row | null>(null);
  const [search, setSearch] = useState(isChinese ? TARGET_UNIT : '498');
  const [units, setUnits] = useState<Row[]>([]);
  const [unitId, setUnitId] = useState(TARGET_UNIT);
  const [detail, setDetail] = useState<Row | null>(null);
  const [profile, setProfile] = useState('community_service');
  const [horizon, setHorizon] = useState('simulator_step');
  const [plan, setPlan] = useState<Row | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  const unitLabel = (value: unknown) => {
    const raw = String(value || '-');
    if (isChinese) return raw.replace(/\|/g, ' · ');
    const parts = raw.split('|');
    const id = parts[parts.length - 1] || raw;
    return t('uwmDemand7.unitId', { id });
  };
  const translatedValue = (scope: string, value: unknown) => {
    const key = String(value || 'unavailable');
    return t(`uwmDemand7.${scope}.${key}`, { defaultValue: key });
  };
  const localizedMapPayload = (payload: Row | null) => {
    if (!payload) return payload;
    const layerKeys = ['target', 'spillover', 'underserved'];
    return {
      ...payload,
      summary: { ...payload.summary, title: t('uwmDemand7.map.title') },
      layers: arr<Row>(payload.layers).map((layer, index) => ({
        ...layer,
        name: t(`uwmDemand7.map.layers.${layerKeys[index] || 'other'}`, {
          defaultValue: String(layer.name || '-'),
        }),
      })),
    };
  };

  const loadOverview = async () => {
    const response = await fetch('/api/uwm/livability/demand7/overview', {
      credentials: 'include',
      headers: getLocaleHeaders(),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(t('uwmDemand7.errors.unavailable'));
    setOverview(payload);
  };

  const searchUnits = async (query = search) => {
    const response = await fetch(`/api/uwm/livability/demand7/units?search=${encodeURIComponent(query)}&limit=50`, {
      credentials: 'include',
      headers: getLocaleHeaders(),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(t('uwmDemand7.errors.search'));
    setUnits(arr<Row>(payload.units));
  };

  const loadDetail = async (selected = unitId) => {
    const response = await fetch(`/api/uwm/livability/demand7/units/${encodeURIComponent(selected)}`, {
      credentials: 'include',
      headers: getLocaleHeaders(),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(t('uwmDemand7.errors.detail'));
    setDetail(payload);
    setPlan(null);
  };

  const initialize = async () => {
    setLoading(true);
    setMessage('');
    try {
      await Promise.all([loadOverview(), searchUnits(unitId), loadDetail(unitId)]);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t('uwmDemand7.errors.unavailable'));
    } finally {
      setLoading(false);
    }
  };

  const selectUnit = async (selected: string) => {
    setUnitId(selected);
    const parts = selected.split('|');
    setSearch(isChinese ? selected : parts[parts.length - 1] || selected);
    setLoading(true);
    setMessage('');
    try {
      await loadDetail(selected);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t('uwmDemand7.errors.detail'));
    } finally {
      setLoading(false);
    }
  };

  const runPlan = async () => {
    setLoading(true);
    setMessage('');
    setPlan(null);
    try {
      const response = await fetch('/api/uwm/livability/demand7/plan', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify({ unit_id: unitId, target_profile: profile, horizon }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(t('uwmDemand7.errors.plan'));
      setPlan(payload);
      if (payload.status === 'completed' && payload.map_payload) {
        window.__handleMapUpdate?.(localizedMapPayload(payload.map_payload));
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t('uwmDemand7.errors.plan'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setSearch(isChinese ? TARGET_UNIT : '498');
    initialize();
  }, [i18n.resolvedLanguage]);

  const recommendation = plan?.recommended_action || {};
  const current = detail?.current_state || {};
  const target = plan?.peer_target || overview?.target_definition?.profile_targets?.[profile] || detail?.peer_target || {};
  const projected = recommendation.projected_state || {};
  const recommendationAction = translatedValue('actions', recommendation.action_type);

  return <div className="uwm-livability-panel" data-testid="uwm-demand7-panel">
    <div className="uwm-livability-panel-title">
      <Target size={16} /><strong>{t('uwmDemand7.title')}</strong>
      <button className="secondary-button" onClick={initialize} disabled={loading}>
        <RefreshCw size={14} />{t('uwmDemand7.refresh')}
      </button>
    </div>
    <p>{t('uwmDemand7.description', {
      nodes: number(1017, 0),
      edges: number(7932, 0),
      transitions: number(6817, 0),
    })}</p>
    {message && <div className="traditional-message error"><AlertTriangle size={15} />{message}</div>}
    <div className="uwm-evidence-grid">
      <div><span>{t('uwmDemand7.kpis.stateNodes')}</span><strong>{number(overview?.counts?.state_nodes, 0)}</strong></div>
      <div><span>{t('uwmDemand7.kpis.spatialEdges')}</span><strong>{number(overview?.counts?.spatial_edges, 0)}</strong></div>
      <div><span>{t('uwmDemand7.kpis.availableActions')}</span><strong>{number(overview?.counts?.available_actions, 0)}</strong></div>
      <div><span>{t('uwmDemand7.kpis.replayTransitions')}</span><strong>{number(overview?.counts?.stored_replay_transitions, 0)}</strong></div>
    </div>

    <div className="traditional-form-grid">
      <label>{t('uwmDemand7.form.unitSearch')}
        <div className="traditional-inline-actions">
          <input value={search} onChange={event => setSearch(event.target.value)} placeholder={t('uwmDemand7.form.searchPlaceholder')} />
          <button className="secondary-button" onClick={() => searchUnits()} disabled={loading}><Search size={14} />{t('uwmDemand7.form.search')}</button>
        </div>
      </label>
      <label>{t('uwmDemand7.form.results')}
        <select value={unitId} onChange={event => selectUnit(event.target.value)}>
          {!units.some(unit => unit.unit_id === unitId) && <option value={unitId}>{unitLabel(unitId)}</option>}
          {units.map(unit => <option key={unit.unit_id} value={unit.unit_id}>{t('uwmDemand7.resultOption', { unit: unitLabel(unit.unit_id), score: number(unit.livability_need_score, 3) })}</option>)}
        </select>
      </label>
      <label>{t('uwmDemand7.form.profile')}
        <select value={profile} onChange={event => { setProfile(event.target.value); setPlan(null); }}>
          {PROFILE_IDS.map(value => <option key={value} value={value}>{t(`uwmDemand7.profiles.${value}`)}</option>)}
        </select>
      </label>
      <label>{t('uwmDemand7.form.horizon')}
        <select value={horizon} onChange={event => { setHorizon(event.target.value); setPlan(null); }}>
          <option value="simulator_step">{t('uwmDemand7.horizons.simulatorStep')}</option>
          <option value="24_month">{t('uwmDemand7.horizons.month24')}</option>
          <option value="five_year">{t('uwmDemand7.horizons.fiveYear')}</option>
        </select>
      </label>
    </div>
    <button className="primary-button" onClick={runPlan} disabled={loading || !detail}>{t('uwmDemand7.run')}</button>

    {detail && <>
      <h4>{t('uwmDemand7.current.title')}</h4>
      <div className="uwm-evidence-grid">
        {INDICATORS.map(([key, lowerBetter]) => <div key={key}>
          <span>{t(`uwmDemand7.indicators.${key}`)}{lowerBetter ? t('uwmDemand7.current.lowerIsBetter') : ''}</span>
          <strong>{number(current[key])} {t('uwmDemand7.transitionArrow')} {number(target[key])}</strong>
        </div>)}
        <div><span>{t('uwmDemand7.current.actionMask')}</span><strong>{t('uwmDemand7.current.itemCount', { count: detail.available_action_count })}</strong></div>
      </div>
    </>}

    {plan?.status === 'blocked' && <div className="traditional-message error" data-testid="demand7-blocked">
      <AlertTriangle size={16} /><div><strong>{horizon === '24_month' ? t('uwmDemand7.blocked.month24') : t('uwmDemand7.blocked.fiveYear')}</strong><br />{t('uwmDemand7.blocked.boundary')}</div>
    </div>}

    {plan?.status === 'completed' && <div data-testid="demand7-result">
      <h4>{t('uwmDemand7.result.title')}</h4>
      <div className="traditional-message success"><ShieldCheck size={16} /><div>
        <Trans
          i18nKey="uwmDemand7.result.summary"
          values={{
            action: recommendationAction,
            closure: number(recommendation.weighted_gap_closure, 6),
            count: number(recommendation.affected_unit_count, 0),
          }}
          components={{ action: <strong /> }}
        />
      </div></div>
      <div className="uwm-evidence-grid">
        {INDICATORS.map(([key]) => <div key={key}><span>{t(`uwmDemand7.indicators.${key}`)}</span><strong>{number(current[key])} {t('uwmDemand7.transitionArrow')} {number(projected[key])}</strong><small>Δ {Number(recommendation.target_unit_delta?.[key] || 0) >= 0 ? '+' : ''}{number(recommendation.target_unit_delta?.[key])}</small></div>)}
      </div>
      <button className="secondary-button" onClick={() => window.__handleMapUpdate?.(localizedMapPayload(plan.map_payload))}><Map size={14} />{t('uwmDemand7.result.sendToMap')}</button>
      <p>{t('uwmDemand7.result.evidence', { grade: translatedValue('evidenceGrades', recommendation.evidence_grade) })}</p>
    </div>}

    <div className="traditional-message error"><AlertTriangle size={15} />{t('uwmDemand7.boundary.horizon')}</div>
    <p><strong>{t('uwmDemand7.boundary.label')}</strong>{t('uwmDemand7.boundary.description')}</p>
  </div>;
}
