import { useState, useRef, useEffect, useCallback, useContext, KeyboardEvent, ChangeEvent } from 'react';
import { useChatMessages, useChatInteract, useChatData, useChatSession, ChainlitContext } from '@chainlit/react-client';
import { useSetRecoilState } from 'recoil';
import { threadIdToResumeState } from '@chainlit/react-client';
import type { IFileRef, IAction } from '@chainlit/react-client';
import ReactMarkdown from 'react-markdown';
import FeedbackBar from './FeedbackBar';

function cleanCotLeakage(text: string): string {
  if (!text || text.length < 20) return text;

  if (text.length < 120 && (text.includes('DELETE/UPDATE/DROP') || text.includes('修改、删除或新增数据') || text.includes('我不能执行'))) {
    return '我不能执行修改、删除或新增数据的操作。我只能帮助查询。';
  }
  if (text.length < 120 && text.startsWith('当前数据库中不存在')) {
    return '当前数据库中不存在与该问题对应的数据字段或数据表，因此无法查询。';
  }

  const finalMarkers = ['已成功', '我无法', '查询成功', '经过查询', '结果如下', '以下是结果', '数据来源表'];
  let trimmed = text;
  for (const marker of finalMarkers) {
    const idx = trimmed.indexOf(marker);
    if (idx > 0) {
      trimmed = trimmed.slice(idx);
      break;
    }
  }

  const patterns = [
    /(?:^|\n)(?:用户(?:想要|要求|想|问|明确)[^\n]{0,200}\n?)+/gm,
    /(?:^|\n)(?:步骤\d+[:：][^\n]{0,200}\n?)+/gm,
    /(?:^|\n)(?:(?:让我|我来|我需要|我应该|我查看|我先|根据规则|根据返回|根据 grounding|不过根据|所以我|实际上|不过，安全|不过，|现在我来|这涉及到|安全规则要求)[^\n]{0,220}\n?)+/gm,
  ];
  let cleaned = trimmed;
  for (const p of patterns) cleaned = cleaned.replace(p, '\n');
  const lines = cleaned.split('\n').map(s => s.trim()).filter(Boolean);
  const result = lines.join('\n');
  return result.length >= 10 ? result : text;
}

interface ChatPanelProps {
  onMapUpdate: (config: any) => void;
  onDataUpdate: (file: string) => void;
  onLayerControl?: (control: any) => void;
}

interface PendingFile {
  file: File;
  progress: number;
  id?: string;
  error?: boolean;
}

interface SessionInfo {
  id: string;
  name: string;
  created_at: string | null;
  updated_at: string | null;
}

