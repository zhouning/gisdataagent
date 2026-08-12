#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const sharp = require("/private/tmp/gda_word_report/node_modules/sharp");
const {
  Document,
  Packer,
  Paragraph,
  TextRun,
  Table,
  TableRow,
  TableCell,
  ImageRun,
  Header,
  Footer,
  AlignmentType,
  PageOrientation,
  LevelFormat,
  HeadingLevel,
  BorderStyle,
  WidthType,
  ShadingType,
  VerticalAlign,
  PageNumber,
  PageBreak,
  TableOfContents,
} = require("/private/tmp/gda_word_report/node_modules/docx");

const REPO = "/Users/zhouning/gisdataagent";
const REPORT_DIR = path.join(REPO, "docs", "reports");
const ASSET_DIR = path.join(REPORT_DIR, "nl2sql_schema_only_word_assets_2026-08-12");
const OUTPUT = path.join(REPORT_DIR, "nl2sql_seven_model_complete_test_report_2026-08-12.docx");

fs.mkdirSync(ASSET_DIR, { recursive: true });

const schemaFiles = {
  qwen27b: "schema_only_technical_postgis_qwen27b_20260812_final.json",
  gemma4_26b: "schema_only_technical_postgis_gemma4_26b_20260812_final.json",
  deepseek_v4_flash: "schema_only_technical_postgis_deepseek_v4_flash_20260812_final.json",
  qwen38max_online: "schema_only_technical_postgis_qwen38max_online_20260812_final.json",
  gemini36_flash_online: "schema_only_technical_postgis_gemini36_flash_online_20260812.json",
  gemma4_31b: "schema_only_technical_postgis_gemma4_31b_20260812.json",
  qwen36_35b: "schema_only_technical_postgis_qwen36_35b_20260812.json",
};
const productFiles = {
  qwen27b: "business_qwen27b_final_20260811.json",
  gemma4_26b: "business_gemma4_26b_final_20260811.json",
  deepseek_v4_flash: "business_deepseek_v4_flash_final_20260811.json",
  qwen38max_online: "business_qwen38max_online_final_20260811.json",
  gemini36_flash_online: "business_gemini36_flash_online_final_20260811.json",
  gemma4_31b: "business_gemma4_31b_final_20260811.json",
  qwen36_35b: "business_qwen36_35b_final_20260812.json",
};
const technicalProductFiles = {
  qwen27b: "technical_qwen27b_final_20260811.json",
  gemma4_26b: "technical_gemma4_26b_final_20260811.json",
  deepseek_v4_flash: "technical_deepseek_v4_flash_final_20260811.json",
  qwen38max_online: "technical_qwen38max_online_final_20260811.json",
  gemini36_flash_online: "technical_gemini36_flash_online_final_20260811.json",
  gemma4_31b: "technical_gemma4_31b_final_20260811.json",
  qwen36_35b: "technical_qwen36_35b_final_20260812.json",
};

const modelOrder = [
  "gemini36_flash_online",
  "gemma4_31b",
  "deepseek_v4_flash",
  "gemma4_26b",
  "qwen38max_online",
  "qwen36_35b",
  "qwen27b",
];
const modelLabel = {
  qwen27b: "本地 Qwen3.6 27B",
  gemma4_26b: "本地 Gemma4 26B",
  deepseek_v4_flash: "在线 DeepSeek v4 Flash",
  qwen38max_online: "在线 Qwen 3.8 Max",
  gemini36_flash_online: "在线 Gemini 3.6 Flash",
  gemma4_31b: "本地 Gemma4 31B",
  qwen36_35b: "本地 Qwen3.6 35B",
};
const shortLabel = {
  qwen27b: "Qwen 27B",
  gemma4_26b: "Gemma 26B",
  deepseek_v4_flash: "DeepSeek",
  qwen38max_online: "Qwen 3.8",
  gemini36_flash_online: "Gemini",
  gemma4_31b: "Gemma 31B",
  qwen36_35b: "Qwen 35B",
};

function readJson(fileName) {
  // A few legacy Python result files contain non-standard JSON NaN values.
  // They represent missing evidence and must not affect report metrics.
  const raw = fs.readFileSync(path.join(REPO, "data_agent", "cq_nl2sql_lake", "results", fileName), "utf8");
  return JSON.parse(raw.replace(/\b(?:NaN|Infinity|-Infinity)\b/g, "null"));
}
const schema = Object.fromEntries(Object.entries(schemaFiles).map(([k, f]) => [k, readJson(f)]));
const productBusiness = Object.fromEntries(Object.entries(productFiles).map(([k, f]) => [k, readJson(f)]));
const productTechnical = Object.fromEntries(Object.entries(technicalProductFiles).map(([k, f]) => [k, readJson(f)]));

function pct(v) { return `${(Number(v) * 100).toFixed(1)}%`; }
function nPct(n, total = 125) { return `${pct(n / total)} (${n}/${total})`; }
function sec(obj, engine, key) { return obj.routes[engine].summary[key]; }
function difficulty(obj, engine, name) { return sec(obj, engine, "by_difficulty")[name].accuracy; }
function avg(values) { return values.reduce((a, b) => a + b, 0) / values.length; }

