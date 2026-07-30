#!/usr/bin/env node

import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

import { chromium } from "playwright";

const ROOT = process.cwd();
const OUTPUT_DIR = path.join(ROOT, "docs", "finals", "assets", "diagrams");

const C = {
  ink: "#17313A",
  muted: "#60727A",
  line: "#8CA0A8",
  pale: "#F4F7F8",
  blue: "#1976D2",
  blueFill: "#EAF3FC",
  teal: "#087E8B",
  tealFill: "#E7F5F5",
  green: "#2E7D32",
  greenFill: "#EDF7EE",
  amber: "#A86200",
  amberFill: "#FFF5E5",
  red: "#C33C54",
  redFill: "#FCECEF",
  violet: "#6950A1",
  violetFill: "#F2EEFA",
  white: "#FFFFFF",
};

function esc(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function textLines({ x, y, lines, size = 24, weight = 400, fill = C.ink, lineHeight = 34, anchor = "start", klass = "" }) {
  const body = lines
    .map((line, index) => `<tspan x="${x}" dy="${index === 0 ? 0 : lineHeight}">${esc(line)}</tspan>`)
    .join("");
  return `<text class="${klass}" x="${x}" y="${y}" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}">${body}</text>`;
}

function title(text, subtitle = "") {
  return [
    textLines({ x: 70, y: 70, lines: [text], size: 38, weight: 700 }),
    subtitle ? textLines({ x: 70, y: 110, lines: [subtitle], size: 20, fill: C.muted }) : "",
    `<line x1="70" y1="132" x2="1530" y2="132" stroke="#D5DEE2" stroke-width="2"/>`,
  ].join("");
}

function box({ x, y, w, h, heading, lines = [], accent = C.blue, fill = C.white, headingSize = 25, bodySize = 20, center = false, dashed = false }) {
  const tx = center ? x + w / 2 : x + 26;
  const anchor = center ? "middle" : "start";
  const lineStart = y + (lines.length ? 70 : h / 2 + 9);
  return [
    `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" fill="${fill}" stroke="${accent}" stroke-width="2.5"${dashed ? ' stroke-dasharray="10 8"' : ""}/>` ,
    `<rect x="${x}" y="${y}" width="8" height="${h}" rx="4" fill="${accent}"/>`,
    textLines({ x: tx, y: lines.length ? y + 39 : y + h / 2 + 9, lines: [heading], size: headingSize, weight: 700, anchor }),
    lines.length ? textLines({ x: tx, y: lineStart, lines, size: bodySize, fill: C.muted, lineHeight: bodySize + 10, anchor }) : "",
  ].join("");
}

function pill({ x, y, w, text, color = C.blue, fill = C.blueFill, size = 18 }) {
  return [
    `<rect x="${x}" y="${y}" width="${w}" height="38" rx="19" fill="${fill}" stroke="${color}" stroke-width="1.5"/>`,
    textLines({ x: x + w / 2, y: y + 25, lines: [text], size, weight: 600, fill: color, anchor: "middle" }),
  ].join("");
}

function arrow(x1, y1, x2, y2, { color = C.line, dashed = false, label = "", labelX, labelY } = {}) {
  return [
    `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${color}" stroke-width="3"${dashed ? ' stroke-dasharray="9 8"' : ""} marker-end="url(#arrow)"/>`,
    label ? textLines({ x: labelX ?? (x1 + x2) / 2, y: labelY ?? (y1 + y2) / 2 - 10, lines: [label], size: 17, weight: 600, fill: color, anchor: "middle" }) : "",
  ].join("");
}

function polyline(points, { color = C.line, dashed = false, label = "", labelX = 0, labelY = 0 } = {}) {
  return [
    `<polyline points="${points.map(([x, y]) => `${x},${y}`).join(" ")}" fill="none" stroke="${color}" stroke-width="3"${dashed ? ' stroke-dasharray="9 8"' : ""} marker-end="url(#arrow)"/>`,
    label ? textLines({ x: labelX, y: labelY, lines: [label], size: 17, weight: 600, fill: color, anchor: "middle" }) : "",
  ].join("");
}

function dot(x, y, number, color = C.blue) {
  return [
    `<circle cx="${x}" cy="${y}" r="22" fill="${color}"/>`,
    textLines({ x, y: y + 7, lines: [number], size: 19, weight: 700, fill: C.white, anchor: "middle" }),
  ].join("");
}

function diamond({ cx, cy, w, h, heading, color = C.amber, fill = C.amberFill }) {
  const points = `${cx},${cy - h / 2} ${cx + w / 2},${cy} ${cx},${cy + h / 2} ${cx - w / 2},${cy}`;
  return [
    `<polygon points="${points}" fill="${fill}" stroke="${color}" stroke-width="2.5"/>`,
    textLines({ x: cx, y: cy + 7, lines: [heading], size: 22, weight: 700, anchor: "middle" }),
  ].join("");
}

function svgFrame(body, { width = 1600, height = 1000, ariaLabel }) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(ariaLabel)}">
  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#8CA0A8"/>
    </marker>
    <style>
      text { font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif; letter-spacing: 0; }
    </style>
  </defs>
  <rect width="${width}" height="${height}" fill="#FFFFFF"/>
  ${body}
