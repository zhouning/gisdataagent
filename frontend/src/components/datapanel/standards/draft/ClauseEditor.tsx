import React, { useEffect, useRef, useState } from "react";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import Link from "@tiptap/extension-link";
import Table from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableHeader from "@tiptap/extension-table-header";
import TableCell from "@tiptap/extension-table-cell";
import { marked } from "marked";
import TurndownService from "turndown";
// @ts-expect-error - turndown-plugin-gfm has no types
import { tables, strikethrough } from "turndown-plugin-gfm";
import {
  acquireLock, heartbeat, releaseLock, saveClause, breakLock,
  getClauseElements,
  StdClause, StdDataElement, ConflictDetail,
} from "../standardsApi";

interface Props {
  clause: StdClause | null;
  isAdmin: boolean;
  onLockChange: (expiresAt: string | null) => void;
  onSaved: (when: string) => void;
}

type EditorState =
  | { kind: "idle" }
  | { kind: "acquiring" }
  | { kind: "editing"; checksum: string; lockExpiresAt: string }
  | { kind: "lockedByOther"; holder: string | null; expiresAt: string | null }
  | { kind: "lost" }
  | { kind: "conflict"; server: ConflictDetail };

const turndown = new TurndownService();
turndown.use([tables, strikethrough]);

/** Keep ONLY the standard metadata header lines (模块:/章节:/表代码:/字段数:/
 *  页码:/表头:/行数:) — strip everything else. The data_element table is
 *  always reconstructed from the API on load, so any leftover table or
 *  scattered cell text in body_md is purely noise. */
function stripExistingTable(md: string): string {
  if (!md) return "";
  const headerKeys = /^(模块|章节|表代码|字段数|页码|表头|行数)\s*[:：]/;
  const lines = md.split("\n");
  const out: string[] = [];
  for (const line of lines) {
    const t = line.trim();
    if (t === "" || headerKeys.test(t)) {
      out.push(line);
    }
    // else: discard (table debris, cell-per-line debris, stray prose)
  }
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trimEnd();
}

function elementsToMarkdownTable(elements: StdDataElement[]): string {
  if (elements.length === 0) return "";
  const rows = elements.map((e, i) =>
    `| ${i + 1} | ${e.code} | ${e.name_zh ?? ""} | ${e.datatype ?? ""} | ${e.obligation ?? "optional"} |`
  );
  return [
    "",
    "| 序号 | 字段代码 | 字段名称 | 类型 | 必选 |",
    "|------|----------|----------|------|------|",
    ...rows,
    "",
  ].join("\n");
}