function escXml(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function svgBarChart(file, title, rows, max = 1, colors = [], formatValue = (value) => `${(value * 100).toFixed(1)}%`) {
  const width = 1100;
  const rowH = 54;
  const left = 260;
  const chartW = 760;
  const height = 86 + rowH * rows.length;
  const bars = rows.map((r, i) => {
    const y = 62 + i * rowH;
    const w = Math.max(2, Math.round(chartW * r.value / max));
    const color = colors[i] || (r.kind === "online" ? "#1976A3" : "#6B7280");
    return `<text x="${left - 16}" y="${y + 24}" text-anchor="end" font-size="20" fill="#263238">${escXml(r.label)}</text>` +
      `<rect x="${left}" y="${y}" width="${w}" height="30" rx="4" fill="${color}"/>` +
      `<text x="${left + w + 12}" y="${y + 23}" font-size="20" fill="#263238">${formatValue(r.value)}</text>`;
  }).join("");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">` +
    `<rect width="100%" height="100%" fill="#FFFFFF"/>` +
    `<text x="30" y="34" font-family="Arial" font-size="24" font-weight="700" fill="#12344D">${escXml(title)}</text>` +
    `<line x1="${left}" y1="50" x2="${left + chartW}" y2="50" stroke="#CBD5E1"/>` + bars + `</svg>`;
  fs.writeFileSync(path.join(ASSET_DIR, file), svg);
}

function svgGroupedChart(file, title, labels, series, max = 1) {
  const width = 1160;
  const height = 420;
  const left = 92;
  const top = 72;
  const chartW = 1010;
  const chartH = 280;
  const groupW = chartW / labels.length;
  const barW = Math.min(34, groupW / (series.length + 2));
  const palette = ["#1976A3", "#F28E2B", "#59A14F", "#B07AA1", "#E15759", "#76B7B2", "#EDC948"];
  let body = `<text x="30" y="36" font-family="Arial" font-size="24" font-weight="700" fill="#12344D">${escXml(title)}</text>`;
  for (let tick = 0; tick <= 4; tick += 1) {
    const value = tick * max / 4;
    const y = top + chartH - (value / max) * chartH;
    body += `<line x1="${left}" y1="${y}" x2="${left + chartW}" y2="${y}" stroke="#E2E8F0"/>`;
    body += `<text x="${left - 12}" y="${y + 6}" text-anchor="end" font-size="16" fill="#64748B">${(value * 100).toFixed(0)}%</text>`;
  }
  labels.forEach((label, i) => {
    const x0 = left + i * groupW;
    body += `<text x="${x0 + groupW / 2}" y="${top + chartH + 28}" text-anchor="middle" font-size="16" fill="#334155">${escXml(label)}</text>`;
    series.forEach((s, j) => {
      const v = s.values[i];
      const h = (v / max) * chartH;
      const x = x0 + (groupW - series.length * barW) / 2 + j * barW;
      const y = top + chartH - h;
      body += `<rect x="${x}" y="${y}" width="${barW - 3}" height="${h}" fill="${palette[j]}"/>`;
    });
  });
  series.forEach((s, i) => {
    const x = left + i * 145;
    body += `<rect x="${x}" y="${height - 34}" width="18" height="18" fill="${palette[i]}"/>`;
    body += `<text x="${x + 25}" y="${height - 19}" font-size="16" fill="#334155">${escXml(s.name)}</text>`;
  });
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="100%" height="100%" fill="#FFFFFF"/>${body}</svg>`;
  fs.writeFileSync(path.join(ASSET_DIR, file), svg);
}

function svgArchitecture(file) {
  const width = 1200;
  const height = 540;
  const boxes = [
    [40, 70, 210, 94, "用户自然语言问题", "#E8F1F8"],
    [300, 70, 210, 94, "意图识别 + 语义解析", "#EAF5EA"],
    [560, 70, 240, 94, "语义层 / schema grounding", "#FFF3D9"],
    [850, 70, 280, 94, "统一模型 harness 生成 SQL", "#FDECEC"],
    [180, 300, 220, 94, "语义修复与方言适配", "#E8F1F8"],
    [490, 300, 220, 94, "AST 安全 / 字段归属 / LIMIT", "#EAF5EA"],
    [800, 300, 260, 94, "PostGIS 或 DuckDB 执行", "#FFF3D9"],
    [510, 450, 240, 58, "错误反馈受控重试", "#FDECEC"],
  ];
  let body = `<text x="40" y="36" font-family="Arial" font-size="25" font-weight="700" fill="#12344D">GIS Data Agent NL2Semantic2SQL 产品链路</text>`;
  boxes.forEach(([x, y, w, h, title, fill]) => {
    body += `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="10" fill="${fill}" stroke="#46657A" stroke-width="2"/>`;
    body += `<text x="${x + w / 2}" y="${y + 43}" text-anchor="middle" font-family="Arial" font-size="20" font-weight="700" fill="#1F2937">${escXml(title)}</text>`;
  });
  const arrows = [
    [250, 117, 300, 117], [510, 117, 560, 117], [800, 117, 850, 117],
    [990, 164, 990, 300], [850, 347, 710, 347], [490, 347, 400, 347],
    [490, 347, 400, 347], [400, 347, 400, 164], [600, 394, 600, 450],
    [750, 479, 930, 394], [600, 450, 600, 394],
  ];
  arrows.forEach(([x1, y1, x2, y2]) => {
    body += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#64748B" stroke-width="3" marker-end="url(#arrow)"/>`;
  });
  body += `<text x="1040" y="250" font-size="16" fill="#64748B">执行失败</text><text x="360" y="260" font-size="16" fill="#64748B">生成后统一治理</text>`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#64748B"/></marker></defs><rect width="100%" height="100%" fill="#FFFFFF"/>${body}</svg>`;
  fs.writeFileSync(path.join(ASSET_DIR, file), svg);
}

