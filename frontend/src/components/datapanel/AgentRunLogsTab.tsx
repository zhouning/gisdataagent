import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Brain, ChevronDown, ChevronRight, Clock, Download, Map, Maximize2, RefreshCw, Route, Wrench, X } from 'lucide-react';

interface RunStep {
  id: string;
  name: string;
  type: string;
  created_at: string | null;
  input?: string;
  output?: string;
  output_preview: string;
  metadata_keys?: string[];
  routing_info?: Record<string, any>;
  memory_extract?: { count?: number; facts?: Array<{ key?: string; value?: string; category?: string }> };
  map_update?: { layer_count?: number; summary?: Record<string, any> };
}

interface AgentRunLog {
  id: string;
  thread_id?: string;
  thread_name?: string;
  run_index?: number | null;
  name: string;
  created_at: string | null;
  updated_at: string | null;
  duration_sec: number | null;
  user_input: string;
  pipeline: string;
  pipeline_name: string;
  intent: string;
  route_reason: string;
  final_answer?: string;
  final_answer_preview: string;
  message_count: number;
  tool_count: number;
  process_count: number;
  memory_count: number;
  map_event_count: number;
  tool_trace: Array<{ name: string; created_at: string | null; input?: string; output?: string; output_preview: string }>;
  memory_events: Array<{ count?: number; tool?: string; output_preview?: string; facts?: Array<{ key?: string; value?: string; category?: string }> }>;
  steps: RunStep[];
}

type FocusFilter = 'all' | 'tool' | 'memory' | 'map';
type GroupByMode = 'run' | 'thread';

function formatTime(value: string | null) {
  if (!value) return '-';
  return new Date(value).toLocaleString();
}

function metric(
  label: string,
  value: number,
  icon: ReactNode,
  options?: { active?: boolean; onClick?: () => void; title?: string },
) {
  const content = (
    <>
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </>
  );
  if (options?.onClick) {
    return (
      <button
        type="button"
        className={`agent-log-metric agent-log-metric-button ${options.active ? 'agent-log-metric-active' : ''}`}
        onClick={options.onClick}
        title={options.title || label}
      >
        {content}
      </button>
    );
  }
  return <span className="agent-log-metric">{content}</span>;
}

