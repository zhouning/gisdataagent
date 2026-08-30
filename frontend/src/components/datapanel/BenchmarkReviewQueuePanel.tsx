import { useEffect, useMemo, useState } from 'react';
import { Check, ChevronLeft, ChevronRight, Eye, RefreshCw, Search, ShieldCheck, XCircle } from 'lucide-react';

type QueueStatus = 'pending_business_gold_review' | 'reviewed' | 'all';
interface ScopeOption { key: string; label: string }
interface BenchmarkItem {
  task_id?: string;
  physical_table?: string;
  physical_field?: string;
  business_asset_id?: string;
  operation?: string;
  field_role?: string;
  labels?: Record<string, string>;
  question_templates?: Record<string, string>;
  languages?: string[];
  review_status?: string;
  semantic_review_status?: string;
  requires_semantic_review?: boolean;
  promotion_requirements?: string[];
  dictionary_evidence?: Record<string, any>;
  candidate_review_status?: string;
  review?: { decision?: string; review_notes?: string; question_templates?: Record<string, string>; reviewed_by?: string; reviewed_at?: string } | null;
}
interface QueueResponse {
  items?: BenchmarkItem[];
  total?: number;
  has_more?: boolean;
  coverage?: Record<string, any>;
  claim_boundary?: Record<string, any>;
  source?: Record<string, any>;
}

const PAGE_SIZE = 20;
const STATUS_LABELS: Record<QueueStatus, string> = {
  pending_business_gold_review: '待 Gold 审核',
  reviewed: '已审核',
  all: '全部',
};
const OPERATION_LABELS: Record<string, string> = {
  aggregate_summary: '汇总统计',
  detail_projection: '明细投影',
  distinct_count: '去重计数',
  distinct_values: '去重值',
  distribution_profile: '分布概览',
  grouped_count: '分组计数',
  map_feature_projection: '地图要素',
  null_profile: '空值概览',
  spatial_extent: '空间范围',
  temporal_range_profile: '时间范围',
  time_bucket_count: '时间分桶',
};

function itemLabel(item: BenchmarkItem): string {
  return [item.physical_table, item.physical_field].filter(Boolean).join(' · ') || item.task_id || '-';
}

function evidenceLabel(item: BenchmarkItem): string {
  const status = String(item.dictionary_evidence?.support_status || 'no_dictionary_evidence');
  return ({
    dictionary_exact_supported: '字典完整支持',
    dictionary_partial_supported: '字典部分支持',
    dictionary_unmatched: '字典未对齐',
    no_dictionary_evidence: '无字典证据',
  } as Record<string, string>)[status] || status;
}