function buildAssets() {
  svgBarChart("schema_accuracy.svg", "Schema-only 总准确率（技术语言 / PostGIS / CQ-125）", modelOrder.map(k => ({ label: shortLabel[k], value: schema[k].summary.execution_accuracy, kind: k.includes("online") || k === "deepseek_v4_flash" ? "online" : "local" })));
  svgBarChart("schema_latency_p95.svg", "Schema-only E2E P95（秒）", modelOrder.map(k => ({ label: shortLabel[k], value: schema[k].summary.latency_ms.e2e_p95 / 1000, kind: k.includes("online") || k === "deepseek_v4_flash" ? "online" : "local" })), 16, [], value => `${value.toFixed(1)} s`);
  const difficultyNames = ["Easy", "Medium", "Hard", "Robustness"];
  const difficultyAverage = difficultyNames.map(name => avg(modelOrder.map(k => schema[k].summary.by_difficulty[name].accuracy)));
  svgGroupedChart("schema_difficulty.svg", "Schema-only 难度分布平均准确率", difficultyNames, [{ name: "七模型平均", values: difficultyAverage }]);
  const upliftRows = modelOrder.map(k => ({ label: shortLabel[k], value: productTechnical[k].routes.postgis.summary.execution_accuracy - schema[k].summary.execution_accuracy }));
  svgBarChart("technical_uplift.svg", "完整产品链路相对 schema-only 增益（技术语言 / PostGIS）", upliftRows, 0.30, upliftRows.map(() => "#2E7D32"));
  svgGroupedChart("route_comparison.svg", "七模型完整产品链路：PostGIS 与数据湖", modelOrder.map(k => shortLabel[k]), [
    { name: "业务 PostGIS", values: modelOrder.map(k => productBusiness[k].routes.postgis.summary.execution_accuracy) },
    { name: "业务 Lake", values: modelOrder.map(k => productBusiness[k].routes.lake.summary.execution_accuracy) },
    { name: "技术 PostGIS", values: modelOrder.map(k => productTechnical[k].routes.postgis.summary.execution_accuracy) },
    { name: "技术 Lake", values: modelOrder.map(k => productTechnical[k].routes.lake.summary.execution_accuracy) },
  ]);
  svgArchitecture("nl2semantic2sql_architecture.svg");
}

const border = { style: BorderStyle.SINGLE, size: 1, color: "CBD5E1" };
const borders = { top: border, bottom: border, left: border, right: border };
const widths = [9360];

function run(text, options = {}) { return new TextRun({ text: String(text), font: "Arial", size: options.size || 22, ...options }); }
function p(text = "", options = {}) { return new Paragraph({ spacing: { after: options.after || 120, line: 300 }, alignment: options.alignment, children: [run(text, options)] }); }
function richP(children, options = {}) { return new Paragraph({ spacing: { after: options.after || 120, line: 300 }, alignment: options.alignment, children }); }
function h(text, level = 1) { return new Paragraph({ heading: level === 1 ? HeadingLevel.HEADING_1 : level === 2 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_3, children: [run(text, { bold: true, color: level === 1 ? "12344D" : "1F4E79", size: level === 1 ? 30 : level === 2 ? 26 : 23 })] }); }
function caption(text) { return p(text, { size: 18, italics: true, color: "64748B", alignment: AlignmentType.CENTER, after: 180 }); }
function bullet(text, ref = "bullets") { return new Paragraph({ numbering: { reference: ref, level: 0 }, spacing: { after: 80, line: 280 }, children: [run(text, { size: 21 })] }); }
function numbered(text, ref = "numbers") { return new Paragraph({ numbering: { reference: ref, level: 0 }, spacing: { after: 80, line: 280 }, children: [run(text, { size: 21 })] }); }
function cell(text, opts = {}) {
  return new TableCell({ width: { size: opts.width || 9360, type: WidthType.DXA }, borders, shading: opts.header ? { fill: "DCEAF2", type: ShadingType.CLEAR } : undefined, verticalAlign: VerticalAlign.CENTER, children: [new Paragraph({ alignment: opts.center ? AlignmentType.CENTER : AlignmentType.LEFT, spacing: { before: 60, after: 60 }, children: [run(text, { size: opts.size || 18, bold: !!opts.header, color: opts.header ? "12344D" : "1F2937" })] })] });
}
function table(headers, rows, opts = {}) {
  const colWidths = opts.widths || headers.map(() => Math.floor(9360 / headers.length));
  const makeRow = (values, header = false) => new TableRow({ tableHeader: header, children: values.map((v, i) => cell(v, { header, center: header || !!opts.center, size: header ? 17 : (opts.size || 16), width: colWidths[i] })) });
  return new Table({ columnWidths: colWidths, width: { size: 9360, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 100, right: 100 }, rows: [makeRow(headers, true), ...rows.map(r => makeRow(r))] });
}
function image(file, width, height, alt) {
  const png = file.replace(/\.svg$/i, ".png");
  const data = fs.readFileSync(path.join(ASSET_DIR, png));
  return new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 100, after: 80 }, children: [new ImageRun({
    type: "png",
    data,
    transformation: { width, height },
    altText: { title: alt, description: alt, name: alt },
  })] });
}
function pageBreak() { return new Paragraph({ children: [new PageBreak()] }); }