function LogDetailContent({
  log,
  groupBy,
  onOpenFull,
}: {
  log: AgentRunLog;
  groupBy: GroupByMode;
  onOpenFull?: () => void;
}) {
  return (
    <>
      <div className="agent-log-detail-grid">
        <div><span>分组</span><strong>{groupBy === 'run' ? `第 ${log.run_index || '-'} 次请求` : '完整会话'}</strong></div>
        <div><span>意图</span><strong>{log.intent || '-'}</strong></div>
        <div><span>依据</span><strong>{log.route_reason || '-'}</strong></div>
        <div><span>耗时</span><strong>{log.duration_sec !== null ? `${log.duration_sec}s` : '-'}</strong></div>
      </div>

      {onOpenFull && (
        <div className="agent-log-detail-actions">
          <button type="button" onClick={onOpenFull} title="查看完整运行详情">
            <Maximize2 size={13} />
            完整详情
          </button>
        </div>
      )}

      <div className="agent-log-section">
        <div className="agent-log-section-title">本次请求</div>
        <div className="agent-log-note">
          <strong>{log.user_input || log.name || '-'}</strong>
          <span>所属会话：{log.thread_name || log.name || '-'}</span>
          {log.final_answer_preview && <span>回复摘要：{log.final_answer_preview}</span>}
        </div>
        {log.final_answer && (
          <pre className="agent-log-fulltext">{log.final_answer}</pre>
        )}
      </div>

      <div className="agent-log-section">
        <div className="agent-log-section-title">工具调用</div>
        {log.tool_trace.length === 0 ? (
          <div className="agent-log-muted">无工具调用</div>
        ) : log.tool_trace.map((tool, i) => (
          <div key={`${tool.name}-${i}`} className="agent-log-tool">
            <div className="agent-log-row">
              <Wrench size={13} />
              <span>{tool.name}</span>
              <em>{tool.output_preview || '-'}</em>
            </div>
            {tool.input && (
              <div className="agent-log-io-block">
                <span>Input</span>
                <pre className="agent-log-fulltext agent-log-fulltext-compact">{tool.input}</pre>
              </div>
            )}
            {tool.output && (
              <div className="agent-log-io-block">
                <span>Output</span>
                <pre className="agent-log-fulltext agent-log-fulltext-compact">{tool.output}</pre>
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="agent-log-section">
        <div className="agent-log-section-title">记忆事件</div>
        {log.memory_events.length === 0 ? (
          <div className="agent-log-muted">无记忆事件</div>
        ) : log.memory_events.map((event, i) => (
          <div key={i} className="agent-log-memory">
            {event.tool ? <span>记忆工具：{event.tool}</span> : <span>提取数量：{event.count ?? (event.facts || []).length}</span>}
            {event.output_preview && <span>结果：{event.output_preview}</span>}
            {(event.facts || []).length === 0 && <span>未返回具体事实明细</span>}
            {(event.facts || []).map((fact, idx) => (
              <span key={idx}>{fact.category || 'memory'}：{fact.key || '-'} → {fact.value || '-'}</span>
            ))}
          </div>
        ))}
      </div>

      <div className="agent-log-section">
        <div className="agent-log-section-title">地图事件</div>
        {log.steps.filter((step) => step.map_update).length === 0 ? (
          <div className="agent-log-muted">无地图事件</div>
        ) : log.steps.filter((step) => step.map_update).map((step) => (
          <div key={`${step.id}-map`} className="agent-log-row">
            <Map size={13} />
            <span>{step.map_update?.layer_count || 0} 个图层</span>
            <em>{JSON.stringify(step.map_update?.summary || {})}</em>
          </div>
        ))}
      </div>

      <div className="agent-log-section">
        <div className="agent-log-section-title">Step 时间线</div>
        <div className="agent-log-steps">
          {log.steps.map((step) => (
            <div key={step.id} className={`agent-log-step agent-log-step-${step.type}`}>
              <span>{formatTime(step.created_at)}</span>
              <strong>{step.type}</strong>
              <em>{step.name || step.output_preview || '-'}</em>
              {step.metadata_keys && step.metadata_keys.length > 0 && (
                <code>{step.metadata_keys.join(', ')}</code>
              )}
              {step.input && (
                <div className="agent-log-step-io">
                  <span>Input</span>
                  <pre className="agent-log-step-output">{step.input}</pre>
                </div>
              )}
              {step.output && (
                <div className="agent-log-step-io">
                  <span>Output</span>
                  <pre className="agent-log-step-output">{step.output}</pre>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

export default function AgentRunLogsTab() {
  const [logs, setLogs] = useState<AgentRunLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState('');
  const [limit, setLimit] = useState(20);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [detailLog, setDetailLog] = useState<AgentRunLog | null>(null);
  const [focus, setFocus] = useState<FocusFilter>('all');
  const [groupBy, setGroupBy] = useState<GroupByMode>('run');

  const loadLogs = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: String(limit), group_by: groupBy });
      if (filter.trim()) params.set('pipeline', filter.trim());
      const resp = await fetch(`/api/agent/run-logs?${params.toString()}`, { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setLogs(data.logs || []);
      }
    } catch {
      setLogs([]);
    } finally {
      setLoading(false);
    }
  }, [filter, groupBy, limit]);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  useEffect(() => {
    if (!detailLog) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDetailLog(null);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [detailLog]);

  const exportJson = useCallback(() => {
    const blob = new Blob([JSON.stringify({ exported_at: new Date().toISOString(), logs }, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `gis-agent-run-logs-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [logs]);

  const totals = useMemo(() => logs.reduce((acc, log) => ({
    tools: acc.tools + log.tool_count,
    memories: acc.memories + log.memory_count,
    maps: acc.maps + log.map_event_count,
  }), { tools: 0, memories: 0, maps: 0 }), [logs]);

  const visibleLogs = useMemo(() => logs.filter((log) => {
    if (focus === 'tool') return log.tool_count > 0;
    if (focus === 'memory') return log.memory_count > 0;
    if (focus === 'map') return log.map_event_count > 0;
    return true;
  }), [focus, logs]);

  const focusText = {
    all: '全部运行',
    tool: '有工具调用的运行',
    memory: '有记忆事件的运行',
    map: '有地图事件的运行',
  }[focus];

  return (
    <div className="agent-run-logs">
      <div className="agent-log-help">
        默认按“每次请求”展示。同一个聊天会话里连续执行 3 个 SQL，会显示为 3 条运行记录。
      </div>
      <div className="agent-log-toolbar">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && loadLogs()}
          placeholder="筛选管线 / 问题"
        />
        <select value={groupBy} onChange={(e) => setGroupBy(e.target.value as GroupByMode)} title="日志分组">
          <option value="run">按请求</option>
          <option value="thread">按会话</option>
        </select>
        <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
          <option value={10}>10条</option>
          <option value={20}>20条</option>
          <option value={50}>50条</option>
        </select>
        <button onClick={loadLogs} disabled={loading} title="刷新">
          <RefreshCw size={14} />
          {loading ? '加载中' : '刷新'}
        </button>
        <button onClick={exportJson} disabled={logs.length === 0} title="导出 JSON">
          <Download size={14} />
          导出
        </button>
      </div>

      <div className="agent-log-summary">
        {metric('运行', logs.length, <Route size={13} />, {
          active: focus === 'all',
          onClick: () => setFocus('all'),
          title: '显示全部运行',
        })}
        {metric('工具调用', totals.tools, <Wrench size={13} />, {
          active: focus === 'tool',
          onClick: () => setFocus('tool'),
          title: '只显示包含工具调用的运行',
        })}
        {metric('记忆', totals.memories, <Brain size={13} />, {
          active: focus === 'memory',
          onClick: () => setFocus('memory'),
          title: '只显示包含记忆事件的运行',
        })}
        {metric('地图事件', totals.maps, <Map size={13} />, {
          active: focus === 'map',
          onClick: () => setFocus('map'),
          title: '只显示包含地图事件的运行',
        })}
      </div>

      {loading && <div className="agent-log-empty">加载中...</div>}
      {!loading && logs.length === 0 && <div className="agent-log-empty">暂无运行日志</div>}
      {!loading && logs.length > 0 && visibleLogs.length === 0 && (
        <div className="agent-log-empty">暂无{focusText}</div>
      )}

      {!loading && visibleLogs.length > 0 && (
        <div className="agent-log-list">
          {visibleLogs.map((log) => {
            const expanded = expandedId === log.id;
            return (
              <div key={log.id} className="agent-log-item">
                <button className="agent-log-main" onClick={() => setExpandedId(expanded ? null : log.id)}>
                  <span className="agent-log-expand">
                    {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                  </span>
                  <span className="agent-log-body">
                    <span className="agent-log-title-row">
                      <span className="agent-log-pipeline">{log.pipeline_name || log.pipeline || 'Agent Run'}</span>
                      <span className="agent-log-time">
                        <Clock size={12} />
                        {formatTime(log.updated_at || log.created_at)}
                      </span>
                    </span>
                    <span className="agent-log-question">{log.user_input || log.name}</span>
                    <span className="agent-log-preview">{log.final_answer_preview || log.route_reason || '无摘要'}</span>
                    <span className="agent-log-inline-metrics">
                      {metric('工具', log.tool_count, <Wrench size={12} />)}
                      {metric('阶段', log.process_count, <Route size={12} />)}
                      {metric('记忆', log.memory_count, <Brain size={12} />)}
                      {metric('地图', log.map_event_count, <Map size={12} />)}
                    </span>
                  </span>
                </button>

                {expanded && (
                  <div className="agent-log-detail">
                    <LogDetailContent log={log} groupBy={groupBy} onOpenFull={() => setDetailLog(log)} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {detailLog && (
        <div className="agent-log-modal-overlay" role="presentation" onClick={() => setDetailLog(null)}>
          <div className="agent-log-modal" role="dialog" aria-modal="true" aria-label="完整运行详情" onClick={(e) => e.stopPropagation()}>
            <div className="agent-log-modal-header">
              <div>
                <strong>{detailLog.pipeline_name || detailLog.pipeline || 'Agent Run'}</strong>
                <span>{detailLog.user_input || detailLog.name || '-'}</span>
              </div>
              <button type="button" onClick={() => setDetailLog(null)} title="关闭完整详情">
                <X size={16} />
              </button>
            </div>
            <div className="agent-log-modal-body">
              <LogDetailContent log={detailLog} groupBy={groupBy} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
