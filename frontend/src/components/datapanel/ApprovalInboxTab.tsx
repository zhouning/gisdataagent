import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
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
import { formatDate, formatNumber } from '../../i18n';

const PAGE_SIZE = 30;
type StatusFilter = '' | ApprovalCase['status'];
type Verdict = Exclude<ApprovalCase['status'], 'pending'>;
type AssignmentOperation = 'assign' | 'reassign' | 'delegate' | 'release';

function formatApprovalDate(value?: string | null): string {
  if (!value) return '-';
  return formatDate(value, {
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

function compactJson(value: Record<string, unknown>, truncatedLabel: string, maxLength = 1800): string {
  const serialized = JSON.stringify(value, null, 2);
  return serialized.length > maxLength
    ? `${serialized.slice(0, maxLength)}\n${truncatedLabel}`
    : serialized;
}

export default function ApprovalInboxTab({
  userRole = 'analyst',
}: {
  userRole?: string;
  username?: string;
}) {
  const { t, i18n } = useTranslation('common');
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

  const statusLabel = (status: ApprovalCase['status']) => t(`approvalInbox.status.${status}`);
  const verdictLabel = (value: Verdict) => t(`approvalInbox.verdict.${value}`);
  const principalLabel = (principal: ApprovalPrincipal) => t('approvalInbox.principalLabel', {
    name: principal.display_name,
    type: t(`approvalInbox.principalType.${principal.principal_type}`),
  });
  const accessReasonText = (accessReason?: string) => accessReason
    ? t(`approvalInbox.accessReason.${accessReason}`, {
      defaultValue: t('approvalInbox.accessReason.default'),
    })
    : t('approvalInbox.accessReason.resolving');
  const errorText = (error: unknown) => {
    if (error instanceof PlatformControlApiError) {
      if (error.status === 401) return t('approvalInbox.errors.unauthorized');
      if (error.status === 403) return t('approvalInbox.errors.forbidden');
      if (error.status === 409) return t('approvalInbox.errors.conflict');
      return t('approvalInbox.errors.requestFailed', {
        requestId: error.requestId ? ` (${error.requestId})` : '',
      });
    }
    return error instanceof Error ? error.message : t('approvalInbox.errors.unavailable');
  };

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
  }, [actionFilter, canUsePlatform, refreshToken, statusFilter, i18n.resolvedLanguage]);

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
  }, [selectedCase?.approval_case_ref, selectedCase?.state_version, userRole, i18n.resolvedLanguage]);

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
        <strong>{t('approvalInbox.accessDeniedTitle')}</strong>
        <span>{t('approvalInbox.accessDeniedDescription')}</span>
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
          <span><strong>{t('approvalInbox.title')}</strong><small>{t('approvalInbox.subtitle')}</small></span>
        </div>
        <button
          type="button"
          className="approval-icon-button"
          onClick={() => setRefreshToken(value => value + 1)}
          disabled={listLoading || decisionLoading}
          title={t('approvalInbox.refresh')}
          aria-label={t('approvalInbox.refresh')}
        >
          <RefreshCw className={listLoading ? 'spinning' : ''} />
        </button>
      </header>

      <div className="approval-inbox-summary" aria-label={t('approvalInbox.pageStats')}>
        <div><span>{t('approvalInbox.stats.actionable')}</span><strong>{formatNumber(pageStats.pending)}</strong></div>
        <div><span>{t('approvalInbox.stats.expired')}</span><strong>{formatNumber(pageStats.expired)}</strong></div>
        <div><span>{t('approvalInbox.stats.terminal')}</span><strong>{formatNumber(pageStats.terminal)}</strong></div>
        <div><span>{t('approvalInbox.stats.currentPage')}</span><strong>{formatNumber(cases.length)}</strong></div>
      </div>

      <form className="approval-inbox-filters" onSubmit={applyActionFilter}>
        <label>
          <span>{t('approvalInbox.filters.status')}</span>
          <select value={statusFilter} onChange={event => setStatusFilter(event.target.value as StatusFilter)}>
            <option value="pending">{statusLabel('pending')}</option>
            <option value="">{t('approvalInbox.filters.all')}</option>
            <option value="approved">{statusLabel('approved')}</option>
            <option value="rejected">{statusLabel('rejected')}</option>
            <option value="cancelled">{statusLabel('cancelled')}</option>
          </select>
        </label>
        <label className="approval-action-filter">
          <span>{t('approvalInbox.filters.action')}</span>
          <span className="approval-filter-input">
            <Search aria-hidden="true" />
            <input
              value={actionInput}
              onChange={event => setActionInput(event.target.value)}
              placeholder={t('approvalInbox.filters.actionPlaceholder')}
              maxLength={128}
            />
          </span>
        </label>
        <button type="submit">{t('approvalInbox.filters.apply')}</button>
      </form>

      {listError && <div className="approval-error" role="alert"><AlertTriangle />{listError}</div>}

      <div className="approval-inbox-layout">
        <aside className="approval-case-browser" aria-label={t('approvalInbox.casesAria')}>
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
                    {itemExpired ? t('approvalInbox.expired') : statusLabel(item.status)}
                  </span>
                  <strong title={item.action}>{item.action}</strong>
                  <small title={item.target_resource_urn}>{resourceName(item.target_resource_urn)}</small>
                  <time>{formatApprovalDate(item.requested_at)}</time>
                  <ChevronRight className="rtl-flip" aria-hidden="true" />
                </button>
              );
            })}
            {!listLoading && cases.length === 0 && (
              <div className="approval-empty">{t('approvalInbox.emptyCases')}</div>
            )}
          </div>
          {hasMore && (
            <button type="button" className="approval-load-more" onClick={loadMore} disabled={listLoading}>
              {listLoading ? t('approvalInbox.loading') : t('approvalInbox.loadMore')}
            </button>
          )}
        </aside>

        <main className="approval-case-detail">
          {!selectedCase && <div className="approval-empty">{t('approvalInbox.selectCase')}</div>}
          {selectedCase && (
            <>
              <div className="approval-detail-heading">
                <div>
                  <span>{selectedCase.action}</span>
                  <h3>{resourceName(selectedCase.target_resource_urn)}</h3>
                  <code title={selectedCase.approval_case_ref}>{selectedCase.approval_case_ref}</code>
                </div>
                <span className={`approval-status ${expired ? 'expired' : selectedCase.status}`}>
                  {expired ? t('approvalInbox.expired') : statusLabel(selectedCase.status)} · v{selectedCase.state_version}
                </span>
              </div>

              <dl className="approval-facts">
                <div><dt><UserRound />{t('approvalInbox.facts.requester')}</dt><dd>{selectedCase.requester_subject}</dd></div>
                <div><dt><Clock3 />{t('approvalInbox.facts.expiresAt')}</dt><dd>{formatApprovalDate(selectedCase.expires_at)}</dd></div>
                <div><dt>{t('approvalInbox.facts.fingerprint')}</dt><dd><code title={selectedCase.target_fingerprint}>{selectedCase.target_fingerprint}</code></dd></div>
                <div><dt>{t('approvalInbox.facts.resource')}</dt><dd>{selectedCase.target_resource_urn}</dd></div>
              </dl>

              <section className="approval-detail-section approval-assignment-section">
                <div className="approval-section-heading">
                  <h4><UserCheck />{t('approvalInbox.assignment.title')}</h4>
                  <span>{assignment ? `v${assignment.assignment_version}` : t('approvalInbox.assignment.unassigned')}</span>
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
                          ? t('approvalInbox.assignment.closed')
                          : t('approvalInbox.assignment.openPool')}
                    </strong>
                    <small>
                      {assignment
                        ? `${assignment.last_reason} · ${formatApprovalDate(assignment.updated_at)}`
                        : t('approvalInbox.assignment.noConstraint')}
                    </small>
                  </span>
                  {assignment?.status === 'assigned' && (
                    <em>{t('approvalInbox.assignment.delegationDepth', {
                      depth: formatNumber(assignment.delegation_depth),
                    })}</em>
                  )}
                </div>

                {assignmentEvents.length > 0 && (
                  <details className="approval-assignment-audit">
                    <summary>{t('approvalInbox.assignment.auditCount', {
                      count: formatNumber(assignmentEvents.length),
                    })}</summary>
                    <ol>
                      {assignmentEvents.map(item => (
                        <li key={item.assignment_event_id}>
                          <span>{t(`approvalInbox.assignment.action.${item.action}`)} · v{item.assignment_version}</span>
                          <strong>{item.to_assignee_subject || t('approvalInbox.assignment.openPool')}</strong>
                          <small>{item.actor_subject} · {formatApprovalDate(item.occurred_at)}</small>
                          <p>{item.reason}</p>
                        </li>
                      ))}
                    </ol>
                  </details>
                )}

                {(canAdminRoute || canDelegate) && (
                  <form className="approval-assignment-form" onSubmit={submitAssignment}>
                    <div className="approval-assignment-actions" role="group" aria-label={t('approvalInbox.assignment.operationsAria')}>
                      {canAdminRoute && (!assignment || assignment.status === 'released') && (
                        <button
                          type="button"
                          className={assignmentOperation === 'assign' ? 'active' : ''}
                          onClick={() => setAssignmentOperation('assign')}
                        ><UserCheck />{t('approvalInbox.assignment.action.assigned')}</button>
                      )}
                      {canAdminRoute && assignment?.status === 'assigned' && (
                        <>
                          <button
                            type="button"
                            className={assignmentOperation === 'reassign' ? 'active' : ''}
                            onClick={() => setAssignmentOperation('reassign')}
                          ><UserCheck />{t('approvalInbox.assignment.action.reassigned')}</button>
                          <button
                            type="button"
                            className={assignmentOperation === 'release' ? 'active' : ''}
                            onClick={() => setAssignmentOperation('release')}
                          ><UserMinus />{t('approvalInbox.assignment.action.released')}</button>
                        </>
                      )}
                      {canDelegate && (
                        <button
                          type="button"
                          className={assignmentOperation === 'delegate' ? 'active' : ''}
                          onClick={() => setAssignmentOperation('delegate')}
                        ><UserRound />{t('approvalInbox.assignment.action.delegated')}</button>
                      )}
                    </div>
                    {assignmentOperation !== 'release' && (
                      <label>
                        <span>{t('approvalInbox.assignment.target')}</span>
                        <select
                          value={assigneeInput}
                          onChange={event => setAssigneeInput(event.target.value)}
                        >
                          <option value="">{t('approvalInbox.assignment.selectEligible')}</option>
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
                      <span>{t('approvalInbox.assignment.reason')}</span>
                      <textarea
                        value={assignmentReason}
                        onChange={event => setAssignmentReason(event.target.value)}
                        maxLength={512}
                        placeholder={t('approvalInbox.assignment.reasonPlaceholder')}
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
                      {assignmentLoading ? t('approvalInbox.submitting') : t('approvalInbox.assignment.confirm')}
                    </button>
                  </form>
                )}
              </section>

              <section className="approval-detail-section">
                <h4>{t('approvalInbox.requestReason')}</h4>
                <p>{selectedCase.request_reason}</p>
                <h4>{t('approvalInbox.requestContext')}</h4>
                <pre>{compactJson(selectedCase.request_context, t('approvalInbox.contentTruncated'))}</pre>
              </section>

              <section className="approval-detail-section">
                <div className="approval-section-heading">
                  <h4><Bell />{t('approvalInbox.notifications.title')}</h4>
                  <span>{t('approvalInbox.itemCount', { count: formatNumber(notifications.length) })}</span>
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
                        {t(`approvalInbox.notifications.status.${item.status}`)}
                      </span>
                      <strong>{t(`approvalInbox.notifications.kind.${item.notification_kind}`)}</strong>
                      <small>{item.channel} · {item.destination_ref}</small>
                      <dl>
                        <div><dt>{t('approvalInbox.notifications.availableAt')}</dt><dd>{formatApprovalDate(item.available_at)}</dd></div>
                        <div><dt>{t('approvalInbox.notifications.attempts')}</dt><dd>{formatNumber(item.attempt_count)}/{formatNumber(item.max_attempts)}</dd></div>
                        <div><dt>{t('approvalInbox.notifications.manualRecoveries')}</dt><dd>{formatNumber(item.recovery_count)}/{formatNumber(10)}</dd></div>
                        {item.completed_at && <div><dt>{t('approvalInbox.notifications.completedAt')}</dt><dd>{formatApprovalDate(item.completed_at)}</dd></div>}
                        {item.last_recovered_at && <div><dt>{t('approvalInbox.notifications.lastRecoveredAt')}</dt><dd>{formatApprovalDate(item.last_recovered_at)}</dd></div>}
                      </dl>
                      {item.last_error && <p title={item.last_error}>{item.last_error}</p>}
                      {item.last_recovered_by && (
                        <small className="approval-recovery-latest">
                          {item.last_recovered_by} · {item.last_recovery_reason}
                        </small>
                      )}
                      {itemRecoveries.length > 0 && (
                        <details className="approval-recovery-audit">
                          <summary>{t('approvalInbox.recovery.auditCount', {
                            count: formatNumber(itemRecoveries.length),
                          })}</summary>
                          <ol>
                            {itemRecoveries.map(recovery => (
                              <li key={recovery.recovery_event_id}>
                                <strong>{t('approvalInbox.recovery.sequence', {
                                  sequence: formatNumber(recovery.recovery_no),
                                })}</strong>
                                <span>{recovery.reason}</span>
                                <small>
                                  {t('approvalInbox.recovery.auditMetadata', {
                                    actor: recovery.actor_subject,
                                    date: formatApprovalDate(recovery.occurred_at),
                                    attempts: formatNumber(recovery.previous_attempt_count),
                                  })}
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
                          <RotateCcw />{t('approvalInbox.recovery.open')}
                        </button>
                      )}
                      {item.status === 'failed' && (staleExpiry || recoveryLimitReached) && (
                        <small className="approval-recovery-blocked">
                          {staleExpiry
                            ? t('approvalInbox.recovery.staleExpiry')
                            : t('approvalInbox.recovery.limitReached')}
                        </small>
                      )}
                      {canRecover && recoveryTarget === item.notification_id && (
                        <form
                          className="approval-recovery-form"
                          onSubmit={event => submitNotificationRecovery(event, item)}
                        >
                          <label>
                            <span>{t('approvalInbox.recovery.reason')}</span>
                            <textarea
                              value={recoveryReason}
                              onChange={event => setRecoveryReason(event.target.value)}
                              maxLength={512}
                              placeholder={t('approvalInbox.recovery.reasonPlaceholder')}
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
                            >{t('approvalInbox.cancel')}</button>
                            <button type="submit" disabled={!recoveryReason.trim() || recoveryLoading}>
                              <RotateCcw />{recoveryLoading
                                ? t('approvalInbox.recovery.recovering')
                                : t('approvalInbox.recovery.confirm')}
                            </button>
                          </div>
                        </form>
                      )}
                    </div>
                    );
                  })}
                  {!eventsLoading && notifications.length === 0 && (
                    <div className="approval-empty compact">{t('approvalInbox.notifications.empty')}</div>
                  )}
                </div>
              </section>

              <section className="approval-detail-section">
                <div className="approval-section-heading">
                  <h4><FileClock />{t('approvalInbox.events.title')}</h4>
                  <span>{t('approvalInbox.itemCount', { count: formatNumber(events.length) })}</span>
                </div>
                {eventsError && <div className="approval-error" role="alert"><AlertTriangle />{eventsError}</div>}
                {eventsLoading && <div className="approval-empty compact">{t('approvalInbox.events.loading')}</div>}
                {!eventsLoading && (
                  <ol className="approval-event-list">
                    {events.map(item => (
                      <li key={item.approval_event_id}>
                        <span className={`approval-event-dot ${item.to_status}`} />
                        <div>
                          <strong>{statusLabel(item.to_status)}</strong>
                          <p>{item.reason}</p>
                          <small>{item.actor_subject} · {formatApprovalDate(item.occurred_at)}</small>
                          {Object.keys(item.details).length > 0 && (
                            <pre>{compactJson(item.details, t('approvalInbox.contentTruncated'), 700)}</pre>
                          )}
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
                          ? t('approvalInbox.decision.notAuthorizedTitle')
                          : expired
                            ? t('approvalInbox.decision.expiredTitle')
                            : selectedCase.status === 'pending'
                              ? t('approvalInbox.decision.resolvingTitle')
                              : t('approvalInbox.decision.terminalTitle', {
                                status: statusLabel(selectedCase.status),
                              })}
                      </strong>
                      <small>
                        {accessDenied
                          ? accessReasonText(actorAccess?.access_reason)
                          : selectedCase.decision_reason || t('approvalInbox.decision.terminalDescription')}
                      </small>
                    </span>
                  </div>
                ) : (
                  <form onSubmit={submitDecision}>
                    <h4>{t('approvalInbox.decision.title')}</h4>
                    <div className="approval-verdict-control" role="group" aria-label={t('approvalInbox.decision.groupAria')}>
                      <button type="button" className={verdict === 'approved' ? 'active approved' : ''} onClick={() => setVerdict('approved')}><CheckCircle2 />{verdictLabel('approved')}</button>
                      <button type="button" className={verdict === 'rejected' ? 'active rejected' : ''} onClick={() => setVerdict('rejected')}><XCircle />{verdictLabel('rejected')}</button>
                      <button type="button" className={verdict === 'cancelled' ? 'active cancelled' : ''} onClick={() => setVerdict('cancelled')}><Ban />{verdictLabel('cancelled')}</button>
                    </div>
                    <label>
                      <span>{t('approvalInbox.decision.reasonLabel', { verdict: verdictLabel(verdict) })}</span>
                      <textarea value={reason} onChange={event => setReason(event.target.value)} maxLength={512} placeholder={t('approvalInbox.decision.reasonPlaceholder')} />
                    </label>
                    {decisionError && <div className="approval-error" role="alert"><AlertTriangle />{decisionError}</div>}
                    <button className="approval-decision-submit" type="submit" disabled={!reason.trim() || decisionLoading}>
                      {decisionLoading
                        ? t('approvalInbox.submitting')
                        : t('approvalInbox.decision.confirm', { verdict: verdictLabel(verdict) })}
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