function schemaRows() {
  return modelOrder.map(k => {
    const s = schema[k];
    return [modelLabel[k], pct(s.summary.by_difficulty.Easy.accuracy), pct(s.summary.by_difficulty.Medium.accuracy), pct(s.summary.by_difficulty.Hard.accuracy), pct(s.summary.by_difficulty.Robustness.accuracy), nPct(s.summary.execution_correct || s.records.filter(r => r.ex).length), pct(s.summary.sql_valid_rate), `${(s.summary.latency_ms.e2e_p50 / 1000).toFixed(3)} s`, `${(s.summary.latency_ms.e2e_p95 / 1000).toFixed(3)} s`];
  });
}
function productRows() {
  return modelOrder.map(k => {
    const b = productBusiness[k].routes;
    const t = productTechnical[k].routes;
    const overall = avg([b.postgis.summary.execution_accuracy, b.lake.summary.execution_accuracy, t.postgis.summary.execution_accuracy, t.lake.summary.execution_accuracy]);
    return [modelLabel[k], pct(b.postgis.summary.execution_accuracy), pct(b.lake.summary.execution_accuracy), pct(t.postgis.summary.execution_accuracy), pct(t.lake.summary.execution_accuracy), pct(overall)];
  });
}
function upliftRows() {
  return modelOrder.map(k => [modelLabel[k], pct(schema[k].summary.execution_accuracy), pct(productTechnical[k].routes.postgis.summary.execution_accuracy), `+${((productTechnical[k].routes.postgis.summary.execution_accuracy - schema[k].summary.execution_accuracy) * 100).toFixed(1)} pp`]);
}
function responseEvidenceRows() {
  return modelOrder.map(k => {
    const s = schema[k];
    const responseModels = [...new Set(s.records.map(r => r.llm_evidence && r.llm_evidence.response_model).filter(Boolean))].join(", ");
    return [modelLabel[k], responseModels, String(s.records.length), String(new Set(s.records.map(r => r.qid)).size), String(s.records.filter(r => r.generator_status !== "ok").length)];
  });
}

async function renderAssets() {
  buildAssets();
  const svgs = fs.readdirSync(ASSET_DIR).filter(file => file.endsWith(".svg"));
  await Promise.all(svgs.map(file => sharp(path.join(ASSET_DIR, file), { density: 180 }).png().toFile(path.join(ASSET_DIR, file.replace(/\.svg$/, ".png")))));
}

async function main() {
await renderAssets();
const children = [];
children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 1500, after: 300 }, children: [run("GIS Data Agent", { size: 32, bold: true, color: "1976A3" })] }));
children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 220 }, children: [run("NL2Semantic2SQL 七模型完整测试报告", { size: 44, bold: true, color: "12344D" })] }));
children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: [run("Schema-only 基线、产品链路、harness 实现与证据审计", { size: 25, color: "46657A" })] }));
children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 900 }, children: [run("重庆 CQ-125 技术/业务语言 × PostGIS/数据湖 · 2026-08-12", { size: 21, color: "64748B" })] }));
children.push(p("本报告用于产品评测与工程复核。七模型 schema-only 基线只衡量模型在物理 schema 条件下直接生成 SQL 的能力；完整产品链路结果用于衡量 GIS Data Agent 的语义层、NL2Semantic2SQL 和通用 harness 的综合作用。", { size: 21, alignment: AlignmentType.CENTER, after: 400 }));
children.push(new Table({ columnWidths: [3120, 3120, 3120], rows: [new TableRow({ children: [cell("报告版本", { header: true, center: true, width: 3120 }), cell("评测日期", { header: true, center: true, width: 3120 }), cell("状态", { header: true, center: true, width: 3120 })] }), new TableRow({ children: [cell("V1.0", { center: true, width: 3120 }), cell("2026-08-12", { center: true, width: 3120 }), cell("正式单轮基线", { center: true, width: 3120 })] })] }));
children.push(pageBreak());

children.push(h("目录", 1));
children.push(new TableOfContents("目录", { hyperlink: true, headingStyleRange: "1-3" }));
children.push(pageBreak());

children.push(h("1. 执行摘要", 1));
children.push(p("本轮完成了两类互补测试：第一类是严格 schema-only 基线，模型只看到通用 PostgreSQL/PostGIS SQL 规则、真实物理 schema 和一条问题；第二类是 GIS Data Agent 当前完整产品链路，启用语义层、意图识别、grounding、统一模型 harness、语义修复、AST 安全治理和执行反馈重试。两类测试使用同一套 CQ-125 题目和统一评分器，但目的不同，不能把它们当成同一种实验。"));
children.push(table(["核心指标", "结果", "解释"], [
  ["Schema-only 平均准确率", "67.8%（593/875）", "七模型 × 125题；直接裸 schema 生成"],
  ["完整链路平均准确率", "88.8%（777/875）", "七模型 × 125题；技术/业务 × PostGIS/数据湖"],
  ["完整链路相对 schema-only", "+约21.0个百分点", "说明语义层和通用 harness 仍有显著价值"],
  ["schema-only 最高模型", "Gemini 3.6 Flash：72.0%", "单轮点估计，不等于稳定排名"],
  ["产品默认路线", "PostGIS NL2Semantic2SQL", "当前四路矩阵中通常高于数据湖"],
], { widths: [2500, 2500, 4360], size: 17 }));
children.push(p("关键结论：裸模型能力不能代表产品问数能力。当前结果中，Qwen3.6 27B 的 schema-only 分数为 60.8%，但完整技术语言/PostGIS 链路为 88.0%，增益达到 27.2 个百分点；这不是题目特判，而是语义映射、空间关系 grounding、结果契约和通用安全治理共同作用的结果。"));
children.push(image("schema_accuracy.svg", 600, 260, "七模型 schema-only 准确率"));
children.push(caption("图 1  七模型 schema-only 技术语言/PostGIS 准确率"));
children.push(pageBreak());

