import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Eye,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react';

import {
  buildCapabilityPreview,
  buildInputScaffold,
  type CapabilityDetail,
  type CapabilityPreview,
  type CapabilityReceipt,
  type CapabilitySummary,
  CapabilityValidationError,
  getWebCapability,
  invokeWebCapability,
  listWebCapabilities,
  requiresCapabilityConfirmation,
  validateCapabilityInput,
} from './capabilityWebClient';
import { formatNumber } from '../../i18n';
import './PlatformCapabilitiesPanel.css';

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof CapabilityValidationError && error.issues.length) {
    return `${error.message}: ${error.issues.join('; ')}`;
  }
  return error instanceof Error ? error.message : fallback;
}

function parseCanonicalInput(
  value: string,
  invalidJsonMessage: string,
  objectExpectedMessage: string,
): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(invalidJsonMessage);
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error(objectExpectedMessage);
  }
  return parsed as Record<string, unknown>;
}

export default function PlatformCapabilitiesPanel({ userRole }: { userRole?: string }) {
  const { t, i18n } = useTranslation('common');
  const [capabilities, setCapabilities] = useState<CapabilitySummary[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [detail, setDetail] = useState<CapabilityDetail | null>(null);
  const [inputText, setInputText] = useState('{}');
  const [search, setSearch] = useState('');
  const [preview, setPreview] = useState<CapabilityPreview | null>(null);
  const [confirmationCode, setConfirmationCode] = useState('');
  const [receipt, setReceipt] = useState<CapabilityReceipt | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [message, setMessage] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    setMessage('');
    try {
      const manifest = await listWebCapabilities();
      setCapabilities(manifest.capabilities);
      setSelectedId((current) => (
        manifest.capabilities.some((item) => item.capability_id === current)
          ? current
          : manifest.capabilities[0]?.capability_id ?? ''
      ));
    } catch (error) {
      setMessage(errorMessage(error, t('capabilities.platform.errors.operationFailed')));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let active = true;
    const summary = capabilities.find((item) => item.capability_id === selectedId);
    setDetailLoading(true);
    setMessage('');
    void getWebCapability(selectedId, summary?.version)
      .then((nextDetail) => {
        if (!active) return;
        setDetail(nextDetail);
        setInputText(JSON.stringify(buildInputScaffold(nextDetail), null, 2));
        setPreview(null);
        setConfirmationCode('');
        setReceipt(null);
      })
      .catch((error) => { if (active) setMessage(errorMessage(error, t('capabilities.platform.errors.operationFailed'))); })
      .finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [capabilities, selectedId, i18n.resolvedLanguage, t]);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return capabilities;
    return capabilities.filter((item) => (
      item.capability_id.toLowerCase().includes(query)
      || item.title.toLowerCase().includes(query)
      || item.operation.toLowerCase().includes(query)
    ));
  }, [capabilities, search]);

  const needsConfirmation = detail ? requiresCapabilityConfirmation(detail) : false;
  const roleAllowed = !detail
    || !userRole
    || detail.spec.policy.allowed_roles.includes(userRole);

  const handlePreview = async () => {
    if (!detail) return;
    setMessage('');
    setReceipt(null);
    try {
      const input = parseCanonicalInput(
        inputText,
        t('capabilities.platform.errors.invalidJson'),
        t('capabilities.platform.errors.objectExpected'),
      );
      validateCapabilityInput(detail, input);
      setPreview(await buildCapabilityPreview(detail, input));
      setConfirmationCode('');
    } catch (error) {
      setPreview(null);
      setMessage(errorMessage(error, t('capabilities.platform.errors.operationFailed')));
    }
  };

  const handleExecute = async () => {
    if (!detail || !preview) return;
    setExecuting(true);
    setMessage('');
    setReceipt(null);
    try {
      const input = parseCanonicalInput(
        inputText,
        t('capabilities.platform.errors.invalidJson'),
        t('capabilities.platform.errors.objectExpected'),
      );
      const nextReceipt = await invokeWebCapability(detail, input, {
        preview,
        confirmationCode,
      });
      setReceipt(nextReceipt);
      setPreview(null);
      setConfirmationCode('');
    } catch (error) {
      setMessage(errorMessage(error, t('capabilities.platform.errors.operationFailed')));
    } finally {
      setExecuting(false);
    }
  };

  const enumLabel = (group: string, value: string) =>
    t(`capabilities.platform.enums.${group}.${value}`, { defaultValue: value });

  const specText = (capabilityId: string, field: 'title' | 'description', fallback: string) =>
    t(`capabilities.platform.specs.${capabilityId}.${field}`, { defaultValue: fallback });

  return (
    <div className="platform-capabilities-panel">
      <aside className="platform-capability-index" aria-label={t('capabilities.platform.listAria')}>
        <div className="platform-capability-index-head">
          <div>
            <strong>CapabilitySpec</strong>
            <span>{t('capabilities.platform.count', { count: formatNumber(capabilities.length) })}</span>
          </div>
          <button type="button" className="platform-icon-button" onClick={() => void refresh()} disabled={loading} title={t('capabilities.platform.refresh')} aria-label={t('capabilities.platform.refresh')}>
            <RefreshCw size={15} className={loading ? 'is-spinning' : ''} />
          </button>
        </div>
        <label className="platform-capability-search">
          <Search size={14} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('capabilities.platform.search')} />
        </label>
        <div className="platform-capability-list">
          {filtered.map((item) => (
            <button
              type="button"
              key={`${item.capability_id}@${item.version}`}
              className={selectedId === item.capability_id ? 'active' : ''}
              onClick={() => setSelectedId(item.capability_id)}
            >
              <span className="platform-capability-list-title">{specText(item.capability_id, 'title', item.title)}</span>
              <code>{item.capability_id}</code>
              <span className="platform-capability-list-meta">
                <b>{enumLabel('operation', item.operation)}</b>
                <span>{item.tier}</span>
                <span>v{item.version}</span>
              </span>
            </button>
          ))}
          {!loading && filtered.length === 0 && <div className="platform-capability-empty">{t('capabilities.platform.empty')}</div>}
        </div>
      </aside>

      <section className="platform-capability-workbench">
        {message && (
          <div className="platform-capability-message error" role="alert">
            <AlertTriangle size={15} />
            <span>{message}</span>
          </div>
        )}
        {detailLoading ? (
          <div className="platform-capability-empty">{t('capabilities.platform.loadingContract')}</div>
        ) : detail ? (
          <>
            <header className="platform-capability-titlebar">
              <div>
                <span className="platform-capability-eyebrow">{detail.spec.owner} / {detail.spec.tier}</span>
                <h3>{specText(detail.spec.capability_id, 'title', detail.spec.title)}</h3>
                <code>{detail.spec.capability_id}@{detail.spec.version}</code>
              </div>
              <div className="platform-capability-badges">
                <span className={`risk-${detail.spec.risk}`}>{t('capabilities.platform.riskBadge', { risk: enumLabel('risk', detail.spec.risk) })}</span>
                <span>{enumLabel('operation', detail.spec.operation)}</span>
                <span>{enumLabel('lifecycle', detail.spec.lifecycle)}</span>
              </div>
            </header>

            <p className="platform-capability-description">{specText(detail.spec.capability_id, 'description', detail.spec.description)}</p>

            <div className="platform-contract-strip">
              <div><span>{t('capabilities.platform.labels.policyAction')}</span><strong>{detail.spec.policy.action}</strong></div>
              <div><span>{t('capabilities.platform.labels.idempotency')}</span><strong>{enumLabel('idempotency', detail.spec.execution.idempotency)}</strong></div>
              <div><span>{t('capabilities.platform.labels.sideEffect')}</span><strong>{enumLabel('sideEffect', detail.spec.side_effect)}</strong></div>
              <div><span>{t('capabilities.platform.labels.fingerprint')}</span><code title={detail.fingerprint}>{detail.fingerprint.slice(0, 12)}</code></div>
            </div>

            {!roleAllowed && (
              <div className="platform-capability-message warning">
                <ShieldCheck size={15} />
                <span>{t('capabilities.platform.roleWarning', { role: userRole })}</span>
              </div>
            )}

            <div className="platform-capability-editor-head">
              <div>
                <strong>{t('capabilities.platform.canonicalInput')}</strong>
                <span>{detail.spec.input.semantic_type}</span>
              </div>
              <button type="button" className="platform-secondary-button" onClick={() => void handlePreview()}>
                <Eye size={14} />{t('capabilities.platform.validatePreview')}
              </button>
            </div>
            <textarea
              className="platform-capability-editor"
              value={inputText}
              onChange={(event) => {
                setInputText(event.target.value);
                setPreview(null);
                setReceipt(null);
              }}
              spellCheck={false}
              aria-label={t('capabilities.platform.inputAria')}
            />

            {preview && (
              <div className={`platform-capability-preview ${needsConfirmation ? 'requires-confirmation' : ''}`}>
                <div className="platform-preview-heading">
                  <div>
                    {needsConfirmation ? <ShieldCheck size={16} /> : <CheckCircle2 size={16} />}
                    <strong>{needsConfirmation ? t('capabilities.platform.pendingConfirmation') : t('capabilities.platform.inputValid')}</strong>
                  </div>
                  <span><Clock3 size={13} />{t('capabilities.platform.validFor')}</span>
                </div>
                {needsConfirmation && (
                  <div className="platform-confirmation-row">
                    <code>{preview.confirmation_code}</code>
                    <input
                      value={confirmationCode}
                      onChange={(event) => setConfirmationCode(event.target.value.toUpperCase())}
                      placeholder={t('capabilities.platform.confirmationPlaceholder')}
                      maxLength={12}
                      autoComplete="off"
                      aria-label={t('capabilities.platform.confirmationAria')}
                    />
                  </div>
                )}
                <button
                  type="button"
                  className="platform-primary-button"
                  onClick={() => void handleExecute()}
                  disabled={executing || !roleAllowed || (needsConfirmation && confirmationCode.length !== 12)}
                >
                  {executing ? <RefreshCw size={14} className="is-spinning" /> : <Play size={14} />}
                  {executing ? t('capabilities.platform.submitting') : needsConfirmation ? t('capabilities.platform.confirmSubmit') : t('capabilities.platform.executeQuery')}
                </button>
              </div>
            )}

            {receipt && (
              <div className="platform-capability-receipt">
                <div className="platform-receipt-heading">
                  <CheckCircle2 size={16} />
                  <strong>{receipt.created === false ? t('capabilities.platform.idempotentReplay') : t('capabilities.platform.accepted')}</strong>
                  <span>HTTP {receipt.status_code}</span>
                </div>
                <div className="platform-receipt-meta">
                  <span>request_id</span><code>{receipt.request_id ?? '-'}</code>
                  <span>created</span><code>{receipt.created === null ? '-' : t(`capabilities.common.${receipt.created ? 'yes' : 'no'}`)}</code>
                </div>
                <pre>{JSON.stringify(receipt.data, null, 2)}</pre>
              </div>
            )}
          </>
        ) : (
          <div className="platform-capability-empty">{t('capabilities.platform.selectCapability')}</div>
        )}
      </section>
    </div>
  );
}
