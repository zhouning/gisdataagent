import React, { useEffect, useRef, useState } from "react";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import Link from "@tiptap/extension-link";
import Table from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableHeader from "@tiptap/extension-table-header";
import TableCell from "@tiptap/extension-table-cell";
import { Citation } from "./citationMark";
import CitationPanel from "./CitationPanel";
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

/** Extract any <table> elements from the HTML, return:
 *  - htmlWithoutTables: the HTML with all <table>...</table> removed
 *  - tableMd: each table converted to clean GFM markdown, joined with \n\n
 */
function extractTablesAsMarkdown(html: string): {
  htmlWithoutTables: string;
  tableMd: string;
} {
  if (typeof DOMParser === "undefined") {
    return { htmlWithoutTables: html, tableMd: "" };
  }
  const doc = new DOMParser().parseFromString(html, "text/html");
  const tables = Array.from(doc.querySelectorAll("table"));
  if (tables.length === 0) {
    return { htmlWithoutTables: html, tableMd: "" };
  }
  const tableMds: string[] = [];
  for (const table of tables) {
    const rows = Array.from(table.querySelectorAll("tr"));
    if (rows.length === 0) continue;
    const cellRows = rows.map((tr) =>
      Array.from(tr.querySelectorAll("th, td")).map((cell) =>
        // collapse internal whitespace, trim
        (cell.textContent || "").replace(/\s+/g, " ").trim(),
      ),
    );
    if (cellRows[0].length === 0) continue;
    const ncols = cellRows[0].length;
    const lines: string[] = [];
    lines.push("| " + cellRows[0].join(" | ") + " |");
    lines.push("|" + " --- |".repeat(ncols));
    for (let i = 1; i < cellRows.length; i++) {
      // pad row to ncols columns
      const row = [...cellRows[i]];
      while (row.length < ncols) row.push("");
      lines.push("| " + row.slice(0, ncols).join(" | ") + " |");
    }
    tableMds.push(lines.join("\n"));
    // remove this table from the DOM
    table.remove();
  }
  return {
    htmlWithoutTables: doc.body.innerHTML,
    tableMd: tableMds.join("\n\n"),
  };
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
  const [citationOpen, setCitationOpen] = useState(false);
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
        Citation,
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
      const rawHtml = marked.parse(combined) as string;
      // Enhance bare [[ref:UUID]] text into chip spans so the Citation mark renders it
      const html = rawHtml.replace(
        /\[\[ref:([0-9a-fA-F-]+)\]\]/g,
        (_m, id) => `<span data-citation="${id}" class="citation-chip">[[ref:${id}]]</span>`
      );
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
    const fullHtml = editor.getHTML();
    const { htmlWithoutTables, tableMd } = extractTablesAsMarkdown(fullHtml);
    const proseMd = turndown.turndown(htmlWithoutTables);
    const md = tableMd ? `${proseMd.trimEnd()}\n\n${tableMd}\n` : proseMd;
    const r = await saveClause(clause.id, state.checksum, md, fullHtml);
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
    <div style={{ display: "flex", flexDirection: "column", height: "100%", position: "relative" }}>
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
          .std-clause-editor .citation-chip {
            display: inline-block;
            padding: 0 4px;
            margin: 0 2px;
            background: #eef6ff;
            border: 1px solid #99c2ee;
            border-radius: 3px;
            font-family: ui-monospace, monospace;
            font-size: 12px;
            color: #0a4;
            white-space: nowrap;
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
        <button
          onClick={() => editor?.chain().focus().addRowAfter().run()}
          disabled={state.kind !== "editing" || !editor?.can().addRowAfter()}
          title="在当前行下方插入新行（光标需在表格内）"
        >
          + 行
        </button>
        <button
          onClick={() => editor?.chain().focus().deleteRow().run()}
          disabled={state.kind !== "editing" || !editor?.can().deleteRow()}
          title="删除当前行（光标需在表格内）"
        >
          − 行
        </button>
        <button
          onClick={() => setCitationOpen(true)}
          disabled={state.kind !== "editing"}
          title="查找并插入引用 (Ctrl+Shift+R)"
        >
          查找引用
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
      {citationOpen && clause && (
        <CitationPanel
          clauseId={clause.id}
          onClose={() => setCitationOpen(false)}
          onInsert={(refId) => {
            editor?.chain().focus().insertContent(
              `<span data-citation="${refId}" class="citation-chip">[[ref:${refId}]]</span>`
            ).run();
            setCitationOpen(false);
          }}
        />
      )}
    </div>
  );
}