children.push(h("2. 测试目标与范围", 1));
children.push(h("2.1 测试问题", 2));
children.push(numbered("模型在没有语义层和 harness 的情况下，能否仅依据真实物理 schema 直接生成可执行且结果正确的空间 SQL？"));
children.push(numbered("产品的语义层、数据模型映射、意图路由、空间 grounding、SQL 治理和执行反馈，能为同一模型增加多少可靠性？"));
children.push(numbered("PostGIS 与治理 GeoParquet/DuckDB 两条执行路线，在业务语言和技术语言下的差异是什么？"));
children.push(numbered("模型响应速度、有效 SQL 率、安全拒答和复杂空间题之间如何权衡？"));
children.push(h("2.2 冻结口径", 2));
children.push(table(["维度", "冻结条件"], [
  ["Benchmark", "重庆 CQ-125；125题；Easy 24、Medium 36、Hard 25、Robustness 40"],
  ["schema-only 输入", "通用 SQL 规则 + 真实物理 schema + 问题；无语义层/本体/embedding/few-shot/重写/执行反馈"],
  ["产品链路", "语义层 + 意图识别 + grounding + 模型 harness + 语义重写 + AST/安全治理 + 执行/受控重试"],
  ["语言", "技术语言 question；业务语言 question_business；两者共享题号和难度分布"],
  ["引擎", "PostGIS 默认路线；治理后的 GeoParquet 使用 DuckDB 数据湖路线"],
  ["模型顺序", "严格串行；本地模型完成后卸载 Ollama，避免资源竞争"],
  ["评分", "统一 scorer；执行题比较结果语义，Robustness 题按安全拒答/LIMIT 契约评分"],
], { widths: [2200, 7160], size: 17 }));
children.push(h("2.3 不应误读的范围", 2));
children.push(bullet("这是重庆样例数据上的产品回归基线，不是宁夏生产数据的准确率承诺。"));
children.push(bullet("这是单轮点估计；1至2题差异不能构成稳定排名或显著性结论。稳定结论至少需要每模型重复三轮，并冻结模型服务版本、提示、随机性和网络条件。"));
children.push(bullet("schema-only 与完整产品链路不是同一条件，schema-only 用于测量模型裸能力，不能替代产品验收分数。"));
children.push(pageBreak());

children.push(h("3. NL2Semantic2SQL 与 harness 实现方法", 1));
children.push(p("当前实现的核心原则是：让模型负责自然语言到候选 SQL 的生成，让 Python 产品代码负责数据语义解析、候选范围、方言、字段归属、安全、结果契约和执行反馈。这样既保留大模型的语言理解能力，又避免把数据库安全和数据治理交给模型自行决定。"));
children.push(image("nl2semantic2sql_architecture.svg", 650, 292, "NL2Semantic2SQL 产品链路架构"));
children.push(caption("图 2  NL2Semantic2SQL 与通用 harness 的执行链路"));
children.push(h("3.1 语义层与数据模型 grounding", 2));
children.push(bullet("语义源目录：通过 agent_semantic_sources 维护业务对象、显示名、别名、描述、几何类型、SRID、查询策略和数据源类型。"));
children.push(bullet("字段注册表：通过 agent_semantic_registry 维护物理字段、语义域、业务别名、单位、描述、几何标记和值语义；新客户通过数据模型/标准映射配置这些信息，而不是修改 SQL 代码。"));
children.push(bullet("解析结果：resolve_semantic_context 对问题做表级/字段级别名匹配、层级分类识别、空间操作识别、区域过滤识别和指标提示生成。"));
children.push(bullet("候选筛选：build_nl2sql_context 对候选表排序、补充 schema、限制候选数量，并在有治理 GeoParquet 时提供 projection_path、CRS、逻辑对象和 PostGIS 映射。"));
children.push(bullet("关系语义：可把本体/知识关系转成受治理的 KG join path 和关系提示，但本体不是记录库，也不直接执行 SQL。"));
children.push(h("3.2 意图识别", 2));
children.push(p("当前有可审计的规则阶段，意图包括 attribute_filter、category_filter、spatial_measurement、spatial_join、knn、aggregation、preview_listing、refusal_intent 和 unknown。规则阶段先处理高风险拒写、KNN、空间连接和聚合等模式；规则不确定时，部分模型族可使用 LLM judge，或按模型族采用规则-only 路径。意图用于决定 grounding 规则、候选数据源、LIMIT 策略和后处理，不用于硬编码某道题的答案。"));
children.push(h("3.3 统一模型 harness", 2));
children.push(p("harness 是围绕模型调用的一组模型无关工程约束，不是另一个模型。当前共享规则包括：只输出单条只读 SELECT/WITH；只能引用 grounding 中的表和字段；不得无理由加入 IS NOT NULL、DISTINCT、ORDER BY、别名、过滤条件或空间半径；空间连接要使用明确 JOIN/ON；PostGIS 和 DuckDB 使用各自方言；结果列和聚合必须服从用户问题和语义契约。"));
children.push(table(["harness 环节", "实现方法", "保护目标"], [
  ["SQL 提取", "从模型正文提取 SELECT/WITH，去除 markdown 围栏和附加说明", "避免自然语言污染执行"],
  ["占位/缺表重试", "检测 SELECT 1、未 grounding 表和缺失空间关系，使用同一配置模型重试", "降低模型漏答和越权引用"],
  ["语义 SQL 修复", "依据问题、语义契约、字段角色、空间关系和单位做通用 rewrite", "修复跨数据集的通用错误，不写 qid 特判"],
  ["AST 后处理", "sqlglot 解析；只读根节点；拒绝 INSERT/UPDATE/DELETE/DDL；修正大小写/中文字段", "防止写操作和字段拼写错误"],
  ["大表与 LIMIT", "识别 large_tables；非聚合预览自动注入 LIMIT 1000；安全预览兜底", "防止全表返回和内存风险"],
  ["运行时 guard", "按物理表和 alias 校验字段归属、可访问表和安全 SQL", "防止候选表之间字段串用"],
  ["执行反馈", "执行错误最多受控重试；重试 SQL 仍要经过 rewrite、AST 和 guard", "修复方言/字段错误但不绕过治理"],
  ["证据记录", "保存 provider、response_model、endpoint、latency、SQL、corrections、retry 和 execution", "可审计、可复现、可定位失败"],
], { widths: [1900, 4700, 2760], size: 16 }));
children.push(h("3.4 语义重写与 AST 不是作弊", 2));
children.push(p("语义重写可以修复“用户明确要求名称但模型误加名称非空”“空间距离单位转换”“CRS/geometry-geography 类型”“KNN 排序”“关联实体计数”等跨数据集问题。它的输入是用户问题、运行时语义配置和真实 schema，规则描述的是通用语义，而不是某个题号的固定答案。AST 后处理只做安全和物理字段治理，不知道 golden SQL，也不读取答案。"));
children.push(pageBreak());

