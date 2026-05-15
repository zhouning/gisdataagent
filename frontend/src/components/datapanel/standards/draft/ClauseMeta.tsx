import React from "react";
import { StdClause } from "../standardsApi";

interface Props {
  clause: StdClause | null;
  lockExpiresAt?: string | null;
  lastSavedAt?: string | null;
}

export default function ClauseMeta({clause, lockExpiresAt, lastSavedAt}: Props) {
  if (!clause) {
    return <div style={{padding: 12, color: "#888"}}>请选择左侧条款</div>;
  }
  return (
    <div style={{padding: 12, fontSize: 13, lineHeight: 1.6}}>
      <h4 style={{marginTop: 0}}>条款元信息</h4>
      <div><b>编号:</b> {clause.clause_no || "-"}</div>
      <div><b>标题:</b> {clause.heading || "-"}</div>
      <div><b>类型:</b> {clause.kind}</div>
      <div><b>路径:</b> <code>{clause.ordinal_path}</code></div>
      <hr style={{margin: "12px 0", border: 0, borderTop: "1px solid #eee"}}/>
      {lockExpiresAt && (
        <div><b>锁过期:</b> {new Date(lockExpiresAt).toLocaleTimeString()}</div>
      )}
      {lastSavedAt && (
        <div><b>上次保存:</b> {new Date(lastSavedAt).toLocaleString()}</div>
      )}
    </div>
  );
}
