import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
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
import { formatNumber, getLocaleHeaders } from '../../i18n';

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
const CASES = [
  {
    key: 'addSchool',
    parcelId: 'parcel_79bb3178da33949459fc',
    target: 'village_public_service_land',
    actionType: 'add_facility' as BusinessAction,
    facilityClass: 'education.school',
    radius: '500',
  },
  {
    key: 'landUseOnly',
    parcelId: 'parcel_79bb3178da33949459fc',
    target: 'village_independent_construction_land',
    actionType: 'change_land_use' as BusinessAction,
    facilityClass: '',
    radius: '',
  },
  {
    key: 'publicService',
    parcelId: 'parcel_21fc78d2bdc55c84a859',
    target: 'village_public_service_land',
    actionType: 'change_land_use' as BusinessAction,
    facilityClass: '',
    radius: '',
  },
];

export default function UwmLivabilityS2Panel() {
  const { t, i18n } = useTranslation('common');
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
  const [rationale, setRationale] = useState(() => t('uwmS2.defaults.rationale'));
  const [rationaleKey, setRationaleKey] = useState('uwmS2.defaults.rationale');
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
        fetch('/api/uwm/livability/s2/catalog', { credentials: 'include', headers: getLocaleHeaders() }),
        fetch('/api/uwm/livability/s2/parcels', { credentials: 'include', headers: getLocaleHeaders() }),
        fetch('/api/uwm/livability/s2/facilities', { credentials: 'include', headers: getLocaleHeaders() }),
        fetch('/api/uwm/livability/s2/planning-projects', { credentials: 'include', headers: getLocaleHeaders() }),
      ]);
      const [catalogPayload, parcelsPayload, facilitiesPayload, projectsPayload] = await Promise.all([
        catalogResponse.json(),
        parcelsResponse.json(),
        facilitiesResponse.json(),
        projectsResponse.json(),
      ]);
      if (!catalogResponse.ok || !parcelsResponse.ok || !facilitiesResponse.ok || !projectsResponse.ok) {
        throw new Error(t('uwmS2.errors.load'));
      }
      setCatalog(catalogPayload);
      setParcels(arr(parcelsPayload.features));
      setFacilities(arr(facilitiesPayload.features));
      setPlanningProjects(arr(projectsPayload.projects));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('uwmS2.errors.load'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    if (rationaleKey) setRationale(t(rationaleKey));
  }, [i18n.resolvedLanguage]);

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
    const nextRationaleKey = `uwmS2.cases.${scenario.key}.rationale`;
    setRationaleKey(nextRationaleKey);
    setRationale(t(nextRationaleKey));
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
      setError(t('uwmS2.errors.requiredAction'));
      return;
    }
    if (actionType !== 'change_land_use' && (!facilityClass || Number(serviceRadius) <= 0)) {
      setError(t('uwmS2.errors.facilityFields'));
      return;
    }
    if (actionType === 'remove_facility' && !facilityId) {
      setError(t('uwmS2.errors.facilityRecord'));
      return;
    }
    const response = await fetch('/api/uwm/livability/s2/validate-action', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
      body: JSON.stringify(body()),
    });
    const payload = await response.json();
    setValidation(payload);
    if (!response.ok) {
      setError(t('uwmS2.errors.validation'));
    }
  };

  const rollout = async () => {
    if (!confirmed) {
      setError(t('uwmS2.errors.confirmation'));
      return;
    }
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/uwm/livability/s2/rollout', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getLocaleHeaders() },
        body: JSON.stringify(body()),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(t('uwmS2.errors.rollout'));
      setRun(payload);
      pushMap(payload);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('uwmS2.errors.rollout'));
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
      summary: { title: t('uwmS2.map.title') },
      layers,
      metadata,
    });
  const locate = () =>
    selected &&
    send([layer(t('uwmS2.map.target'), { type: 'FeatureCollection', features: [selected] }, MAP_STYLES.target)], {
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
        layer(t('uwmS2.map.target'), evidence.target_parcel || { type: 'FeatureCollection', features: [selected] }, MAP_STYLES.target),
        layer(t('uwmS2.map.affected'), evidence.affected_parcels || { type: 'FeatureCollection', features: [] }, MAP_STYLES.affected),
        layer(t('uwmS2.map.baseline'), evidence.baseline_service_areas || { type: 'FeatureCollection', features: [] }, MAP_STYLES.baseline),
        layer(t('uwmS2.map.intervention'), evidence.intervention_service_areas || { type: 'FeatureCollection', features: [] }, MAP_STYLES.intervention),
        layer(t('uwmS2.map.newlyCovered'), evidence.newly_covered_parcels || { type: 'FeatureCollection', features: [] }, MAP_STYLES.newlyCovered),
        layer(t('uwmS2.map.newlyUncovered'), evidence.newly_uncovered_parcels || { type: 'FeatureCollection', features: [] }, MAP_STYLES.newlyUncovered),
        layer(t('uwmS2.map.planningResources'), evidence.planning_resources || { type: 'FeatureCollection', features: [] }, MAP_STYLES.planningResource),
        layer(t('uwmS2.map.facilities'), evidence.facilities || { type: 'FeatureCollection', features: [] }, MAP_STYLES.facility),
      ],
      {
        evidence_only: true,
        proxy_distance_bands_m: [50, 150, 300],
        assessment_digest: rec(payload.business_assessment).assessment_digest,
        affected_node_ids: messages.map((message) => message.target_node_id),
      },
    );
  };

  useEffect(() => {
    if (run?.run_id) pushMap(run);
  }, [i18n.resolvedLanguage]);

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
  const recommendationCode = text(assessment.recommendation);
  const recommendation = assessment.recommendation
    ? t(`uwmS2.recommendations.${recommendationCode}`, { defaultValue: recommendationCode })
    : '-';
  const booleanLabel = (value: unknown) => t(`uwmS2.boolean.${Boolean(value) ? 'yes' : 'no'}`);
  const ruleLabel = (rule: string) => t(`uwmS2.rules.${rule}`, { defaultValue: rule });
  const percent = (value: unknown) => typeof value === 'number'
    ? formatNumber(value / 100, { style: 'percent', minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : '-';

  return (
    <section className="traditional-workspace s2-workspace">
      <div className="traditional-panel s2-header">
        <div>
          <h3>{t('uwmS2.header.title')}</h3>
          <p>{t('uwmS2.header.subtitle')}</p>
        </div>
        <button className="secondary-button" onClick={load} disabled={loading}>
          <RefreshCw size={14} />{t('uwmS2.header.refresh')}
        </button>
      </div>

      <div className="traditional-panel s2-boundary">
        <AlertTriangle size={18} />
        <div>
          <strong>{t('uwmS2.boundary.title')}</strong>
          <p>{t('uwmS2.boundary.description', {
            completeness: t(`uwmS2.completeness.${catalog.facility_inventory_complete ? 'complete' : 'incomplete'}`),
          })}</p>
        </div>
      </div>

      {error && <div className="traditional-error">{error}</div>}

      <div className="s2-case-row">
        {CASES.map((scenario) => (
          <button className="secondary-button" key={scenario.key} onClick={() => loadCase(scenario)}>
            {t(`uwmS2.cases.${scenario.key}.name`)}
          </button>
        ))}
      </div>

      <div className="s2-grid">
        <div className="traditional-panel">
          <h4>{t('uwmS2.steps.selectParcel')}</h4>
          <label className="s2-search-label">
            <Search size={14} />
            {t('uwmS2.parcel.searchLabel')}
            <input
              value={search}
              disabled={loading && !parcels.length}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t('uwmS2.parcel.searchPlaceholder')}
            />
          </label>
          <div className="s2-filter-row">
            <select value={villageFilter} onChange={(event) => setVillageFilter(event.target.value)}>
              <option value="">{t('uwmS2.parcel.allVillages')}</option>
              {villages.map((village) => <option key={village}>{village}</option>)}
            </select>
            <select value={landUseFilter} onChange={(event) => setLandUseFilter(event.target.value)}>
              <option value="">{t('uwmS2.parcel.allLandUses')}</option>
              {classes.map((item) => <option key={item}>{item}</option>)}
            </select>
          </div>
          <p>{loading && !parcels.length
            ? t('uwmS2.parcel.loading')
            : t('uwmS2.parcel.matchCount', {
              count: `${formatNumber(filtered.length)}${filtered.length === 30 ? '+' : ''}`,
              total: formatNumber(parcels.length),
            })}</p>
          <div className="s2-parcel-results">
            {filtered.map((parcel) => {
              const item = rec(parcel.properties);
              return (
                <button
                  aria-label={t('uwmS2.parcel.selectAria', { id: parcel.id })}
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
            {!loading && !filtered.length && <p>{t('uwmS2.parcel.empty')}</p>}
          </div>
        </div>

        <div className="traditional-panel">
          <h4>{t('uwmS2.steps.defineAction')}</h4>
          {selected ? (
            <>
              <div className="s2-parcel-card">
                <span>{t('uwmS2.parcel.id')}</span><strong>{parcelId}</strong>
                <span>{t('uwmS2.parcel.village')}</span><strong>{text(properties.planning_area_id)}</strong>
                <span>{t('uwmS2.parcel.sourceLandUse')}</span><strong>{text(properties.source_land_use_name)}</strong>
                <span>{t('uwmS2.parcel.currentLandUse')}</span><strong>{text(properties.current_land_use_class)}</strong>
                <span>{t('uwmS2.parcel.plannedLandUse')}</span><strong>{text(properties.planned_land_use_class)}</strong>
              </div>
              <button className="secondary-button" onClick={locate}><LocateFixed size={14} />{t('uwmS2.parcel.locate')}</button>
            </>
          ) : <p>{t('uwmS2.parcel.selectFirst')}</p>}

          <label>{t('uwmS2.action.label')}
            <select value={actionType} disabled={!selected} onChange={(event) => { setActionType(event.target.value as BusinessAction); reset(); }}>
              <option value="change_land_use">{t('uwmS2.action.changeLandUse')}</option>
              <option value="add_facility">{t('uwmS2.action.addFacility')}</option>
              <option value="remove_facility">{t('uwmS2.action.removeFacility')}</option>
            </select>
          </label>
          <label>{t('uwmS2.action.targetLandUse')}
            <select value={targetClass} disabled={!selected} onChange={(event) => { setTargetClass(event.target.value); reset(); }}>
              <option value="">{t('uwmS2.common.select')}</option>
              {arr<string>(catalog.land_use_classes).map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
          <label>{t('uwmS2.action.alternativeLandUse')}
            <select value={alternativeClass} disabled={!selected} onChange={(event) => { setAlternativeClass(event.target.value); reset(); }}>
              <option value="">{t('uwmS2.action.none')}</option>
              {arr<string>(catalog.land_use_classes).map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>

          {actionType !== 'change_land_use' && (
            <div className="s2-facility-action">
              <label>{t('uwmS2.action.facilityClass')}
                <input
                  list="s2-facility-classes"
                  value={facilityClass}
                  onChange={(event) => { setFacilityClass(event.target.value); setFacilityId(''); reset(); }}
                  placeholder={t('uwmS2.action.facilityPlaceholder')}
                />
                <datalist id="s2-facility-classes">
                  {arr<string>(catalog.observed_facility_classes).map((value) => <option key={value} value={value} />)}
                  <option value="education.school" />
                  <option value="healthcare.primary" />
                  <option value="park.public" />
                </datalist>
              </label>
              <label>{t('uwmS2.action.planningEvidence')}
                <select
                  value={planningProjectId}
                  onChange={(event) => {
                    const projectId = event.target.value;
                    const project = planningProjects.find((item) => item.project_id === projectId);
                    setPlanningProjectId(projectId);
                    if (project?.canonical_facility_class) setFacilityClass(project.canonical_facility_class);
                    if (project?.project_name) {
                      setRationaleKey('');
                      setRationale(t('uwmS2.action.projectRationale', { name: project.project_name }));
                    }
                    reset();
                  }}
                >
                  <option value="">{t('uwmS2.action.noPlanningProject')}</option>
                  {availablePlanningProjects.map((project) => (
                    <option key={project.project_id} value={project.project_id}>
                      {text(project.project_name)} · {text(project.canonical_facility_class)}
                    </option>
                  ))}
                </select>
              </label>
              {actionType === 'remove_facility' && (
                <label>{t('uwmS2.action.facilityRecord')}
                  <select value={facilityId} onChange={(event) => { setFacilityId(event.target.value); reset(); }}>
                    <option value="">{t('uwmS2.common.select')}</option>
                    {removableFacilities.map((facility) => (
                      <option key={facility.id} value={facility.id}>
                        {text(rec(facility.properties).name)} · {text(facility.id)}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label>{t('uwmS2.action.serviceRadius')}
                <input type="number" min="1" step="50" value={serviceRadius} onChange={(event) => { setServiceRadius(event.target.value); reset(); }} />
              </label>
              <label>{t('uwmS2.action.radiusEvidence')}
                <select value={radiusEvidenceSource} onChange={(event) => { setRadiusEvidenceSource(event.target.value); reset(); }}>
                  <option value="user_scenario_assumption">{t('uwmS2.action.userAssumption')}</option>
                  <option value="authoritative_profile">{t('uwmS2.action.authoritativeProfile')}</option>
                </select>
              </label>
              <label className="s2-confirm">
                <input type="checkbox" checked={criticalFacility} onChange={(event) => { setCriticalFacility(event.target.checked); reset(); }} />
                {t('uwmS2.action.criticalFacility')}
              </label>
            </div>
          )}

          <label>{t('uwmS2.action.rationale')}
            <textarea value={rationale} disabled={!selected} onChange={(event) => { setRationaleKey(''); setRationale(event.target.value); reset(); }} />
          </label>
          <p><strong>{t('uwmS2.action.snapshot')}</strong>{text(catalog.snapshot_digest)}</p>
        </div>

        <div className="traditional-panel">
          <h4>{t('uwmS2.steps.validate')}</h4>
          <button className="secondary-button" disabled={!selected || !targetClass || !rationale.trim()} onClick={validate}>
            <ShieldCheck size={14} />{t('uwmS2.validation.validateAction')}
          </button>
          {validation && (
            <div className="s2-validation-summary">
              <span>{t('uwmS2.validation.valid')}</span><strong>{booleanLabel(validationPayload.valid)}</strong>
              <span>{t('uwmS2.validation.transitionStatus')}</span><strong>{t(`statusLabels.${text(transition.status)}`, { defaultValue: text(transition.status) })}</strong>
              <span>{t('uwmS2.validation.preview')}</span><strong>{preview.recommendation
                ? t(`uwmS2.recommendations.${text(preview.recommendation)}`, { defaultValue: text(preview.recommendation) })
                : '-'}</strong>
              <span>{t('uwmS2.validation.reviewRequired')}</span><strong>{booleanLabel(validationPayload.review_required)}</strong>
              {arr<string>(preview.blockers).length > 0 && <p>{t('uwmS2.validation.blockers', { blockers: arr<string>(preview.blockers).join(' / ') })}</p>}
              <p>{transition.status === 'unresolved'
                ? t('uwmS2.validation.unresolved')
                : t('uwmS2.validation.resolved')}</p>
            </div>
          )}
          <label className="s2-confirm">
            <input type="checkbox" disabled={!validationReady} checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
            {t('uwmS2.validation.confirm')}
          </label>
          <button className="primary-button" disabled={loading || !validationReady || !confirmed} onClick={rollout}>
            <Play size={14} />{loading ? t('uwmS2.validation.running') : t('uwmS2.validation.run')}
          </button>
        </div>

        <div className="traditional-panel s2-business-result">
          <h4>{t('uwmS2.steps.result')}</h4>
          {!resultReady ? <p>{t('uwmS2.result.empty')}</p> : (
            <>
              <div className={`s2-recommendation ${text(assessment.recommendation)}`}>
                <span>{t('uwmS2.result.recommendation')}</span>
                <strong>{recommendation}</strong>
                <small>{text(assessment.evidence_level)}</small>
              </div>
              <div className="traditional-kpi-grid">
                <div className="traditional-kpi"><span>{t('uwmS2.result.baselineCoverage')}</span><strong>{percent(baselineCoverage.coverage_percent)}</strong></div>
                <div className="traditional-kpi"><span>{t('uwmS2.result.interventionCoverage')}</span><strong>{percent(interventionCoverage.coverage_percent)}</strong></div>
                <div className="traditional-kpi"><span>{t('uwmS2.result.deltaPoints')}</span><strong>{assessment.coverage_delta_percentage_points == null ? '-' : formatNumber(Number(assessment.coverage_delta_percentage_points), { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong></div>
                <div className="traditional-kpi"><span>{t('uwmS2.result.newlyCovered')}</span><strong>{formatNumber(arr(assessment.newly_covered_parcel_ids).length)}</strong></div>
              </div>
              <h5>{t('uwmS2.result.why')}</h5>
              <ol className="s2-explanation-chain">
                <li>{t('uwmS2.result.reasonSnapshot')} <code>{text(run?.snapshot_digest)}</code></li>
                <li>{t('uwmS2.result.reasonRadius', { radius: formatNumber(Number(assessment.parameters?.service_radius_m || 0)) })}</li>
                <li>{t('uwmS2.result.reasonCoverage', {
                  delta: formatNumber(Number(assessment.coverage_delta_percentage_points || 0), { maximumFractionDigits: 2 }),
                })}</li>
                <li>{t('uwmS2.result.reasonRules', { rules: arr<string>(assessment.triggered_rules).map(ruleLabel).join(t('uwmS2.common.listSeparator')) })}</li>
                <li>{t('uwmS2.result.reasonUwm')}</li>
              </ol>
              {arr<string>(assessment.blockers).length > 0 && <p><strong>{t('uwmS2.result.blockers')}</strong>{arr<string>(assessment.blockers).join(' / ')}</p>}
              {arr<string>(assessment.completeness_warnings).length > 0 && <p><strong>{t('uwmS2.result.warnings')}</strong>{arr<string>(assessment.completeness_warnings).join(' / ')}</p>}
              <p><strong>{t('uwmS2.result.claimBoundary')}</strong>{text(assessment.claim_boundary)}</p>
              {assessment.planning_project_evidence && (
                <div className="s2-project-evidence">
                  <h5>{t('uwmS2.result.projectEvidence')}</h5>
                  <p><strong>{text(assessment.planning_project_evidence.project_name)}</strong> · {text(assessment.planning_project_evidence.project_category)}</p>
                  <p>{t('uwmS2.result.projectLocation', {
                    location: text(assessment.planning_project_evidence.location_text),
                    status: text(assessment.planning_project_evidence.spatial_evidence_status),
                  })}</p>
                  <p>{t('uwmS2.result.projectSource', {
                    file: text(assessment.planning_project_evidence.source_ref?.source_file),
                    row: text(assessment.planning_project_evidence.source_ref?.excel_row),
                  })}</p>
                  <p>{t('uwmS2.result.projectBoundary')}</p>
                </div>
              )}
              <button className="secondary-button" onClick={() => pushMap()}><Map size={14} />{t('uwmS2.result.sendToMap')}</button>
            </>
          )}
        </div>
      </div>

      {resultReady && (
        <div className="traditional-panel">
          <h4><GitCompare size={16} /> {t('uwmS2.mechanism.title')}</h4>
          <div className="s2-timeline">
            <span>{t('uwmS2.mechanism.t0')}<br /><strong>{text(properties.current_land_use_class)}</strong></span>
            <ChevronRight />
            <span>{t('uwmS2.mechanism.action')}<br /><strong>{text(assessment.action?.action_type)}</strong></span>
            <ChevronRight />
            <span>{t('uwmS2.mechanism.t1')}<br /><strong>{text(rec(t1.direct_state_delta).to_land_use_class)}</strong></span>
            <ChevronRight />
            <span>{t('uwmS2.mechanism.t2')}<br /><strong>{t('uwmS2.mechanism.signals', { count: formatNumber(arr(t2.messages).length) })}</strong></span>
            <ChevronRight />
            <span>{t('uwmS2.mechanism.coverageDelta')}<br /><strong>{t('uwmS2.mechanism.percentagePoints', {
              value: formatNumber(Number(assessment.coverage_delta_percentage_points || 0), { maximumFractionDigits: 2 }),
            })}</strong></span>
          </div>
          <div className="traditional-kpi-grid">
            <div className="traditional-kpi"><span>{t('uwmS2.mechanism.nodes')}</span><strong>{formatNumber(Number(execution.rollout_node_count || 0))}</strong></div>
            <div className="traditional-kpi"><span>{t('uwmS2.mechanism.edges')}</span><strong>{t('uwmS2.mechanism.edgeCount', { count: formatNumber(Number(execution.rollout_edge_count || 0)) })}</strong></div>
            <div className="traditional-kpi"><span>{t('uwmS2.mechanism.villageAggregation')}</span><strong>{t('uwmS2.mechanism.crossScaleCount', { count: formatNumber(Number(execution.cross_scale_edge_count || 0)) })}</strong></div>
            <div className="traditional-kpi"><span>{t('uwmS2.mechanism.runId')}</span><strong>{text(run?.run_id)}</strong></div>
          </div>
          <p>{t('uwmS2.mechanism.distanceBoundary')}</p>
          <p>{t('uwmS2.mechanism.attribution')}</p>
          <h5>{t('uwmS2.mechanism.unavailableEffects')}</h5>
          <div className="s2-chip-list">{arr<string>(rolloutPayload.unavailable_effects).map((value) => <span key={value}>{value}</span>)}</div>
        </div>
      )}

      {resultReady && (
        <div className="traditional-panel">
          <button className="s2-audit-toggle" onClick={() => setAuditOpen((value) => !value)}>
            {auditOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}{t('uwmS2.audit.title')}
          </button>
          {auditOpen && (
            <div className="s2-audit-grid">
              <div><h5>{t('uwmS2.audit.directState')}</h5><pre>{JSON.stringify(rolloutPayload.direct_state_delta || {}, null, 2)}</pre></div>
              <div><h5>{t('uwmS2.audit.businessAssessment')}</h5><pre>{JSON.stringify(assessment, null, 2)}</pre></div>
              <div><h5>{t('uwmS2.audit.uncertainty')}</h5><pre>{JSON.stringify(rolloutPayload.uncertainty || {}, null, 2)}</pre></div>
              <div><h5>{t('uwmS2.audit.executionScope')}</h5><pre>{JSON.stringify(run?.execution_scope || {}, null, 2)}</pre></div>
              <div><h5>{t('uwmS2.audit.attributionLedger')}</h5><pre>{JSON.stringify(technicalAudit, null, 2)}</pre></div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