children.push(h("4. Schema-only 七模型基线结果", 1));
children.push(p("本节采用正式 schema-only 文件。每个模型 125 条记录、125 个唯一 qid、generator_status 非 ok 为 0，且服务端 response_model 与请求模型一致。模型只能依据物理 schema 推断表、字段和 PostGIS 函数，因此该结果主要反映模型裸 SQL 能力和空间 SQL 常识。"));
children.push(image("schema_accuracy.svg", 600, 260, "Schema-only 准确率"));
children.push(caption("图 3  Schema-only 总准确率；在线模型用蓝色，本地模型用灰色"));
children.push(table(["模型", "Easy", "Medium", "Hard", "Robustness", "总准确率", "有效SQL", "P50", "P95"], schemaRows(), { widths: [1800, 720, 800, 720, 900, 1150, 900, 750, 820], size: 14 }));
children.push(caption("表 1  Schema-only 技术语言/PostGIS/CQ-125 正式结果"));
children.push(image("schema_difficulty.svg", 620, 224, "Schema-only 难度分布"));
children.push(caption("图 4  七模型 schema-only 按难度平均准确率"));
children.push(p("观察：Easy 题平均表现明显高于 Medium/Hard；复杂空间关系、聚合维度、KNN、包含方向和实体角色是裸 schema 条件下的主要难点。Robustness 分数较高并不等于查询语义正确，因为其中一部分题目只要求安全拒答或 LIMIT 约束。"));
children.push(image("schema_latency_p95.svg", 600, 260, "Schema-only P95"));
children.push(caption("图 5  Schema-only 端到端 P95 延迟；DeepSeek 尾延迟受在线网络/推理影响"));
children.push(pageBreak());

children.push(h("5. 完整产品链路结果与路线对照", 1));
children.push(p("完整链路测试开启当前产品的语义层、意图识别、grounding、模型 harness、语义重写、AST/安全治理和受控执行反馈。Benchmark few-shot、未审核 few-shot 和跨领域 few-shot 在本轮均关闭，因此结果不是把测试题答案检索给模型。"));
children.push(image("route_comparison.svg", 650, 235, "PostGIS 与数据湖路线"));
children.push(caption("图 6  七模型完整产品链路的业务/技术语言与执行引擎对比"));
children.push(table(["模型", "业务 PostGIS", "业务 Lake", "技术 PostGIS", "技术 Lake", "四路平均"], productRows(), { widths: [2200, 1500, 1500, 1500, 1500, 1160], size: 16 }));
children.push(caption("表 2  完整产品链路四维矩阵；四路平均不是新的验收指标，仅用于横向概览"));
children.push(h("5.1 技术语言/PostGIS：与 schema-only 的直接对照", 2));
children.push(table(["模型", "Schema-only", "完整链路", "绝对增益"], upliftRows(), { widths: [3000, 1900, 1900, 2560], size: 17 }));
children.push(image("technical_uplift.svg", 600, 260, "产品链路增益"));
children.push(caption("图 7  完整技术语言/PostGIS 产品链路相对 schema-only 的增益"));
children.push(p("完整链路平均 88.8%，schema-only 平均 67.8%，相差约 21.0 个百分点。最大单模型增益是 Qwen3.6 27B 的 +27.2 pp，最小是 Gemma4 31B 的 +16.8 pp。这个结果支持继续投入语义层和 harness，但不能推出任意客户数据都会获得同样增益。"));
children.push(h("5.2 业务语言与技术语言", 2));
children.push(p("技术语言直接暴露物理对象或字段，主要测量 SQL 生成和空间 SQL 执行能力；业务语言使用“地类、道路、兴趣点、面积、权属”等业务表达，模型需要依赖语义层和数据模型把业务术语映射到物理字段。当前七模型完整链路中，业务语言普遍低于技术语言，说明下一步提升重点应放在术语、字段角色、指标口径和关系语义，而不是只换更大的模型。"));
children.push(table(["模型", "业务四路平均", "技术四路平均", "技术-业务差值"], modelOrder.map(k => {
  const b = avg([productBusiness[k].routes.postgis.summary.execution_accuracy, productBusiness[k].routes.lake.summary.execution_accuracy]);
  const t = avg([productTechnical[k].routes.postgis.summary.execution_accuracy, productTechnical[k].routes.lake.summary.execution_accuracy]);
  return [modelLabel[k], pct(b), pct(t), `+${((t - b) * 100).toFixed(1)} pp`];
}), { widths: [3100, 2100, 2100, 2060], size: 17 }));
children.push(h("5.3 PostGIS 与数据湖", 2));
children.push(p("PostGIS 是当前默认路线：查询对象通常已经加载到受治理的空间表，语义层维护物理字段和几何元数据，NL2Semantic2SQL 生成 PostgreSQL/PostGIS SQL 后直接执行。数据湖路线不把原始 GDB 目录交给模型，而是先将治理后的对象投影为 GeoParquet，在语义目录中维护投影路径、字段契约、几何类型和 CRS，再由 lake_sql_executor 生成/规范化 DuckDB 空间 SQL。两条路线使用独立 golden，不能用 PostGIS golden 直接评分 DuckDB。"));
children.push(bullet("PostGIS 优点：空间函数和生产查询路径成熟，当前产品准确率更高。"));
children.push(bullet("数据湖优点：适合大文件治理后直接查询，不需要把所有原始记录复制进本体库或临时重载 PostGIS。"));
children.push(bullet("数据湖缺口：DuckDB 空间方言、CRS 对齐、投影字段完整性、结果列/排序契约仍需继续加固。"));
children.push(pageBreak());