</svg>`;
}

function architectureOverview() {
  const parts = [title("GIS Data Agent 总体技术架构", "模型负责决策，专业工具负责计算，独立代码负责审核与证据")];
  parts.push(box({ x: 70, y: 160, w: 300, h: 105, heading: "用户目标", lines: ["自然语言问题", "显式 @ 路由"], accent: C.teal, fill: C.tealFill }));
  parts.push(box({ x: 450, y: 160, w: 480, h: 105, heading: "@NL2SQL", lines: ["高频空间问数", "Gemma 4 合成 GeoSQL"], accent: C.blue, fill: C.blueFill }));
  parts.push(box({ x: 1010, y: 160, w: 520, h: 105, heading: "@WorldModelV21", lines: ["县域空间优化", "Gemma 4 动态选择下一工具"], accent: C.violet, fill: C.violetFill }));
  parts.push(arrow(370, 212, 450, 212));
  parts.push(polyline([[370, 225], [410, 225], [410, 145], [1270, 145], [1270, 160]]));

  parts.push(box({ x: 70, y: 315, w: 1460, h: 125, heading: "Gemma 4 26B 决策面", lines: ["意图理解  ·  GeoSQL 合成  ·  工具选择  ·  根据反馈停止 / 恢复 / 提交"], accent: C.blue, fill: C.blueFill, center: true, headingSize: 29, bodySize: 22 }));
  parts.push(arrow(690, 265, 690, 315));
  parts.push(arrow(1270, 265, 1270, 315));

  parts.push(box({ x: 70, y: 490, w: 1460, h: 120, heading: "Google ADK 运行时", lines: ["LlmAgent / BaseAgent  ·  10 个函数工具  ·  session / event  ·  function_call / function_response"], accent: C.teal, fill: C.tealFill, center: true, headingSize: 29, bodySize: 22 }));
  parts.push(arrow(800, 440, 800, 490));

  parts.push(box({ x: 70, y: 660, w: 700, h: 135, heading: "NL2Semantic2GeoSQL 行动面", lines: ["Semantic Layer + GeoSQL Harness", "PostGIS 只读执行 + 三层地图证据"], accent: C.blue, fill: C.white }));
  parts.push(box({ x: 830, y: 660, w: 700, h: 135, heading: "县域耕地空间优化行动面", lines: ["Transition Ensemble + ONNX Runtime", "MPC + 真实县域环境执行"], accent: C.violet, fill: C.white }));
  parts.push(arrow(530, 610, 420, 660));
  parts.push(arrow(1070, 610, 1180, 660));

  parts.push(box({ x: 70, y: 845, w: 1460, h: 105, heading: "治理与证据面", lines: ["版本兼容  ·  SQL 安全  ·  硬约束校验  ·  Verified Episodic Memory  ·  Map / Trace / PDF"], accent: C.green, fill: C.greenFill, center: true, headingSize: 28, bodySize: 21 }));
  parts.push(arrow(420, 795, 420, 845));
  parts.push(arrow(1180, 795, 1180, 845));
  return svgFrame(parts.join(""), { ariaLabel: "GIS Data Agent 总体技术架构" });
}

function twoLevelPlanning() {
  const p = [title("两层规划：任务决策与数值优化", "两层都称为规划，但责任、输入和证据完全不同")];
  p.push(`<rect x="70" y="165" width="1460" height="300" rx="8" fill="${C.blueFill}" stroke="${C.blue}" stroke-width="2.5"/>`);
  p.push(textLines({ x: 105, y: 205, lines: ["任务级规划"], size: 29, weight: 700, fill: C.blue }));
  p.push(pill({ x: 1250, y: 177, w: 230, text: "由 Gemma 4 决定", color: C.blue, fill: C.white }));
  const task = [
    [110, "用户目标", ["问题、版本、资源"]],
    [420, "Gemma 4 + ADK", ["理解目标并选工具"]],
    [760, "函数工具反馈", ["状态、结果、审计结论"]],
    [1100, "下一动作", ["停止 / 恢复 / 提交"]],
  ];
  task.forEach(([x, heading, lines]) => p.push(box({ x, y: 250, w: 270, h: 130, heading, lines, accent: C.blue, fill: C.white, center: true, headingSize: 23, bodySize: 18 })));
  p.push(arrow(380, 315, 420, 315));
  p.push(arrow(690, 315, 760, 315));
  p.push(arrow(1030, 315, 1100, 315));
  p.push(polyline([[1235, 380], [1235, 425], [555, 425], [555, 380]], { color: C.blue, label: "结构化反馈驱动下一步", labelX: 900, labelY: 418 }));

  p.push(`<rect x="70" y="520" width="1460" height="300" rx="8" fill="${C.violetFill}" stroke="${C.violet}" stroke-width="2.5"/>`);
  p.push(textLines({ x: 105, y: 560, lines: ["数值级规划"], size: 29, weight: 700, fill: C.violet }));
  p.push(pill({ x: 1240, y: 532, w: 240, text: "确定性算法执行", color: C.violet, fill: C.white }));
  const numeric = [
    [110, "空间状态", ["17 维 block", "12 维全局"]],
    [420, "转移模型集成", ["预测 s' 与 reward"]],
    [760, "MPC 搜索", ["比较候选 rollout"]],
    [1100, "真实环境执行", ["执行首个行动", "重新观测状态"]],
  ];
  numeric.forEach(([x, heading, lines]) => p.push(box({ x, y: 610, w: 270, h: 145, heading, lines, accent: C.violet, fill: C.white, center: true, headingSize: 23, bodySize: 18 })));
  p.push(arrow(380, 682, 420, 682));
  p.push(arrow(690, 682, 760, 682));
  p.push(arrow(1030, 682, 1100, 682));
  p.push(polyline([[1235, 755], [1235, 790], [245, 790], [245, 755]], { color: C.violet, label: "滚动优化：每一步重新观测", labelX: 740, labelY: 786 }));

  p.push(box({ x: 315, y: 865, w: 970, h: 70, heading: "责任边界：Gemma 4 决定调用什么；MPC 计算具体空间行动；独立代码审核结果", accent: C.red, fill: C.redFill, center: true, headingSize: 22 }));
  return svgFrame(p.join(""), { ariaLabel: "任务级规划与数值级规划的责任边界" });
}

function adkTrajectories() {
  const p = [title("Gemma 4 + ADK 三类真实工具轨迹", "同一 Agent 根据版本、资源和审计反馈形成 2 / 6 / 8 工具分支")];
  const cols = [
    { x: 70, title: "版本不兼容", badge: "2 个工具后停止", color: C.red, fill: C.redFill, toolCount: 2, nodes: ["检查版本与能力", "检查资源与契约", "停止并报告缺口"] },
    { x: 570, title: "首次规划成功", badge: "6 个工具后提交", color: C.green, fill: C.greenFill, nodes: ["检查版本与能力", "检查资源与契约", "召回已验证经验", "执行 / 复用 A–D", "确定性审计通过", "提交已验证经验"] },
    { x: 1070, title: "失败后恢复", badge: "8 个工具，一次重规划", color: C.amber, fill: C.amberFill, nodes: ["检查版本与能力", "检查资源与契约", "召回已验证经验", "执行 / 复用 A–D", "首次审计失败", "单独重跑 MPC", "再次审计通过", "提交已验证经验"] },
  ];
  cols.forEach((col) => {
    p.push(`<rect x="${col.x}" y="165" width="450" height="755" rx="8" fill="${col.fill}" stroke="${col.color}" stroke-width="2.5"/>`);
    p.push(textLines({ x: col.x + 225, y: 212, lines: [col.title], size: 28, weight: 700, fill: col.color, anchor: "middle" }));
    p.push(pill({ x: col.x + 95, y: 235, w: 260, text: col.badge, color: col.color, fill: C.white, size: 17 }));
    const gap = col.nodes.length <= 3 ? 145 : col.nodes.length === 6 ? 92 : 72;
    const start = col.nodes.length <= 3 ? 365 : 335;
    col.nodes.forEach((node, index) => {
      const cy = start + index * gap;
      const terminal = index === col.nodes.length - 1;
      const markerText = terminal && col.toolCount ? "×" : String(index + 1);
      p.push(dot(col.x + 55, cy, markerText, terminal ? col.color : C.ink));
      p.push(`<rect x="${col.x + 95}" y="${cy - 28}" width="315" height="56" rx="6" fill="${terminal ? C.white : "#FFFFFFCC"}" stroke="${terminal ? col.color : C.line}" stroke-width="2"/>`);
      p.push(textLines({ x: col.x + 252, y: cy + 7, lines: [node], size: 19, weight: terminal ? 700 : 500, fill: terminal ? col.color : C.ink, anchor: "middle" }));
      if (!terminal) p.push(arrow(col.x + 55, cy + 24, col.x + 55, cy + gap - 24));
    });
  });
  p.push(textLines({ x: 800, y: 965, lines: ["可靠性证据：三类受控场景各 10 次，30/30 达到预期终态与精确工具轨迹"], size: 21, weight: 600, fill: C.ink, anchor: "middle" }));
  return svgFrame(p.join(""), { ariaLabel: "ADK 两工具、六工具和八工具轨迹" });
}

