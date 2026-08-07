import { useEffect, useMemo, useState, type FormEvent } from 'react';
import {
  AlertTriangle,
  Ban,
  Bell,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileClock,
  Inbox,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  UserCheck,
  UserMinus,
  UserRound,
  XCircle,
} from 'lucide-react';
import {
  decideApprovalCase,
  getApprovalCaseAssignment,
  getApprovalCaseEvents,
  getApprovalCaseNotifications,
  listApprovalPrincipals,
  listApprovalCases,
  PlatformControlApiError,
  retryApprovalCaseNotification,
  transitionApprovalCaseAssignment,
  type ApprovalCase,
  type ApprovalCaseAssignment,
  type ApprovalCaseAssignmentEvent,
  type ApprovalAssignmentActorAccess,
  type ApprovalCaseEvent,
  type ApprovalCaseNotification,
  type ApprovalCaseNotificationRecoveryEvent,
  type ApprovalPrincipal,
} from './platformControlApi';

const PAGE_SIZE = 30;
type StatusFilter = '' | ApprovalCase['status'];
type Verdict = Exclude<ApprovalCase['status'], 'pending'>;
type AssignmentOperation = 'assign' | 'reassign' | 'delegate' | 'release';

const STATUS_LABELS: Record<ApprovalCase['status'], string> = {
  pending: '待审批',
  approved: '已批准',
  rejected: '已驳回',
  cancelled: '已取消',
};

const VERDICT_LABELS: Record<Verdict, string> = {
  approved: '批准',
  rejected: '驳回',
  cancelled: '取消',
};

const NOTIFICATION_KIND_LABELS: Record<ApprovalCaseNotification['notification_kind'], string> = {
  requested: '请求提醒',
  expired: '到期告警',
  decided: '关闭通知',
};

const NOTIFICATION_STATUS_LABELS: Record<ApprovalCaseNotification['status'], string> = {
  pending: '待投递',
  in_flight: '投递中',
  done: '已送达',
  failed: '投递失败',
  suppressed: '已抑制',
};

const ASSIGNMENT_ACTION_LABELS: Record<ApprovalCaseAssignmentEvent['action'], string> = {
  assigned: '指派',
  reassigned: '重指派',
  delegated: '委托',
  released: '释放',
  closed: '关闭',
};