children.push(h("6. Harness 对产品可靠性的具体贡献", 1));
children.push(p("harness 的价值不只是“多写几条 prompt”。它把模型输出变成可验证、可拒绝、可修复、可追踪的生产查询。下面按用户可感知的风险解释其作用。"));
children.push(table(["风险", "没有 harness 时", "当前产品处理"], [
  ["模型输出解释文字", "SQL 解析失败或执行异常", "严格提取 SELECT/WITH，去围栏和附加说明"],
  ["引用不存在字段", "数据库报错，或错误表字段被误用", "grounding 候选范围 + AST 字段归属 + 运行时 guard"],
  ["误生成写操作", "可能改变数据", "AST 拒绝 INSERT/UPDATE/DELETE/DDL，只允许只读根节点"],
  ["大表无 LIMIT", "全表返回、内存或网络风险", "large-table LIMIT 1000 和安全预览兜底"],
  ["空间关系漏掉/方向错", "结果看似可执行但语义错误", "意图路由、空间 grounding、缺关系受控重试和通用 rewrite"],
  ["PostGIS/DuckDB 方言混用", "类型、函数或 Binder 错误", "按执行引擎选择 dialect，并做 CRS/空间 SQL 规范化"],
  ["执行失败", "一次失败即结束", "最多 MAX_RETRIES 次，错误反馈仍经过全部安全校验"],
  ["无法定位质量问题", "只能看到“模型不准”", "记录 SQL、raw SQL、corrections、retry、response_model、延迟和执行状态"],
], { widths: [1800, 3600, 3960], size: 16 }));
children.push(h("6.1 产品化底线", 2));
children.push(bullet("禁止按题号、完整问题、CQ 表名、字段值、golden SQL 或固定答案增加特判。"));
children.push(bullet("允许并且必须保留通用的语义规则、安全规则、字段契约、空间关系规则和方言适配。"));
children.push(bullet("任何新规则都必须在中性单元测试、当前 benchmark 和未参与开发的留出数据集上验证。"));
children.push(bullet("结果报告必须同时保留准确率、有效 SQL 率、拒答准确率、P50/P95、失败类型和可复现证据。"));
children.push(h("6.2 向量 embedding 的位置", 2));
children.push(p("当前本机配置的文本 embedding 是 Ollama 的 nomic-embed-text-v2-moe。它服务于语义/参考查询的向量检索能力；但本轮 schema-only 基线明确关闭 few-shot 和 embedding 检索，所以不能把 schema-only 分数的差异归因于向量模型。完整产品可以在经过审核的语义层、业务语言集和技术表达集上启用检索，但必须将检索内容限制为当前租户/数据域的已审核合同，不能把 benchmark 题答案当作生产知识。"));
children.push(pageBreak());

