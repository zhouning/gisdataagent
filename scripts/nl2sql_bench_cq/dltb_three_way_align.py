"""Three-way alignment: docx DLTB ↔ cq_dltb (actual PG) ↔ XMI 现状地类图斑."""
import json
import re
import yaml
from pathlib import Path

ROOT = Path(r"D:\adk")

# 1) docx DLTB (just extracted)
docx_yaml = ROOT / "data_agent" / "standards" / "compiled_docx" / "02_统一调查监测.yaml"
docx_doc = yaml.safe_load(docx_yaml.read_text(encoding="utf-8"))
dltb_docx = None
for ft in docx_doc["field_tables"]:
    if (ft.get("table_code") or "").upper() == "DLTB":
        dltb_docx = ft; break
docx_fields = [
    {"code": fd["code"].upper(), "cn": fd["name_cn"], "type": fd["dtype"],
     "len": fd["length"], "domain": fd["domain"], "constraint": fd["constraint"]}
    for fd in dltb_docx["fields"]
]
docx_codes = {f["code"]: f for f in docx_fields}

# 2) Real cq_dltb columns from dump
dump = (ROOT / "cq_dltb_dump.sql").read_text(encoding="utf-8")
m = re.search(r"CREATE TABLE public\.cq_dltb\s*\((.*?)\);", dump, re.S)
cols_block = m.group(1)
real_cols = []
for line in cols_block.splitlines():
    line = line.strip().rstrip(",")
    if not line or line.startswith("CONSTRAINT"):
        continue
    parts = line.split()
    if not parts: continue
    real_cols.append({"name": parts[0].lower(), "type": " ".join(parts[1:])})
real_codes = {c["name"].upper(): c for c in real_cols}

# 3) XMI 现状地类图斑
xmi_json = ROOT / "data_agent" / "standards" / "compiled" / "xmi_normalized" / "02统一调查监测__8d530b44.json"
xmi_doc = json.loads(xmi_json.read_text(encoding="utf-8"))
xmi_class = None
for c in xmi_doc["classes"]:
    if c["class_name"] == "现状地类图斑":
        xmi_class = c; break
xmi_attrs = [
    {"cn": a.get("attribute_name",""), "type": a.get("attribute_type",""),
     "lower": a.get("lower",""), "upper": a.get("upper","")}
    for a in xmi_class["attributes"]
]
xmi_cn_set = {a["cn"] for a in xmi_attrs}

# Map XMI cn ↔ docx via cn name (XMI has no code; docx has both)
docx_cn_to_code = {f["cn"]: f["code"] for f in docx_fields}
xmi_via_docx_code = {docx_cn_to_code.get(a["cn"], "?"): a for a in xmi_attrs}

# ---------------------------------------------------------------- Report
print("="*90)
print("DLTB 三方对齐报告: docx 标准 ↔ cq_dltb 实际表 ↔ XMI 现状地类图斑")
print("="*90)
print(f"docx 字段数:        {len(docx_fields)}")
print(f"cq_dltb 实际列数:    {len(real_cols)} (其中业务字段去除 objectid/shape: {len(real_cols)-2})")
print(f"XMI 属性数:          {len(xmi_attrs)}")
print()

# All codes ordered by docx sequence
print(f"{'编码':10s}  {'中文名':16s}  {'docx':5s}  {'real':5s}  {'XMI':5s}  说明")
print("-"*90)
all_codes = []
seen = set()
for f in docx_fields:
    all_codes.append(f["code"])
    seen.add(f["code"])
# Real-only codes (e.g. objectid, shape)
for c in real_codes:
    if c not in seen:
        all_codes.append(c); seen.add(c)

for code in all_codes:
    doc = docx_codes.get(code)
    real = real_codes.get(code)
    xmi_cn = doc["cn"] if doc else ""
    xmi_present = "✓" if xmi_cn in xmi_cn_set else ""
    cn = doc["cn"] if doc else "(non-std)"
    d_mark = "✓" if doc else ""
    r_mark = "✓" if real else ""
    x_mark = xmi_present if doc else ""

    flags = []
    if doc and not real: flags.append("real 缺")
    if real and not doc: flags.append("docx 缺")
    if doc and not xmi_present: flags.append("XMI 缺")
    if doc and xmi_present and not real: flags.append("仅概念层")
    # Type mismatch heuristic
    if doc and real:
        dt = (doc["type"] or "").lower()
        rt = (real["type"] or "").lower()
        if "float" in dt and "numeric" not in rt and "double" not in rt and "float" not in rt:
            flags.append(f"类型差异 {doc['type']}↔{real['type'][:20]}")
        elif "char" in dt and "char" not in rt and "varchar" not in rt and "text" not in rt:
            flags.append(f"类型差异 {doc['type']}↔{real['type'][:20]}")

    print(f"  {code:10s}  {cn[:14]:14s}  {d_mark:5s}  {r_mark:5s}  {x_mark:5s}  {'; '.join(flags)}")

print()
print("="*90)
print("汇总指标")
print("="*90)
in_docx = set(docx_codes)
in_real = set(real_codes) - {"OBJECTID", "SHAPE"}
in_xmi  = {docx_cn_to_code.get(a["cn"]) for a in xmi_attrs if a["cn"] in docx_cn_to_code}
print(f"docx ∩ real:        {len(in_docx & in_real):3d}  / docx {len(in_docx)} / real {len(in_real)}")
print(f"docx ∩ XMI:         {len(in_docx & in_xmi):3d}  / XMI {len(in_xmi)}")
print(f"real ∩ XMI:         {len(in_real & in_xmi):3d}")
print(f"三方都有:           {len(in_docx & in_real & in_xmi):3d}")
print()
print(f"real 多出 (非标准列):  {sorted(in_real - in_docx)}")
print(f"XMI 多出 (中文未映射):  {[a['cn'] for a in xmi_attrs if a['cn'] not in docx_cn_to_code]}")
print(f"docx 有但 real 缺:    {sorted(in_docx - in_real)}")
print(f"docx 有但 XMI 缺:     {sorted(in_docx - in_xmi)[:15]}{'...' if len(in_docx - in_xmi)>15 else ''}")
