import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  Database,
  FileCheck2,
  Fingerprint,
  HardDrive,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  X,
} from 'lucide-react';
import {
  createArchitectureChangeReview,
  getArchitectureChangeApprovalCase,
  getResourceVersionArchitecture,
  getResourceVersionArchitectureReconciliation,
  listResourceVersions,
  PlatformControlApiError,
  type ApprovalCase,
  type ArchitectureReconciliation,
  type ResourceVersion,
  type ResourceVersionArchitecture,
} from './platformControlApi';
import { formatDate, formatNumber } from '../../i18n';

const PAGE_SIZE = 30;
const REVIEWABLE_STATUSES = new Set([
  'schema_drift',
  'location_drift',
  'schema_and_location_drift',
  'tombstoned',
]);

function resourceName(resourceUrn: string): string {
  const parts = resourceUrn.split('/');
  return parts[parts.length - 1] || resourceUrn;
}

function resourceKind(resourceUrn: string): string {
  const parts = resourceUrn.split('/');
  return parts[parts.length - 2] || 'resource';
}

function formatModelDate(value?: string | null): string {
  if (!value) return '-';
  return formatDate(value, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function shortFingerprint(value?: string | null): string {
  if (!value) return '-';
  return value.length > 18 ? `${value.slice(0, 10)}...${value.slice(-6)}` : value;
}

function statusTone(status?: string): string {
  if (status === 'in_sync') return 'healthy';
  if (status === 'unobserved' || status === 'unbound' || status === 'stale') return 'warning';
  return status ? 'critical' : 'neutral';
}

function ComponentFact({
  icon,
  title,
  present,
  primary,
  secondary,
  fingerprint,
}: {
  icon: ReactNode;
  title: string;
  present: boolean;
  primary: string;
  secondary: string;
  fingerprint?: string | null;
}) {
  const { t } = useTranslation('common');
  return (
    <article className={`model-component-fact ${present ? 'present' : 'missing'}`}>
      <div className="model-component-icon">{icon}</div>
      <div className="model-component-body">
        <div className="model-component-title">
          <strong>{title}</strong>
          <span>{present
            ? t('dataModelWorkbench.components.registered')
            : t('dataModelWorkbench.components.missing')}</span>
        </div>
        <div className="model-component-primary">{primary}</div>
        <div className="model-component-secondary">{secondary}</div>
      </div>
      {fingerprint && (
        <code className="model-component-fingerprint" title={fingerprint}>
          {shortFingerprint(fingerprint)}
        </code>
      )}
    </article>
  );
}

export default function DataModelWorkbenchTab({ userRole = 'analyst' }: { userRole?: string }) {
  const { t, i18n } = useTranslation('common');
  const canReadPlatform = userRole === 'admin' || userRole === 'platform_operator';
  const [versions, setVersions] = useState<ResourceVersion[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [architecture, setArchitecture] = useState<ResourceVersionArchitecture | null>(null);
  const [reconciliation, setReconciliation] = useState<ArchitectureReconciliation | null>(null);
  const [search, setSearch] = useState('');
  const [hasMore, setHasMore] = useState(false);
  const [listLoading, setListLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [approvalCase, setApprovalCase] = useState<ApprovalCase | null>(null);
  const [approvalError, setApprovalError] = useState('');
  const [reviewFormOpen, setReviewFormOpen] = useState(false);
  const [reviewReason, setReviewReason] = useState('');
  const [reviewExpiryHours, setReviewExpiryHours] = useState(72);
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const errorText = (error: unknown): string => {
    if (error instanceof PlatformControlApiError) {
      if (error.status === 401) return t('dataModelWorkbench.errors.unauthorized');
      if (error.status === 403) return t('dataModelWorkbench.errors.forbidden');
      return error.requestId ? `${error.message} (${error.requestId})` : error.message;
    }
    return error instanceof Error ? error.message : t('dataModelWorkbench.errors.unavailable');
  };
  const statusLabel = (status: string) => t(`dataModelWorkbench.status.${status}`, {
    defaultValue: status,
  });
  const actionLabel = (action: string) => t(`dataModelWorkbench.actions.${action}`, {
    defaultValue: action,
  });
  const objectStateLabel = (state: string) => t(`dataModelWorkbench.objectState.${state}`, {
    defaultValue: state,
  });
  const approvalStatusLabel = (status: ApprovalCase['status']) => (
    t(`dataModelWorkbench.approval.status.${status}`)
  );

  useEffect(() => {
    if (!canReadPlatform) return;
    const controller = new AbortController();
    setListLoading(true);
    setListError('');
    listResourceVersions(PAGE_SIZE, 0, controller.signal)
      .then(page => {
        setVersions(page.items);
        setHasMore(page.has_more);
        setSelectedId(current => (
          current && page.items.some(item => item.resource_version_id === current)
            ? current
            : page.items[0]?.resource_version_id || null
        ));
      })
      .catch(error => {
        if (!(error instanceof DOMException && error.name === 'AbortError')) {
          setListError(errorText(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setListLoading(false);
      });
    return () => controller.abort();
  }, [canReadPlatform, refreshToken, i18n.resolvedLanguage]);

  useEffect(() => {
    if (!selectedId || !canReadPlatform) {
      setArchitecture(null);
      setReconciliation(null);
      return;
    }
    const controller = new AbortController();
    setDetailLoading(true);
    setDetailError('');
    setApprovalError('');
    setApprovalCase(null);
    setReviewFormOpen(false);
    Promise.all([
      getResourceVersionArchitecture(selectedId, controller.signal),
      getResourceVersionArchitectureReconciliation(selectedId, controller.signal),
    ])
      .then(async ([architectureValue, reconciliationValue]) => {
        setArchitecture(architectureValue);
        setReconciliation(reconciliationValue);
        const observation = reconciliationValue.latest_observation;
        if (observation && REVIEWABLE_STATUSES.has(reconciliationValue.status)) {
          try {
            const existingCase = await getArchitectureChangeApprovalCase(
              observation.observation_id,
              controller.signal,
            );
            if (!controller.signal.aborted) setApprovalCase(existingCase);
          } catch (error) {
            if (!(error instanceof DOMException && error.name === 'AbortError')) {
              setApprovalError(errorText(error));
            }
          }
        }
      })
      .catch(error => {
        if (!(error instanceof DOMException && error.name === 'AbortError')) {
          setArchitecture(null);
          setReconciliation(null);
          setDetailError(errorText(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [canReadPlatform, selectedId, refreshToken, i18n.resolvedLanguage]);

  const filteredVersions = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return versions;
    return versions.filter(version => (
      version.resource_urn.toLowerCase().includes(query)
      || version.resource_version_id.toLowerCase().includes(query)
      || version.version_key.toLowerCase().includes(query)
    ));
  }, [search, versions]);

  const selectedVersion = versions.find(
    version => version.resource_version_id === selectedId,
  ) || null;

  const loadMore = async () => {
    if (listLoading || !hasMore) return;
    setListLoading(true);
    setListError('');
    try {
      const page = await listResourceVersions(PAGE_SIZE, versions.length);
      setVersions(current => [...current, ...page.items]);
      setHasMore(page.has_more);
    } catch (error) {
      setListError(errorText(error));
    } finally {
      setListLoading(false);
    }
  };

  const submitArchitectureReview = async () => {
    const reason = reviewReason.trim();
    if (!selectedId || !reason || reviewSubmitting) return;
    setReviewSubmitting(true);
    setApprovalError('');
    try {
      const result = await createArchitectureChangeReview(
        selectedId,
        reason,
        reviewExpiryHours,
      );
      setApprovalCase(result.approval_case);
      setArchitecture(result.reconciliation.architecture);
      setReconciliation(result.reconciliation);
      setReviewFormOpen(false);
      setReviewReason('');
    } catch (error) {
      setApprovalError(errorText(error));
    } finally {
      setReviewSubmitting(false);
    }
  };

  if (!canReadPlatform) {
    return (
      <div className="model-access-denied" role="alert">
        <ShieldCheck aria-hidden="true" />
        <strong>{t('dataModelWorkbench.accessDeniedTitle')}</strong>
        <span>{t('dataModelWorkbench.accessDeniedDescription')}</span>
      </div>
    );
  }

  const schema = architecture?.schema_version_record;
  const contract = architecture?.data_contract_version_record;
  const location = architecture?.physical_location;
  const binding = architecture?.binding;
  const observation = reconciliation?.latest_observation;
  const currentStatus = reconciliation?.status || '';
  const canRequestReview = REVIEWABLE_STATUSES.has(currentStatus);
  const approvalExpired = approvalCase?.status === 'pending'
    && new Date(approvalCase.expires_at).getTime() <= Date.now();

  return (
    <div className="model-workbench">
      <div className="model-workbench-toolbar">
        <div className="model-workbench-heading">
          <Boxes aria-hidden="true" />
          <div>
            <strong>{t('dataModelWorkbench.title')}</strong>
            <span>{t('dataModelWorkbench.resourceVersionCount', {
              count: formatNumber(versions.length),
            })}</span>
          </div>
        </div>
        <button
          className="model-icon-button"
          onClick={() => setRefreshToken(value => value + 1)}
          disabled={listLoading || detailLoading}
          title={t('dataModelWorkbench.refresh')}
          aria-label={t('dataModelWorkbench.refresh')}
        >
          <RefreshCw className={listLoading || detailLoading ? 'spinning' : ''} />
        </button>
      </div>

      <div className="model-workbench-layout">
        <aside className="model-version-browser" aria-label={t('dataModelWorkbench.resourceVersionsAria')}>
          <label className="model-search">
            <Search aria-hidden="true" />
            <input
              value={search}
              onChange={event => setSearch(event.target.value)}
              placeholder={t('dataModelWorkbench.searchPlaceholder')}
            />
          </label>

          {listError && (
            <div className="model-inline-error" role="alert">
              <AlertTriangle aria-hidden="true" />
              <span>{listError}</span>
            </div>
          )}

          <div className="model-version-list">
            {filteredVersions.map(version => (
              <button
                key={version.resource_version_id}
                className={selectedId === version.resource_version_id ? 'active' : ''}
                onClick={() => setSelectedId(version.resource_version_id)}
              >
                <span className="model-version-kind">{resourceKind(version.resource_urn)}</span>
                <strong title={version.resource_urn}>{resourceName(version.resource_urn)}</strong>
                <small>{version.version_key} · {formatModelDate(version.created_at)}</small>
                <ChevronRight className="rtl-flip" aria-hidden="true" />
              </button>
            ))}
            {!listLoading && filteredVersions.length === 0 && (
              <div className="model-empty-state">{t('dataModelWorkbench.emptyVersions')}</div>
            )}
          </div>

          {hasMore && !search && (
            <button className="model-load-more" onClick={loadMore} disabled={listLoading}>
              {listLoading ? t('dataModelWorkbench.loading') : t('dataModelWorkbench.loadMore')}
            </button>
          )}
        </aside>

        <main className="model-detail">
          {detailLoading && !architecture && (
            <div className="model-detail-loading">
              <RefreshCw className="spinning" aria-hidden="true" />
              <span>{t('dataModelWorkbench.loadingArchitecture')}</span>
            </div>
          )}

          {detailError && (
            <div className="model-inline-error detail" role="alert">
              <AlertTriangle aria-hidden="true" />
              <span>{detailError}</span>
            </div>
          )}

          {selectedVersion && architecture && reconciliation && (
            <>
              <header className="model-detail-header">
                <div>
                  <span className="model-detail-kind">{resourceKind(selectedVersion.resource_urn)}</span>
                  <h3>{resourceName(selectedVersion.resource_urn)}</h3>
                  <code title={selectedVersion.resource_urn}>{selectedVersion.resource_urn}</code>
                </div>
                <span className={`model-status-badge ${statusTone(currentStatus)}`}>
                  {statusLabel(currentStatus)}
                </span>
              </header>

              <section className="model-summary" aria-label={t('dataModelWorkbench.summaryAria')}>
                <div>
                  <span>{t('dataModelWorkbench.summary.architectureReady')}</span>
                  <strong className={architecture.architecture_ready ? 'healthy' : 'warning'}>
                    {architecture.architecture_ready
                      ? t('dataModelWorkbench.boolean.yes')
                      : t('dataModelWorkbench.boolean.no')}
                  </strong>
                </div>
                <div>
                  <span>{t('dataModelWorkbench.summary.componentCompleteness')}</span>
                  <strong>{formatNumber(4 - architecture.missing_components.length)}/{formatNumber(4)}</strong>
                </div>
                <div>
                  <span>{t('dataModelWorkbench.summary.schemaMatches')}</span>
                  <strong>{reconciliation.schema_matches == null
                    ? '-'
                    : reconciliation.schema_matches
                      ? t('dataModelWorkbench.boolean.yes')
                      : t('dataModelWorkbench.boolean.no')}</strong>
                </div>
                <div>
                  <span>{t('dataModelWorkbench.summary.locationMatches')}</span>
                  <strong>{reconciliation.location_matches == null
                    ? '-'
                    : reconciliation.location_matches
                      ? t('dataModelWorkbench.boolean.yes')
                      : t('dataModelWorkbench.boolean.no')}</strong>
                </div>
              </section>

              <section className="model-detail-section">
                <div className="model-section-heading">
                  <Database aria-hidden="true" />
                  <h4>{t('dataModelWorkbench.components.title')}</h4>
                  <span>{architecture.missing_components.length
                    ? t('dataModelWorkbench.components.missingCount', {
                      count: formatNumber(architecture.missing_components.length),
                    })
                    : t('dataModelWorkbench.components.complete')}</span>
                </div>
                <div className="model-component-list">
                  <ComponentFact
                    icon={<Database aria-hidden="true" />}
                    title={t('dataModelWorkbench.components.technicalStructure')}
                    present={Boolean(schema)}
                    primary={schema ? `${schema.authority_system} · ${schema.schema_format}` : t('dataModelWorkbench.components.schemaNotRegistered')}
                    secondary={schema ? `${schema.authority_namespace} / ${schema.authority_object_id} · ${schema.authority_version_ref}` : 'schema_version'}
                    fingerprint={schema?.schema_sha256}
                  />
                  <ComponentFact
                    icon={<FileCheck2 aria-hidden="true" />}
                    title={t('dataModelWorkbench.components.dataContract')}
                    present={Boolean(contract)}
                    primary={contract ? `${contract.contract_kind} · ${contract.enforcement_mode}` : t('dataModelWorkbench.components.contractNotRegistered')}
                    secondary={contract ? `${contract.authority_system} · ${contract.authority_namespace} / ${contract.authority_object_id}` : 'data_contract_version'}
                    fingerprint={contract?.contract_sha256}
                  />
                  <ComponentFact
                    icon={<HardDrive aria-hidden="true" />}
                    title={t('dataModelWorkbench.components.physicalLocation')}
                    present={Boolean(location)}
                    primary={location ? `${location.provider_system} · ${location.location_kind}` : t('dataModelWorkbench.components.locationNotRegistered')}
                    secondary={location ? `${location.provider_namespace} / ${location.provider_locator} · ${location.snapshot_ref || location.revision_ref}` : 'physical_location'}
                    fingerprint={location?.location_sha256}
                  />
                  <ComponentFact
                    icon={<Fingerprint aria-hidden="true" />}
                    title={t('dataModelWorkbench.components.architectureBinding')}
                    present={Boolean(binding)}
                    primary={binding
                      ? t('dataModelWorkbench.components.boundAt', { date: formatModelDate(binding.bound_at) })
                      : t('dataModelWorkbench.components.bindingNotRegistered')}
                    secondary={binding ? binding.bound_by : 'architecture_binding'}
                    fingerprint={binding?.binding_sha256}
                  />
                </div>
              </section>

              <section className="model-detail-section model-reconciliation-section">
                <div className="model-section-heading">
                  <RefreshCw aria-hidden="true" />
                  <h4>{t('dataModelWorkbench.reconciliation.title')}</h4>
                  <span>{formatModelDate(reconciliation.evaluated_at)}</span>
                </div>
                {observation ? (
                  <dl className="model-observation-grid">
                    <div><dt>{t('dataModelWorkbench.reconciliation.provider')}</dt><dd>{observation.provider_system}</dd></div>
                    <div><dt>{t('dataModelWorkbench.reconciliation.objectState')}</dt><dd>{objectStateLabel(observation.object_state)}</dd></div>
                    <div><dt>{t('dataModelWorkbench.reconciliation.observedAt')}</dt><dd>{formatModelDate(observation.observed_at)}</dd></div>
                    <div><dt>{t('dataModelWorkbench.reconciliation.validUntil')}</dt><dd>{formatModelDate(observation.fresh_until)}</dd></div>
                    <div className="wide"><dt>{t('dataModelWorkbench.reconciliation.object')}</dt><dd>{observation.provider_namespace} / {observation.provider_object_id}</dd></div>
                  </dl>
                ) : (
                  <div className="model-no-observation">{t('dataModelWorkbench.reconciliation.noObservation')}</div>
                )}
              </section>

              {reconciliation.required_actions.length > 0 && (
                <section className="model-detail-section model-actions-section">
                  <div className="model-section-heading">
                    <AlertTriangle aria-hidden="true" />
                    <h4>{t('dataModelWorkbench.requiredActions')}</h4>
                    <span>{t('dataModelWorkbench.itemCount', {
                      count: formatNumber(reconciliation.required_actions.length),
                    })}</span>
                  </div>
                  <ol>
                    {reconciliation.required_actions.map(action => (
                      <li key={action}>
                        <span>{actionLabel(action)}</span>
                        <code>{action}</code>
                      </li>
                    ))}
                  </ol>

                  {approvalError && (
                    <div className="model-inline-error model-approval-error" role="alert">
                      <AlertTriangle aria-hidden="true" />
                      <span>{approvalError}</span>
                    </div>
                  )}

                  {canRequestReview && approvalCase && (
                    <div className={`model-approval-state ${approvalCase.status} ${approvalExpired ? 'expired' : ''}`}>
                      <div className="model-approval-state-heading">
                        <ClipboardCheck aria-hidden="true" />
                        <strong>{approvalExpired
                          ? t('dataModelWorkbench.approval.expired')
                          : approvalStatusLabel(approvalCase.status)}</strong>
                        <span>v{approvalCase.state_version}</span>
                      </div>
                      <code title={approvalCase.approval_case_ref}>{approvalCase.approval_case_ref}</code>
                      <dl>
                        <div><dt>{t('dataModelWorkbench.approval.requester')}</dt><dd>{approvalCase.requester_subject}</dd></div>
                        <div><dt>{t('dataModelWorkbench.approval.expiresAt')}</dt><dd>{formatModelDate(approvalCase.expires_at)}</dd></div>
                        {approvalCase.decided_by && <div><dt>{t('dataModelWorkbench.approval.decider')}</dt><dd>{approvalCase.decided_by}</dd></div>}
                      </dl>
                    </div>
                  )}

                  {canRequestReview && !approvalCase && !reviewFormOpen && (
                    <button
                      className="model-review-button"
                      onClick={() => setReviewFormOpen(true)}
                    >
                      <ClipboardCheck aria-hidden="true" />
                      <span>{t('dataModelWorkbench.review.open')}</span>
                    </button>
                  )}

                  {canRequestReview && !approvalCase && reviewFormOpen && (
                    <div className="model-review-form">
                      <label>
                        <span>{t('dataModelWorkbench.review.reason')}</span>
                        <textarea
                          value={reviewReason}
                          onChange={event => setReviewReason(event.target.value)}
                          maxLength={512}
                          rows={3}
                          autoFocus
                          placeholder={t('dataModelWorkbench.review.reasonPlaceholder')}
                        />
                      </label>
                      <div className="model-review-form-footer">
                        <label>
                          <span>{t('dataModelWorkbench.review.expiry')}</span>
                          <select
                            value={reviewExpiryHours}
                            onChange={event => setReviewExpiryHours(Number(event.target.value))}
                          >
                            <option value={24}>{t('dataModelWorkbench.review.hours', { count: formatNumber(24) })}</option>
                            <option value={72}>{t('dataModelWorkbench.review.hours', { count: formatNumber(72) })}</option>
                            <option value={168}>{t('dataModelWorkbench.review.days', { count: formatNumber(7) })}</option>
                          </select>
                        </label>
                        <div>
                          <button
                            className="model-icon-button"
                            onClick={() => {
                              setReviewFormOpen(false);
                              setReviewReason('');
                            }}
                            disabled={reviewSubmitting}
                            title={t('dataModelWorkbench.review.cancel')}
                            aria-label={t('dataModelWorkbench.review.cancel')}
                          >
                            <X aria-hidden="true" />
                          </button>
                          <button
                            className="model-review-submit"
                            onClick={submitArchitectureReview}
                            disabled={!reviewReason.trim() || reviewSubmitting}
                          >
                            {reviewSubmitting
                              ? <RefreshCw className="spinning" aria-hidden="true" />
                              : <Send aria-hidden="true" />}
                            <span>{reviewSubmitting
                              ? t('dataModelWorkbench.review.submitting')
                              : t('dataModelWorkbench.review.submit')}</span>
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                </section>
              )}

              {reconciliation.status === 'in_sync' && (
                <div className="model-synchronized">
                  <CheckCircle2 aria-hidden="true" />
                  <span>{t('dataModelWorkbench.synchronized')}</span>
                </div>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