export function BenchmarkReviewQueuePanel({ scopeOptions }: { scopeOptions: ScopeOption[] }) {
  const [scope, setScope] = useState(scopeOptions[0]?.key || '');
  const [status, setStatus] = useState<QueueStatus>('pending_business_gold_review');
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<QueueResponse | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});
  const [reviewing, setReviewing] = useState<string | null>(null);

  useEffect(() => {
    if (!scopeOptions.some(option => option.key === scope)) setScope(scopeOptions[0]?.key || '');
  }, [scopeOptions, scope]);

  const load = async (nextOffset = offset) => {
    if (!scope) return;
    setLoading(true); setError('');
    try {
      const params = new URLSearchParams({ scope, status, offset: String(nextOffset), limit: String(PAGE_SIZE) });
      if (search.trim()) params.set('search', search.trim());
      const response = await fetch(`/api/semantic/governance/benchmark-review-queue?${params.toString()}`, { credentials: 'include' });
      const payload = await response.json() as QueueResponse & { error?: string };
      if (!response.ok) throw new Error(payload.error || 'Benchmark 审核队列加载失败');
      setOffset(nextOffset); setData(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Benchmark 审核队列加载失败');
      setData(null);
    } finally { setLoading(false); }
  };

  useEffect(() => { setOffset(0); void load(0); }, [scope, status]);

  const submitReview = async (taskId: string, decision: 'approved_for_gold' | 'needs_changes' | 'rejected') => {
    const notes = reviewNotes[taskId] || '';
    if ((decision !== 'approved_for_gold') && !notes.trim()) {
      setError('退回或拒绝题位时必须填写审核意见');
      return;
    }
    setReviewing(taskId); setError('');
    try {
      const response = await fetch(`/api/semantic/governance/benchmark-review-queue/${encodeURIComponent(taskId)}/review?scope=${encodeURIComponent(scope)}`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, review_notes: notes }),
      });
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error || '审核记录保存失败');
      await load(offset);
    } catch (err) {
      setError(err instanceof Error ? err.message : '审核记录保存失败');
    } finally { setReviewing(null); }
  };

  const coverage = data?.coverage || {};
  const languageCount = coverage.language_variant_count || 0;
  const operationCount = useMemo(() => Object.keys(coverage.operation_counts || {}).length, [coverage]);
  if (!scopeOptions.length) return null;
  return <section className="semantic-benchmark-review-queue">
    <div className="semantic-review-queue-heading">
      <div><span className="semantic-workspace-kicker">BUSINESS BENCHMARK REVIEW</span><h4>业务问数题位审核</h4><p>按字段角色生成的候选题位；专家确认题意和口径后，才可独立冻结 Gold。</p></div>
      <div className="semantic-review-queue-gate"><ShieldCheck size={14} />候选不是 Gold</div>
    </div>
    <div className="semantic-review-queue-toolbar">
      <div className="semantic-review-queue-scopes">{scopeOptions.map(option => <button type="button" key={option.key} className={scope === option.key ? 'active' : ''} onClick={() => setScope(option.key)}>{option.label}</button>)}</div>
      <select value={status} onChange={event => setStatus(event.target.value as QueueStatus)} aria-label="Benchmark 审核状态">{Object.entries(STATUS_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
      <div className="semantic-review-queue-search"><Search size={13} /><input value={search} onChange={event => setSearch(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') void load(0); }} placeholder="搜索表、字段、题面或字典说明" /><button type="button" className="btn-secondary btn-sm" onClick={() => void load(0)}><RefreshCw size={13} /></button></div>
    </div>
    <div className="semantic-review-queue-kpis"><span>当前题位 <b>{data?.total || 0}</b></span><span>三语言变体 <b>{languageCount}</b></span><span>操作类型 <b>{operationCount}</b></span><span>已审核字段 <b>{coverage.reviewed_business_field_count || 0}</b></span><span>待补语义字段 <b>{coverage.candidate_field_count || 0}</b></span><span className="queue-boundary"><XCircle size={12} />Gold/运行时：否</span></div>
    {error && <div className="semantic-alert error">⚠ {error}</div>}
    {loading && !data && <div className="semantic-loading">正在加载题位...</div>}
    {!loading && data && !data.items?.length && <div className="semantic-empty">当前筛选条件下没有题位。</div>}
    <div className="semantic-review-queue-list">{(data?.items || []).map((item, index) => { const id = String(item.task_id || index); const open = expanded === id; const review = item.review; return <article key={id} className={`semantic-review-queue-item ${open ? 'open' : ''}`}>
      <div className="semantic-review-queue-item-main"><button type="button" className="semantic-review-queue-item-toggle" onClick={() => setExpanded(open ? null : id)}><span className="queue-item-kind">{OPERATION_LABELS[item.operation || ''] || item.operation || '题位'}</span><strong>{itemLabel(item)}</strong><span className="queue-item-status"><Eye size={12} />{item.review_status === 'reviewed' ? (review?.decision === 'approved_for_gold' ? '已确认可生成 Gold' : '已审核') : '待 Gold 审核'} · {item.requires_semantic_review ? '待语义审核' : '语义已审核'}</span><small>{evidenceLabel(item)} · {item.business_asset_id || '-'} · {item.task_id || '-'}</small></button></div>
      {open && <div className="semantic-review-queue-item-detail benchmark-review-item-detail"><div className="benchmark-question-grid">{(['zh', 'en', 'ar'] as const).map(language => <div key={language}><span>{language.toUpperCase()} 题面</span><p>{review?.question_templates?.[language] || item.question_templates?.[language] || '未生成'}</p></div>)}</div><div className="queue-evidence-grid"><div><span>字段与操作</span><pre>{JSON.stringify({ field: item.physical_field, role: item.field_role, operation: item.operation, labels: item.labels, semantic_review_status: item.semantic_review_status, requires_semantic_review: item.requires_semantic_review }, null, 2)}</pre></div><div><span>字典证据</span><pre>{JSON.stringify(item.dictionary_evidence || {}, null, 2)}</pre></div></div><div className="queue-decisions"><b>发布前必须确认</b>{(item.promotion_requirements || []).map(requirement => <span key={requirement}>{requirement}</span>)}</div><div className="benchmark-review-actions"><textarea value={reviewNotes[id] ?? review?.review_notes ?? ''} onChange={event => setReviewNotes(previous => ({ ...previous, [id]: event.target.value }))} placeholder="审核意见（退回或拒绝时必填）" maxLength={4000} aria-label={`${id} 审核意见`} /><div><button type="button" className="btn-secondary btn-sm" disabled={reviewing === id} onClick={() => void submitReview(id, 'needs_changes')}><RefreshCw size={13} />退回修改</button><button type="button" className="btn-secondary btn-sm" disabled={reviewing === id} onClick={() => void submitReview(id, 'rejected')}><XCircle size={13} />拒绝题位</button><button type="button" className="btn-primary btn-sm" disabled={reviewing === id} onClick={() => void submitReview(id, 'approved_for_gold')}><Check size={13} />确认可生成 Gold</button></div>{review && <small>最近审核：{review.reviewed_by || '-'} · {review.decision || '-'} · 仍不是 Gold</small>}</div></div>}
    </article>; })}</div>
    {data && (offset > 0 || data.has_more) && <div className="semantic-review-queue-pagination"><span>第 {Math.floor(offset / PAGE_SIZE) + 1} 页 · {offset + 1}-{Math.min(offset + PAGE_SIZE, data.total || 0)} / {data.total || 0}</span><div><button type="button" className="btn-secondary btn-sm" disabled={loading || offset === 0} onClick={() => void load(Math.max(0, offset - PAGE_SIZE))}><ChevronLeft size={13} />上一页</button><button type="button" className="btn-secondary btn-sm" disabled={loading || !data.has_more} onClick={() => void load(offset + PAGE_SIZE)}>下一页<ChevronRight size={13} /></button></div></div>}
  </section>;
}
