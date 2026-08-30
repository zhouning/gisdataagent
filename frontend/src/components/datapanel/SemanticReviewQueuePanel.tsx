import { useEffect, useMemo, useState } from 'react';
import { Check, CheckCircle2, ChevronLeft, ChevronRight, ClipboardPlus, Eye, RefreshCw, Search, ShieldCheck, XCircle } from 'lucide-react';

type QueueKind = 'table' | 'field' | 'relationship';
type QueueStatus = 'review_required' | 'reviewed' | 'all';

interface ScopeOption { key: string; label: string }
interface QueueItem {
  task_id?: string;
  kind?: string;
  physical_table?: string;
  target_table?: string;
  physical_field?: string;
  relation_id?: string;
  review_status?: string;
  binding_status?: string;
  dictionary_evidence?: Record<string, any>;
  current?: Record<string, any>;
  suggested?: Record<string, any>;
  candidate?: Record<string, any>;
  required_decisions?: string[];
  draft?: { entry_type: string; payload: Record<string, any>; not_approved: boolean } | null;
  candidate_review_status?: string;
  review?: { decision?: string; review_notes?: string; reviewed_by?: string; reviewed_at?: string } | null;
}

interface QueueResponse {
  items?: QueueItem[];
  total?: number;
  has_more?: boolean;
  offset?: number;
  limit?: number;
  coverage?: Record<string, any>;
  claim_boundary?: Record<string, any>;
  error?: string;
}

const KIND_LABELS: Record<QueueKind, string> = {
  table: '表审核',
  field: '字段审核',
  relationship: '关系审核',
};

function labelFor(item: QueueItem): string {
  if (item.physical_field) return `${item.physical_table || '-'} · ${item.physical_field}`;
  if (item.target_table) return `${item.physical_table || '-'} → ${item.target_table}`;
  return item.physical_table || item.task_id || '-';
}

function dictionaryStatus(item: QueueItem): string {
  const status = String(item.dictionary_evidence?.support_status || 'no_dictionary_evidence');
  return ({
    dictionary_exact_supported: '字典完整支持',
    dictionary_partial_supported: '字典部分支持',
    dictionary_unmatched: '字典未对齐',
    no_dictionary_evidence: '无字典证据',
  } as Record<string, string>)[status] || status;
}

const PAGE_SIZE = 30;