function nl2sqlPipeline() {
  const p = [title("NL2Semantic2GeoSQL 完整执行链", "Gemma 4 负责 SQL 合成；语义约束、安全、执行与地图证据由确定性组件负责")];
  const steps = [
    ["用户问题", "自然语言空间目标", C.teal, C.tealFill],
    ["显式路由", "MentionNL2SQL", C.blue, C.blueFill],
    ["语义解析", "表 / 字段 / 别名 / 单位", C.teal, C.tealFill],
    ["实时 Grounding", "类型 / geometry / SRID", C.teal, C.tealFill],
    ["Few-shot 检索", "相似参考查询", C.teal, C.tealFill],
    ["Gemma 4 合成", "SQL only · T=0", C.blue, C.blueFill],
    ["空间语义改写", "米制距离 / SRID / 去重", C.violet, C.violetFill],
    ["安全与运行校验", "只读 / AST / allow-list", C.red, C.redFill],
    ["PostGIS 执行", "真实数据 · 结构化结果", C.green, C.greenFill],
    ["证据与沉淀", "标量 + SQL + 地图 + 案例", C.green, C.greenFill],
  ];
  const xs = [70, 375, 680, 985, 1290];
  steps.forEach(([heading, body, accent, fill], index) => {
    const row = index < 5 ? 0 : 1;
    const position = row === 0 ? index : 9 - index;
    const x = xs[position];
    const y = row === 0 ? 210 : 570;
    p.push(dot(x + 28, y - 25, String(index + 1), accent));
    p.push(box({ x, y, w: 240, h: 150, heading, lines: [body], accent, fill, center: true, headingSize: 23, bodySize: 18 }));
    if (index < 4) p.push(arrow(x + 240, y + 75, xs[position + 1], y + 75));
    if (index === 4) p.push(polyline([[x + 120, y + 150], [x + 120, 500], [xs[4] + 120, 500], [xs[4] + 120, 570]]));
    if (index >= 5 && index < 9) p.push(arrow(x, y + 75, xs[position - 1] + 240, y + 75));
  });
  p.push(`<rect x="70" y="790" width="1460" height="110" rx="8" fill="${C.pale}" stroke="#C8D3D8" stroke-width="2"/>`);
  p.push(textLines({ x: 105, y: 830, lines: ["关键失败策略"], size: 23, weight: 700, fill: C.red }));
  p.push(textLines({ x: 105, y: 868, lines: ["未 grounding 表、未知列、写操作、危险 SQL 或地图数量不一致：拒绝执行或判定演示失败"], size: 21, fill: C.ink }));
  p.push(pill({ x: 1120, y: 820, w: 350, text: "运行成功 ≠ 语义必然正确", color: C.red, fill: C.white, size: 19 }));
  return svgFrame(p.join(""), { ariaLabel: "NL2Semantic2GeoSQL 十步执行链" });
}

