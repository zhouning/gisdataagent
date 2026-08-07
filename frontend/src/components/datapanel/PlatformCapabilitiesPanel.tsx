import { useCallback, useEffect, useMemo, useState } from 'react';
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
import './PlatformCapabilitiesPanel.css';

function errorMessage(error: unknown): string {
  if (error instanceof CapabilityValidationError && error.issues.length) {
    return `${error.message}：${error.issues.join('；')}`;
  }
  return error instanceof Error ? error.message : '能力操作失败';
}

function parseCanonicalInput(value: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error('请输入有效的 JSON');
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error('canonical input 必须是一个 JSON 对象');
  }
  return parsed as Record<string, unknown>;
}

export default function PlatformCapabilitiesPanel({ userRole }: { userRole?: string }) {
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
      setMessage(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, []);

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
      .catch((error) => { if (active) setMessage(errorMessage(error)); })
      .finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [capabilities, selectedId]);

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
      const input = parseCanonicalInput(inputText);
      validateCapabilityInput(detail, input);
      setPreview(await buildCapabilityPreview(detail, input));
      setConfirmationCode('');
    } catch (error) {
      setPreview(null);
      setMessage(errorMessage(error));
    }
  };

  const handleExecute = async () => {
    if (!detail || !preview) return;
    setExecuting(true);
    setMessage('');
    setReceipt(null);
    try {
      const input = parseCanonicalInput(inputText);
      const nextReceipt = await invokeWebCapability(detail, input, {
        preview,
        confirmationCode,
      });
      setReceipt(nextReceipt);
      setPreview(null);
      setConfirmationCode('');
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setExecuting(false);
    }
  };

  return (
    <div className="platform-capabilities-panel">
      <aside className="platform-capability-index" aria-label="平台能力清单">
        <div className="platform-capability-index-head">
          <div>
            <strong>CapabilitySpec</strong>
            <span>{capabilities.length} 个 Web 能力</span>
          </div>
          <button type="button" className="platform-icon-button" onClick={() => void refresh()} disabled={loading} title="刷新能力清单">
            <RefreshCw size={15} className={loading ? 'is-spinning' : ''} />
          </button>
        </div>
        <label className="platform-capability-search">
          <Search size={14} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索能力" />
        </label>
        <div className="platform-capability-list">
          {filtered.map((item) => (
            <button
              type="button"
              key={`${item.capability_id}@${item.version}`}
              className={selectedId === item.capability_id ? 'active' : ''}
              onClick={() => setSelectedId(item.capability_id)}
            >
              <span className="platform-capability-list-title">{item.title}</span>
              <code>{item.capability_id}</code>
              <span className="platform-capability-list-meta">
                <b>{item.operation}</b>
                <span>{item.tier}</span>
                <span>v{item.version}</span>
              </span>
            </button>
          ))}
          {!loading && filtered.length === 0 && <div className="platform-capability-empty">暂无匹配能力</div>}
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
          <div className="platform-capability-empty">正在读取能力合同...</div>
        ) : detail ? (
          <>
            <header className="platform-capability-titlebar">
              <div>
                <span className="platform-capability-eyebrow">{detail.spec.owner} / {detail.spec.tier}</span>
                <h3>{detail.spec.title}</h3>
                <code>{detail.spec.capability_id}@{detail.spec.version}</code>
              </div>
              <div className="platform-capability-badges">
                <span className={`risk-${detail.spec.risk}`}>{detail.spec.risk} risk</span>
                <span>{detail.spec.operation}</span>
                <span>{detail.spec.lifecycle}</span>
              </div>
            </header>

            <p className="platform-capability-description">{detail.spec.description}</p>

            <div className="platform-contract-strip">
              <div><span>Policy action</span><strong>{detail.spec.policy.action}</strong></div>
              <div><span>Idempotency</span><strong>{detail.spec.execution.idempotency}</strong></div>
              <div><span>Side effect</span><strong>{detail.spec.side_effect}</strong></div>
              <div><span>Fingerprint</span><code title={detail.fingerprint}>{detail.fingerprint.slice(0, 12)}</code></div>
            </div>

            {!roleAllowed && (
              <div className="platform-capability-message warning">
                <ShieldCheck size={15} />
                <span>当前角色 {userRole} 不在合同提示角色中；服务端策略仍是最终授权依据。</span>
              </div>
            )}

            <div className="platform-capability-editor-head">
              <div>
                <strong>Canonical input</strong>
                <span>{detail.spec.input.semantic_type}</span>
              </div>
              <button type="button" className="platform-secondary-button" onClick={() => void handlePreview()}>
                <Eye size={14} />校验并预览
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
              aria-label="Canonical capability input JSON"
            />

            {preview && (
              <div className={`platform-capability-preview ${needsConfirmation ? 'requires-confirmation' : ''}`}>
                <div className="platform-preview-heading">
                  <div>
                    {needsConfirmation ? <ShieldCheck size={16} /> : <CheckCircle2 size={16} />}
                    <strong>{needsConfirmation ? '待人工确认' : '输入已通过合同校验'}</strong>
                  </div>
                  <span><Clock3 size={13} />5 分钟有效</span>
                </div>
                {needsConfirmation && (
                  <div className="platform-confirmation-row">
                    <code>{preview.confirmation_code}</code>
                    <input
                      value={confirmationCode}
                      onChange={(event) => setConfirmationCode(event.target.value.toUpperCase())}
                      placeholder="输入确认码"
                      maxLength={12}
                      autoComplete="off"
                      aria-label="高风险调用确认码"
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
                  {executing ? '提交中' : needsConfirmation ? '确认并提交' : '执行查询'}
                </button>
              </div>
            )}

            {receipt && (
              <div className="platform-capability-receipt">
                <div className="platform-receipt-heading">
                  <CheckCircle2 size={16} />
                  <strong>{receipt.created === false ? '幂等重放' : '调用已受理'}</strong>
                  <span>HTTP {receipt.status_code}</span>
                </div>
                <div className="platform-receipt-meta">
                  <span>request_id</span><code>{receipt.request_id ?? '-'}</code>
                  <span>created</span><code>{receipt.created === null ? '-' : String(receipt.created)}</code>
                </div>
                <pre>{JSON.stringify(receipt.data, null, 2)}</pre>
              </div>
            )}
          </>
        ) : (
          <div className="platform-capability-empty">选择一个平台能力查看合同</div>
        )}
      </section>
    </div>
  );
}