export function SemanticReviewQueuePanel({ scopeOptions, onDraftCreated }: { scopeOptions: ScopeOption[]; onDraftCreated?: () => void }) {
  const [scope, setScope] = useState(scopeOptions[0]?.key || '');
  const [kind, setKind] = useState<QueueKind>('field');
  const [status, setStatus] = useState<QueueStatus>('review_required');
  const [search, setSearch] = useState('');
  const [data, setData] = useState<QueueResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});
  const [reviewing, setReviewing] = useState<string | null>(null);

  useEffect(() => {
    if (!scopeOptions.some(option => option.key === scope)) setScope(scopeOptions[0]?.key || '');
  }, [scopeOptions, scope]);

  const load = async (nextOffset = offset) => {
    if (!scope) return;
    setLoading(true); setError('');
    try {
      const params = new URLSearchParams({ scope, kind, status, offset: String(nextOffset), limit: String(PAGE_SIZE) });
      if (search.trim()) params.set('search', search.trim());
      const response = await fetch(`/api/semantic/governance/review-queue?${params.toString()}`, { credentials: 'include' });
      const payload = await response.json() as QueueResponse;
      if (!response.ok) throw new Error(payload.error || '审核队列加载失败');
      setOffset(nextOffset);
      setData(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : '审核队列加载失败');
      setData(null);
    } finally { setLoading(false); }
  };

  useEffect(() => { setOffset(0); void load(0); }, [scope, kind, status]);

  const coverage = data?.coverage || {};
  const countLabel = useMemo(() => {
    const reviewed = kind === 'table' ? coverage.reviewed_table_count : kind === 'field' ? coverage.reviewed_field_count : coverage.reviewed_relationship_count;
    const total = kind === 'table' ? coverage.table_task_count : kind === 'field' ? coverage.field_task_count : coverage.relationship_task_count;
    return `${reviewed || 0} / ${total || 0}`;
  }, [coverage, kind]);

  const createDraft = async (item: QueueItem) => {
    if (!item.draft || !item.draft.entry_type) return;
    setLoading(true); setError(''); setMessage('');
    try {
      const params = new URLSearchParams({ scope });
      const response = await fetch(`/api/semantic/governance/${item.draft.entry_type}?${params.toString()}`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payload: item.draft.payload }),
      });
      const payload = await response.json() as Record<string, any>;
      if (!response.ok) throw new Error(payload.error || '草稿创建失败');
      setMessage(`${labelFor(item)} 已载入版本草稿；仍需人工补充并审核发布。`);
      onDraftCreated?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : '草稿创建失败');
    } finally { setLoading(false); }
  };

  const submitReview = async (item: QueueItem, decision: 'approved_for_draft' | 'needs_changes' | 'rejected') => {
    const taskId = String(item.task_id || '');
    if (!taskId) return;
    const notes = reviewNotes[taskId] ?? item.review?.review_notes ?? '';
    if ((decision === 'needs_changes' || decision === 'rejected') && !notes.trim()) {
      setError('退回修改或拒绝时必须填写审核意见。');
      return;
    }
    setReviewing(taskId); setError(''); setMessage('');
    try {
      const response = await fetch(`/api/semantic/governance/review-queue/${encodeURIComponent(kind)}/${encodeURIComponent(taskId)}/review?scope=${encodeURIComponent(scope)}`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, review_notes: notes }),
      });
      const payload = await response.json() as Record<string, any>;
      if (!response.ok) throw new Error(payload.error || '审核结果保存失败');
      setMessage(`${labelFor(item)} 的审核结论已保存；该结论不会直接授权运行时。`);
      await load(offset);
    } catch (err) {
      setError(err instanceof Error ? err.message : '审核结果保存失败');
    } finally { setReviewing(null); }
  };

  if (!scopeOptions.length) return null;
  return <section className="semantic-review-queue">
    <div className="semantic-review-queue-heading">
      <div><span className="semantic-workspace-kicker">EXPERT REVIEW QUEUE</span><h4>业务语义审核队列</h4><p>从统一元数据和字典证据生成候选草稿；未审核内容不会进入问数运行时。</p></div>
      <div className="semantic-review-queue-gate"><ShieldCheck size={14} />候选不是审批结果</div>
    </div>
    <div className="semantic-review-queue-toolbar">
      <div className="semantic-review-queue-scopes">{scopeOptions.map(option => <button type="button" key={option.key} className={scope === option.key ? 'active' : ''} onClick={() => setScope(option.key)}>{option.label}</button>)}</div>
      <select value={kind} onChange={event => setKind(event.target.value as QueueKind)} aria-label="审核任务类型">{Object.entries(KIND_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
      <select value={status} onChange={event => setStatus(event.target.value as QueueStatus)} aria-label="审核状态"><option value="review_required">待审核</option><option value="reviewed">已审核</option><option value="all">全部</option></select>
      <div className="semantic-review-queue-search"><Search size={13} /><input value={search} onChange={event => setSearch(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') void load(0); }} placeholder="搜索表、字段或字典说明" /><button type="button" className="btn-secondary btn-sm" onClick={() => void load(0)}><RefreshCw size={13} /></button></div>
    </div>
    <div className="semantic-review-queue-kpis"><span>当前任务 <b>{data?.total || 0}</b></span><span>已审核 / 总任务 <b>{countLabel}</b></span><span>已持久化结论 <b>{coverage.persisted_review_count || 0}</b></span><span>字典完整支持 <b>{coverage.dictionary_exact_supported_field_count || 0}</b></span><span>关系待审核 <b>{coverage.review_required_relationship_count || 0}</b></span><span className="queue-boundary"><XCircle size={12} />运行时授权：否</span></div>
    {error && <div className="semantic-alert error">⚠ {error}</div>}
    {message && <div className="semantic-alert info">{message}</div>}
    {loading && !data && <div className="semantic-loading">正在加载审核队列...</div>}
    {!loading && data && !data.items?.length && <div className="semantic-empty">当前筛选条件下没有任务。</div>}
    <div className="semantic-review-queue-list">{(data?.items || []).map((item, index) => { const id = String(item.task_id || index); const open = expanded === id; const review = item.review; return <article key={id} className={`semantic-review-queue-item ${open ? 'open' : ''}`}>
      <div className="semantic-review-queue-item-main"><button type="button" className="semantic-review-queue-item-toggle" onClick={() => setExpanded(open ? null : id)}><span className="queue-item-kind">{KIND_LABELS[kind]}</span><strong>{labelFor(item)}</strong><span className="queue-item-status">{item.review_status === 'reviewed' ? <><CheckCircle2 size={12} />已审核</> : <><Eye size={12} />待审核</>}</span><small>{dictionaryStatus(item)} · {item.task_id || '-'}</small></button><button type="button" className="btn-secondary btn-sm" disabled={loading || !item.draft} onClick={() => void createDraft(item)}><ClipboardPlus size={13} />载入草稿</button></div>
      {open && <div className="semantic-review-queue-item-detail"><div className="queue-evidence-grid"><div><span>当前语义</span><pre>{JSON.stringify(item.current || item.candidate || {}, null, 2)}</pre></div><div><span>建议草稿</span><pre>{JSON.stringify(item.draft?.payload || item.suggested || {}, null, 2)}</pre></div></div><div className="queue-decisions"><b>需专家确认</b>{(item.required_decisions || []).map(decision => <span key={decision}>{decision}</span>)}</div><div className="semantic-review-actions"><textarea value={reviewNotes[id] ?? review?.review_notes ?? ''} onChange={event => setReviewNotes(previous => ({ ...previous, [id]: event.target.value }))} placeholder="审核意见（退回或拒绝时必填）" maxLength={4000} aria-label={`${id} 审核意见`} /><div><button type="button" className="btn-secondary btn-sm" disabled={reviewing === id} onClick={() => void submitReview(item, 'needs_changes')}><RefreshCw size={13} />退回修改</button><button type="button" className="btn-secondary btn-sm" disabled={reviewing === id} onClick={() => void submitReview(item, 'rejected')}><XCircle size={13} />拒绝</button><button type="button" className="btn-primary btn-sm" disabled={reviewing === id} onClick={() => void submitReview(item, 'approved_for_draft')}><Check size={13} />确认可进入草稿</button></div>{review && <small>最近审核：{review.reviewed_by || '-'} · {review.decision || '-'} · 不等于运行时授权</small>}</div></div>}
    </article>; })}</div>
    {data && (offset > 0 || data.has_more) && <div className="semantic-review-queue-pagination"><span>第 {Math.floor(offset / PAGE_SIZE) + 1} 页 · {offset + 1}-{Math.min(offset + PAGE_SIZE, data.total || 0)} / {data.total || 0}</span><div><button type="button" className="btn-secondary btn-sm" disabled={loading || offset === 0} onClick={() => void load(Math.max(0, offset - PAGE_SIZE))}><ChevronLeft size={13} />上一页</button><button type="button" className="btn-secondary btn-sm" disabled={loading || !data.has_more} onClick={() => void load(offset + PAGE_SIZE)}>下一页<ChevronRight size={13} /></button></div></div>}
  </section>;
}