function gwmMpcArchitecture() {
  const p = [title("领域化 GWM 原型与 MPC 的严格关系", "学习型状态转移模型是动力学内核；MPC 消费模型预测，但不是世界模型本身")];
  p.push(box({ x: 430, y: 155, w: 740, h: 105, heading: "Gemma 4 + Google ADK 任务级控制", lines: ["理解目标 · 选择工具 · 根据反馈停止 / 恢复 / 提交"], accent: C.blue, fill: C.blueFill, center: true, headingSize: 27, bodySize: 20 }));
  p.push(`<rect x="70" y="305" width="840" height="420" rx="8" fill="${C.violetFill}" stroke="${C.violet}" stroke-width="3" stroke-dasharray="12 8"/>`);
  p.push(textLines({ x: 105, y: 350, lines: ["GWM 动力学内核"], size: 29, weight: 700, fill: C.violet }));
  p.push(box({ x: 110, y: 405, w: 300, h: 130, heading: "状态 S", lines: ["2,640 blocks × 17 维", "县域全局 12 维"], accent: C.teal, fill: C.white, center: true, headingSize: 24, bodySize: 18 }));
  p.push(box({ x: 110, y: 575, w: 300, h: 105, heading: "行动 A", lines: ["选择可行 block", "执行 paired swaps"], accent: C.amber, fill: C.white, center: true, headingSize: 24, bodySize: 18 }));
  p.push(box({ x: 500, y: 440, w: 355, h: 190, heading: "转移模型集成 Tθ", lines: ["3 个独立 ONNX 成员", "预测 next state", "预测 reward"], accent: C.violet, fill: C.white, center: true, headingSize: 25, bodySize: 19 }));
  p.push(arrow(410, 470, 500, 500, { label: "s", labelY: 462 }));
  p.push(arrow(410, 625, 500, 575, { label: "a", labelY: 630 }));

  p.push(box({ x: 1000, y: 335, w: 500, h: 145, heading: "MPC 规划器", lines: ["在模型上比较候选 rollout", "只执行预测回报最高方案的第一步"], accent: C.blue, fill: C.blueFill, center: true, headingSize: 27, bodySize: 19 }));
  p.push(arrow(855, 500, 1000, 420, { label: "ŝ' , r̂", labelY: 438 }));
  p.push(box({ x: 1000, y: 535, w: 500, h: 145, heading: "真实县域环境", lines: ["执行行动并重新观测", "产生真实 reward 与空间产物"], accent: C.green, fill: C.greenFill, center: true, headingSize: 27, bodySize: 19 }));
  p.push(arrow(1250, 480, 1250, 535, { label: "首个行动", labelX: 1355, labelY: 516 }));
  p.push(polyline([[1000, 610], [940, 610], [940, 760], [260, 760], [260, 535]], { color: C.green, label: "真实观测形成下一状态", labelX: 610, labelY: 750 }));

  p.push(box({ x: 100, y: 820, w: 650, h: 115, heading: "独立硬约束校验", lines: ["面积不减少 · 坡度下降 · 连片度提升 · 产物完整"], accent: C.red, fill: C.redFill, center: true, headingSize: 25, bodySize: 19 }));
  p.push(box({ x: 850, y: 820, w: 650, h: 115, heading: "Verified Episodic Memory", lines: ["仅通过校验的运行经验可保存并被下次召回"], accent: C.green, fill: C.greenFill, center: true, headingSize: 25, bodySize: 19 }));
  p.push(polyline([[1250, 680], [1250, 790], [800, 790], [800, 878], [750, 878]], { color: C.green, label: "真实结果与空间产物", labelX: 1015, labelY: 780 }));
  p.push(arrow(750, 878, 850, 878, { label: "通过后提交", labelY: 860 }));
  p.push(polyline([[1175, 820], [1540, 820], [1540, 210], [1170, 210]], { color: C.green, dashed: true, label: "下一任务召回", labelX: 1370, labelY: 198 }));
  return svgFrame(p.join(""), { ariaLabel: "地理空间世界模型原型、MPC 和审核记忆的关系" });
}

