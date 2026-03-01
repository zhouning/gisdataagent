import { useState, useRef, useEffect, useCallback, KeyboardEvent, ChangeEvent } from 'react';
import { useChatMessages, useChatInteract, useChatData } from '@chainlit/react-client';
import type { IFileRef } from '@chainlit/react-client';
import ReactMarkdown from 'react-markdown';

interface ChatPanelProps {
  onMapUpdate: (config: any) => void;
  onDataUpdate: (file: string) => void;
}

interface PendingFile {
  file: File;
  progress: number;
  id?: string;
  error?: boolean;
}

export default function ChatPanel({ onMapUpdate, onDataUpdate }: ChatPanelProps) {
  const { messages } = useChatMessages();
  const { sendMessage, uploadFile } = useChatInteract();
  const { askUser, actions, loading } = useChatData();
  const [input, setInput] = useState('');
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const processedMetaRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (!messages || messages.length === 0) return;
    for (const msg of messages) {
      if (processedMetaRef.current.has(msg.id)) continue;
      const meta = msg.metadata as any;
      if (!meta) continue;
      if (meta.map_update) {
        onMapUpdate(meta.map_update);
        processedMetaRef.current.add(msg.id);
      }
      if (meta.data_update) {
        onDataUpdate(meta.data_update.csv || meta.data_update.file);
        processedMetaRef.current.add(msg.id);
      }
    }
  }, [messages, onMapUpdate, onDataUpdate]);

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

  const flatMessages = flattenMessages(messages || []);

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <svg className="chat-header-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
        <span>对话</span>
      </div>

      <div className="chat-messages">
        {flatMessages.map((msg) => {
          const isUser = msg.type?.includes('user');
          return (
            <div key={msg.id} className={`chat-message ${isUser ? 'user' : 'assistant'}`}>
              {!isUser && <div className="assistant-avatar">AI</div>}
              <div className="message-content">
                {isUser ? (
                  <span>{msg.output}</span>
                ) : (
                  <ReactMarkdown>{msg.output || ''}</ReactMarkdown>
                )}
                {msg.elements?.map((el: any) => (
                  <span key={el.id} className="file-chip" title={el.name}>
                    {getFileIcon(el.name)} {el.name}
                  </span>
                ))}
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

        {actions.length > 0 && !askUser && (
          <div className="action-buttons" style={{ padding: '0 4px' }}>
            {actions.map((action) => (
              <button key={action.id} className="action-btn" onClick={() => action.onClick()}>
                {action.label || action.name}
              </button>
            ))}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-area">
        {pendingFiles.length > 0 && (
          <div className="pending-files">
            {pendingFiles.map((pf, idx) => (
              <span key={idx} className={`file-chip ${pf.error ? 'file-error' : ''}`}>
                {pf.error ? '\u274C' : pf.progress < 100 ? `${Math.round(pf.progress)}%` : '\u2705'}{' '}
                {pf.file.name}
                <button className="file-chip-remove" onClick={() => removePendingFile(pf.file)}>\u00D7</button>
              </span>
            ))}
          </div>
        )}
        <div className="chat-input-container">
          <input
            ref={fileInputRef}
            type="file"
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
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
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
