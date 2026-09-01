import { useState, useRef, useEffect, useCallback, useContext, KeyboardEvent, ChangeEvent } from 'react';
import { useChatMessages, useChatInteract, useChatData, useChatSession, ChainlitContext } from '@chainlit/react-client';
import { useRecoilValue, useSetRecoilState } from 'recoil';
import {
  actionState,
  askUserState,
  currentThreadIdState,
  elementState,
  firstUserInteraction,
  loadingState,
  messagesState,
  sideViewState,
  tasklistState,
  threadIdToResumeState,
  tokenCountState,
} from '@chainlit/react-client';
import type { IFileRef, IAction } from '@chainlit/react-client';
import ReactMarkdown from 'react-markdown';
import { useTranslation } from 'react-i18next';
import FeedbackBar from './FeedbackBar';
import Nl2SqlAnswer from './Nl2SqlAnswer';
import Nl2SqlClarification, { Nl2SqlClarificationPayload } from './Nl2SqlClarification';
import { formatDate, getLocale, getLocaleHeaders, type Locale } from '../i18n';

function cleanCotLeakage(text: string, translate?: (key: string) => string): string {
  if (!text || text.length < 20) return text;

  if (text.length < 120 && (text.includes('DELETE/UPDATE/DROP') || text.includes('修改、删除或新增数据') || text.includes('我不能执行'))) {
    return translate ? translate('chat.readOnlyNotice') : '我不能执行修改、删除或新增数据的操作。我只能帮助查询。';
  }
  if (text.length < 120 && text.startsWith('当前数据库中不存在')) {
    return translate ? translate('chat.noMatchingData') : '当前数据库中不存在与该问题对应的数据字段或数据表，因此无法查询。';
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

interface S2MapSelection {
  parcelId: string;
  planningAreaId?: string;
  sourceLandUseName?: string;
}

type Nl2SqlExecutionEngine = 'postgis' | 'lake';

const NL2SQL_ENGINE_STORAGE_KEY = 'gda.nl2sql.execution-engine';

function initialNl2SqlExecutionEngine(): Nl2SqlExecutionEngine {
  if (typeof window === 'undefined') return 'postgis';
  return window.localStorage.getItem(NL2SQL_ENGINE_STORAGE_KEY) === 'lake'
    ? 'lake'
    : 'postgis';
}

function dispatchWorkspaceUpdate(update: any) {
  if (!update || !['ontology', 'ontology_demo'].includes(update.tab)) return;
  (window as any).__pendingGdaWorkspaceUpdate = update;
  window.dispatchEvent(new CustomEvent('gda-workspace-update', { detail: update }));
}

export default function ChatPanel({ onMapUpdate, onDataUpdate, onLayerControl }: ChatPanelProps) {
  const { t, i18n } = useTranslation('common');
  const { messages, threadId: currentThreadId } = useChatMessages();
  const chatInteract = useChatInteract() as ReturnType<typeof useChatInteract> & {
    setIdToResume?: (threadId?: string) => void;
  };
  const { sendMessage, uploadFile, clear } = chatInteract;
  const { askUser, actions, loading } = useChatData();
  const { sessionId, connect, disconnect, session } = useChatSession();
  const setRecoilIdToResume = useSetRecoilState(threadIdToResumeState);
  const threadIdToResume = useRecoilValue(threadIdToResumeState);
  const setMessages = useSetRecoilState(messagesState);
  const setElements = useSetRecoilState(elementState);
  const setTasklists = useSetRecoilState(tasklistState);
  const setActions = useSetRecoilState(actionState);
  const setTokenCount = useSetRecoilState(tokenCountState);
  const setLoading = useSetRecoilState(loadingState);
  const setAskUser = useSetRecoilState(askUserState);
  const setSideView = useSetRecoilState(sideViewState);
  const setCurrentThreadId = useSetRecoilState(currentThreadIdState);
  const setFirstUserInteraction = useSetRecoilState(firstUserInteraction);
  const apiClient = useContext(ChainlitContext);
  const [input, setInput] = useState('');
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);
  const [isRecording, setIsRecording] = useState(false);
  const [voiceLang, setVoiceLang] = useState<Locale>(() => getLocale());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const processedMetaRef = useRef<Set<string>>(new Set());
  const recognitionRef = useRef<any>(null);
  const prevLoadingRef = useRef(false);
  const s2SelectionTemplateRef = useRef('');
  const [s2MapSelection, setS2MapSelection] = useState<S2MapSelection | null>(null);
  const [nl2sqlExecutionEngine, setNl2SqlExecutionEngine] =
    useState<Nl2SqlExecutionEngine>(initialNl2SqlExecutionEngine);
  // Chainlit's sendMessage optimistically adds the user message even when the
  // Socket.IO transport is not connected.  Keep an explicit connection state
  // so a click during the new-chat reconnect window cannot create a message
  // that only exists in the browser and never reaches the backend.
  const [socketConnected, setSocketConnected] = useState(false);

  useEffect(() => {
    setVoiceLang(getLocale());
  }, [i18n.resolvedLanguage]);

  useEffect(() => {
    const socket = session?.socket;
    if (!socket) {
      setSocketConnected(false);
      return;
    }
    const sync = () => setSocketConnected(Boolean(socket.connected));
    sync();
    socket.on('connect', sync);
    socket.on('disconnect', sync);
    socket.on('connect_error', sync);
    return () => {
      socket.off('connect', sync);
      socket.off('disconnect', sync);
      socket.off('connect_error', sync);
    };
  }, [session]);

  // Session management state
  const [showSessions, setShowSessions] = useState(false);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [resumingSessionId, setResumingSessionId] = useState<string | null>(null);
  const [connectMode, setConnectMode] = useState<'new' | 'resume' | null>(null);
  // Socket.IO can be connected before Chainlit finishes on_chat_start.  The
  // backend marks the session-ready welcome message explicitly; resumed
  // threads use their existing thread id as the equivalent readiness signal.
  const [sessionReady, setSessionReady] = useState(false);

  useEffect(() => {
    if (!socketConnected || connectMode) {
      if (!socketConnected || connectMode) setSessionReady(false);
      return;
    }
    const hasReadyMarker = (messages || []).some((step: any) => (
      step?.metadata?.session_ready === true
      || (step?.steps || []).some((child: any) => child?.metadata?.session_ready === true)
    ));
    if (hasReadyMarker || Boolean(currentThreadId)) setSessionReady(true);
  }, [socketConnected, connectMode, messages, currentThreadId]);

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
    for (const msg of flattenMessages(messages)) {
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
      if (meta.workspace_update) {
        dispatchWorkspaceUpdate(meta.workspace_update);
        processedMetaRef.current.add(msg.id);
      }
      if (meta.memory_extract) {
        processedMetaRef.current.add(msg.id);
      }
      if (meta.s2_parcel_selection) {
        s2SelectionTemplateRef.current = String(meta.s2_parcel_selection.prompt_template || '');
        setS2MapSelection(null);
        processedMetaRef.current.add(msg.id);
      }
      if (meta.subtask_progress) {
        processedMetaRef.current.add(msg.id);
      }
    }
  }, [messages, onMapUpdate, onDataUpdate, onLayerControl]);

  useEffect(() => {
    const handleS2ParcelSelection = (rawEvent: Event) => {
      const detail = (rawEvent as CustomEvent).detail || {};
      const parcelId = String(detail.parcelId || '');
      if (!parcelId.startsWith('parcel_')) return;
      const template = s2SelectionTemplateRef.current;
      setInput(template
        ? template.replace('{parcel_id}', parcelId)
        : t('chat.s2SelectionPrompt', { parcelId }));
      setS2MapSelection({
        parcelId,
        planningAreaId: String(detail.planningAreaId || ''),
        sourceLandUseName: String(detail.sourceLandUseName || ''),
      });
      window.setTimeout(() => textareaRef.current?.focus(), 0);
    };
    window.addEventListener('s2-map-parcel-selected', handleS2ParcelSelection);
    return () => window.removeEventListener('s2-map-parcel-selected', handleS2ParcelSelection);
  }, [t]);

  useEffect(() => {
    const handleChatPrefill = (rawEvent: Event) => {
      const detail = (rawEvent as CustomEvent<{ text?: string }>).detail;
      const text = String(detail?.text || '').trim();
      if (!text) return;
      setInput(text);
      window.setTimeout(() => textareaRef.current?.focus(), 0);
    };
    window.addEventListener('gda-chat-prefill', handleChatPrefill);
    return () => window.removeEventListener('gda-chat-prefill', handleChatPrefill);
  }, []);

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
            if (data.workspace_update) {
              dispatchWorkspaceUpdate(data.workspace_update);
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
    if (!socketConnected || !sessionReady) {
      // Do not call sendMessage here: it intentionally performs an optimistic
      // local insert, which would otherwise look like a successful send.
      console.warn('[ChatPanel] message not sent because Chainlit session is not ready');
      return;
    }
    const fileRefs: IFileRef[] = pendingFiles
      .filter((f) => f.id && !f.error)
      .map((f) => ({ id: f.id! }));
    sendMessage(
      {
        name: 'user',
        type: 'user_message',
        output: text || t('chat.fileUploadMessage'),
        metadata: { nl2sql_execution_engine: nl2sqlExecutionEngine, locale: getLocale() },
      },
      fileRefs.length > 0 ? fileRefs : undefined
    );
    setInput('');
    setS2MapSelection(null);
    setPendingFiles([]);
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  }, [input, pendingFiles, sendMessage, nl2sqlExecutionEngine, socketConnected, sessionReady, t]);

  const handleNl2SqlClarificationSelect = useCallback((text: string) => {
    setInput(text);
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  }, []);

  const selectNl2SqlExecutionEngine = useCallback((engine: Nl2SqlExecutionEngine) => {
    setNl2SqlExecutionEngine(engine);
    window.localStorage.setItem(NL2SQL_ENGINE_STORAGE_KEY, engine);
  }, []);

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
      apiClient.callAction(action, sessionId)
        .then(() => {
          const fetchPending = () => {
            fetch('/api/map/pending', { credentials: 'include' })
              .then(r => r.json())
              .then(data => {
                if (data.map_update) onMapUpdate(data.map_update);
                if (data.data_update) onDataUpdate(data.data_update.csv || data.data_update.file);
                if (data.workspace_update) dispatchWorkspaceUpdate(data.workspace_update);
              })
              .catch(() => {});
          };
          window.setTimeout(fetchPending, 300);
          window.setTimeout(fetchPending, 1800);
        })
        .catch((err: any) => console.error('[ActionBtn] callAction failed:', err));
    } else {
      console.warn('[ActionBtn] apiClient or sessionId unavailable');
    }
  }, [apiClient, sessionId, onMapUpdate, onDataUpdate]);

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

  const setResumeThreadId = useCallback((threadId?: string) => {
    chatInteract.setIdToResume?.(threadId);
    setRecoilIdToResume(threadId);
  }, [chatInteract, setRecoilIdToResume]);

  const resetVisibleChatState = useCallback(() => {
    setMessages([]);
    setElements([]);
    setTasklists([]);
    setActions([]);
    setTokenCount(0);
    setLoading(false);
    setAskUser(undefined);
    setSideView(undefined);
    setCurrentThreadId(undefined);
    setFirstUserInteraction(undefined);
  }, [
    setMessages,
    setElements,
    setTasklists,
    setActions,
    setTokenCount,
    setLoading,
    setAskUser,
    setSideView,
    setCurrentThreadId,
    setFirstUserInteraction,
  ]);

  useEffect(() => {
    if (!connectMode) return;
    if (connectMode === 'resume' && !threadIdToResume) return;
    if (connectMode === 'new' && threadIdToResume) return;

    processedMetaRef.current.clear();
    disconnect();

    if (connectMode === 'resume') {
      resetVisibleChatState();
    } else {
      clear();
    }

    const timer = window.setTimeout(() => {
      connect({ userEnv: { locale: getLocale() } });
      if (connectMode === 'resume') {
        window.setTimeout(() => setResumingSessionId(null), 3000);
      }
      setConnectMode(null);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [connectMode, threadIdToResume]);

  useEffect(() => {
    if (resumingSessionId && currentThreadId === resumingSessionId) {
      setResumingSessionId(null);
      setShowSessions(false);
    }
  }, [resumingSessionId, currentThreadId]);

  const handleNewChat = useCallback(() => {
    // Clear resume ID so Chainlit creates a fresh thread
    setSessionReady(false);
    setResumeThreadId(undefined);
    setResumingSessionId(null);
    setConnectMode('new');
    setShowSessions(false);
  }, [setResumeThreadId]);

  const handleResumeSession = useCallback((threadId: string) => {
    setSessionReady(false);
    setResumeThreadId(threadId);
    setResumingSessionId(threadId);
    setConnectMode('resume');
  }, [setResumeThreadId]);

  const handleDeleteSession = useCallback(async (threadId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm(t('chat.deleteSessionConfirm'))) return;
    try {
      await fetch(`/api/sessions/${threadId}`, { method: 'DELETE', credentials: 'include' });
      setSessions(prev => prev.filter(s => s.id !== threadId));
    } catch { /* ignore */ }
  }, [t]);

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
        <span>{t('chat.title')}</span>
        <div className="chat-header-actions">
          <button className="chat-header-btn" onClick={handleNewChat} title={t('chat.newChat')} aria-label={t('chat.newChat')}>
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 5v14M5 12h14"/>
            </svg>
          </button>
          <button className={`chat-header-btn ${showSessions ? 'active' : ''}`} onClick={handleToggleSessions} title={t('chat.history')} aria-label={t('chat.history')}>
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
            <span>{t('chat.history')}</span>
            <button className="session-close-btn" onClick={() => setShowSessions(false)} aria-label={t('chat.closeHistory')}>&times;</button>
          </div>
          {sessionsLoading ? (
            <div className="session-empty">{t('app.loading')}</div>
          ) : sessions.length === 0 ? (
            <div className="session-empty">{t('chat.noHistory')}</div>
          ) : (
            <div className="session-items">
              {sessions.map(s => (
                <div
                  key={s.id}
                  className={`session-item ${s.id === currentThreadId ? 'session-item-active' : ''} ${s.id === resumingSessionId ? 'session-item-resuming' : ''}`}
                  onClick={() => handleResumeSession(s.id)}
                >
                  <div className="session-item-name">{s.name || t('chat.untitledSession')}</div>
                  <div className="session-item-meta">
                    {s.id === resumingSessionId ? t('chat.resumeLoading') : s.updated_at ? formatDate(s.updated_at, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''}
                  </div>
                  <button
                    className="session-item-delete"
                    onClick={(e) => handleDeleteSession(s.id, e)}
                    title={t('chat.deleteSession')}
                    aria-label={t('chat.deleteSession')}
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
          const nl2sqlPresentation = meta?.nl2sql_presentation;
          const nl2sqlClarification = meta?.nl2sql_clarification as Nl2SqlClarificationPayload | undefined;
          const displayOutput = isUser ? (msg.output || '') : cleanCotLeakage(msg.output || '', t);
          return (
            <div key={msg.id} className={`chat-message ${isUser ? 'user' : 'assistant'} ${nl2sqlPresentation ? 'nl2sql-message' : ''}`}>
              {!isUser && <div className="assistant-avatar">AI</div>}
              <div className="message-content">
                {routingInfo && !nl2sqlPresentation && (
                  <div className="routing-card">
                    <div className="routing-card-row">
                      <span className="routing-label">{t('chat.intent')}</span>
                      <span className={`pipeline-badge ${routingInfo.pipeline}`}>{routingInfo.intent}</span>
                    </div>
                    <div className="routing-card-row">
                      <span className="routing-label">{t('chat.pipeline')}</span>
                      <span className="routing-value">{routingInfo.pipeline_name}</span>
                    </div>
                    {routingInfo.reason && (
                      <div className="routing-card-row">
                        <span className="routing-label">{t('chat.reason')}</span>
                        <span className="routing-reason">{routingInfo.reason}</span>
                      </div>
                    )}
                  </div>
                )}
                {isUser ? (
                  <span>{displayOutput}</span>
                ) : nl2sqlPresentation ? (
                  <Nl2SqlAnswer presentation={nl2sqlPresentation} />
                ) : displayOutput ? (
                  <ReactMarkdown>{displayOutput}</ReactMarkdown>
                ) : null}
                {!isUser && !nl2sqlPresentation && nl2sqlClarification && (
                  <Nl2SqlClarification
                    clarification={nl2sqlClarification}
                    onSelect={handleNl2SqlClarificationSelect}
                  />
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
            <div className="message-content">{t('chat.pleaseUploadFile')}</div>
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
        {s2MapSelection && (
          <div className="s2-map-selection-banner" role="status">
            <div>
              <strong>{t('chat.mapParcelSelected')}</strong>
              <span>{s2MapSelection.parcelId}</span>
              {(s2MapSelection.planningAreaId || s2MapSelection.sourceLandUseName) && (
                <small>
                  {[s2MapSelection.planningAreaId, s2MapSelection.sourceLandUseName].filter(Boolean).join(' · ')}
                </small>
              )}
            </div>
            <button
              type="button"
              onClick={() => {
                setS2MapSelection(null);
                setInput('');
              }}
              aria-label={t('chat.clearMapSelection')}
            >×</button>
          </div>
        )}
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
        <div className="nl2sql-engine-row">
          <span>{t('chat.queryEngine')}</span>
          <span className={`chat-transport-status ${sessionReady ? 'connected' : 'connecting'}`} role="status">
            {sessionReady ? t('chat.connected') : socketConnected ? t('chat.initializing') : t('chat.connecting')}
          </span>
          <div className="nl2sql-engine-segment" role="group" aria-label={t('chat.queryEngineAria')}>
            <button
              type="button"
              className={nl2sqlExecutionEngine === 'postgis' ? 'active' : ''}
              onClick={() => selectNl2SqlExecutionEngine('postgis')}
              title={t('chat.postgisTitle')}
              aria-pressed={nl2sqlExecutionEngine === 'postgis'}
            >PostGIS</button>
            <button
              type="button"
              className={nl2sqlExecutionEngine === 'lake' ? 'active' : ''}
              onClick={() => selectNl2SqlExecutionEngine('lake')}
              title={t('chat.lakeTitle')}
              aria-pressed={nl2sqlExecutionEngine === 'lake'}
            >{t('chat.lake')}</button>
          </div>
        </div>
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
          <button className="btn-attach" onClick={() => fileInputRef.current?.click()} title={t('chat.uploadFile')} aria-label={t('chat.uploadFile')}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
            </svg>
          </button>
          {speechSupported && (
            <button
              className={`btn-voice ${isRecording ? 'recording' : ''}`}
              onClick={toggleVoiceRecording}
              onContextMenu={(e) => { e.preventDefault(); toggleVoiceLang(); }}
              title={isRecording ? t('chat.stopRecording') : `${t('chat.voiceInput')} (${voiceLang === 'zh-CN' ? t('language.zhCN') : voiceLang === 'ar-AE' ? t('language.arAE') : 'English'})`}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/>
                <line x1="8" y1="23" x2="16" y2="23"/>
              </svg>
              <span className="voice-lang-badge">{t(`chat.voiceBadge.${voiceLang}`, { defaultValue: voiceLang === 'zh-CN' ? 'ZH' : voiceLang === 'ar-AE' ? 'AR' : 'EN' })}</span>
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
            placeholder={t('chat.inputPlaceholder')}
            rows={1}
          />
          <button
            className="btn-send"
            onClick={handleSend}
            disabled={!socketConnected || !sessionReady || (!input.trim() && pendingFiles.length === 0)}
            title={sessionReady ? t('chat.send') : t('chat.sessionInitializing')}
          >
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
    // Chainlit emits uncaught handler exceptions as ``run`` steps with
    // ``isError``.  They are not message steps, so filtering them out made a
    // failed request look exactly like a request that never got a response.
    // Keep the raw detail out of the UI and surface one actionable assistant
    // message; the server log/audit trail remains the diagnostic source.
    if (step.type === 'run' && step.isError && step.output) {
      result.push({
        ...step,
        type: 'assistant_message',
        output: '请求处理失败，系统未返回结果。请稍后重试；若持续出现，请联系管理员。',
        metadata: {
          ...(step.metadata || {}),
          nl2sql_error: {
            code: 'unhandled_backend_error',
            sql_executed: false,
          },
        },
      });
    }
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
