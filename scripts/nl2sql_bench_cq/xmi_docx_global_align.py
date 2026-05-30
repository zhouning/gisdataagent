"""Global cross-check: XMI classes ↔ docx field tables.

For each XMI class, try to match a docx field table by:
1. class_name == docx table_name_cn (or "{class_name}属性结构" pattern)
2. fuzzy match on stripped/normalised names

Outputs:
- compiled/cross_check/xmi_docx_alignment.yaml  (machine)
- compiled/cross_check/alignment_report.md      (human)
"""
import json
import re
import yaml
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"D:\adk")
COMP_XMI  = ROOT / "data_agent" / "standards" / "compiled"
COMP_DOCX = ROOT / "data_agent" / "standards" / "compiled_docx"
OUT_DIR   = ROOT / "data_agent" / "standards" / "compiled" / "cross_check"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------- Load XMI ----------
xmi_classes = []  # list of {module, class_name, attr_names: set, attrs: list}
for jp in (COMP_XMI / "xmi_normalized").glob("*.json"):
    doc = json.loads(jp.read_text(encoding="utf-8"))
    module = doc.get("module_name") or doc.get("module_id")
    for c in doc.get("classes", []):
        attrs = [a.get("attribute_name", "") for a in c.get("attributes", [])]
        attrs = [a for a in attrs if a]
        xmi_classes.append({
            "module": module,
            "class_name": c.get("class_name", ""),
            "attr_names": set(attrs),
            "attr_count": len(attrs),
        })

# ---------- Load docx field tables ----------
docx_tables = []  # list of {module, table_name_cn, table_code, field_codes: set, field_cns: set, source_file}
for yp in COMP_DOCX.glob("*.yaml"):
    if yp.name.startswith("_"):
        continue
    doc = yaml.safe_load(yp.read_text(encoding="utf-8"))
    module = doc.get("module")
    for ft in doc.get("field_tables", []):
        codes = {(f["code"] or "").upper() for f in ft["fields"] if f.get("code")}
        cns = {f["name_cn"] for f in ft["fields"] if f.get("name_cn")}
        docx_tables.append({
            "module": module,
            "table_name_cn": ft.get("table_name_cn", ""),
            "table_code": (ft.get("table_code") or "").upper(),
            "section_path": ft.get("section_path", []),
            "field_codes": codes,
            "field_cns": cns,
            "field_count": len(ft["fields"]),
            "caption_raw": ft.get("caption_raw", ""),
        })

# ---------- Build name lookup ----------
def normalize_name(s: str) -> str:
    s = re.sub(r"[\s（()【】\[\]：:、，,。.属性结构描述表属性结构表]", "", s)
    return s.strip().lower()

docx_by_norm_name = defaultdict(list)
for t in docx_tables:
    if t["table_name_cn"]:
        # Try both with and without "属性结构" suffix variants
        for nm in {t["table_name_cn"],
                   re.sub(r"属性结构描述表$", "", t["table_name_cn"]),
                   re.sub(r"属性结构$", "", t["table_name_cn"])}:
            if nm:
                docx_by_norm_name[normalize_name(nm)].append(t)

# ---------- Match ----------
def find_match(xmi_class_name: str, xmi_module: str) -> list[dict]:
    candidates = []
    norm = normalize_name(xmi_class_name)
    # Exact normalised
    if norm in docx_by_norm_name:
        candidates.extend(docx_by_norm_name[norm])
    # Contains either way
    if not candidates:
        for k, lst in docx_by_norm_name.items():
            if norm and (norm in k or k in norm):
                candidates.extend(lst)
    # Prefer same module if multiple
    if len(candidates) > 1:
        same_mod = [c for c in candidates if c["module"].endswith(xmi_module) or xmi_module in c["module"]]
        if same_mod:
            return same_mod
    return candidates

alignments = []
for x in xmi_classes:
    matches = find_match(x["class_name"], x["module"])
    if not matches:
        alignments.append({"xmi": x, "docx_match": None})
        continue
    # Pick best by attr-name overlap with docx field_cns
    best = max(matches, key=lambda m: len(x["attr_names"] & m["field_cns"]))
    alignments.append({"xmi": x, "docx_match": best})

# ---------- Stats ----------
total = len(alignments)
matched = sum(1 for a in alignments if a["docx_match"])
not_matched = total - matched

# Per-alignment field-level diff
detail_rows = []
for a in alignments:
    x = a["xmi"]
    d = a["docx_match"]
    if not d:
        detail_rows.append({
            "module": x["module"],
            "xmi_class": x["class_name"],
            "xmi_attr_count": x["attr_count"],
            "docx_table": None,
            "docx_field_count": 0,
            "common": 0,
            "xmi_only": list(x["attr_names"]),
            "docx_only": [],
            "status": "NO_DOCX_MATCH",
        })
        continue
    common = x["attr_names"] & d["field_cns"]
    xmi_only = x["attr_names"] - d["field_cns"]
    docx_only = d["field_cns"] - x["attr_names"]
    detail_rows.append({
        "module": x["module"],
        "xmi_class": x["class_name"],
        "xmi_attr_count": x["attr_count"],
        "docx_table": d["table_name_cn"] or d["caption_raw"][:50],
        "docx_table_code": d["table_code"],
        "docx_field_count": d["field_count"],
        "common": len(common),
        "xmi_only_count": len(xmi_only),
        "docx_only_count": len(docx_only),
        "xmi_only": sorted(xmi_only),
        "docx_only": sorted(docx_only),
        "status": "EXACT" if not xmi_only and not docx_only else ("XMI_SUBSET" if not xmi_only else "DIFF"),
    })

