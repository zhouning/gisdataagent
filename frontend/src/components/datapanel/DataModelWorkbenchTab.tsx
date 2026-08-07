import { useEffect, useMemo, useState, type ReactNode } from 'react';
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

const PAGE_SIZE = 30;
const REVIEWABLE_STATUSES = new Set([
  'schema_drift',
  'location_drift',
  'schema_and_location_drift',
  'tombstoned',
]);

const STATUS_LABELS: Record<string, string> = {
  unobserved: '未观测',
  unbound: '未绑定',
  in_sync: '一致',
  stale: '观测过期',
  schema_drift: '结构漂移',
  location_drift: '位置漂移',
  schema_and_location_drift: '结构与位置漂移',
  tombstoned: '源对象已删除',
};

const ACTION_LABELS: Record<string, string> = {
  harvest_provider: '采集提供方架构证据',
  register_architecture: '登记完整架构绑定',
  refresh_observation: '刷新提供方观测',
  review_schema_drift: '发起结构漂移复核',
  review_location_drift: '发起位置漂移复核',
  investigate_tombstone: '核查源对象删除事件',
};

const APPROVAL_STATUS_LABELS: Record<ApprovalCase['status'], string> = {
  pending: '待审批',
  approved: '已批准',
  rejected: '已驳回',
  cancelled: '已取消',
};

function resourceName(resourceUrn: string): string {
  const parts = resourceUrn.split('/');
  return parts[parts.length - 1] || resourceUrn;
}

function resourceKind(resourceUrn: string): string {
  const parts = resourceUrn.split('/');
  return parts[parts.length - 2] || 'resource';
}