function transitionNetwork() {
  const p = [title("状态转移模型成员结构", "每个成员约 237K 参数；3 个独立成员导出 ONNX 并在 CPU 上批量推理")];
  const inputs = [
    { y: 205, title: "Block 状态", lines: ["2,640 × 17"], color: C.teal, fill: C.tealFill },
    { y: 410, title: "行动索引", lines: ["Discrete(n_blocks)"], color: C.amber, fill: C.amberFill },
    { y: 615, title: "县域全局状态", lines: ["12 维"], color: C.blue, fill: C.blueFill },
  ];
  inputs.forEach((item) => p.push(box({ x: 70, y: item.y, w: 270, h: 120, heading: item.title, lines: item.lines, accent: item.color, fill: item.fill, center: true, headingSize: 23, bodySize: 19 })));
  p.push(box({ x: 425, y: 185, w: 300, h: 150, heading: "共享 Block Encoder", lines: ["17 → 64 → 32", "所有 blocks 共享权重"], accent: C.teal, fill: C.white, center: true, headingSize: 23, bodySize: 19 }));
  p.push(box({ x: 425, y: 395, w: 300, h: 150, heading: "Action Embedding", lines: ["n_blocks → 32", "选择目标 block"], accent: C.amber, fill: C.white, center: true, headingSize: 23, bodySize: 19 }));
  p.push(box({ x: 425, y: 605, w: 300, h: 150, heading: "Global Encoder", lines: ["12 → 64 → 32"], accent: C.blue, fill: C.white, center: true, headingSize: 23, bodySize: 19 }));
  p.push(arrow(340, 265, 425, 265));
  p.push(arrow(340, 470, 425, 470));
  p.push(arrow(340, 675, 425, 675));
  p.push(box({ x: 795, y: 235, w: 310, h: 120, heading: "Mean Pooling", lines: ["所有 block 编码 → 32"], accent: C.teal, fill: C.tealFill, center: true, headingSize: 23, bodySize: 19 }));
  p.push(box({ x: 795, y: 440, w: 310, h: 180, heading: "Context 拼接", lines: ["selected block 32", "+ action 32 + global 32", "+ mean pool 32 = 128"], accent: C.violet, fill: C.violetFill, center: true, headingSize: 25, bodySize: 19 }));
  p.push(arrow(725, 260, 795, 295));
  p.push(polyline([[725, 315], [755, 315], [755, 480], [795, 480]], { label: "selected", labelX: 785, labelY: 380 }));
  p.push(polyline([[725, 470], [760, 470], [760, 520], [795, 520]]));
  p.push(polyline([[725, 680], [760, 680], [760, 560], [795, 560]]));
  p.push(arrow(950, 355, 950, 440));

  const heads = [
    { y: 190, title: "Block Delta Head", lines: ["128 → 256 → 256 → 17"], color: C.teal, fill: C.tealFill },
    { y: 390, title: "Global Delta Head", lines: ["128 → 256 → 12"], color: C.blue, fill: C.blueFill },
    { y: 590, title: "Reward Head", lines: ["128 → 64 → 1"], color: C.green, fill: C.greenFill },
  ];
  heads.forEach((item) => {
    p.push(box({ x: 1180, y: item.y, w: 350, h: 135, heading: item.title, lines: item.lines, accent: item.color, fill: item.fill, center: true, headingSize: 23, bodySize: 19 }));
    p.push(arrow(1105, 530, 1180, item.y + 68));
  });
  p.push(box({ x: 300, y: 830, w: 1000, h: 95, heading: "3-member Ensemble → ONNX Runtime → MPC 批量评估候选行动", accent: C.violet, fill: C.pale, center: true, headingSize: 26 }));
  return svgFrame(p.join(""), { width: 1600, height: 970, ariaLabel: "237K 参数状态转移网络结构" });
}