export default function ClauseEditor({
  clause,
  isAdmin,
  onLockChange,
  onSaved,
}: Props) {
  const [state, setState] = useState<EditorState>({ kind: "idle" });
  const heartbeatRef = useRef<number | null>(null);

  const editor = useEditor(
    {
      extensions: [
        StarterKit,
        Placeholder.configure({ placeholder: "开始编写条款内容…" }),
        Link,
        Table.configure({ resizable: false }),
        TableRow,
        TableHeader,
        TableCell,
      ],
      editable: false,
      content: "",
    },
    [clause?.id],
  );

  // Keep editable in sync with state
  useEffect(() => {
    editor?.setEditable(state.kind === "editing");
  }, [editor, state.kind]);

  // Acquire lock when clause changes
  useEffect(() => {
    if (!clause || !editor) {
      setState({ kind: "idle" });
      return;
    }

    let cancelled = false;

    setState({ kind: "acquiring" });

    acquireLock(clause.id).then(async (r) => {
      if (cancelled) return;

      if ("status" in r && r.status === 423) {
        setState({
          kind: "lockedByOther",
          holder: r.body.holder,
          expiresAt: r.body.expires_at,
        });
        onLockChange(null);
        return;
      }

      // r is AcquireLockResponse here
      const ok = r as Exclude<typeof r, { status: 423; body: unknown }>;
      const elementsResp = await getClauseElements(clause.id);
      if (cancelled) return;
      const cleanedBody = stripExistingTable(ok.body_md);
      const tableMd = elementsToMarkdownTable(elementsResp.data_elements);
      const combined = cleanedBody + (tableMd ? "\n\n" + tableMd : "");
      const html = marked.parse(combined) as string;
      editor.commands.setContent(html, false);
      setState({
        kind: "editing",
        checksum: ok.checksum,
        lockExpiresAt: ok.lock_expires_at,
      });
      onLockChange(ok.lock_expires_at);

      heartbeatRef.current = window.setInterval(async () => {
        const h = await heartbeat(clause.id);
        if ("status" in h && h.status === 410) {
          if (heartbeatRef.current !== null) clearInterval(heartbeatRef.current);
          setState({ kind: "lost" });
          onLockChange(null);
        } else if ("lock_expires_at" in h) {
          onLockChange(h.lock_expires_at);
        }
      }, 30_000);
    });

    return () => {
      cancelled = true;
      if (heartbeatRef.current !== null) {
        clearInterval(heartbeatRef.current);
        heartbeatRef.current = null;
      }
      // Best-effort fire-and-forget
      releaseLock(clause.id);
      onLockChange(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clause?.id, editor]);

  const onSave = async () => {
    if (!clause || !editor || state.kind !== "editing") return;
    const html = editor.getHTML();
    const md = turndown.turndown(html);
    const r = await saveClause(clause.id, state.checksum, md, html);
    if ("status" in r && r.status === 409) {
      setState({ kind: "conflict", server: r.body });
    } else if ("status" in r && r.status === 410) {
      if (heartbeatRef.current !== null) {
        clearInterval(heartbeatRef.current);
        heartbeatRef.current = null;
      }
      setState({ kind: "lost" });
      onLockChange(null);
    } else if ("checksum" in r) {
      // Preserve lockExpiresAt — server doesn't update it on save
      const prevLockExpiresAt = state.lockExpiresAt;
      setState({
        kind: "editing",
        checksum: r.checksum,
        lockExpiresAt: prevLockExpiresAt,
      });
      onSaved(r.updated_at);
    }
  };

  const onForceBreak = async () => {
    if (!clause) return;
    await breakLock(clause.id);
    // Re-acquire after a short tick
    setState({ kind: "idle" });
    setTimeout(() => setState({ kind: "acquiring" }), 100);
  };

  if (!clause) {
    return (
      <div style={{ padding: 24, color: "#888" }}>
        请从左侧选择条款开始编辑
      </div>
    );
  }

  const statusBarBg =
    state.kind === "editing"
      ? "#e6f7ee"
      : state.kind === "lockedByOther"
        ? "#fff3cd"
        : state.kind === "lost"
          ? "#fde2e2"
          : "#f4f4f4";

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Status bar */}
      <div
        style={{
          padding: 8,
          background: statusBarBg,
          fontSize: 13,
          borderBottom: "1px solid #ddd",
        }}
      >
        {state.kind === "acquiring" && "🔄 正在获取锁…"}
        {state.kind === "editing" &&
          `🟢 已加锁，${new Date(state.lockExpiresAt).toLocaleTimeString()} 后过期`}
        {state.kind === "lockedByOther" && (
          <span>
            🟡 被 <b>{state.holder ?? "其他用户"}</b> 锁定中
            {isAdmin && (
              <button
                onClick={onForceBreak}
                style={{ marginLeft: 8 }}
              >
                强制破锁
              </button>
            )}
          </span>
        )}
        {state.kind === "lost" && "🔴 锁丢失，重新选择条款以继续"}
        {state.kind === "conflict" &&
          "⚠️ 服务端版本已变化，下方按钮重置后再编辑"}
        {state.kind === "idle" && ""}
      </div>

      {/* Editor area */}
      <div
        className="std-clause-editor"
        style={{
          flex: 1,
          overflow: "auto",
          padding: 12,
          background: "#fff",
          color: "#222",
        }}
      >
        <style>{`
          .std-clause-editor .ProseMirror {
            min-height: 100%;
            outline: none;
            color: #222;
            line-height: 1.6;
          }
          .std-clause-editor .ProseMirror p { margin: 0 0 8px; }
          .std-clause-editor .ProseMirror h1,
          .std-clause-editor .ProseMirror h2,
          .std-clause-editor .ProseMirror h3 {
            color: #111; margin: 12px 0 6px;
          }
          .std-clause-editor .ProseMirror code {
            background: #f4f4f4; padding: 1px 4px; border-radius: 3px;
            font-family: ui-monospace, monospace;
          }
          .std-clause-editor .ProseMirror pre {
            background: #f6f8fa; padding: 8px; border-radius: 4px;
            overflow-x: auto;
          }
          .std-clause-editor .ProseMirror a { color: #0969da; }
          .std-clause-editor .ProseMirror table {
            border-collapse: collapse; width: 100%; margin: 8px 0;
          }
          .std-clause-editor .ProseMirror th,
          .std-clause-editor .ProseMirror td {
            border: 1px solid #ccc; padding: 4px 8px; text-align: left;
          }
          .std-clause-editor .ProseMirror th { background: #f0f0f0; font-weight: 600; }
          .std-clause-editor .ProseMirror p.is-editor-empty:first-child::before {
            content: attr(data-placeholder);
            color: #aaa;
            float: left;
            height: 0;
            pointer-events: none;
          }
        `}</style>
        <EditorContent editor={editor} />
      </div>

      {/* Toolbar */}
      <div
        style={{
          padding: 8,
          borderTop: "1px solid #ddd",
          display: "flex",
          gap: 8,
          alignItems: "center",
        }}
      >
        <button onClick={onSave} disabled={state.kind !== "editing"}>
          保存
        </button>
        {state.kind === "conflict" && (
          <>
            <span style={{ color: "#a60", fontSize: 12 }}>
              服务端版本：{state.server.server_body_md.slice(0, 60)}…
            </span>
            <button onClick={() => setState({ kind: "idle" })}>关闭</button>
          </>
        )}
      </div>
    </div>
  );
}