function formatDate(value?: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function isExpired(item: ApprovalCase): boolean {
  return item.status === 'pending' && new Date(item.expires_at).getTime() <= Date.now();
}

function resourceName(resourceUrn: string): string {
  return resourceUrn.split('/').pop() || resourceUrn;
}

function principalLabel(principal: ApprovalPrincipal): string {
  return `${principal.display_name} · ${principal.principal_type === 'team' ? '团队' : '个人'}`;
}

function accessReasonText(reason?: string): string {
  const labels: Record<string, string> = {
    reserved: '该事项已由其他负责人或团队承接',
    not_registered: '当前账号尚未登记为审批主体',
    inactive: '当前审批主体已停用',
    not_approval_eligible: '当前账号未获得审批资格',
    unavailable: '当前账号处于不在岗状态',
    not_yet_valid: '审批资格尚未生效',
    expired: '审批资格已经到期',
    requester_is_not_independent: '申请人不能审批自己的申请',
  };
  return reason ? labels[reason] || '当前身份不满足审批资格规则' : '正在解析审批资格';
}

function compactJson(value: Record<string, unknown>, maxLength = 1800): string {
  const serialized = JSON.stringify(value, null, 2);
  return serialized.length > maxLength
    ? `${serialized.slice(0, maxLength)}\n...内容已截断`
    : serialized;
}

function errorText(error: unknown): string {
  if (error instanceof PlatformControlApiError) {
    if (error.status === 401) return '登录状态已失效';
    if (error.status === 403) return '当前身份无权执行该审批操作';
    if (error.status === 409) return '审批状态已变化，请刷新后重试';
    return error.requestId ? `${error.message} (${error.requestId})` : error.message;
  }
  return error instanceof Error ? error.message : '审批中心暂不可用';
}

export default function ApprovalInboxTab({
  userRole = 'analyst',
}: {
  userRole?: string;
  username?: string;
}) {
  const canUsePlatform = userRole === 'admin' || userRole === 'platform_operator';
  const [cases, setCases] = useState<ApprovalCase[]>([]);
  const [selectedRef, setSelectedRef] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('pending');
  const [actionInput, setActionInput] = useState('');
  const [actionFilter, setActionFilter] = useState('');
  const [hasMore, setHasMore] = useState(false);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [events, setEvents] = useState<ApprovalCaseEvent[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsError, setEventsError] = useState('');
  const [notifications, setNotifications] = useState<ApprovalCaseNotification[]>([]);
  const [assignment, setAssignment] = useState<ApprovalCaseAssignment | null>(null);
  const [assignmentEvents, setAssignmentEvents] = useState<ApprovalCaseAssignmentEvent[]>([]);
  const [actorAccess, setActorAccess] = useState<ApprovalAssignmentActorAccess | null>(null);
  const [approvalPrincipals, setApprovalPrincipals] = useState<ApprovalPrincipal[]>([]);
  const [assignmentOperation, setAssignmentOperation] = useState<AssignmentOperation>('assign');
  const [assigneeInput, setAssigneeInput] = useState('');
  const [assignmentReason, setAssignmentReason] = useState('');
  const [assignmentLoading, setAssignmentLoading] = useState(false);
  const [assignmentError, setAssignmentError] = useState('');
  const [recoveries, setRecoveries] = useState<ApprovalCaseNotificationRecoveryEvent[]>([]);
  const [recoveryTarget, setRecoveryTarget] = useState<string | null>(null);
  const [recoveryReason, setRecoveryReason] = useState('');
  const [recoveryLoading, setRecoveryLoading] = useState(false);
  const [recoveryError, setRecoveryError] = useState('');
  const [verdict, setVerdict] = useState<Verdict>('approved');
  const [reason, setReason] = useState('');
  const [decisionLoading, setDecisionLoading] = useState(false);
  const [decisionError, setDecisionError] = useState('');
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    if (!canUsePlatform) return;
    const controller = new AbortController();
    setListLoading(true);
    setListError('');
    listApprovalCases(
      {
        status: statusFilter || undefined,
        action: actionFilter || undefined,
        limit: PAGE_SIZE,
        offset: 0,
      },
      controller.signal,
    )
      .then(page => {
        setCases(page.items);
        setHasMore(page.has_more);
        setSelectedRef(current => (
          current && page.items.some(item => item.approval_case_ref === current)
            ? current
            : page.items[0]?.approval_case_ref || null
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
  }, [actionFilter, canUsePlatform, refreshToken, statusFilter]);

  const selectedCase = useMemo(
    () => cases.find(item => item.approval_case_ref === selectedRef) || null,
    [cases, selectedRef],
  );

  useEffect(() => {
    if (!selectedCase) {
      setEvents([]);
      setNotifications([]);
      setAssignment(null);
      setAssignmentEvents([]);
      setActorAccess(null);
      setRecoveries([]);
      return;
    }
    const controller = new AbortController();
    setEventsLoading(true);
    setEventsError('');
    setEvents([]);
    setNotifications([]);
    setAssignment(null);
    setAssignmentEvents([]);
    setActorAccess(null);
    setAssigneeInput('');
    setAssignmentReason('');
    setAssignmentError('');
    setRecoveries([]);
    setRecoveryTarget(null);
    setRecoveryReason('');
    setRecoveryError('');
    Promise.all([
      getApprovalCaseEvents(selectedCase.approval_case_ref, controller.signal),
      getApprovalCaseNotifications(selectedCase.approval_case_ref, controller.signal),
      getApprovalCaseAssignment(selectedCase.approval_case_ref, controller.signal),
      listApprovalPrincipals(true, controller.signal),
    ])
      .then(([eventItems, notificationView, assignmentView, principalView]) => {
        setEvents(eventItems);
        setNotifications(notificationView.items);
        setRecoveries(notificationView.recoveries);
        setAssignment(assignmentView.current);
        setAssignmentEvents(assignmentView.events);
        setActorAccess(assignmentView.actor_access);
        setApprovalPrincipals(principalView.items);
        setAssignmentOperation(
          !assignmentView.current || assignmentView.current.status === 'released'
            ? 'assign'
            : (userRole === 'admin' ? 'reassign' : 'delegate'),
        );
      })
      .catch(error => {
        if (!(error instanceof DOMException && error.name === 'AbortError')) {
          setEventsError(errorText(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setEventsLoading(false);
      });
    return () => controller.abort();
  }, [selectedCase?.approval_case_ref, selectedCase?.state_version, userRole]);

  const pageStats = useMemo(() => ({
    pending: cases.filter(item => item.status === 'pending' && !isExpired(item)).length,
    expired: cases.filter(isExpired).length,
    terminal: cases.filter(item => item.status !== 'pending').length,
  }), [cases]);

  const applyActionFilter = (event: FormEvent) => {
    event.preventDefault();
    setActionFilter(actionInput.trim());
  };

  const loadMore = async () => {
    if (listLoading || !hasMore) return;
    setListLoading(true);
    setListError('');
    try {
      const page = await listApprovalCases({
        status: statusFilter || undefined,
        action: actionFilter || undefined,
        limit: PAGE_SIZE,
        offset: cases.length,
      });
      setCases(current => [...current, ...page.items]);
      setHasMore(page.has_more);
    } catch (error) {
      setListError(errorText(error));
    } finally {
      setListLoading(false);
    }
  };

  const submitDecision = async (event: FormEvent) => {
    event.preventDefault();
    const normalizedReason = reason.trim();
    if (!selectedCase || !normalizedReason || decisionLoading) return;
    setDecisionLoading(true);
    setDecisionError('');
    try {
      const decided = await decideApprovalCase(selectedCase.approval_case_ref, {
        expected_state_version: selectedCase.state_version,
        verdict,
        reason: normalizedReason,
        details: { channel: 'approval_inbox' },
      });
      setCases(current => current.map(item => (
        item.approval_case_ref === decided.approval_case_ref ? decided : item
      )));
      setReason('');
    } catch (error) {
      setDecisionError(errorText(error));
    } finally {
      setDecisionLoading(false);
    }
  };

  const submitNotificationRecovery = async (
    event: FormEvent,
    notification: ApprovalCaseNotification,
  ) => {
    event.preventDefault();
    const normalizedReason = recoveryReason.trim();
    if (!selectedCase || !normalizedReason || recoveryLoading || userRole !== 'admin') return;
    setRecoveryLoading(true);
    setRecoveryError('');
    try {
      await retryApprovalCaseNotification(
        selectedCase.approval_case_ref,
        notification.notification_id,
        {
          expected_attempt_count: notification.attempt_count,
          reason: normalizedReason,
        },
      );
      const notificationView = await getApprovalCaseNotifications(
        selectedCase.approval_case_ref,
      );
      setNotifications(notificationView.items);
      setRecoveries(notificationView.recoveries);
      setRecoveryTarget(null);
      setRecoveryReason('');
    } catch (error) {
      setRecoveryError(errorText(error));
    } finally {
      setRecoveryLoading(false);
    }
  };

  const submitAssignment = async (event: FormEvent) => {
    event.preventDefault();
    const normalizedReason = assignmentReason.trim();
    const normalizedAssignee = assigneeInput.trim();
    if (
      !selectedCase
      || !normalizedReason
      || assignmentLoading
      || (assignmentOperation !== 'release' && !normalizedAssignee)
    ) return;
    setAssignmentLoading(true);
    setAssignmentError('');
    try {
      await transitionApprovalCaseAssignment(
        selectedCase.approval_case_ref,
        {
          expected_assignment_version: assignment?.assignment_version || 0,
          operation: assignmentOperation,
          ...(assignmentOperation === 'release' ? {} : { assignee_subject: normalizedAssignee }),
          reason: normalizedReason,
        },
      );
      const assignmentView = await getApprovalCaseAssignment(
        selectedCase.approval_case_ref,
      );
      setAssignment(assignmentView.current);
      setAssignmentEvents(assignmentView.events);
      setActorAccess(assignmentView.actor_access);
      setAssignmentOperation(
        assignmentView.current?.status === 'assigned'
          ? (userRole === 'admin' ? 'reassign' : 'delegate')
          : 'assign',
      );
      setAssigneeInput('');
      setAssignmentReason('');
    } catch (error) {
      setAssignmentError(errorText(error));
    } finally {
      setAssignmentLoading(false);
    }
  };

  if (!canUsePlatform) {
    return (
      <div className="model-access-denied" role="alert">
        <ShieldCheck aria-hidden="true" />
        <strong>平台角色权限不足</strong>
        <span>统一审批中心仅对平台管理员和平台操作员开放。</span>
      </div>
    );
  }

  const expired = selectedCase ? isExpired(selectedCase) : false;
  const decisionDisabled = !selectedCase
    || selectedCase.status !== 'pending'
    || expired
    || !actorAccess?.can_decide;
  const accessDenied = selectedCase?.status === 'pending'
    && !expired
    && actorAccess?.can_decide === false;
  const canAdminRoute = userRole === 'admin' && selectedCase?.status === 'pending' && !expired;
  const canDelegate = actorAccess?.can_delegate === true
    && selectedCase?.status === 'pending'
    && !expired;

  return (
    <div className="approval-inbox">
      <header className="approval-inbox-header">
        <div>
          <Inbox aria-hidden="true" />
          <span><strong>统一审批中心</strong><small>ApprovalCase 权威收件箱</small></span>
        </div>
        <button
          type="button"
          className="approval-icon-button"
          onClick={() => setRefreshToken(value => value + 1)}
          disabled={listLoading || decisionLoading}
          title="刷新审批状态"
          aria-label="刷新审批状态"
        >
          <RefreshCw className={listLoading ? 'spinning' : ''} />
        </button>
      </header>

      <div className="approval-inbox-summary" aria-label="当前页审批统计">
        <div><span>可处理</span><strong>{pageStats.pending}</strong></div>
        <div><span>已过期</span><strong>{pageStats.expired}</strong></div>
        <div><span>已终结</span><strong>{pageStats.terminal}</strong></div>
        <div><span>当前页</span><strong>{cases.length}</strong></div>
      </div>

      <form className="approval-inbox-filters" onSubmit={applyActionFilter}>
        <label>
          <span>状态</span>
          <select value={statusFilter} onChange={event => setStatusFilter(event.target.value as StatusFilter)}>
            <option value="pending">待审批</option>
            <option value="">全部</option>
            <option value="approved">已批准</option>
            <option value="rejected">已驳回</option>
            <option value="cancelled">已取消</option>
          </select>
        </label>
        <label className="approval-action-filter">
          <span>动作</span>
          <span className="approval-filter-input">
            <Search aria-hidden="true" />
            <input
              value={actionInput}
              onChange={event => setActionInput(event.target.value)}
              placeholder="精确动作标识"
              maxLength={128}
            />
          </span>
        </label>
        <button type="submit">筛选</button>
      </form>

      {listError && <div className="approval-error" role="alert"><AlertTriangle />{listError}</div>}

      <div className="approval-inbox-layout">
        <aside className="approval-case-browser" aria-label="审批事项">
          <div className="approval-case-list">
            {cases.map(item => {
              const itemExpired = isExpired(item);
              return (
                <button
                  type="button"
                  key={item.approval_case_ref}
                  className={selectedRef === item.approval_case_ref ? 'active' : ''}
                  onClick={() => {
                    setSelectedRef(item.approval_case_ref);
                    setDecisionError('');
                  }}
                >
                  <span className={`approval-status ${itemExpired ? 'expired' : item.status}`}>
                    {itemExpired ? '已过期' : STATUS_LABELS[item.status]}
                  </span>
                  <strong title={item.action}>{item.action}</strong>
                  <small title={item.target_resource_urn}>{resourceName(item.target_resource_urn)}</small>
                  <time>{formatDate(item.requested_at)}</time>
                  <ChevronRight aria-hidden="true" />
                </button>
              );
            })}
            {!listLoading && cases.length === 0 && <div className="approval-empty">暂无符合条件的审批事项</div>}
          </div>
          {hasMore && (
            <button type="button" className="approval-load-more" onClick={loadMore} disabled={listLoading}>
              {listLoading ? '加载中...' : '加载更多'}
            </button>
          )}
        </aside>

        <main className="approval-case-detail">
          {!selectedCase && <div className="approval-empty">选择审批事项查看详情</div>}
          {selectedCase && (
            <>
              <div className="approval-detail-heading">
                <div>
                  <span>{selectedCase.action}</span>
                  <h3>{resourceName(selectedCase.target_resource_urn)}</h3>
                  <code title={selectedCase.approval_case_ref}>{selectedCase.approval_case_ref}</code>
                </div>
                <span className={`approval-status ${expired ? 'expired' : selectedCase.status}`}>
                  {expired ? '已过期' : STATUS_LABELS[selectedCase.status]} · v{selectedCase.state_version}
                </span>
              </div>

              <dl className="approval-facts">
                <div><dt><UserRound />发起人</dt><dd>{selectedCase.requester_subject}</dd></div>
                <div><dt><Clock3 />有效期至</dt><dd>{formatDate(selectedCase.expires_at)}</dd></div>
                <div><dt>目标指纹</dt><dd><code title={selectedCase.target_fingerprint}>{selectedCase.target_fingerprint}</code></dd></div>
                <div><dt>目标资源</dt><dd>{selectedCase.target_resource_urn}</dd></div>
              </dl>

              <section className="approval-detail-section approval-assignment-section">
                <div className="approval-section-heading">
                  <h4><UserCheck />负责人路由</h4>
                  <span>{assignment ? `v${assignment.assignment_version}` : '未指派'}</span>
                </div>
                <div className={`approval-assignment-current ${assignment?.status || 'unassigned'}`}>
                  <UserRound />
                  <span>
                    <strong>
                      {assignment?.status === 'assigned'
                        ? approvalPrincipals.find(
                          item => item.principal_subject === assignment.assignee_subject,
                        )?.display_name || assignment.assignee_subject
                        : assignment?.status === 'closed'
                          ? '路由已关闭'
                          : '开放处理池'}
                    </strong>
                    <small>
                      {assignment
                        ? `${assignment.last_reason} · ${formatDate(assignment.updated_at)}`
                        : '尚未建立负责人约束'}
                    </small>
                  </span>
                  {assignment?.status === 'assigned' && (
                    <em>委托深度 {assignment.delegation_depth}/5</em>
                  )}
                </div>

                {assignmentEvents.length > 0 && (
                  <details className="approval-assignment-audit">
                    <summary>路由审计 {assignmentEvents.length} 条</summary>
                    <ol>
                      {assignmentEvents.map(item => (
                        <li key={item.assignment_event_id}>
                          <span>{ASSIGNMENT_ACTION_LABELS[item.action]} · v{item.assignment_version}</span>
                          <strong>{item.to_assignee_subject || '开放处理池'}</strong>
                          <small>{item.actor_subject} · {formatDate(item.occurred_at)}</small>
                          <p>{item.reason}</p>
                        </li>
                      ))}
                    </ol>
                  </details>
                )}

                {(canAdminRoute || canDelegate) && (
                  <form className="approval-assignment-form" onSubmit={submitAssignment}>
                    <div className="approval-assignment-actions" role="group" aria-label="负责人路由操作">
                      {canAdminRoute && (!assignment || assignment.status === 'released') && (
                        <button
                          type="button"
                          className={assignmentOperation === 'assign' ? 'active' : ''}
                          onClick={() => setAssignmentOperation('assign')}
                        ><UserCheck />指派</button>
                      )}
                      {canAdminRoute && assignment?.status === 'assigned' && (
                        <>
                          <button
                            type="button"
                            className={assignmentOperation === 'reassign' ? 'active' : ''}
                            onClick={() => setAssignmentOperation('reassign')}
                          ><UserCheck />重指派</button>
                          <button
                            type="button"
                            className={assignmentOperation === 'release' ? 'active' : ''}
                            onClick={() => setAssignmentOperation('release')}
                          ><UserMinus />释放</button>
                        </>
                      )}
                      {canDelegate && (
                        <button
                          type="button"
                          className={assignmentOperation === 'delegate' ? 'active' : ''}
                          onClick={() => setAssignmentOperation('delegate')}
                        ><UserRound />委托</button>
                      )}
                    </div>
                    {assignmentOperation !== 'release' && (
                      <label>
                        <span>目标负责人</span>
                        <select
                          value={assigneeInput}
                          onChange={event => setAssigneeInput(event.target.value)}
                        >
                          <option value="">选择当前合格主体</option>
                          {approvalPrincipals
                            .filter(item => item.principal_subject !== assignment?.assignee_subject)
                            .map(item => (
                              <option key={item.principal_subject} value={item.principal_subject}>
                                {principalLabel(item)}
                              </option>
                            ))}
                        </select>
                      </label>
                    )}
                    <label>
                      <span>路由理由</span>
                      <textarea
                        value={assignmentReason}
                        onChange={event => setAssignmentReason(event.target.value)}
                        maxLength={512}
                        placeholder="填写可审计的指派或委托依据"
                      />
                    </label>
                    {assignmentError && <div className="approval-error" role="alert"><AlertTriangle />{assignmentError}</div>}
                    <button
                      type="submit"
                      className="approval-assignment-submit"
                      disabled={
                        assignmentLoading
                        || !assignmentReason.trim()
                        || (assignmentOperation !== 'release' && !assigneeInput.trim())
                      }
                    >
                      {assignmentLoading ? '提交中...' : '确认路由变更'}
                    </button>
                  </form>
                )}
              </section>

              <section className="approval-detail-section">
                <h4>申请理由</h4>
                <p>{selectedCase.request_reason}</p>
                <h4>请求上下文</h4>
                <pre>{compactJson(selectedCase.request_context)}</pre>
              </section>

              <section className="approval-detail-section">
                <div className="approval-section-heading">
                  <h4><Bell />通知与 SLA</h4>
                  <span>{notifications.length} 条</span>
                </div>
                <div className="approval-notification-list">
                  {notifications.map(item => {
                    const itemRecoveries = recoveries.filter(
                      recovery => recovery.notification_id === item.notification_id,
                    );
                    const staleExpiry = item.notification_kind === 'expired'
                      && selectedCase.status !== 'pending';
                    const recoveryLimitReached = item.recovery_count >= 10;
                    const canRecover = userRole === 'admin'
                      && item.status === 'failed'
                      && !staleExpiry
                      && !recoveryLimitReached;
                    return (
                    <div key={item.notification_id}>
                      <span className={`approval-delivery-status ${item.status}`}>
                        {NOTIFICATION_STATUS_LABELS[item.status]}
                      </span>
                      <strong>{NOTIFICATION_KIND_LABELS[item.notification_kind]}</strong>
                      <small>{item.channel} · {item.destination_ref}</small>
                      <dl>
                        <div><dt>可投递</dt><dd>{formatDate(item.available_at)}</dd></div>
                        <div><dt>尝试</dt><dd>{item.attempt_count}/{item.max_attempts}</dd></div>
                        <div><dt>人工恢复</dt><dd>{item.recovery_count}/10</dd></div>
                        {item.completed_at && <div><dt>完成</dt><dd>{formatDate(item.completed_at)}</dd></div>}
                        {item.last_recovered_at && <div><dt>最近恢复</dt><dd>{formatDate(item.last_recovered_at)}</dd></div>}
                      </dl>
                      {item.last_error && <p title={item.last_error}>{item.last_error}</p>}
                      {item.last_recovered_by && (
                        <small className="approval-recovery-latest">
                          {item.last_recovered_by} · {item.last_recovery_reason}
                        </small>
                      )}
                      {itemRecoveries.length > 0 && (
                        <details className="approval-recovery-audit">
                          <summary>恢复审计 {itemRecoveries.length} 条</summary>
                          <ol>
                            {itemRecoveries.map(recovery => (
                              <li key={recovery.recovery_event_id}>
                                <strong>第 {recovery.recovery_no} 次</strong>
                                <span>{recovery.reason}</span>
                                <small>
                                  {recovery.actor_subject} · {formatDate(recovery.occurred_at)} · 原尝试 {recovery.previous_attempt_count}
                                </small>
                              </li>
                            ))}
                          </ol>
                        </details>
                      )}
                      {canRecover && recoveryTarget !== item.notification_id && (
                        <button
                          type="button"
                          className="approval-recovery-open"
                          onClick={() => {
                            setRecoveryTarget(item.notification_id);
                            setRecoveryReason('');
                            setRecoveryError('');
                          }}
                        >
                          <RotateCcw />人工恢复
                        </button>
                      )}
                      {item.status === 'failed' && (staleExpiry || recoveryLimitReached) && (
                        <small className="approval-recovery-blocked">
                          {staleExpiry ? '审批已终结，到期告警不可重放' : '已达到人工恢复上限'}
                        </small>
                      )}
                      {canRecover && recoveryTarget === item.notification_id && (
                        <form
                          className="approval-recovery-form"
                          onSubmit={event => submitNotificationRecovery(event, item)}
                        >
                          <label>
                            <span>恢复理由</span>
                            <textarea
                              value={recoveryReason}
                              onChange={event => setRecoveryReason(event.target.value)}
                              maxLength={512}
                              placeholder="填写故障处理和重投依据"
                            />
                          </label>
                          {recoveryError && <div className="approval-error" role="alert"><AlertTriangle />{recoveryError}</div>}
                          <div>
                            <button
                              type="button"
                              onClick={() => {
                                setRecoveryTarget(null);
                                setRecoveryReason('');
                                setRecoveryError('');
                              }}
                              disabled={recoveryLoading}
                            >取消</button>
                            <button type="submit" disabled={!recoveryReason.trim() || recoveryLoading}>
                              <RotateCcw />{recoveryLoading ? '恢复中...' : '确认重投'}
                            </button>
                          </div>
                        </form>
                      )}
                    </div>
                    );
                  })}
                  {!eventsLoading && notifications.length === 0 && (
                    <div className="approval-empty compact">暂无通知投递记录</div>
                  )}
                </div>
              </section>

              <section className="approval-detail-section">
                <div className="approval-section-heading">
                  <h4><FileClock />审计事件</h4>
                  <span>{events.length} 条</span>
                </div>
                {eventsError && <div className="approval-error" role="alert"><AlertTriangle />{eventsError}</div>}
                {eventsLoading && <div className="approval-empty compact">加载事件...</div>}
                {!eventsLoading && (
                  <ol className="approval-event-list">
                    {events.map(item => (
                      <li key={item.approval_event_id}>
                        <span className={`approval-event-dot ${item.to_status}`} />
                        <div>
                          <strong>{STATUS_LABELS[item.to_status]}</strong>
                          <p>{item.reason}</p>
                          <small>{item.actor_subject} · {formatDate(item.occurred_at)}</small>
                          {Object.keys(item.details).length > 0 && <pre>{compactJson(item.details, 700)}</pre>}
                        </div>
                      </li>
                    ))}
                  </ol>
                )}
              </section>

              <section className="approval-decision-section">
                {decisionDisabled ? (
                  <div className={`approval-terminal ${accessDenied ? 'reserved' : expired ? 'expired' : selectedCase.status}`}>
                    {accessDenied ? <UserRound /> : expired ? <Clock3 /> : <ShieldCheck />}
                    <span>
                      <strong>
                        {accessDenied
                          ? '当前身份不可处理此事项'
                          : expired
                            ? '审批窗口已关闭'
                            : selectedCase.status === 'pending'
                              ? '审批资格解析中'
                              : `该事项${STATUS_LABELS[selectedCase.status]}`}
                      </strong>
                      <small>
                        {accessDenied
                          ? accessReasonText(actorAccess?.access_reason)
                          : selectedCase.decision_reason || '不可再提交终态决定'}
                      </small>
                    </span>
                  </div>
                ) : (
                  <form onSubmit={submitDecision}>
                    <h4>提交终态决定</h4>
                    <div className="approval-verdict-control" role="group" aria-label="审批决定">
                      <button type="button" className={verdict === 'approved' ? 'active approved' : ''} onClick={() => setVerdict('approved')}><CheckCircle2 />批准</button>
                      <button type="button" className={verdict === 'rejected' ? 'active rejected' : ''} onClick={() => setVerdict('rejected')}><XCircle />驳回</button>
                      <button type="button" className={verdict === 'cancelled' ? 'active cancelled' : ''} onClick={() => setVerdict('cancelled')}><Ban />取消</button>
                    </div>
                    <label>
                      <span>{VERDICT_LABELS[verdict]}理由</span>
                      <textarea value={reason} onChange={event => setReason(event.target.value)} maxLength={512} placeholder="必须填写可审计的决定理由" />
                    </label>
                    {decisionError && <div className="approval-error" role="alert"><AlertTriangle />{decisionError}</div>}
                    <button className="approval-decision-submit" type="submit" disabled={!reason.trim() || decisionLoading}>
                      {decisionLoading ? '提交中...' : `确认${VERDICT_LABELS[verdict]}`}
                    </button>
                  </form>
                )}
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