function autonomyStateMachine() {
  const p = [title("受控自主决策状态机", "自主性体现在观察、选择、反馈后恢复或停止；权限边界由代码强制执行")];
  p.push(pill({ x: 695, y: 155, w: 210, text: "START", color: C.ink, fill: C.pale, size: 21 }));
  p.push(box({ x: 550, y: 230, w: 500, h: 95, heading: "检查版本、能力与资源", accent: C.blue, fill: C.blueFill, center: true, headingSize: 24 }));
  p.push(arrow(800, 193, 800, 230));
  p.push(diamond({ cx: 800, cy: 390, w: 390, h: 105, heading: "版本与资源可用？", color: C.amber, fill: C.amberFill }));
  p.push(arrow(800, 325, 800, 338));
  p.push(box({ x: 1125, y: 340, w: 370, h: 100, heading: "停止并报告缺口", lines: ["不自动降级旧算法"], accent: C.red, fill: C.redFill, center: true, headingSize: 23, bodySize: 18 }));
  p.push(arrow(995, 390, 1125, 390, { color: C.red, label: "否", labelY: 375 }));
  p.push(box({ x: 550, y: 485, w: 500, h: 95, heading: "召回已验证经验", accent: C.teal, fill: C.tealFill, center: true, headingSize: 24 }));
  p.push(arrow(800, 443, 800, 485, { color: C.green, label: "是", labelX: 835, labelY: 472 }));
  p.push(box({ x: 550, y: 635, w: 500, h: 95, heading: "执行 Pipeline / MPC Plan", accent: C.violet, fill: C.violetFill, center: true, headingSize: 24 }));
  p.push(arrow(800, 580, 800, 635));
  p.push(diamond({ cx: 800, cy: 805, w: 430, h: 115, heading: "确定性审核通过？", color: C.amber, fill: C.amberFill }));
  p.push(arrow(800, 730, 800, 748));
  p.push(box({ x: 1130, y: 755, w: 370, h: 100, heading: "提交已验证经验", lines: ["幂等写入 + SHA-256"], accent: C.green, fill: C.greenFill, center: true, headingSize: 22, bodySize: 18 }));
  p.push(arrow(1015, 805, 1130, 805, { color: C.green, label: "通过", labelY: 790 }));
  p.push(box({ x: 105, y: 755, w: 340, h: 100, heading: "最多重规划一次", lines: ["仅重跑 Tool 4 MPC"], accent: C.amber, fill: C.amberFill, center: true, headingSize: 22, bodySize: 18 }));
  p.push(arrow(585, 805, 445, 805, { color: C.amber, label: "首次失败", labelY: 790 }));
  p.push(arrow(800, 862, 800, 910, { color: C.red, label: "缺产物", labelX: 860, labelY: 895 }));
  p.push(box({ x: 105, y: 910, w: 340, h: 100, heading: "再次确定性审核", accent: C.amber, fill: C.white, center: true, headingSize: 22 }));
  p.push(arrow(275, 855, 275, 910));
  p.push(box({ x: 630, y: 910, w: 340, h: 100, heading: "转人工复核", lines: ["二次失败或缺少空间产物"], accent: C.red, fill: C.redFill, center: true, headingSize: 22, bodySize: 17 }));
  p.push(arrow(445, 960, 630, 960, { color: C.red, label: "失败", labelY: 945 }));
  p.push(polyline([[275, 1010], [275, 1035], [1315, 1035], [1315, 855]], { color: C.green, label: "通过", labelX: 800, labelY: 1028 }));
  return svgFrame(p.join(""), { width: 1600, height: 1080, ariaLabel: "受控自主决策状态机" });
}

