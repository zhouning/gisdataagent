"""Diff docx-derived semantic config vs hand-written register_cq_semantic.py.

For cq_land_use_dltb (mapped to docx DLTB):
  - Run semantic_config_generator on DLTB
  - Load the hand-written COLUMNS["cq_land_use_dltb"] dict
  - Per column, diff: domain / aliases / unit / desc

Output:
  - Stdout: human-readable per-column diff table
  - markdown report at docs/dltb_semantic_diff.md
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "nl2sql_bench_cq"))

from data_agent.standards.semantic_config_generator import generate_semantic_config
import register_cq_semantic as rcs


def diff_field(code: str, hand: dict, derived: dict) -> dict:
    """Compare one column's hand vs derived config."""
    h_aliases = set(hand.get("aliases", []) or [])
    d_aliases = set(derived.get("aliases", []) or [])
    return {
        "code": code,
        "domain_hand":    hand.get("domain"),
        "domain_derived": derived.get("domain"),
        "domain_match":   hand.get("domain") == derived.get("domain"),
        "aliases_common":     sorted(h_aliases & d_aliases),
        "aliases_hand_only":  sorted(h_aliases - d_aliases),
        "aliases_derived_only": sorted(d_aliases - h_aliases),
        "unit_hand":     hand.get("unit", ""),
        "unit_derived":  derived.get("unit", ""),
        "unit_match":    hand.get("unit", "") == derived.get("unit", ""),
        "desc_hand":     (hand.get("desc") or "").strip(),
        "desc_derived":  (derived.get("desc") or "").strip(),
    }


def main():
    pg_table = "cq_land_use_dltb"
    hand_cols = rcs.COLUMNS[pg_table]
    real_columns = list(hand_cols.keys())  # use hand-written column set as PG truth

    gen = generate_semantic_config("02_统一调查监测.yaml", "DLTB", real_columns)

    rows = []
    only_in_hand = []
    only_in_docx = gen["docx_only"]
    pg_only      = gen["pg_only"]

    for col_name, hand_meta in hand_cols.items():
        derived_meta = gen["derived"].get(col_name)
        if derived_meta is None:
            only_in_hand.append(col_name)
        else:
            rows.append(diff_field(col_name, hand_meta, derived_meta))

    # ------------------------------------------------------------------ print
    print("="*100)
    print("DLTB semantic config diff — docx-derived vs hand-written")
    print("="*100)
    print(f"  PG columns (hand):        {len(hand_cols)}")
    print(f"  docx DLTB fields:         {gen['docx_field_count']}")
    print(f"  diffable pairs:           {len(rows)}")
    print(f"  hand-only (无 docx 来源):  {len(only_in_hand)}  → {only_in_hand}")
    print(f"  docx-only (国标缺失字段):  {len(only_in_docx)} → 治理素材")
    print()

    # Domain match
    dom_match = sum(1 for r in rows if r["domain_match"])
    print(f"domain match: {dom_match}/{len(rows)}")
    unit_match = sum(1 for r in rows if r["unit_match"])
    print(f"unit match:   {unit_match}/{len(rows)}")
    # aliases overlap
    avg_overlap = sum(len(r["aliases_common"]) for r in rows) / max(1, len(rows))
    avg_hand    = sum(len(r["aliases_hand_only"])+len(r["aliases_common"]) for r in rows) / max(1, len(rows))
    avg_derived = sum(len(r["aliases_derived_only"])+len(r["aliases_common"]) for r in rows) / max(1, len(rows))
    print(f"aliases avg: common={avg_overlap:.1f}, hand_total={avg_hand:.1f}, derived_total={avg_derived:.1f}")
    print()

    print(f"{'COL':18s}  {'domain hand':15s}  {'domain derived':15s}  {'unit h':6s}  {'unit d':6s}  共有别名  人工独有  docx独有")
    print("-"*120)
    for r in rows:
        print(f"  {r['code'][:16]:16s}  "
              f"{(r['domain_hand'] or '-'):15s}  "
              f"{(r['domain_derived'] or '-'):15s}  "
              f"{r['unit_hand'][:5]:6s}  "
              f"{r['unit_derived'][:5]:6s}  "
              f"{len(r['aliases_common']):3d}      "
              f"{len(r['aliases_hand_only']):3d}     "
              f"{len(r['aliases_derived_only']):3d}")
    print()

    # ------------------------------------------------------------------ markdown
    md = []
    md.append("# DLTB 语义层配置 diff: docx 自动派生 vs 人工手写\n")
    md.append(f"PG 表: `{pg_table}` (人工注册 {len(hand_cols)} 列)")
    md.append(f"docx 国标: DLTB ({gen['docx_field_count']} 字段)\n")
    md.append("## 总体")
    md.append(f"- domain 匹配率: **{dom_match}/{len(rows)} = {100*dom_match/max(1,len(rows)):.0f}%**")
    md.append(f"- unit 匹配率: **{unit_match}/{len(rows)} = {100*unit_match/max(1,len(rows)):.0f}%**")
    md.append(f"- aliases 平均: 共有 {avg_overlap:.1f}, 人工独有 {avg_hand-avg_overlap:.1f}, docx独有 {avg_derived-avg_overlap:.1f}")
    md.append(f"- 仅人工有 (无 docx 对应): {only_in_hand}  ← 大概率是 ArcGIS 派生列 (SHAPE_Length / SHAPE_Area / geometry) 或 PG 元数据")
    md.append(f"- 仅 docx 有 ({len(only_in_docx)} 个国标字段): 治理价值 — 实际表未实现的标准字段\n")
    md.append("## 每列详细\n")
    for r in rows:
        md.append(f"### {r['code']}")
        md.append(f"- domain: hand=`{r['domain_hand']}` ↔ derived=`{r['domain_derived']}` {'✓' if r['domain_match'] else '⚠️ 不一致'}")
        md.append(f"- unit:   hand=`{r['unit_hand']}` ↔ derived=`{r['unit_derived']}` {'✓' if r['unit_match'] else '⚠️ 不一致'}")
        md.append(f"- aliases:")
        if r["aliases_common"]:
            md.append(f"  - 共有: {r['aliases_common']}")
        if r["aliases_hand_only"]:
            md.append(f"  - **仅人工** (工程要补的): {r['aliases_hand_only']}")
        if r["aliases_derived_only"]:
            md.append(f"  - 仅 docx: {r['aliases_derived_only']}")
        md.append(f"- desc hand: {r['desc_hand']}")
        md.append(f"- desc derived: {r['desc_derived']}")
        md.append("")
    md.append("## docx 多出的国标字段 (治理素材，姿态3)\n")
    md.append("以下国标字段定义在 docx 里，但实际 PG 表没实现：")
    for c in only_in_docx:
        md.append(f"- `{c}`")

    out_md = ROOT / "docs" / "dltb_semantic_diff.md"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"Markdown report: {out_md}")


if __name__ == "__main__":
    main()