# Aggregate
xmi_subset_count = sum(1 for r in detail_rows if r["status"] == "XMI_SUBSET")
exact_count = sum(1 for r in detail_rows if r["status"] == "EXACT")
diff_count = sum(1 for r in detail_rows if r["status"] == "DIFF")
nomatch_count = sum(1 for r in detail_rows if r["status"] == "NO_DOCX_MATCH")

# Sum of "docx only" — fields docx has but XMI doesn't
total_docx_only_fields = sum(r.get("docx_only_count", 0) for r in detail_rows if r.get("docx_only_count"))
total_xmi_only_fields = sum(r.get("xmi_only_count", 0) for r in detail_rows if r.get("xmi_only_count"))

# ---------- Output YAML ----------
out_yaml = {
    "stats": {
        "xmi_classes_total": total,
        "matched_to_docx_table": matched,
        "not_matched": not_matched,
        "match_rate": round(matched / total * 100, 1),
        "exact_attr_match": exact_count,
        "xmi_is_subset_of_docx": xmi_subset_count,
        "diff_both_sides": diff_count,
        "xmi_attrs_missing_from_docx_total": total_xmi_only_fields,
        "docx_fields_missing_from_xmi_total": total_docx_only_fields,
    },
    "alignments": detail_rows,
}
(OUT_DIR / "xmi_docx_alignment.yaml").write_text(
    yaml.safe_dump(out_yaml, allow_unicode=True, sort_keys=False), encoding="utf-8"
)

# ---------- Output Markdown report ----------
md = []
md.append("# XMI ↔ docx 全局一致性报告\n")
md.append(f"生成自 `data_agent/standards/compiled/` 与 `compiled_docx/`。\n")
md.append("## 总体指标\n")
md.append(f"- XMI 类总数：**{total}**")
md.append(f"- 匹配到 docx 字段表：**{matched}** ({out_yaml['stats']['match_rate']}%)")
md.append(f"- 未匹配：**{not_matched}**")
md.append(f"- 完全一致 (EXACT)：**{exact_count}**")
md.append(f"- XMI 是 docx 子集 (XMI_SUBSET)：**{xmi_subset_count}**")
md.append(f"- 双向有差异 (DIFF)：**{diff_count}**")
md.append(f"- XMI 属性在 docx 找不到 (累计)：**{total_xmi_only_fields}**")
md.append(f"- docx 字段在 XMI 找不到 (累计)：**{total_docx_only_fields}**")
md.append("")
md.append("## 差异最大的 20 个匹配对\n")
diff_rows = [r for r in detail_rows if r["status"] in ("DIFF", "XMI_SUBSET")]
diff_rows.sort(key=lambda r: r.get("docx_only_count", 0) + r.get("xmi_only_count", 0), reverse=True)
md.append("| 模块 | XMI 类 | docx 表 | XMI 属性数 | docx 字段数 | 共有 | XMI 缺 (docx 有 XMI 无) | XMI 多 (XMI 有 docx 无) |")
md.append("|---|---|---|---|---|---|---|---|")
for r in diff_rows[:20]:
    md.append(f"| {r['module']} | {r['xmi_class']} | {r['docx_table']} | {r['xmi_attr_count']} | {r['docx_field_count']} | {r['common']} | {r['docx_only_count']} | {r['xmi_only_count']} |")
md.append("")
md.append("## 未匹配的 XMI 类（前 30 个）\n")
no_match = [r for r in detail_rows if r["status"] == "NO_DOCX_MATCH"]
md.append(f"共 {len(no_match)} 个。前 30 个：\n")
md.append("| 模块 | 类名 | 属性数 |")
md.append("|---|---|---|")
for r in no_match[:30]:
    md.append(f"| {r['module']} | {r['xmi_class']} | {r['xmi_attr_count']} |")

(OUT_DIR / "alignment_report.md").write_text("\n".join(md), encoding="utf-8")

print(f"XMI classes:                       {total}")
print(f"  matched to docx table:           {matched} ({out_yaml['stats']['match_rate']}%)")
print(f"  no match:                        {not_matched}")
print(f"  EXACT (attr names identical):    {exact_count}")
print(f"  XMI_SUBSET (XMI ⊂ docx):         {xmi_subset_count}")
print(f"  DIFF (both sides have unique):   {diff_count}")
print(f"XMI attrs missing from docx total: {total_xmi_only_fields}")
print(f"docx fields missing from XMI total:{total_docx_only_fields}")
print()
print(f"Wrote:")
print(f"  {OUT_DIR / 'xmi_docx_alignment.yaml'}")
print(f"  {OUT_DIR / 'alignment_report.md'}")