function knowledgeMemoryLoop() {
  const p = [title("知识与记忆的受控更新闭环", "记忆保存已发生且可复核的经验；知识保存领域定义、规则与适用范围")];
  const nodes = [
    { x: 100, y: 235, w: 360, h: 125, title: "候选事实 / 经验", lines: ["GeoSQL 成功案例", "县域规划 episode"], color: C.teal, fill: C.tealFill },
    { x: 620, y: 175, w: 360, h: 145, title: "来源与适用范围", lines: ["版本 · 时间 · 空间范围", "数据集 · 摘要哈希"], color: C.blue, fill: C.blueFill },
    { x: 1140, y: 235, w: 360, h: 125, title: "分级验证", lines: ["自动校验", "高风险项人工审批"], color: C.amber, fill: C.amberFill },
    { x: 1140, y: 610, w: 360, h: 125, title: "激活为可用知识", lines: ["Verified Memory", "Reference Query / Registry"], color: C.green, fill: C.greenFill },
    { x: 620, y: 680, w: 360, h: 145, title: "运行中检索与引用", lines: ["按数据集与版本隔离", "记录 provenance"], color: C.violet, fill: C.violetFill },
    { x: 100, y: 610, w: 360, h: 125, title: "新结果与新证据", lines: ["真实执行结果", "审核结论与反馈"], color: C.teal, fill: C.tealFill },
  ];
  nodes.forEach((n) => p.push(box({ x: n.x, y: n.y, w: n.w, h: n.h, heading: n.title, lines: n.lines, accent: n.color, fill: n.fill, center: true, headingSize: 24, bodySize: 18 })));
  p.push(arrow(460, 297, 620, 248));
  p.push(arrow(980, 248, 1140, 297));
  p.push(arrow(1320, 360, 1320, 610));
  p.push(arrow(1140, 672, 980, 752));
  p.push(arrow(620, 752, 460, 672));
  p.push(arrow(280, 610, 280, 360));
  p.push(box({ x: 535, y: 420, w: 530, h: 150, heading: "治理规则", lines: ["SQL 可执行 ≠ 语义正确", "审核未通过不得写入经验", "新证据可触发再验证 / 降级 / 废止"], accent: C.red, fill: C.redFill, center: true, headingSize: 25, bodySize: 19 }));
  p.push(polyline([[800, 420], [800, 350], [1140, 350]], { color: C.red, dashed: true }));
  p.push(pill({ x: 100, y: 855, w: 420, text: "即时 / 会话记忆：提供上下文", color: C.muted, fill: C.pale, size: 19 }));
  p.push(pill({ x: 590, y: 855, w: 420, text: "领域经验：只追加、带证据", color: C.green, fill: C.greenFill, size: 19 }));
  p.push(pill({ x: 1080, y: 855, w: 420, text: "语义知识：版本化、可撤销", color: C.blue, fill: C.blueFill, size: 19 }));
  return svgFrame(p.join(""), { ariaLabel: "知识与记忆更新闭环" });
}