function formatDate(value?: string | null): string {
  if (!value) return '-';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('zh-CN', {
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

function errorText(error: unknown): string {
  if (error instanceof PlatformControlApiError) {
    if (error.status === 401) return '登录状态已失效';
    if (error.status === 403) return '当前角色无权访问平台模型';
    return error.requestId ? `${error.message} (${error.requestId})` : error.message;
  }
  return error instanceof Error ? error.message : '平台模型暂不可用';
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
  return (
    <article className={`model-component-fact ${present ? 'present' : 'missing'}`}>
      <div className="model-component-icon">{icon}</div>
      <div className="model-component-body">
        <div className="model-component-title">
          <strong>{title}</strong>
          <span>{present ? '已登记' : '缺失'}</span>
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
  }, [canReadPlatform, refreshToken]);

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
  }, [canReadPlatform, selectedId, refreshToken]);

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
        <strong>平台角色权限不足</strong>
        <span>数据模型控制面仅对平台管理员和平台操作员开放。</span>
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
            <strong>数据模型</strong>
            <span>{versions.length} 个资源版本</span>
          </div>
        </div>
        <button
          className="model-icon-button"
          onClick={() => setRefreshToken(value => value + 1)}
          disabled={listLoading || detailLoading}
          title="刷新模型状态"
          aria-label="刷新模型状态"
        >
          <RefreshCw className={listLoading || detailLoading ? 'spinning' : ''} />
        </button>
      </div>

      <div className="model-workbench-layout">
        <aside className="model-version-browser" aria-label="资源版本">
          <label className="model-search">
            <Search aria-hidden="true" />
            <input
              value={search}
              onChange={event => setSearch(event.target.value)}
              placeholder="搜索资源或版本"
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
                <small>{version.version_key} · {formatDate(version.created_at)}</small>
                <ChevronRight aria-hidden="true" />
              </button>
            ))}
            {!listLoading && filteredVersions.length === 0 && (
              <div className="model-empty-state">暂无资源版本</div>
            )}
          </div>

          {hasMore && !search && (
            <button className="model-load-more" onClick={loadMore} disabled={listLoading}>
              {listLoading ? '加载中...' : '加载更多'}
            </button>
          )}
        </aside>

        <main className="model-detail">
          {detailLoading && !architecture && (
            <div className="model-detail-loading">
              <RefreshCw className="spinning" aria-hidden="true" />
              <span>正在读取架构权威视图...</span>
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
                  {STATUS_LABELS[currentStatus] || currentStatus}
                </span>
              </header>

              <section className="model-summary" aria-label="模型状态摘要">
                <div>
                  <span>架构就绪</span>
                  <strong className={architecture.architecture_ready ? 'healthy' : 'warning'}>
                    {architecture.architecture_ready ? '是' : '否'}
                  </strong>
                </div>
                <div>
                  <span>组件完整度</span>
                  <strong>{4 - architecture.missing_components.length}/4</strong>
                </div>
                <div>
                  <span>结构一致</span>
                  <strong>{reconciliation.schema_matches == null ? '-' : reconciliation.schema_matches ? '是' : '否'}</strong>
                </div>
                <div>
                  <span>位置一致</span>
                  <strong>{reconciliation.location_matches == null ? '-' : reconciliation.location_matches ? '是' : '否'}</strong>
                </div>
              </section>

              <section className="model-detail-section">
                <div className="model-section-heading">
                  <Database aria-hidden="true" />
                  <h4>架构组件</h4>
                  <span>{architecture.missing_components.length ? `${architecture.missing_components.length} 项缺失` : '绑定完整'}</span>
                </div>
                <div className="model-component-list">
                  <ComponentFact
                    icon={<Database aria-hidden="true" />}
                    title="技术结构"
                    present={Boolean(schema)}
                    primary={schema ? `${schema.authority_system} · ${schema.schema_format}` : '未登记 SchemaVersion'}
                    secondary={schema ? `${schema.authority_namespace} / ${schema.authority_object_id} · ${schema.authority_version_ref}` : 'schema_version'}
                    fingerprint={schema?.schema_sha256}
                  />
                  <ComponentFact
                    icon={<FileCheck2 aria-hidden="true" />}
                    title="数据契约"
                    present={Boolean(contract)}
                    primary={contract ? `${contract.contract_kind} · ${contract.enforcement_mode}` : '未登记 DataContractVersion'}
                    secondary={contract ? `${contract.authority_system} · ${contract.authority_namespace} / ${contract.authority_object_id}` : 'data_contract_version'}
                    fingerprint={contract?.contract_sha256}
                  />
                  <ComponentFact
                    icon={<HardDrive aria-hidden="true" />}
                    title="物理位置"
                    present={Boolean(location)}
                    primary={location ? `${location.provider_system} · ${location.location_kind}` : '未登记 PhysicalLocation'}
                    secondary={location ? `${location.provider_namespace} / ${location.provider_locator} · ${location.snapshot_ref || location.revision_ref}` : 'physical_location'}
                    fingerprint={location?.location_sha256}
                  />
                  <ComponentFact
                    icon={<Fingerprint aria-hidden="true" />}
                    title="架构绑定"
                    present={Boolean(binding)}
                    primary={binding ? `绑定于 ${formatDate(binding.bound_at)}` : '未登记 ArchitectureBinding'}
                    secondary={binding ? binding.bound_by : 'architecture_binding'}
                    fingerprint={binding?.binding_sha256}
                  />
                </div>
              </section>

              <section className="model-detail-section model-reconciliation-section">
                <div className="model-section-heading">
                  <RefreshCw aria-hidden="true" />
                  <h4>运行态对账</h4>
                  <span>{formatDate(reconciliation.evaluated_at)}</span>
                </div>
                {observation ? (
                  <dl className="model-observation-grid">
                    <div><dt>提供方</dt><dd>{observation.provider_system}</dd></div>
                    <div><dt>对象状态</dt><dd>{observation.object_state}</dd></div>
                    <div><dt>观测时间</dt><dd>{formatDate(observation.observed_at)}</dd></div>
                    <div><dt>有效期至</dt><dd>{formatDate(observation.fresh_until)}</dd></div>
                    <div className="wide"><dt>对象</dt><dd>{observation.provider_namespace} / {observation.provider_object_id}</dd></div>
                  </dl>
                ) : (
                  <div className="model-no-observation">尚无提供方观测</div>
                )}
              </section>

              {reconciliation.required_actions.length > 0 && (
                <section className="model-detail-section model-actions-section">
                  <div className="model-section-heading">
                    <AlertTriangle aria-hidden="true" />
                    <h4>必需治理动作</h4>
                    <span>{reconciliation.required_actions.length} 项</span>
                  </div>
                  <ol>
                    {reconciliation.required_actions.map(action => (
                      <li key={action}>
                        <span>{ACTION_LABELS[action] || action}</span>
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
                        <strong>{approvalExpired ? '审批已过期' : APPROVAL_STATUS_LABELS[approvalCase.status]}</strong>
                        <span>v{approvalCase.state_version}</span>
                      </div>
                      <code title={approvalCase.approval_case_ref}>{approvalCase.approval_case_ref}</code>
                      <dl>
                        <div><dt>发起人</dt><dd>{approvalCase.requester_subject}</dd></div>
                        <div><dt>有效期至</dt><dd>{formatDate(approvalCase.expires_at)}</dd></div>
                        {approvalCase.decided_by && <div><dt>审批人</dt><dd>{approvalCase.decided_by}</dd></div>}
                      </dl>
                    </div>
                  )}

                  {canRequestReview && !approvalCase && !reviewFormOpen && (
                    <button
                      className="model-review-button"
                      onClick={() => setReviewFormOpen(true)}
                    >
                      <ClipboardCheck aria-hidden="true" />
                      <span>发起架构变更评审</span>
                    </button>
                  )}

                  {canRequestReview && !approvalCase && reviewFormOpen && (
                    <div className="model-review-form">
                      <label>
                        <span>评审原因</span>
                        <textarea
                          value={reviewReason}
                          onChange={event => setReviewReason(event.target.value)}
                          maxLength={512}
                          rows={3}
                          autoFocus
                        />
                      </label>
                      <div className="model-review-form-footer">
                        <label>
                          <span>有效期</span>
                          <select
                            value={reviewExpiryHours}
                            onChange={event => setReviewExpiryHours(Number(event.target.value))}
                          >
                            <option value={24}>24 小时</option>
                            <option value={72}>72 小时</option>
                            <option value={168}>7 天</option>
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
                            title="取消"
                            aria-label="取消"
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
                            <span>{reviewSubmitting ? '提交中...' : '提交评审'}</span>
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
                  <span>权威绑定与最新提供方证据一致</span>
                </div>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