export default function ChatPanel({ onMapUpdate, onDataUpdate, onLayerControl }: ChatPanelProps) {
  const { messages } = useChatMessages();
  const { sendMessage, uploadFile, clear } = useChatInteract();
  const { askUser, actions, loading } = useChatData();
  const { sessionId, connect, disconnect } = useChatSession();
  const setIdToResume = useSetRecoilState(threadIdToResumeState);
  const apiClient = useContext(ChainlitContext);
  const [input, setInput] = useState('');
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);
  const [isRecording, setIsRecording] = useState(false);
  const [voiceLang, setVoiceLang] = useState<'zh-CN' | 'en-US'>('zh-CN');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const processedMetaRef = useRef<Set<string>>(new Set());
  const recognitionRef = useRef<any>(null);
  const prevLoadingRef = useRef(false);

  // Session management state
  const [showSessions, setShowSessions] = useState(false);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);

  // Mention autocomplete state
  const [mentionTargets, setMentionTargets] = useState<Array<{
    handle: string; label: string; type: string;
    description: string; allowed: boolean;
    display_name: string; aliases: string[]; pinned: boolean; hidden: boolean;
  }>>([]);
  const [showMention, setShowMention] = useState(false);
  const [mentionFilter, setMentionFilter] = useState('');
  const [mentionIndex, setMentionIndex] = useState(0);
  const mentionRef = useRef<HTMLDivElement>(null);

  // Check browser support for Web Speech API
  const speechSupported = typeof window !== 'undefined' &&
    ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (!messages || messages.length === 0) return;
    for (const msg of messages) {
      if (processedMetaRef.current.has(msg.id)) continue;
      const meta = msg.metadata as any;
      // Debug: log all messages with metadata
      if (meta && Object.keys(meta).length > 0) {
        console.log('[ChatPanel] msg with metadata:', msg.id, 'keys:', Object.keys(meta), 'output_len:', (msg.output || '').length);
      }
      if (!meta) continue;
      if (meta.map_update) {
        console.log('[ChatPanel] map_update detected:', JSON.stringify(meta.map_update).substring(0, 200));
        onMapUpdate(meta.map_update);
        processedMetaRef.current.add(msg.id);
      }
      if (meta.layer_control && onLayerControl) {
        onLayerControl(meta.layer_control);
        processedMetaRef.current.add(msg.id);
      }
      if (meta.data_update) {
        onDataUpdate(meta.data_update.csv || meta.data_update.file);
        processedMetaRef.current.add(msg.id);
      }
      if (meta.memory_extract) {
        processedMetaRef.current.add(msg.id);
      }
      if (meta.subtask_progress) {
        processedMetaRef.current.add(msg.id);
      }
    }
  }, [messages, onMapUpdate, onDataUpdate, onLayerControl]);

  // Poll /api/map/pending when assistant response completes (loading: true → false)
  // This bypasses Chainlit's limitation of not delivering step-level metadata via WebSocket.
  // Fetches twice: immediately + after 2s delay (ensures pending queue is written)
  useEffect(() => {
    if (prevLoadingRef.current && !loading) {
      const fetchPending = () => {
        fetch('/api/map/pending', { credentials: 'include' })
          .then(r => r.json())
          .then(data => {
            if (data.map_update) {
              console.log('[ChatPanel] map_update from /api/map/pending:', JSON.stringify(data.map_update).substring(0, 200));
              onMapUpdate(data.map_update);
            }
            if (data.data_update) {
              onDataUpdate(data.data_update.csv || data.data_update.file);
            }
          })
          .catch(() => {});
      };
      fetchPending();
      // Retry after 2s to catch late-written pending updates
      const timer = setTimeout(fetchPending, 2000);
      return () => clearTimeout(timer);
    }
    prevLoadingRef.current = loading;
  }, [loading, onMapUpdate, onDataUpdate]);

  const handleFileSelect = useCallback(async (e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    const newPending: PendingFile[] = [];
    for (let i = 0; i < files.length; i++) {
      newPending.push({ file: files[i], progress: 0 });
    }
    setPendingFiles((prev) => [...prev, ...newPending]);
    for (const entry of newPending) {
      try {
        const { promise } = uploadFile(entry.file, (progress) => {
          setPendingFiles((prev) =>
            prev.map((f) => (f.file === entry.file ? { ...f, progress } : f))
          );
        });
        const result = await promise;
        setPendingFiles((prev) =>
          prev.map((f) => (f.file === entry.file ? { ...f, id: result.id, progress: 100 } : f))
        );
      } catch {
        setPendingFiles((prev) =>
          prev.map((f) => (f.file === entry.file ? { ...f, error: true } : f))
        );
      }
    }
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, [uploadFile]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text && pendingFiles.length === 0) return;
    const fileRefs: IFileRef[] = pendingFiles
      .filter((f) => f.id && !f.error)
      .map((f) => ({ id: f.id! }));
    sendMessage(
      { name: 'user', type: 'user_message', output: text || '(文件上传)' },
      fileRefs.length > 0 ? fileRefs : undefined
    );
    setInput('');
    setPendingFiles([]);
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  }, [input, pendingFiles, sendMessage]);

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (showMention) {
      const filtered = mentionTargets.filter(t => matchTarget(t, mentionFilter));
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setMentionIndex(i => Math.min(i + 1, filtered.length - 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setMentionIndex(i => Math.max(i - 1, 0));
        return;
      }
      if ((e.key === 'Enter' || e.key === 'Tab') && filtered.length > 0) {
        e.preventDefault();
        const selected = filtered[mentionIndex];
        setInput(`@${selected.handle} `);
        setShowMention(false);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setShowMention(false);
        return;
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  const handleTextareaInput = () => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + 'px';
    }
  };

  const removePendingFile = (file: File) => {
    setPendingFiles((prev) => prev.filter((f) => f.file !== file));
  };

  const handleAction = useCallback((action: IAction) => {
    if (apiClient && sessionId) {
      apiClient.callAction(action, sessionId).catch((err: any) =>
        console.error('[ActionBtn] callAction failed:', err)
      );
    } else {
      console.warn('[ActionBtn] apiClient or sessionId unavailable');
    }
  }, [apiClient, sessionId]);

  const toggleVoiceRecording = useCallback(() => {
    if (!speechSupported) return;

    if (isRecording && recognitionRef.current) {
      recognitionRef.current.stop();
      setIsRecording(false);
      return;
    }

    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.lang = voiceLang;
    recognition.interimResults = false;
    recognition.continuous = false;

    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript;
      setInput((prev) => prev + (prev ? ' ' : '') + transcript);
      setIsRecording(false);
    };

    recognition.onerror = () => {
      setIsRecording(false);
    };

    recognition.onend = () => {
      setIsRecording(false);
    };

    recognitionRef.current = recognition;
    recognition.start();
    setIsRecording(true);
  }, [speechSupported, isRecording, voiceLang]);

  const toggleVoiceLang = useCallback(() => {
    setVoiceLang((prev) => prev === 'zh-CN' ? 'en-US' : 'zh-CN');
  }, []);

  const matchTarget = useCallback((t: {
    handle: string; display_name: string; aliases: string[]; hidden: boolean; allowed: boolean;
  }, q: string) => {
    if (t.hidden || !t.allowed) return false;
    if (!q) return true;
    if (t.handle.toLowerCase().includes(q)) return true;
    if (t.display_name && t.display_name.toLowerCase().includes(q)) return true;
    if (t.aliases && t.aliases.some(a => a.toLowerCase().includes(q))) return true;
    return false;
  }, []);

  const fetchMentionTargets = useCallback(async () => {
    try {
      const resp = await fetch('/api/agents/mention-targets', { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setMentionTargets(data.targets || []);
      }
    } catch { /* ignore */ }
  }, []);

  // --- Session management ---
  const fetchSessions = useCallback(async () => {
    setSessionsLoading(true);
    try {
      const resp = await fetch('/api/sessions', { credentials: 'include' });
      if (resp.ok) {
        const data = await resp.json();
        setSessions(data.sessions || []);
      }
    } catch { /* ignore */ }
    finally { setSessionsLoading(false); }
  }, []);

  const handleNewChat = useCallback(() => {
    // Clear resume ID so Chainlit creates a fresh thread
    setIdToResume(undefined);
    clear();
    processedMetaRef.current.clear();
    disconnect();
    setTimeout(() => connect({ userEnv: {} }), 300);
    setShowSessions(false);
  }, [clear, disconnect, connect, setIdToResume]);

  const handleResumeSession = useCallback((threadId: string) => {
    setIdToResume(threadId);
    clear();
    processedMetaRef.current.clear();
    disconnect();
    setTimeout(() => connect({ userEnv: {} }), 300);
    setShowSessions(false);
  }, [clear, disconnect, connect, setIdToResume]);

  const handleDeleteSession = useCallback(async (threadId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('确定删除此会话？')) return;
    try {
      await fetch(`/api/sessions/${threadId}`, { method: 'DELETE', credentials: 'include' });
      setSessions(prev => prev.filter(s => s.id !== threadId));
    } catch { /* ignore */ }
  }, []);

  const handleToggleSessions = useCallback(() => {
    const next = !showSessions;
    setShowSessions(next);
    if (next) fetchSessions();
  }, [showSessions, fetchSessions]);

  const flatMessages = flattenMessages(messages || []);

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <svg className="chat-header-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
        <span>对话</span>
        <div className="chat-header-actions">
          <button className="chat-header-btn" onClick={handleNewChat} title="新建对话">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 5v14M5 12h14"/>
            </svg>
          </button>
          <button className={`chat-header-btn ${showSessions ? 'active' : ''}`} onClick={handleToggleSessions} title="历史会话">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
            </svg>
          </button>
        </div>
      </div>

      {/* Session history panel */}
      {showSessions && (
        <div className="session-list">
          <div className="session-list-header">
            <span>历史会话</span>
            <button className="session-close-btn" onClick={() => setShowSessions(false)}>&times;</button>
          </div>
          {sessionsLoading ? (
            <div className="session-empty">加载中...</div>
          ) : sessions.length === 0 ? (
            <div className="session-empty">暂无历史会话</div>
          ) : (
            <div className="session-items">
              {sessions.map(s => (
                <div
                  key={s.id}
                  className={`session-item ${s.id === sessionId ? 'session-item-active' : ''}`}
                  onClick={() => handleResumeSession(s.id)}
                >
                  <div className="session-item-name">{s.name || '未命名会话'}</div>
                  <div className="session-item-meta">
                    {s.updated_at ? new Date(s.updated_at).toLocaleString() : ''}
                  </div>
                  <button
                    className="session-item-delete"
                    onClick={(e) => handleDeleteSession(s.id, e)}
                    title="删除"
                  >&times;</button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="chat-messages">
        {flatMessages.map((msg) => {
          const isUser = msg.type?.includes('user');
          const meta = msg.metadata as any;
          const routingInfo = meta?.routing_info;
          const displayOutput = isUser ? (msg.output || '') : cleanCotLeakage(msg.output || '');
          return (
            <div key={msg.id} className={`chat-message ${isUser ? 'user' : 'assistant'}`}>
              {!isUser && <div className="assistant-avatar">AI</div>}
              <div className="message-content">
                {routingInfo ? (
                  <div className="routing-card">
                    <div className="routing-card-row">
                      <span className="routing-label">意图</span>
                      <span className={`pipeline-badge ${routingInfo.pipeline}`}>{routingInfo.intent}</span>
                    </div>
                    <div className="routing-card-row">
                      <span className="routing-label">管线</span>
                      <span className="routing-value">{routingInfo.pipeline_name}</span>
                    </div>
                    {routingInfo.reason && (
                      <div className="routing-card-row">
                        <span className="routing-label">依据</span>
                        <span className="routing-reason">{routingInfo.reason}</span>
                      </div>
                    )}
                  </div>
                ) : isUser ? (
                  <span>{displayOutput}</span>
                ) : (
                  <ReactMarkdown>{displayOutput}</ReactMarkdown>
                )}
                {msg.elements?.map((el: any) => (
                  <span key={el.id} className="file-chip" title={el.name}>
                    {getFileIcon(el.name)} {el.name}
                  </span>
                ))}
                {!isUser && displayOutput && (
                  <FeedbackBar
                    messageId={msg.id || ''}
                    query={(() => {
                      const idx = flatMessages.indexOf(msg);
                      for (let i = idx - 1; i >= 0; i--) {
                        if (flatMessages[i].type?.includes('user')) return flatMessages[i].output || '';
                      }
                      return '';
                    })()}
                    response={displayOutput}
                    pipelineType={routingInfo?.pipeline}
                  />
                )}
              </div>
            </div>
          );
        })}

        {loading && (
          <div className="chat-message assistant">
            <div className="assistant-avatar">AI</div>
            <div className="message-content">
              <div className="streaming-indicator">
                <span className="streaming-dot" />
                <span className="streaming-dot" />
                <span className="streaming-dot" />
              </div>
            </div>
          </div>
        )}

        {askUser && askUser.spec.type === 'action' && (
          <div className="chat-message assistant">
            <div className="assistant-avatar">AI</div>
            <div className="message-content">
              <div className="action-buttons">
                {actions
                  .filter((a) => a.forId === askUser.spec.step_id)
                  .map((action) => (
                    <button key={action.id} className="action-btn" onClick={() => askUser.callback(action)}>
                      {action.label || action.name}
                    </button>
                  ))}
              </div>
            </div>
          </div>
        )}

        {askUser && askUser.spec.type === 'file' && (
          <div className="chat-message assistant">
            <div className="assistant-avatar">AI</div>
            <div className="message-content">请上传文件</div>
          </div>
        )}

        {actions.length > 0 && !askUser && (() => {
          // Deduplicate: keep only the latest action per name+value
          const seen = new Set<string>();
          const unique = [...actions].reverse().filter((a) => {
            const key = `${a.name}_${(a as any).value ?? ''}`;
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
          }).reverse();
          return (
            <div className="action-buttons" style={{ padding: '0 4px' }}>
              {unique.map((action) => (
                <button key={action.id} className="action-btn" onClick={() => {
                  handleAction(action);
                }}>
                  {action.label || action.name}
                </button>
              ))}
            </div>
          );
        })()}

        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-area">
        {pendingFiles.length > 0 && (
          <div className="pending-files">
            {pendingFiles.map((pf, idx) => (
              <span key={idx} className={`file-chip ${pf.error ? 'file-error' : ''}`}>
                {pf.error ? '\u274C' : pf.progress < 100 ? `${Math.round(pf.progress)}%` : '\u2705'}{' '}
                {pf.file.name}
                <button className="file-chip-remove" onClick={() => removePendingFile(pf.file)}>×</button>
              </span>
            ))}
          </div>
        )}
        <div className="chat-input-container">
          {showMention && (
            <div className="mention-dropdown" ref={mentionRef}>
              {mentionTargets
                .filter(t => matchTarget(t, mentionFilter))
                .sort((a, b) => (a.pinned === b.pinned ? 0 : a.pinned ? -1 : 1))
                .map((t, idx) => (
                  <div
                    key={t.handle}
                    className={`mention-item ${idx === mentionIndex ? 'mention-item-active' : ''}`}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      setInput(`@${t.handle} `);
                      setShowMention(false);
                      textareaRef.current?.focus();
                    }}
                  >
                    <span className="mention-handle">@{t.display_name || t.handle}</span>
                    <span className="mention-type">{t.type}</span>
                    <span className="mention-desc">
                      {t.aliases && t.aliases.length > 0
                        ? `${t.description} · 别名: ${t.aliases.join(', ')}`
                        : t.description}
                    </span>
                  </div>
                ))}
              {mentionTargets.filter(t => matchTarget(t, mentionFilter)).length === 0 && (
                <div className="mention-item mention-empty">无匹配目标</div>
              )}
            </div>
          )}
          <input
            ref={fileInputRef}
            multiple
            accept=".csv,.xlsx,.xls,.shp,.zip,.geojson,.gpkg,.kml,.kmz,.png,.jpg,.docx,.pdf"
            onChange={handleFileSelect}
            style={{ display: 'none' }}
          />
          <button className="btn-attach" onClick={() => fileInputRef.current?.click()} title="上传文件">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
            </svg>
          </button>
          {speechSupported && (
            <button
              className={`btn-voice ${isRecording ? 'recording' : ''}`}
              onClick={toggleVoiceRecording}
              onContextMenu={(e) => { e.preventDefault(); toggleVoiceLang(); }}
              title={isRecording ? '停止录音' : `语音输入 (${voiceLang === 'zh-CN' ? '中文' : 'EN'})`}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/>
                <line x1="8" y1="23" x2="16" y2="23"/>
              </svg>
              <span className="voice-lang-badge">{voiceLang === 'zh-CN' ? '中' : 'EN'}</span>
            </button>
          )}
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => {
              const val = e.target.value;
              setInput(val);
              const match = val.match(/^\s*@(\S*)$/);
              if (match) {
                if (mentionTargets.length === 0) fetchMentionTargets();
                setMentionFilter(match[1].toLowerCase());
                setShowMention(true);
                setMentionIndex(0);
              } else if (val.match(/^\s*@\S+\s/)) {
                setShowMention(false);
              } else if (!val.startsWith('@')) {
                setShowMention(false);
              }
            }}
            onKeyDown={handleKeyDown}
            onInput={handleTextareaInput}
            placeholder="输入消息... (Enter 发送)"
            rows={1}
          />
          <button className="btn-send" onClick={handleSend} disabled={!input.trim() && pendingFiles.length === 0} title="发送">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}

function flattenMessages(steps: any[]): any[] {
  const result: any[] = [];
  for (const step of steps) {
    if (step.type?.includes('message') && step.output) result.push(step);
    if (step.steps && step.steps.length > 0) result.push(...flattenMessages(step.steps));
  }
  return result;
}

function getFileIcon(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'shp': case 'geojson': case 'gpkg': case 'kml': return '\uD83D\uDDFA\uFE0F';
    case 'csv': case 'xlsx': case 'xls': return '\uD83D\uDCCA';
    case 'html': return '\uD83C\uDF10';
    case 'png': case 'jpg': return '\uD83D\uDDBC\uFE0F';
    case 'docx': case 'pdf': return '\uD83D\uDCC4';
    default: return '\uD83D\uDCC1';
  }
}