function deploymentTopology() {
  const p = [title("决赛运行与部署拓扑", "核心服务本地或内网部署；模型、数据、算法资源与用户产物边界清晰")];
  p.push(box({ x: 70, y: 330, w: 270, h: 145, heading: "现场浏览器", lines: ["PPT / Demo 操作端", "HTTP :8000"], accent: C.teal, fill: C.tealFill, center: true, headingSize: 25, bodySize: 19 }));
  p.push(`<rect x="410" y="170" width="1110" height="650" rx="8" fill="${C.pale}" stroke="#AFC0C7" stroke-width="2.5" stroke-dasharray="12 8"/>`);
  p.push(textLines({ x: 445, y: 215, lines: ["Docker Compose / 内网运行边界"], size: 28, weight: 700, fill: C.ink }));
  p.push(box({ x: 465, y: 295, w: 380, h: 210, heading: "GIS Data Agent App", lines: ["Chainlit + API", "Google ADK 运行时", "用户与运行目录隔离"], accent: C.blue, fill: C.blueFill, center: true, headingSize: 26, bodySize: 19 }));
  p.push(arrow(340, 402, 465, 402, { label: "请求 / 地图 / 报告", labelX: 402, labelY: 372 }));

  p.push(box({ x: 930, y: 260, w: 250, h: 125, heading: "Gemma 4 / Ollama", lines: ["本地模型服务"], accent: C.blue, fill: C.white, center: true, headingSize: 22, bodySize: 18 }));
  p.push(box({ x: 1225, y: 260, w: 240, h: 125, heading: "PostGIS", lines: ["只读空间查询", ":5432"], accent: C.teal, fill: C.white, center: true, headingSize: 22, bodySize: 18 }));
  p.push(box({ x: 930, y: 440, w: 250, h: 125, heading: "Redis", lines: ["会话与运行状态", ":6379"], accent: C.amber, fill: C.white, center: true, headingSize: 22, bodySize: 18 }));
  p.push(box({ x: 1225, y: 440, w: 240, h: 125, heading: "MinIO（可选）", lines: ["对象存储扩展", "非主 Demo 依赖"], accent: C.muted, fill: C.white, center: true, headingSize: 21, bodySize: 17 }));
  p.push(arrow(845, 350, 930, 322));
  p.push(polyline([[845, 375], [885, 375], [885, 235], [1345, 235], [1345, 260]]));
  p.push(arrow(845, 425, 930, 502));
  p.push(polyline([[845, 450], [885, 450], [885, 590], [1345, 590], [1345, 565]], { dashed: true }));

  p.push(box({ x: 465, y: 610, w: 310, h: 140, heading: "只读算法资源", lines: ["0.3.3 / 2.2.3 包", "Bishan prepared + ONNX"], accent: C.violet, fill: C.violetFill, center: true, headingSize: 23, bodySize: 18 }));
  p.push(box({ x: 835, y: 610, w: 310, h: 140, heading: "按用户隔离的产物", lines: ["uploads / output", "Map / Audit / PDF"], accent: C.green, fill: C.greenFill, center: true, headingSize: 23, bodySize: 18 }));
  p.push(box({ x: 1205, y: 610, w: 260, h: 140, heading: "预检与健康检查", lines: ["版本 · 模型 · 数据", "app / db / redis"], accent: C.red, fill: C.redFill, center: true, headingSize: 22, bodySize: 18 }));
  p.push(arrow(620, 610, 620, 505));
  p.push(arrow(790, 505, 935, 610));
  p.push(polyline([[1205, 680], [1175, 680], [1175, 785], [430, 785], [430, 475], [465, 475]], { color: C.red, dashed: true, label: "启动前", labelX: 800, labelY: 776 }));
  p.push(box({ x: 260, y: 865, w: 1080, h: 75, heading: "失败策略：版本、模型、数据或核心服务预检不通过时停止，不在现场临时降级", accent: C.red, fill: C.redFill, center: true, headingSize: 22 }));
  return svgFrame(p.join(""), { ariaLabel: "GIS Data Agent 决赛运行和部署拓扑" });
}

const diagrams = [
  ["architecture_overview", architectureOverview],
  ["two_level_planning", twoLevelPlanning],
  ["adk_tool_trajectories", adkTrajectories],
  ["nl2semantic2geosql_pipeline", nl2sqlPipeline],
  ["gwm_mpc_architecture", gwmMpcArchitecture],
  ["transition_network", transitionNetwork],
  ["autonomy_state_machine", autonomyStateMachine],
  ["knowledge_memory_loop", knowledgeMemoryLoop],
  ["deployment_topology", deploymentTopology],
];

async function main() {
  await mkdir(OUTPUT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    for (const [name, build] of diagrams) {
      const svg = build();
      if (svg.includes("undefined")) throw new Error(`${name}: generated SVG contains undefined`);
      const svgPath = path.join(OUTPUT_DIR, `${name}.svg`);
      const pngPath = path.join(OUTPUT_DIR, `${name}.png`);
      await writeFile(svgPath, svg, "utf8");

      const dimensions = /width="(\d+)" height="(\d+)"/.exec(svg);
      const width = Number(dimensions[1]);
      const height = Number(dimensions[2]);
      const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 2 });
      const page = await context.newPage();
      await page.setContent(`<html><head><style>html,body{margin:0;padding:0;background:#fff;overflow:hidden}svg{display:block}</style></head><body>${svg}</body></html>`);
      await page.locator("svg").screenshot({ path: pngPath, animations: "disabled" });
      await context.close();
      process.stdout.write(`${name}: ${width * 2}x${height * 2}\n`);
    }
  } finally {
    await browser.close();
  }
}

await main();