children.push(h("7. 结果证据与审计", 1));
children.push(h("7.1 冻结哈希", 2));
children.push(table(["证据项", "SHA-256"], [
  ["Benchmark", "e5a3e94ee1554063e525f261625c33aaeafdf131b97c7346a88483c4cec2944a"],
  ["物理 schema", "40666d01196f79d6eefbbc08c55bfc864d9700e0f9dd9b2009e4c9dfa3407883"],
  ["Schema-only system prompt", "01b3cfdd107cc1d018b80fcfceb79b3bed94e732039cc5f97a45fa11f62a9dc0"],
  ["Scorer", "81895b9f5b8a926500417ea42a01a2a3da86aabe263e9d6bfd189966d823b8e1"],
  ["Schema-only runner", "b88f99a04882a3723ef3749b299c30a16ae20565f1a89b1916274ad4a2214e08"],
], { widths: [2700, 6660], size: 15 }));
children.push(h("7.2 结果文件完整性", 2));
children.push(table(["模型", "记录数", "唯一 qid", "生成失败", "服务端 response_model"], responseEvidenceRows(), { widths: [2700, 1200, 1300, 1300, 2860], size: 15 }));
children.push(p("DeepSeek 正式轮中有一题首次出现 SSL EOF。该题没有被判作正确，随后仅按原题重试并生成成功；正式结果使用重试后的完整文件，网络失败证据另存为 schema_only_technical_postgis_deepseek_v4_flash_20260812_final_transport_failure.json，不纳入正式统计。"));
children.push(h("7.3 结果文件路径", 2));
for (const k of modelOrder) children.push(bullet(`Schema-only：data_agent/cq_nl2sql_lake/results/${schemaFiles[k]}`));
children.push(p("完整产品链路结果：data_agent/cq_nl2sql_lake/results/business_*_final_20260811.json 和 technical_*_final_20260811.json；Qwen3.6 35B 使用 20260812 文件。实现方法的核心代码位于 data_agent/nl2sql_grounding.py、data_agent/nl2sql_executor.py、data_agent/nl2sql_semantic_rewrite.py、data_agent/sql_postprocessor.py、data_agent/semantic_layer.py 和 data_agent/lake_sql_executor.py。"));
children.push(pageBreak());

children.push(h("8. 工程结论与下一步", 1));
children.push(h("8.1 当前结论", 2));
children.push(numbered("当前 PostGIS NL2Semantic2SQL 是生产默认路线。它在本轮四路产品矩阵中整体优于数据湖路线，且空间 SQL 生态和执行稳定性更成熟。", "final-numbers"));
children.push(numbered("语义层、数据模型映射和 harness 仍有显著增益，不能将当前产品简化为“把 schema 交给模型”。", "final-numbers"));
children.push(numbered("本地模型并不因参数更大而必然更准；在线模型也不必然适合内网，模型选择必须同时考虑数据出域政策、延迟、费用、稳定性和可审计性。", "final-numbers"));
children.push(numbered("本体模型在问数中承担业务概念、关系和跨对象语义的辅助 grounding；数据记录仍保存在 PostGIS 或数据湖，不能把本体实例库当成查询事实库。", "final-numbers"));
children.push(numbered("当前七模型结果是 CQ-125 的工程基线，不能直接转化为宁夏客户验收承诺。", "final-numbers"));
children.push(h("8.2 下一步优化优先级", 2));
children.push(table(["优先级", "工作项", "验收方式"], [
  ["P0", "建立四川/宁夏或其他未参与开发数据集的留出 benchmark，覆盖业务语言、技术语言、PostGIS、数据湖", "至少三轮；报告置信区间、失败族和跨数据集泛化"],
  ["P0", "补齐语义层数据模型导入、字段角色、值域、单位、空间关系和版本审批", "随机新对象配置后可问数，不修改代码"],
  ["P1", "完善 DuckDB 空间方言、CRS 对齐、GeoParquet 投影字段完整性", "独立 DuckDB golden 和大文件样例回归"],
  ["P1", "建立审核业务语言集/技术表达集的检索策略", "留出集对比检索开关，禁止 benchmark 泄漏"],
  ["P1", "完善结果列、排序、空值和实体计数契约", "逐题结果语义比较 + golden 可重复性审计"],
  ["P2", "重复七模型至少三轮并加入成本、吞吐、P95、失败重试率", "模型选择从单分数升级为质量/延迟/成本 Pareto"],
], { widths: [1100, 4800, 3460], size: 16 }));
children.push(h("8.3 最终判断", 2));
children.push(p("本轮测试已经完成了“裸模型基线”和“产品完整链路”的可审计对照。结果支持继续完善语义层和通用 harness，也支持把 PostGIS 作为默认问数路线、把数据湖 SQL 适配器作为治理数据的并行路线。下一阶段的核心不是继续在 CQ-125 上堆规则，而是以未参与开发的新数据集验证“汇聚任意数据 → 配置数据模型/语义层/本体关系 → 智能问数”的产品化泛化能力。"));
children.push(p("报告生成时间：2026-08-12。", { size: 18, color: "64748B", alignment: AlignmentType.RIGHT }));

const doc = new Document({
  creator: "GIS Data Agent",
  title: "GIS Data Agent NL2Semantic2SQL 七模型完整测试报告",
  subject: "Schema-only 基线、NL2Semantic2SQL 与 harness 评测",
  description: "重庆 CQ-125 技术/业务语言与 PostGIS/数据湖完整测试报告",
  styles: {
    default: { document: { run: { font: "Arial", size: 22, color: "1F2937" } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", run: { font: "Arial", size: 44, bold: true, color: "12344D" }, paragraph: { alignment: AlignmentType.CENTER, spacing: { after: 200 } } },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: "Arial", size: 30, bold: true, color: "12344D" }, paragraph: { spacing: { before: 280, after: 180 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: "Arial", size: 26, bold: true, color: "1F4E79" }, paragraph: { spacing: { before: 220, after: 140 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: "Arial", size: 23, bold: true, color: "2F6380" }, paragraph: { spacing: { before: 160, after: 100 }, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    ],
  },
  sections: [{
    properties: { page: { margin: { top: 1200, right: 1200, bottom: 1200, left: 1200 }, pageNumbers: { start: 1, formatType: "decimal" } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [run("GIS Data Agent  |  NL2Semantic2SQL 评测报告", { size: 16, color: "64748B" })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [run("机密评测资料  ·  第 ", { size: 16, color: "64748B" }), new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 16, color: "64748B" })] })] }) },
    children,
  }],
});

const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(OUTPUT, buffer);
  console.log(OUTPUT);
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
