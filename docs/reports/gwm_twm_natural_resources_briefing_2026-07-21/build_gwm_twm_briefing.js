const fs = require('fs');
const path = require('path');

process.env.NODE_PATH = '/Users/zhouning/ppt_rebuild_uwm/node_modules';
require('module').Module._initPaths();

const pptxgen = require('pptxgenjs');

const OUT_DIR = __dirname;
const PPTX_OUT = path.join(OUT_DIR, 'GWM_TWM_省自然资源厅信息中心技术汇报_主任汇报口径版_2026-07-22.pptx');
const ASSET_ROOT = '/Users/zhouning/gisdataagent/docs';
const COVER_IMAGE = path.join(ASSET_ROOT, 'reports/data_for_ai_gwm_customer_2026-07-17/assets/cover_data_for_ai.png');
const MAP_STRIP = path.join(ASSET_ROOT, 'articles/geospatial_world_model_alphago_moment_assets/fig3_twm_flus_prediction_maps.png');
const PAPER58_REPORT = '/Users/zhouning/paper58_rebase_untracked_backup_20260629_210115/paper/rse_submission_paper58/paper58_geosos_flus_comparison_report_2026-06-24.md';

const pptx = new pptxgen();
pptx.defineLayout({ name: 'GWM_WIDE', width: 13.333333, height: 7.5 });
pptx.layout = 'GWM_WIDE';
pptx.author = 'GIS Data Agent / GWM Research';
pptx.company = 'GIS Data Agent';
pptx.subject = '面向省级自然资源治理的地理空间世界模型技术汇报';
pptx.title = '地理空间世界模型：从空间优化到可验证的国土空间推演内核';
pptx.lang = 'zh-CN';
pptx.theme = {
  headFontFace: 'Hiragino Sans GB',
  bodyFontFace: 'Hiragino Sans GB',
  lang: 'zh-CN'
};

const S = pptx.ShapeType;
const C = {
  bg: 'F5F7F6',
  paper: 'FFFFFF',
  ink: '17252A',
  text: '32474D',
  muted: '6C7C80',
  line: 'D0DBD8',
  teal: '137F7A',
  tealDark: '0E5C59',
  tealSoft: 'E2F2EF',
  green: '2D8A57',
  greenSoft: 'E7F3EA',
  blue: '356CA8',
  blueSoft: 'E7EFF8',
  gold: 'B17B20',
  goldSoft: 'FFF3D9',
  red: 'B04A50',
  redSoft: 'FBE9EA',
  violet: '705FA7',
  violetSoft: 'EEEAF8',
  dark: '102F34',
  dark2: '183F43',
  graySoft: 'EDF1F0'
};

const TOTAL = 29;

function addText(slide, text, x, y, w, h, opts = {}) {
  slide.addText(text, {
    x, y, w, h,
    fontFace: opts.fontFace || 'Hiragino Sans GB',
    fontSize: opts.fontSize ?? 12,
    color: opts.color || C.text,
    bold: opts.bold || false,
    align: opts.align || 'left',
    valign: opts.valign || 'mid',
    margin: opts.margin ?? 0,
    fit: opts.fit || 'shrink',
    breakLine: false,
    paraSpaceAfterPt: 0,
    lineSpacingMultiple: opts.lineSpacingMultiple ?? 0.92,
    isTextBox: true,
    ...opts
  });
}

function addBox(slide, x, y, w, h, fill, line = C.line, radius = 0.05, lineWidth = 0.7) {
  slide.addShape(radius > 0 ? S.roundRect : S.rect, {
    x, y, w, h,
    rectRadius: radius,
    fill: { color: fill },
    line: { color: line, width: lineWidth }
  });
}

function addLine(slide, x, y, w, h, color = C.line, width = 1, beginArrowType, endArrowType, dashType) {
  slide.addShape(S.line, {
    x, y, w, h,
    line: { color, width, beginArrowType, endArrowType, dashType }
  });
}

function addCircle(slide, x, y, d, fill, line = fill, lineWidth = 0.7) {
  slide.addShape(S.ellipse, { x, y, w: d, h: d, fill: { color: fill }, line: { color: line, width: lineWidth } });
}

function addPill(slide, text, x, y, w, fill, color = C.ink, line = fill, fontSize = 8.2) {
  addBox(slide, x, y, w, 0.28, fill, line, 0.14, 0.5);
  addText(slide, text, x + 0.06, y + 0.025, w - 0.12, 0.2, { fontSize, color, bold: true, align: 'center' });
}

function addBullet(slide, text, x, y, w, h, opts = {}) {
  addCircle(slide, x, y + 0.105, 0.07, opts.bulletColor || C.teal);
  addText(slide, text, x + 0.15, y, w - 0.15, h, {
    fontSize: opts.fontSize ?? 10.2,
    color: opts.color || C.text,
    bold: opts.bold || false,
    valign: 'top',
    lineSpacingMultiple: 0.9
  });
}

function addSectionTag(slide, section) {
  addPill(slide, section, 0.38, 0.22, 1.42, C.tealSoft, C.tealDark, C.tealSoft, 7.3);
}

function addHeader(slide, page, section, title, claim, source) {
  slide.background = { color: C.bg };
  addSectionTag(slide, section);
  addText(slide, title, 0.39, 0.60, 12.10, 0.42, { fontSize: 23.5, color: C.ink, bold: true, valign: 'top' });
  addText(slide, claim, 0.40, 1.03, 12.10, 0.30, { fontSize: 10.2, color: C.tealDark, bold: true, valign: 'top' });
  addLine(slide, 0.39, 1.36, 12.54, 0, C.line, 0.8);
  addLine(slide, 0.39, 7.12, 12.54, 0, C.line, 0.7);
  addText(slide, source, 0.40, 7.18, 10.95, 0.13, { fontSize: 5.8, color: C.muted, valign: 'top' });
  const currentPage = pptx._slides.length;
  addText(slide, String(currentPage).padStart(2, '0') + ' / ' + TOTAL, 12.12, 7.17, 0.80, 0.15, { fontSize: 6.7, color: C.muted, align: 'right' });
}

function addNote(slide, key, points, sources) {
  slide.addNotes([
    `核心判断：${key}`,
    '',
    ...points.map((p) => `- ${p}`),
    '',
    '项目依据：',
    ...sources.map((s) => `- ${s}`)
  ].join('\n'));
}

function addFlowArrow(slide, x, y, w = 0.34, color = C.teal) {
  addLine(slide, x, y, w, 0, color, 1.6, undefined, 'triangle');
}

function addMiniLabel(slide, text, x, y, w, color = C.muted) {
  addText(slide, text, x, y, w, 0.17, { fontSize: 6.7, color, bold: true, align: 'center' });
}

function slide01() {
  const slide = pptx.addSlide();
  slide.background = { color: C.dark };
  if (fs.existsSync(COVER_IMAGE)) {
    slide.addImage({ path: COVER_IMAGE, x: 0, y: 0, w: 13.333333, h: 7.5 });
  }
  slide.addShape(S.rect, { x: 0, y: 0, w: 13.333333, h: 7.5, fill: { color: C.dark, transparency: 24 }, line: { color: C.dark, transparency: 100 } });
  slide.addShape(S.rect, { x: 0, y: 0, w: 7.18, h: 7.5, fill: { color: '0B282C', transparency: 4 }, line: { color: '0B282C', transparency: 100 } });
  addPill(slide, 'TECHNICAL BRIEFING · V6', 0.72, 0.60, 2.25, '1B4C50', 'CFE9E5', '417176', 7.5);
  addText(slide, '地理空间世界模型', 0.72, 1.36, 5.90, 0.67, { fontSize: 31, color: 'FFFFFF', bold: true, valign: 'top' });
  addText(slide, '从空间优化到可验证的\n国土空间推演内核', 0.72, 2.08, 5.95, 1.42, { fontSize: 27, color: 'FFFFFF', bold: true, valign: 'top', lineSpacingMultiple: 0.86 });
  addText(slide, 'Geospatial World Model (GWM)  ·  Territory World Model (TWM)', 0.75, 3.48, 5.85, 0.22, { fontFace: 'Arial', fontSize: 9.6, color: '9FC8C2', bold: true, valign: 'top' });
  addText(slide, '面向自然资源治理的状态建模、行动推演与决策支撑', 0.75, 3.75, 5.85, 0.60, { fontSize: 11.2, color: 'D4E8E5', valign: 'top' });
  addLine(slide, 0.74, 4.63, 5.56, 0, '5CB9A6', 1.2);
  addText(slide, '汇报对象：某省自然资源厅信息中心\n技术专题汇报  |  2026-07-22', 0.75, 4.86, 5.25, 0.72, { fontSize: 10.6, color: 'D4E8E5', valign: 'top' });
  addText(slide, 'GWM / TWM', 11.13, 6.84, 1.50, 0.24, { fontSize: 10, color: 'D4E8E5', bold: true, align: 'right' });
  addNote(slide,
    '本次汇报不把世界模型讲成大模型概念，而是讨论一个可验证、可审计的空间状态转移与规划内核。',
    [
      '汇报从既有深度强化学习空间优化研究出发，但重点是问题如何从“求最优布局”升级为“模拟行动后的世界”。',
      'GeoSOS-FLUS 被用作权威传统基线；比较重点既包括同题实验，也包括架构能力边界。',
      'TWM 是 GWM 在自然资源领域的实例，不替代一张图、遥感平台或法定审批系统。'
    ],
    ['用户给定汇报思路；GWM_RESEARCH_PRINCIPLES.md；GWM_RUNTIME_KERNEL_AND_GEOSPATIAL_KERNEL_RELATIONSHIP.md']
  );
}

function slideAgenda() {
  const slide = pptx.addSlide();
  addHeader(slide, 2, '汇报目录', '汇报框架：问题、证据、机制、应用与试点', '全篇围绕现实需求、实证基础、技术内核、业务价值和实施路径五个层次展开。', '本页为全篇导航；页码对应本版 29 页汇报材料');

  addBox(slide, 0.56, 1.57, 12.20, 0.48, C.dark, C.dark, 0.04, 0);
  addText(slide, '核心判断 · P03', 0.82, 1.68, 1.62, 0.23, { fontSize: 10.6, color: 'FFFFFF', bold: true });
  addText(slide, '研究对象  /  对标结论  /  技术内核  /  平台形态', 2.65, 1.67, 7.14, 0.23, { fontSize: 9.4, color: 'D4E8E5', bold: true, align: 'center' });
  addText(slide, '全篇结论摘要', 10.07, 1.68, 2.35, 0.22, { fontSize: 8.4, color: '9FC8C2', bold: true, align: 'right' });

  const chapters = [
    ['01', '问题与起点', 'P04–11', 'GWM 的提出背景与数据基础', '从世界模型谱系、空间优化实践和数据契约说明研究对象的演进', C.teal, C.tealSoft],
    ['02', '对标与证据', 'P12–14', '能力边界与证据强度', '以 GeoSOS-FLUS 强基线检验当前效果与架构能力空间', C.gold, C.goldSoft],
    ['03', '技术内核', 'P15–20', 'GWM 推演机制', '说明 Geospatial Kernel、Runtime、Simulator、状态写回与理论来源', C.blue, C.blueSoft],
    ['04', '领域实例', 'P21–27', 'TWM 业务价值', '将 GWM 契约实例化为自然资源对象、规则、行动与可审计方案', C.green, C.greenSoft],
    ['05', '平台与试点', 'P28–29', '平台架构与实施路径', '构建 LLM + WM 平台，并从省级真实业务闭环启动联合试点', C.violet, C.violetSoft]
  ];

  addText(slide, '章节', 0.76, 2.21, 2.21, 0.20, { fontSize: 7.4, color: C.muted, bold: true });
  addText(slide, '本章主题', 3.30, 2.21, 3.20, 0.20, { fontSize: 7.4, color: C.muted, bold: true });
  addText(slide, '汇报重点', 7.00, 2.21, 5.15, 0.20, { fontSize: 7.4, color: C.muted, bold: true });

  chapters.forEach((chapter, i) => {
    const y = 2.48 + i * 0.82;
    addBox(slide, 0.56, y, 12.20, 0.68, i % 2 === 0 ? C.paper : C.graySoft, C.line, 0.02, 0.55);
    addBox(slide, 0.56, y, 0.10, 0.68, chapter[5], chapter[5], 0, 0);
    addText(slide, chapter[0], 0.79, y + 0.15, 0.48, 0.28, { fontFace: 'Arial', fontSize: 13.2, color: chapter[5], bold: true, align: 'center' });
    addText(slide, chapter[1], 1.39, y + 0.11, 1.15, 0.25, { fontSize: 10.7, color: C.ink, bold: true });
    addPill(slide, chapter[2], 1.39, y + 0.39, 0.78, chapter[6], chapter[5], chapter[6], 6.8);
    addText(slide, chapter[3], 3.30, y + 0.13, 3.12, 0.32, { fontSize: 10.1, color: chapter[5], bold: true });
    addText(slide, chapter[4], 7.00, y + 0.10, 5.25, 0.42, { fontSize: 8.4, color: C.text, valign: 'top' });
  });

  addLine(slide, 1.02, 6.67, 10.98, 0, C.line, 0.7);
  addText(slide, '一条主线', 0.79, 6.73, 0.93, 0.22, { fontSize: 8.5, color: C.tealDark, bold: true });
  addText(slide, '现实决策难题', 1.92, 6.72, 1.39, 0.23, { fontSize: 8.3, color: C.ink, bold: true, align: 'center' });
  addFlowArrow(slide, 3.43, 6.83, 0.47, C.teal);
  addText(slide, '可验证证据', 4.01, 6.72, 1.31, 0.23, { fontSize: 8.3, color: C.ink, bold: true, align: 'center' });
  addFlowArrow(slide, 5.46, 6.83, 0.47, C.teal);
  addText(slide, '可运行机制', 6.05, 6.72, 1.31, 0.23, { fontSize: 8.3, color: C.ink, bold: true, align: 'center' });
  addFlowArrow(slide, 7.50, 6.83, 0.47, C.teal);
  addText(slide, '可衡量业务价值', 8.10, 6.72, 1.67, 0.23, { fontSize: 8.3, color: C.ink, bold: true, align: 'center' });
  addFlowArrow(slide, 9.92, 6.83, 0.47, C.teal);
  addText(slide, '可执行试点', 10.52, 6.72, 1.38, 0.23, { fontSize: 8.3, color: C.ink, bold: true, align: 'center' });

  addNote(slide,
    '全篇不是按模型名称展开，而是按“必要性—可信性—可实现性—业务价值—行动路径”展开。',
    [
      '第 3 页先给四个判断，帮助听众建立整场汇报的坐标系。',
      '第一章解释为什么问题会从空间优化升级为世界模型，并落到状态—动作—结果数据契约。',
      '第二章用 GeoSOS-FLUS 作为权威强基线，既证明能力空间，也约束当前主张。',
      '第三章集中回答技术实现，避免 Geospatial Kernel、Runtime 和 Simulator 的角色混淆。',
      '第四、五章回到自然资源业务价值、证据成熟度、平台形态与省级试点。'
    ],
    ['本版汇报逐页结构与现场叙事设计']
  );
}

function slide02() {
  const slide = pptx.addSlide();
  addHeader(slide, 2, '结论先行', '地理空间世界模型的四项核心判断', '四项判断分别界定研究对象、对标结论、技术内核和目标平台形态。', '来源：GWM Research Principles；DAM-GK Research Spec；TWM validation / runtime benchmark');

  const items = [
    ['01', '问题升级', '从“在给定状态上优化”升级为“学习状态如何随行动变化，并在未来状态中继续规划”。', C.teal, C.tealSoft],
    ['02', '对标结论', 'GeoSOS-FLUS 是成熟强基线；GWM 的能力空间更宽，当前整体精度与生产成熟度仍处于验证阶段。', C.gold, C.goldSoft],
    ['03', '技术核心', 'DAM-GK 负责空间动力学；GWM Runtime 负责状态、动作、写回、不确定性、证据与领域适配。', C.blue, C.blueSoft],
    ['04', '平台形态', 'TWM 是 GWM 的自然资源实例；未来智能体平台应由 LLM 负责语义编排、WM 负责数值推演。', C.green, C.greenSoft]
  ];
  items.forEach((it, i) => {
    const y = 1.63 + i * 1.27;
    addText(slide, it[0], 0.58, y + 0.02, 0.72, 0.44, { fontSize: 20, color: it[3], bold: true, align: 'center' });
    addLine(slide, 1.47, y + 0.08, 0, 0.84, it[3], 3.2);
    addText(slide, it[1], 1.72, y, 2.10, 0.34, { fontSize: 15, color: C.ink, bold: true, valign: 'top' });
    addText(slide, it[2], 3.70, y, 8.75, 0.76, { fontSize: 11.4, color: C.text, valign: 'top', lineSpacingMultiple: 0.88 });
    if (i < items.length - 1) addLine(slide, 1.73, y + 1.03, 10.73, 0, C.line, 0.6);
  });
  addBox(slide, 0.58, 6.55, 11.88, 0.35, C.dark, C.dark, 0.04, 0);
  addText(slide, '证据口径：架构能力、已实现机制、已验证效果和生产可用性实行分层陈述。', 0.78, 6.62, 11.45, 0.18, { fontSize: 9.6, color: 'FFFFFF', bold: true, align: 'center' });
  addNote(slide,
    '先给出结论可以避免把 GWM 误解成“更大的土地利用预测模型”。',
    [
      '对技术型听众，最重要的是把研究对象、证据层级和工程成熟度说清楚。',
      '后续每页分别回答：为什么提出、与 FLUS 有何不同、核心算子如何工作、TWM 如何落地、哪里仍未完成。',
      '汇报中凡是“上限”均指能力空间，不指当前所有指标已经占优。'
    ],
    ['docs/research/GWM_RESEARCH_PRINCIPLES.md', 'docs/research/DAM_GK_RESEARCH_SPEC.md', 'docs/reports/twm_runtime_benchmark_v1.json']
  );
}

function slide03() {
  const slide = pptx.addSlide();
  addHeader(slide, 5, '研究起点', '空间优化研究向世界模型演进', '地块、规划单元、片区和县域的连续研究，逐步形成面向状态转移、长期效应和工程部署的技术主线。', '来源：Paper1-Paper4 / Paper9 项目材料；farmland-drl-optimization；paper3；paper4；paper9 MNR package');

  addLine(slide, 1.05, 3.18, 11.10, 0, C.line, 3.0);
  const xs = [1.10, 3.55, 6.00, 8.45, 10.90];
  const stages = [
    ['地块级', '受约束 DRL', '坡度 / 连片度 / 面积平衡', C.teal],
    ['规划单元级', '维度不变策略', '跨规模动作评分与迁移', C.blue],
    ['街区 / 片区级', '序列情景筛选', '从图斑动作到政策场景', C.violet],
    ['县域级', '多主体协同', '跨乡镇资源分配与稳定性', C.gold],
    ['工程化', '模型式规划', '采样-训练-MPC-审计-内网', C.green]
  ];
  stages.forEach((st, i) => {
    addCircle(slide, xs[i], 2.93, 0.50, st[3], 'FFFFFF', 1.3);
    addText(slide, String(i + 1), xs[i], 3.01, 0.50, 0.20, { fontSize: 9, color: 'FFFFFF', bold: true, align: 'center' });
    addText(slide, st[0], xs[i] - 0.54, 2.06, 1.58, 0.28, { fontSize: 11.5, color: st[3], bold: true, align: 'center' });
    addText(slide, st[1], xs[i] - 0.65, 2.37, 1.80, 0.33, { fontSize: 10.6, color: C.ink, bold: true, align: 'center' });
    addText(slide, st[2], xs[i] - 0.78, 3.62, 2.10, 0.62, { fontSize: 8.8, color: C.text, align: 'center', valign: 'top' });
  });
  addBox(slide, 0.67, 4.73, 12.00, 1.25, C.paper, C.line, 0.06, 0.8);
  addText(slide, '由优化问题形成的能力需求', 0.95, 4.99, 2.60, 0.28, { fontSize: 13.2, color: C.ink, bold: true });
  addText(slide, '既有优化器侧重在给定状态上选择动作；多期治理进一步要求显式建模状态转移、长期效应、空间溢出及证据边界。', 3.53, 4.90, 8.70, 0.72, { fontSize: 11.2, color: C.text, valign: 'top' });
  addPill(slide, '优化给定世界', 2.15, 6.26, 2.05, C.graySoft, C.text, C.line, 8.6);
  addFlowArrow(slide, 4.43, 6.40, 1.15, C.teal);
  addPill(slide, '模拟行动后的世界', 5.82, 6.26, 2.40, C.tealSoft, C.tealDark, C.teal, 8.6);
  addFlowArrow(slide, 8.48, 6.40, 1.15, C.green);
  addPill(slide, '在未来世界中规划', 9.86, 6.26, 2.40, C.greenSoft, C.green, C.green, 8.6);
  addNote(slide,
    'GWM 的真正起点是空间优化研究中反复出现的“模型缺少可用的未来世界”问题。',
    [
      '早期工作解决的是耕地布局在坡度、连片度和面积平衡约束下如何优化。',
      '随后尺度从地块扩展到规划单元、片区和县域，并引入多主体协同与模型式规划。',
      'Paper9 的关键工程转折是把采样、训练、MPC 规划、硬门禁和审计形成可部署链路。',
      'GWM 继续追问：转移模型本身能否成为跨场景、可递归、可验证的空间动力学内核。'
    ],
    ['farmland-drl-optimization/README.md', 'paper3-block-level-farmland-drl/README.md', 'paper4-county-marl-farmland-consolidation/README.md', 'paper9-mnr-offline-package/README.md']
  );
}

function slide04() {
  const slide = pptx.addSlide();
  addHeader(slide, 8, '问题升级', '从空间优化器到世界模型：显式状态转移与递归规划', 'GWM 在策略搜索基础上增加行动条件转移、状态写回、关系重算和未来状态再规划。', '理论：MDP / model-based RL / state-space model；项目：GWM Research Principles');

  addText(slide, '传统空间优化', 0.70, 1.70, 2.25, 0.34, { fontSize: 15, color: C.muted, bold: true, align: 'center' });
  addBox(slide, 0.70, 2.16, 3.00, 2.78, C.paper, C.line, 0.06, 0.8);
  addText(slide, 'π(a | s)', 1.14, 2.48, 2.12, 0.52, { fontFace: 'Arial', fontSize: 28, color: C.tealDark, bold: true, align: 'center' });
  addText(slide, '给定状态 s\n直接选择动作 a', 1.08, 3.20, 2.22, 0.75, { fontSize: 13, color: C.ink, bold: true, align: 'center', valign: 'top' });
  addText(slide, '适合：明确奖励、稳定约束、有限动作空间', 1.02, 4.27, 2.35, 0.40, { fontSize: 8.8, color: C.muted, align: 'center' });

  addFlowArrow(slide, 4.03, 3.46, 0.70, C.gold);
  addText(slide, '研究对象改变', 3.91, 2.92, 0.98, 0.23, { fontSize: 7.4, color: C.gold, bold: true, align: 'center' });

  addText(slide, '地理空间世界模型', 5.03, 1.70, 2.65, 0.34, { fontSize: 15, color: C.tealDark, bold: true, align: 'center' });
  addBox(slide, 5.00, 2.16, 7.62, 2.78, C.tealSoft, C.teal, 0.06, 1.0);
  addText(slide, 'P(Sₜ₊₁ | Sₜ, Aₜ, Cₜ, Gₜ)', 5.43, 2.43, 6.76, 0.50, { fontFace: 'Arial', fontSize: 24, color: C.tealDark, bold: true, align: 'center' });
  const labels = [
    ['Sₜ', '可更新的多尺度状态'],
    ['Aₜ', '结构化治理行动'],
    ['Cₜ', '天气 / 历史\n区域上下文'],
    ['Gₜ', '可变化的空间关系图']
  ];
  labels.forEach((d, i) => {
    const x = 5.32 + i * 1.78;
    addText(slide, d[0], x, 3.34, 0.55, 0.27, { fontFace: 'Arial', fontSize: 13, color: C.tealDark, bold: true, align: 'center' });
    addText(slide, d[1], x - 0.35, 3.69, 1.25, 0.54, { fontSize: 8.2, color: C.text, align: 'center', valign: 'top' });
  });
  addText(slide, '输出：未来状态 + 关系变化 + 风险 / 效用 + 不确定性', 5.38, 4.47, 6.92, 0.25, { fontSize: 10.2, color: C.ink, bold: true, align: 'center' });

  const questions = [
    ['状态写回', '每一步预测结果形成下一步可消费状态。'],
    ['关系重算', '道路、水系与功能联系随治理行动动态更新。'],
    ['递归规划', 'Planner 在预测的未来状态中重新评估行动。']
  ];
  questions.forEach((q, i) => {
    const x = 0.70 + i * 4.02;
    addText(slide, q[0], x, 5.48, 3.65, 0.31, { fontSize: 12.5, color: i === 0 ? C.tealDark : (i === 1 ? C.blue : C.green), bold: true, align: 'center' });
    addText(slide, q[1], x + 0.18, 5.90, 3.30, 0.62, { fontSize: 9.2, color: C.text, align: 'center', valign: 'top' });
  });
  addNote(slide,
    '世界模型的定义门槛不是使用了深度学习，而是行动进入转移、未来状态写回、关系重算并支持再规划。',
    [
      '策略模型直接学习动作选择；世界模型显式学习或维护环境转移。两者可以组合，但不能混为一谈。',
      '对自然资源而言，状态必须包含对象、场、关系、规则、证据和尺度信息。',
      '语言模型不能直接生成数值推演结论，数值结果必须由受约束的模拟器给出。'
    ],
    ['Sutton & Barto, Reinforcement Learning', 'Moerland et al., Model-based RL Survey', 'docs/research/GWM_RESEARCH_PRINCIPLES.md']
  );
}

function slideStateActionOutcomeDifference() {
  const slide = pptx.addSlide();
  addHeader(slide, 9, '数据逻辑', '状态—动作—结果：GWM 的训练数据契约', '与常规机器学习相比，差异集中在样本组织、预测目标、递归运行方式和验证协议。', '理论：state-space model / MDP / model-based RL；数据纪律：action-conditioned transition / temporal holdout / causal identification');

  addBox(slide, 0.58, 1.60, 5.72, 1.57, C.paper, C.line, 0.06, 0.8);
  addPill(slide, '常规监督学习 / 预测模型', 0.83, 1.82, 2.06, C.graySoft, C.text, C.line, 7.7);
  addText(slide, 'ŷ = fθ(x)', 0.92, 2.20, 1.82, 0.39, { fontFace: 'Arial', fontSize: 22, color: C.muted, bold: true, align: 'center' });
  addText(slide, '预测目标：在历史观测分布内，\n估计对象对应的标签、分数或数值。', 2.96, 1.96, 2.96, 0.73, { fontSize: 9.7, color: C.text, bold: true, align: 'center', valign: 'top' });
  addText(slide, '例：地块适宜性、违法风险、项目获批概率', 0.90, 2.78, 4.98, 0.20, { fontSize: 7.7, color: C.muted, align: 'center' });

  addBox(slide, 6.55, 1.60, 6.18, 1.57, C.tealSoft, C.teal, 0.06, 1.0);
  addPill(slide, 'GWM / TWM 转移模型', 6.82, 1.82, 1.85, C.paper, C.tealDark, C.paper, 7.7);
  addText(slide, 'Ŝₜ₊₁, Ŷₜ:ₜ₊H = Tθ(Sₜ, Aₜ, Eₜ)', 6.88, 2.20, 3.34, 0.39, { fontFace: 'Arial', fontSize: 16.5, color: C.tealDark, bold: true, align: 'center' });
  addText(slide, '预测目标：给定当前状态和可执行行动，\n估计下一状态及后续结果。', 10.18, 1.96, 2.17, 0.73, { fontSize: 9.5, color: C.ink, bold: true, align: 'center', valign: 'top' });
  addText(slide, '例：原案、缩减、移位分别改变哪些冲突、指标和后续可行动作', 6.93, 2.78, 5.31, 0.20, { fontSize: 7.6, color: C.tealDark, align: 'center' });

  const cols = [0.55, 2.10, 6.27];
  const widths = [1.55, 4.17, 6.48];
  const heads = [
    ['比较维度', C.dark, 'FFFFFF'],
    ['常规预测任务', C.graySoft, C.ink],
    ['世界模型任务', C.tealSoft, C.tealDark]
  ];
  heads.forEach((h, i) => {
    addBox(slide, cols[i], 3.45, widths[i], 0.42, h[1], i === 2 ? C.teal : (i === 0 ? C.dark : C.line), 0.02, 0.6);
    addText(slide, h[0], cols[i] + 0.06, 3.54, widths[i] - 0.12, 0.22, { fontSize: 8.4, color: h[2], bold: true, align: 'center' });
  });
  const rows = [
    ['样本单位', '相对独立的 (x, y)', '时间对齐的 (Sₜ, Aₜ, Eₜ, Sₜ₊₁ / Y) 转移事件'],
    ['动作角色', '可缺失，或只是普通特征', '是可选择、可约束、指向明确对象的控制变量'],
    ['学习目标', '预测标签、分数或单期数值', '预测状态增量、关系变化、滞后结果与不确定性'],
    ['上线用法', '一次打分、分类或排序', '状态写回 → 多步 rollout → 比较行动序列 → 再规划'],
    ['验证重点', '单步误差与分布内泛化', '时间 / 区域留出、多步漂移、动作消融、约束违反和离支持风险']
  ];
  rows.forEach((r, ri) => {
    const y = 3.87 + ri * 0.50;
    r.forEach((cell, ci) => {
      const fill = ci === 2 ? (ri % 2 === 0 ? 'EDF8F5' : C.tealSoft) : (ri % 2 === 0 ? C.paper : C.graySoft);
      addBox(slide, cols[ci], y, widths[ci], 0.50, fill, ci === 2 ? C.teal : C.line, 0, ci === 2 ? 0.65 : 0.4);
      addText(slide, cell, cols[ci] + 0.08, y + 0.09, widths[ci] - 0.16, 0.31, { fontFace: ri === 0 && ci > 0 ? 'Arial' : 'Hiragino Sans GB', fontSize: ci === 0 ? 7.9 : 7.5, color: ci === 2 ? C.tealDark : (ci === 0 ? C.ink : C.text), bold: ci === 0 || ci === 2, align: 'center', valign: 'top' });
    });
  });

  addBox(slide, 0.72, 6.53, 11.88, 0.37, C.goldSoft, C.gold, 0.04, 0.7);
  addText(slide, '因果适用边界：因果效应识别需进一步处理混杂、重叠性、同期行动、时间窗与负对照。', 0.94, 6.61, 11.44, 0.20, { fontSize: 8.5, color: C.ink, bold: true, align: 'center' });
  addNote(slide,
    '世界模型和常规机器学习都依赖统计拟合；区别是世界模型拟合一个可被行动条件化、可递归消费的转移系统。',
    [
      '如果只给模型状态和结果，却不记录期间采取了什么行动，模型只能学习不同治理策略混合后的平均变化。',
      '如果把 action 仅当普通特征，却没有对象、参数、实际发生时间和可行域，规划器无法生成或约束新的候选行动。',
      '世界模型的预测会写回成为下一步输入，因此单步误差可能累积；验证必须加入多步稳定性、动作消融和离支持检测。',
      '同一种神经网络既可用于普通预测也可用于世界模型；真正的差别是数据契约、训练目标、运行闭环和证据责任。',
      'action-conditioned prediction 不是自动的 causal effect。只有在处理混杂、行动重叠性、同期干预和时间窗之后，才能升级因果主张。'
    ],
    ['docs/reports/geospatial_world_model_state_action_outcome_data_discussion_2026-07-18.md', 'Sutton & Barto, Reinforcement Learning', 'Moerland et al., Model-based RL Survey', 'Pearl, Causality']
  );
}

function slideStateActionOutcomeDataContract() {
  const slide = pptx.addSlide();
  addHeader(slide, 10, '数据闭环', '省级试点的数据闭环：对象、行动与结果的时空对齐', '可信转移样本由同一对象、准确时间、实际行动、规则版本、前后观测和证据来源共同构成。', '来源：GWM 状态－动作－结果数据讨论；TWM production input requirements；intervention evidence certificate / geospatial kernel data compilation');

  addText(slide, '一条可训练 transition sample', 0.62, 1.54, 2.74, 0.27, { fontFace: 'Arial', fontSize: 11.5, color: C.ink, bold: true });
  const stages = [
    ['Sₜ  行动前状态', '对象 / 几何版本\n属性 / 关系 / 规则', C.blue, C.blueSoft],
    ['Aₜ  实际行动', '行动类型 / 目标对象\n参数 / 主体 / 发生时间', C.teal, C.tealSoft],
    ['Eₜ  外生条件', '天气 / 市场 / 上级政策\n同期其他项目与自然过程', C.gold, C.goldSoft],
    ['Sₜ₊₁ / Y  结果', '对象与关系变化\n业务结论 / 滞后成效 / 不确定性', C.green, C.greenSoft]
  ];
  const stageX = [0.57, 3.47, 6.37, 9.27];
  stages.forEach((s, i) => {
    addBox(slide, stageX[i], 1.93, 2.49, 1.18, s[3], s[2], 0.05, 0.8);
    addText(slide, s[0], stageX[i] + 0.14, 2.11, 2.21, 0.27, { fontFace: 'Arial', fontSize: 10.2, color: s[2], bold: true, align: 'center' });
    addText(slide, s[1], stageX[i] + 0.18, 2.50, 2.13, 0.43, { fontSize: 7.8, color: C.text, align: 'center', valign: 'top' });
    if (i < stages.length - 1) addFlowArrow(slide, stageX[i] + 2.58, 2.51, 0.22, C.muted);
  });
  addBox(slide, 0.80, 3.30, 11.75, 0.39, C.dark, C.dark, 0.04, 0);
  addText(slide, '关联主键：stable object ID  +  geometry version  +  event time  +  rule version  +  provenance', 1.07, 3.39, 11.20, 0.20, { fontFace: 'Arial', fontSize: 8.7, color: 'FFFFFF', bold: true, align: 'center' });

  addText(slide, '现有系统的数据映射', 0.64, 3.96, 3.08, 0.28, { fontSize: 13.0, color: C.ink, bold: true });
  const mappings = [
    ['一张图 / 调查监测 / 遥感', 'Sₜ 与 Sₜ₊₁：权威对象、几何、属性、关系'],
    ['审批 / 执法 / 整治 / 调度', 'Aₜ：行动类型、作用对象与实际执行时间'],
    ['气象 / 市场 / 同期项目', 'Eₜ：影响结果的外生环境与同期事件'],
    ['复核 / 验收 / 后续监测', 'Y：是否获批、是否整改、指标与滞后成效']
  ];
  mappings.forEach((m, i) => {
    const y = 4.37 + i * 0.48;
    addBox(slide, 0.62, y, 5.78, 0.41, i % 2 === 0 ? C.paper : C.graySoft, C.line, 0.02, 0.45);
    addText(slide, m[0], 0.78, y + 0.09, 2.17, 0.23, { fontSize: 7.8, color: C.tealDark, bold: true });
    addText(slide, m[1], 2.98, y + 0.07, 3.22, 0.27, { fontSize: 7.2, color: C.text, valign: 'top' });
  });

  addLine(slide, 6.66, 4.05, 0, 2.23, C.line, 0.8);
  addText(slide, '事件链数据支撑的四项能力', 7.00, 3.96, 5.56, 0.28, { fontSize: 13.0, color: C.ink, bold: true });
  const capabilities = [
    ['01', '行动敏感性', '区分“不行动、缩减、移位、整治”等条件下的不同转移'],
    ['02', '多步推演', '把 Sₜ₊₁ 写回，重算关系与可行动作，再预测下一步'],
    ['03', '方案比较', '在历史支持范围与硬约束内比较候选行动序列'],
    ['04', '审计校准', '追溯数据、行动、模型和规则版本，用真实结果回灌纠偏']
  ];
  capabilities.forEach((c, i) => {
    const x = 7.00 + (i % 2) * 2.83;
    const y = 4.39 + Math.floor(i / 2) * 0.91;
    addBox(slide, x, y, 2.58, 0.73, i === 3 ? C.greenSoft : C.tealSoft, i === 3 ? C.green : C.teal, 0.05, 0.7);
    addText(slide, c[0], x + 0.13, y + 0.10, 0.39, 0.22, { fontFace: 'Arial', fontSize: 8.4, color: i === 3 ? C.green : C.tealDark, bold: true, align: 'center' });
    addText(slide, c[1], x + 0.57, y + 0.09, 1.80, 0.23, { fontSize: 8.7, color: C.ink, bold: true });
    addText(slide, c[2], x + 0.18, y + 0.38, 2.22, 0.25, { fontSize: 6.5, color: C.text, align: 'center', valign: 'top' });
  });

  addBox(slide, 0.72, 6.48, 11.87, 0.42, C.redSoft, C.red, 0.04, 0.7);
  addText(slide, '数据准入规则：行动阶段统一编码为 planned / authorized / started / executed / completed / operational。', 0.93, 6.57, 11.46, 0.23, { fontFace: 'Arial', fontSize: 8.1, color: C.ink, bold: true, align: 'center' });
  addNote(slide,
    '自然资源部门通常不缺图层，真正稀缺的是能够按对象和时间连接起来的行动前后闭环。',
    [
      '基础测绘、调查监测和一张图主要提供 observation；世界模型还要统一对象身份、历史版本、关系和规则，形成可更新 state。',
      '审批、执法、整治和调度系统提供 action，但必须记录实际执行阶段，不能把规划、批准和真正发生混为一谈。',
      '结果既包括即时下一状态 Sₜ₊₁，也包括可能滞后的业务、资源与生态指标 Y；两者都要保留观测窗口和来源。',
      '外生条件 Eₜ 用于避免把降雨、市场变化、上级政策或同期项目的影响错误归给当前行动。',
      '首期试点无需汇聚全省所有数据，优先打通一条对象身份稳定、行动时间可靠、结果可复核的业务闭环。'
    ],
    ['docs/reports/geospatial_world_model_state_action_outcome_data_discussion_2026-07-18.md', 'docs/twm-production-input-data-requirements.md', 'data_agent/uwm/intervention_evidence_certificate_spec.yaml']
  );
}

function slide05() {
  const slide = pptx.addSlide();
  addHeader(slide, 11, '权威对标', 'GeoSOS-FLUS：土地利用模拟的权威对标基线', '同题实验检验当前效果，架构分析检验能力空间，两类证据共同界定 GWM 的阶段性位置。', '基线：Liu et al. 2017 FLUS；Li et al. 2011 GeoSOS；项目比较文档');

  addText(slide, 'GeoSOS-FLUS 的权威性', 0.65, 1.68, 3.36, 0.36, { fontSize: 15, color: C.ink, bold: true });
  const flusPoints = [
    '成熟的 CA / ANN 土地利用模拟路线',
    '自适应惯性与地类竞争机制',
    '长期用于城市增长与情景分配',
    '能够提供可复现的软件与论文基线'
  ];
  flusPoints.forEach((p, i) => addBullet(slide, p, 0.72, 2.20 + i * 0.61, 3.45, 0.43, { fontSize: 9.9, bulletColor: C.gold }));

  addLine(slide, 4.36, 1.78, 0, 4.60, C.line, 0.8);
  addText(slide, '两层对标框架', 4.73, 1.68, 3.50, 0.36, { fontSize: 15, color: C.ink, bold: true });
  addBox(slide, 4.70, 2.17, 3.52, 1.60, C.blueSoft, C.blue, 0.05, 0.8);
  addText(slide, 'A. 同题实证', 4.98, 2.39, 2.96, 0.28, { fontSize: 13.5, color: C.blue, bold: true, align: 'center' });
  addText(slide, '同一初始图 / 留出真值 / 评价掩膜\n比较 FoM、F1、OA、Kappa 等指标', 4.98, 2.79, 2.96, 0.62, { fontSize: 9.4, color: C.text, align: 'center', valign: 'top' });
  addBox(slide, 4.70, 4.02, 3.52, 1.60, C.tealSoft, C.teal, 0.05, 0.8);
  addText(slide, 'B. 架构上限', 4.98, 4.24, 2.96, 0.28, { fontSize: 13.5, color: C.tealDark, bold: true, align: 'center' });
  addText(slide, '状态 / 行动 / 转移 / 写回 / 不确定性\n证据门控 / 规划闭环 / 领域扩展', 4.98, 4.64, 2.96, 0.62, { fontSize: 9.4, color: C.text, align: 'center', valign: 'top' });

  addLine(slide, 8.55, 1.78, 0, 4.60, C.line, 0.8);
  addText(slide, 'Paper58：表征与分配的实验路径', 8.88, 1.68, 3.76, 0.36, { fontSize: 15, color: C.ink, bold: true });
  addBox(slide, 8.88, 2.18, 3.73, 2.47, C.paper, C.line, 0.05, 0.8);
  addText(slide, 'GeoFM / AlphaEarth 表征', 9.13, 2.43, 3.20, 0.30, { fontSize: 11.5, color: C.violet, bold: true, align: 'center' });
  addFlowArrow(slide, 10.50, 2.94, 0.48, C.violet);
  addText(slide, '潜在适宜性 + 历史转移先验', 9.13, 3.10, 3.20, 0.30, { fontSize: 11.2, color: C.ink, bold: true, align: 'center' });
  addFlowArrow(slide, 10.50, 3.61, 0.48, C.violet);
  addText(slide, '需求约束的空间分配', 9.13, 3.78, 3.20, 0.30, { fontSize: 11.2, color: C.ink, bold: true, align: 'center' });
  addText(slide, '作用：验证 latent representation + allocation 能否挑战官方 FLUS console 基线', 9.18, 4.22, 3.10, 0.28, { fontSize: 8.0, color: C.muted, align: 'center' });

  addBox(slide, 0.68, 6.12, 11.93, 0.55, C.goldSoft, C.gold, 0.05, 0.7);
  addText(slide, '协议要求：固定数据来源、时间切分与评价目标，并分别报告不同内部特征和机制的实验结果。', 0.91, 6.23, 11.47, 0.25, { fontSize: 9.5, color: C.ink, bold: true, align: 'center' });
  addNote(slide,
    'GeoSOS-FLUS 是传统土地利用模拟中的强基线，选择它可以避免只和弱启发式方法比较。',
    [
      'FLUS 的强项是给定需求、驱动和邻域规则后的多地类分配。',
      'Paper58 不是 GWM 全部，而是尝试把地理基础表征、潜在适宜性和需求约束分配组合起来。',
      '同题实验回答当前效果；架构比较回答能力空间。两者缺一不可。'
    ],
    ['docs/twm-vs-geosos-flus-comparison.md', 'docs/twm-vs-geosos-flus-academic-positioning.md', PAPER58_REPORT]
  );
}

function slide06() {
  const slide = pptx.addSlide();
  addHeader(slide, 12, '阶段性实证', '阶段性实证：变化识别优势与整体一致性差距', 'Paper58 与 TWM 100-case 采用不同协议，均显示变化识别潜力，同时暴露空间误报和整体地图保持问题。', '来源：twm-geosos-flus-superiority-analysis-2026-07-02；Paper58 FLUS comparison report');

  addText(slide, 'TWM vs 固定 FLUS-console：100-case strict', 0.66, 1.60, 5.68, 0.31, { fontSize: 13.8, color: C.ink, bold: true });
  addText(slide, '横轴为 TWM - FLUS；右侧更好，左侧更差', 0.66, 1.94, 5.68, 0.20, { fontSize: 7.8, color: C.muted });
  const metrics = [
    ['Change F1', 0.070240, '0.325', '0.254'],
    ['Change FoM', 0.044707, '0.196', '0.151'],
    ['Overall Accuracy', -0.017399, '0.901', '0.918'],
    ['Kappa', -0.039776, '0.771', '0.810'],
    ['Macro-F1', -0.020851, '0.485', '0.506']
  ];
  const zeroX = 3.45;
  addLine(slide, zeroX, 2.30, 0, 2.63, C.muted, 1.0, undefined, undefined, 'dash');
  addText(slide, '-0.08', 1.94, 5.00, 0.45, 0.16, { fontFace: 'Arial', fontSize: 6.7, color: C.muted, align: 'center' });
  addText(slide, '0', zeroX - 0.12, 5.00, 0.24, 0.16, { fontFace: 'Arial', fontSize: 6.7, color: C.muted, align: 'center' });
  addText(slide, '+0.08', 4.85, 5.00, 0.55, 0.16, { fontFace: 'Arial', fontSize: 6.7, color: C.muted, align: 'center' });
  metrics.forEach((m, i) => {
    const y = 2.36 + i * 0.50;
    addText(slide, m[0], 0.72, y, 1.45, 0.24, { fontSize: 8.6, color: C.text, bold: true });
    const len = Math.abs(m[1]) / 0.08 * 1.45;
    const x = m[1] >= 0 ? zeroX : zeroX - len;
    slide.addShape(S.rect, { x, y: y + 0.035, w: len, h: 0.18, fill: { color: m[1] >= 0 ? C.teal : C.red }, line: { color: m[1] >= 0 ? C.teal : C.red, width: 0 } });
    addText(slide, `${m[1] >= 0 ? '+' : ''}${m[1].toFixed(3)}`, m[1] >= 0 ? x + len + 0.05 : x - 0.58, y, 0.54, 0.24, { fontFace: 'Arial', fontSize: 7.4, color: m[1] >= 0 ? C.tealDark : C.red, bold: true, align: m[1] >= 0 ? 'left' : 'right' });
    addText(slide, `TWM ${m[2]}  |  FLUS ${m[3]}`, 4.96, y, 1.27, 0.24, { fontFace: 'Arial', fontSize: 6.6, color: C.muted, align: 'right' });
  });

  addLine(slide, 6.58, 1.67, 0, 3.73, C.line, 0.8);
  addText(slide, 'Paper58-LAS：7 区域 LOAO 候选选择审计', 6.92, 1.60, 5.67, 0.31, { fontSize: 13.8, color: C.ink, bold: true });
  const stats = [
    ['+0.1657', 'F1 平均优势'],
    ['+0.0744', 'FoM 平均优势'],
    ['6 / 7', '区域优于官方 FLUS console'],
    ['仍为负', 'allocation disagreement']
  ];
  stats.forEach((st, i) => {
    const x = 6.93 + (i % 2) * 2.78;
    const y = 2.24 + Math.floor(i / 2) * 1.18;
    addText(slide, st[0], x, y, 2.36, 0.43, { fontFace: 'Arial', fontSize: 23, color: i === 3 ? C.red : C.violet, bold: true, align: 'center' });
    addText(slide, st[1], x, y + 0.48, 2.36, 0.28, { fontSize: 8.7, color: C.text, bold: true, align: 'center' });
  });
  addBox(slide, 6.93, 4.73, 5.46, 0.48, C.redSoft, C.red, 0.04, 0.6);
  addText(slide, '后续验证项：GeoSOS-FLUS 原生工作流、更稳健需求模型、zero-local-data 验证', 7.11, 4.83, 5.10, 0.23, { fontSize: 8.3, color: C.red, bold: true, align: 'center' });

  if (fs.existsSync(MAP_STRIP)) {
    slide.addImage({ path: MAP_STRIP, x: 0.72, y: 5.50, w: 11.88, h: 1.27 });
  }
  addText(slide, '图：单案例定性对比，仅用于说明“整体保持”与“变化命中”之间的权衡；不与上方聚合结果混算。', 2.48, 6.82, 8.45, 0.17, { fontSize: 6.3, color: C.muted, align: 'center' });
  addNote(slide,
    '当前最稳妥的实证结论是：变化发生位置的识别更强，但整体地图一致性仍落后。',
    [
      '100-case strict 中 TWM 的 Change F1 与 FoM 高于固定 FLUS-console baseline。',
      'OA、Kappa、Macro-F1 仍较低，说明模型对变化更敏感，也产生了更多误报。',
      'Paper58 的 7 区域 LOAO 结果显示 latent suitability + allocation 有潜力，但仍不能升级为正式全面超越。',
      '两个协议的数据、任务和候选选择方式不同，不能把优势数字相加。'
    ],
    ['docs/twm-geosos-flus-superiority-analysis-2026-07-02.md', PAPER58_REPORT]
  );
}

function slide07() {
  const slide = pptx.addSlide();
  addHeader(slide, 13, '能力边界', 'GWM 能力边界更宽，工程成熟度仍处于验证阶段', 'GWM 扩展了状态、行动、递归推演和审计闭环；GeoSOS-FLUS 在经典土地利用模拟任务上仍具有成熟优势。', '来源：TWM vs GeoSOS-FLUS academic positioning；GWM Runtime / Kernel relationship');

  const rows = [
    ['建模对象', '土地利用类型与栅格分配', '多尺度对象 / 场 / 关系 / 规则 / 证据状态'],
    ['动作语义', '需求、情景、约束进入模拟', '规范化行动是状态转移的一等条件'],
    ['空间机制', 'ANN 适宜性 + CA 邻域 + 竞争惯性', '行动条件关系门控 + 时滞 + 动态拓扑'],
    ['时间机制', '面向目标期的格局模拟', '递归写回、多步 rollout、误差与不确定性传播'],
    ['决策闭环', '模拟可与优化算法耦合', 'Planner 强制消费未来状态与 simulator trace'],
    ['治理边界', '主要依赖情景与模型校准', '规则、因果校准、证据门控、人工复核、审计'],
    ['领域扩展', '土地利用模拟与空间优化见长', '通过 Domain Adapter 扩展土地 / 城市 / 水文等领域'],
    ['当前成熟度', '成熟经典模型与软件', '研究原型；共享 Runtime 未完全抽取，核心假设仍待验证']
  ];
  const x0 = 0.55, y0 = 1.65;
  addBox(slide, x0, y0, 2.00, 0.46, C.dark, C.dark, 0.02, 0);
  addBox(slide, x0 + 2.00, y0, 4.12, 0.46, C.goldSoft, C.gold, 0.02, 0.7);
  addBox(slide, x0 + 6.12, y0, 6.14, 0.46, C.tealSoft, C.teal, 0.02, 0.7);
  addText(slide, '比较维度', x0, y0 + 0.08, 2.00, 0.25, { fontSize: 9.6, color: 'FFFFFF', bold: true, align: 'center' });
  addText(slide, 'GeoSOS-FLUS', x0 + 2.00, y0 + 0.08, 4.12, 0.25, { fontSize: 10, color: C.gold, bold: true, align: 'center' });
  addText(slide, 'GWM / TWM 目标架构', x0 + 6.12, y0 + 0.08, 6.14, 0.25, { fontSize: 10, color: C.tealDark, bold: true, align: 'center' });
  rows.forEach((r, i) => {
    const y = y0 + 0.46 + i * 0.57;
    const fill = i % 2 === 0 ? C.paper : C.graySoft;
    addBox(slide, x0, y, 2.00, 0.57, fill, C.line, 0, 0.5);
    addBox(slide, x0 + 2.00, y, 4.12, 0.57, fill, C.line, 0, 0.5);
    addBox(slide, x0 + 6.12, y, 6.14, 0.57, fill, C.line, 0, 0.5);
    addText(slide, r[0], x0 + 0.11, y + 0.08, 1.78, 0.34, { fontSize: 8.8, color: C.ink, bold: true, align: 'center' });
    addText(slide, r[1], x0 + 2.15, y + 0.07, 3.82, 0.39, { fontSize: 8.2, color: C.text, align: 'center' });
    addText(slide, r[2], x0 + 6.28, y + 0.07, 5.82, 0.39, { fontSize: 8.2, color: C.text, align: 'center' });
  });
  addBox(slide, 0.72, 6.58, 11.89, 0.34, C.dark, C.dark, 0.04, 0);
  addText(slide, '目标架构：以 FLUS 作为土地利用模拟强基线，构建跨任务的“状态-行动-转移-规划-证据”公共内核。', 0.93, 6.66, 11.47, 0.17, { fontSize: 9.2, color: 'FFFFFF', bold: true, align: 'center' });
  addNote(slide,
    'GWM 相对 FLUS 的优势首先是问题定义和架构能力空间，而不是当前生产成熟度。',
    [
      'FLUS 在土地利用 CA 模拟、需求分配和软件成熟度上仍是强基线。',
      'GWM 把行动、动态关系、状态写回、不确定性和证据门控放进统一运行语义。',
      '因此，GWM 可以容纳 FLUS 作为某一类 transition backend 或 baseline，而不应简单宣称替代。'
    ],
    ['docs/twm-vs-geosos-flus-academic-positioning.md', 'docs/research/GWM_RUNTIME_KERNEL_AND_GEOSPATIAL_KERNEL_RELATIONSHIP.md']
  );
}

function slide08() {
  const slide = pptx.addSlide();
  addHeader(slide, 14, 'GWM 总体架构', 'GWM 总体架构：运行内核、空间动力学内核与领域实例', '可信状态、转移计算、递归运行、证据边界和领域适配共同构成 GWM 的研究与运行体系。', '来源：GWM Runtime / Geospatial Kernel Relationship；Geospatial Kernel core architecture report');

  const layers = [
    ['权威数据与 GIS 底座', ['一张图 / 调查监测', '遥感 / IoT / 文书', 'CRS / 拓扑 / 版本 / 谱系'], C.graySoft, C.text],
    ['GWM Runtime Kernel', ['StateSnapshot', 'CanonicalAction / Transition', '写回 / Rollout / UQ / Evidence Ledger'], C.blueSoft, C.blue],
    ['Geospatial Kernel', ['DAM-GK', '关系门控 / 时滞 / 软拓扑', '概率转移 / 多尺度一致性'], C.tealSoft, C.tealDark],
    ['领域适配与任务', ['TWM 自然资源', 'UWM 城市系统', 'HydroControl 水文验证'], C.greenSoft, C.green],
    ['业务消费', ['Simulator / Planner', '风险预警 / 方案比选', '人工复核 / GIS 回写 / 审计'], C.goldSoft, C.gold]
  ];
  layers.forEach((l, i) => {
    const y = 1.62 + i * 0.98;
    addBox(slide, 0.72, y, 2.20, 0.72, l[3], l[3], 0.05, 0);
    addText(slide, l[0], 0.85, y + 0.18, 1.94, 0.34, { fontSize: 10.8, color: 'FFFFFF', bold: true, align: 'center' });
    l[1].forEach((cell, j) => {
      const x = 3.20 + j * 3.05;
      addBox(slide, x, y, 2.73, 0.72, l[2], l[3], 0.05, 0.7);
      addText(slide, cell, x + 0.14, y + 0.13, 2.45, 0.42, { fontSize: 9.0, color: C.ink, bold: j === 0, align: 'center' });
    });
    if (i < layers.length - 1) {
      addLine(slide, 6.65, y + 0.74, 0, 0.22, C.muted, 1.3, undefined, 'triangle');
    }
  });
  addText(slide, '架构关系', 10.72, 2.36, 1.72, 0.22, { fontSize: 7.4, color: C.red, bold: true, align: 'center' });
  addLine(slide, 11.57, 2.64, 0, 1.46, C.red, 1.4, undefined, 'triangle', 'dash');
  addText(slide, 'Runtime：可靠运行与审计\nKernel：空间状态转移', 10.48, 4.26, 2.18, 0.50, { fontSize: 8.6, color: C.red, bold: true, align: 'center', valign: 'top' });
  addNote(slide,
    'GWM 的系统边界由 Runtime 和 Geospatial Kernel 共同构成，二者缺一不可。',
    [
      'Runtime 统一状态版本、动作契约、转移来源、状态写回、不确定性和证据账本。',
      'Geospatial Kernel 学习空间关系在当前状态和行动下如何生效、传播和改变。',
      'TWM、UWM、HydroControl 是领域绑定或验证轨道，不与 GWM 并列。',
      '当前共享 Runtime Kernel 尚未完成平台级抽取，这是后续工程化的重要工作。'
    ],
    ['docs/research/GWM_RUNTIME_KERNEL_AND_GEOSPATIAL_KERNEL_RELATIONSHIP.md', 'docs/reports/gwm_geospatial_kernel_core_architecture_design_theory_and_gis_relationship_2026-07-20.md']
  );
}

function slide09() {
  const slide = pptx.addSlide();
  addHeader(slide, 15, 'DAM Geospatial Kernel', 'DAM-GK：行动条件、多尺度、动态空间转移内核', 'Dynamic Action-conditioned Multi-scale 在动态空间图上建模行动、时滞、传播和拓扑变化。', '正式定义：docs/research/DAM_GK_RESEARCH_SPEC.md');

  addBox(slide, 0.66, 1.72, 3.04, 3.35, C.paper, C.line, 0.06, 0.8);
  addText(slide, '输入世界状态', 0.93, 1.98, 2.50, 0.30, { fontSize: 13.5, color: C.ink, bold: true, align: 'center' });
  const inputs = [
    ['Gₜ', '多关系空间图'],
    ['Sₜ', '节点 / 场当前状态'],
    ['Aₜ', '行动类型 / 目标 / 强度'],
    ['Cₜ', '时间 / forcing / 区域上下文'],
    ['Eₜ', 'Gₜ 内边属性：距离 / 方向 / 地形 / 尺度']
  ];
  inputs.forEach((d, i) => {
    const y = 2.50 + i * 0.47;
    addText(slide, d[0], 0.98, y, 0.54, 0.25, { fontFace: 'Arial', fontSize: 12, color: C.blue, bold: true, align: 'center' });
    addText(slide, d[1], 1.63, y, 1.70, 0.25, { fontSize: 8.8, color: C.text });
  });

  addFlowArrow(slide, 3.93, 3.29, 0.72, C.teal);
  addBox(slide, 4.92, 1.72, 3.55, 3.35, C.tealSoft, C.teal, 0.06, 1.2);
  addText(slide, 'DAM-GK', 5.51, 1.98, 2.38, 0.40, { fontFace: 'Arial', fontSize: 24, color: C.tealDark, bold: true, align: 'center' });
  const mechanisms = [
    '行动条件关系门控',
    '多关系消息传播',
    '可学习的时间滞后',
    '状态条件软拓扑重写',
    '概率状态转移与异方差 UQ',
    '细-粗尺度一致性约束'
  ];
  mechanisms.forEach((m, i) => addPill(slide, m, 5.20 + (i % 2) * 1.53, 2.62 + Math.floor(i / 2) * 0.60, 1.37, i % 2 === 0 ? C.paper : C.greenSoft, C.ink, i % 2 === 0 ? C.teal : C.green, 7.0));
  addText(slide, 'Kθ(Gₜ,Sₜ,Aₜ,Cₜ) → (Φₜ:ₜ₊H, ΔGₜ:ₜ₊H, Uₜ:ₜ₊H)', 5.04, 4.55, 3.30, 0.27, { fontFace: 'Arial', fontSize: 9.5, color: C.tealDark, bold: true, align: 'center' });

  addFlowArrow(slide, 8.71, 3.29, 0.72, C.teal);
  addBox(slide, 9.70, 1.72, 2.97, 3.35, C.paper, C.line, 0.06, 0.8);
  addText(slide, '输出与递归', 10.00, 1.98, 2.36, 0.30, { fontSize: 13.5, color: C.ink, bold: true, align: 'center' });
  const outputs = [
    ['Φ', '有效关系 / 延迟传播'],
    ['ΔG', '关系 / 拓扑变化'],
    ['U', '预测不确定性'],
    ['Sₜ₊₁', '由 Runtime 转移头形成']
  ];
  outputs.forEach((d, i) => {
    const y = 2.55 + i * 0.55;
    addText(slide, d[0], 10.00, y, 0.62, 0.27, { fontFace: 'Arial', fontSize: 13, color: C.green, bold: true, align: 'center' });
    addText(slide, d[1], 10.74, y, 1.48, 0.27, { fontSize: 8.7, color: C.text });
  });
  addBox(slide, 10.04, 4.58, 2.30, 0.31, C.greenSoft, C.green, 0.04, 0.6);
  addText(slide, '写回 → 重算关系 → 下一步', 10.12, 4.64, 2.14, 0.16, { fontSize: 7.8, color: C.green, bold: true, align: 'center' });

  addText(slide, '机制有效性验证', 0.78, 5.48, 2.26, 0.28, { fontSize: 12.7, color: C.ink, bold: true });
  const ctrls = ['动作打乱', '时间打乱', '关系类型打乱', '空间重连', '固定拓扑', '禁止写回'];
  ctrls.forEach((t, i) => addPill(slide, t, 3.16 + i * 1.49, 5.43, 1.26, C.redSoft, C.red, C.redSoft, 7.5));
  addText(slide, '验证标准：关键机制消融后，应观察到稳定、可复现的性能或校准退化。', 1.63, 6.22, 10.20, 0.34, { fontSize: 10.2, color: C.red, bold: true, align: 'center' });
  addNote(slide,
    'DAM-GK 的研究命题是学习行动条件化、带时滞、可重写拓扑的多尺度空间转移；下方公式是正式接口定义，不是已被证实的具体网络形式。',
    [
      'Dynamic：关系与拓扑随状态和行动变化。',
      'Action-conditioned：同一状态下，不同行动应产生不同的有效边与未来状态。',
      'Multi-scale：细尺度预测与粗尺度状态必须通过显式聚合关系保持一致。',
      'E_t 是 G_t 中的边属性；正式 Kernel 接口输出 Phi、Delta G 与 U，Runtime 再结合转移头形成并写回下一状态。',
      '它必须接受负对照和消融；普通 GNN、缓冲区或固定邻接只能作为组件或基线。'
    ],
    ['docs/research/DAM_GK_RESEARCH_SPEC.md', 'docs/reports/gwm_geospatial_kernel_core_architecture_design_theory_and_gis_relationship_2026-07-20.md']
  );
}

function slide10() {
  const slide = pptx.addSlide();
  addHeader(slide, 16, 'GWM Runtime Kernel', 'GWM Runtime：统一世界模型运行与审计生命周期', 'Runtime 统一状态、行动、转移来源、状态写回、不确定性、证据和复演语义。', '来源：GWM_RUNTIME_KERNEL_AND_GEOSPATIAL_KERNEL_RELATIONSHIP.md');

  const steps = [
    ['01', 'StateSnapshot', '版本化多尺度状态\n对象 / 场 / 图 / 质量'],
    ['02', 'CanonicalAction', '动作类型 / 目标 / 强度\n可行域 / 业务语义'],
    ['03', 'Transition Source', 'DAM-GK / 规则 / 物理\n模型版本 / 数据谱系'],
    ['04', 'Write-back & Rollout', '状态写回 / 关系重算\n多步误差与 UQ 传播'],
    ['05', 'EvidenceClaimLedger', '证据等级 / 主张降级\n审计 / 回滚 / 复演']
  ];
  steps.forEach((st, i) => {
    const x = 0.60 + i * 2.54;
    addText(slide, st[0], x + 0.80, 1.62, 0.48, 0.26, { fontFace: 'Arial', fontSize: 10, color: C.teal, bold: true, align: 'center' });
    addCircle(slide, x + 0.88, 1.98, 0.34, C.teal, C.teal, 0);
    if (i < steps.length - 1) addLine(slide, x + 1.20, 2.15, 2.18, 0, C.teal, 1.5, undefined, 'triangle');
    addBox(slide, x, 2.56, 2.18, 1.55, i === 2 ? C.tealSoft : C.paper, i === 2 ? C.teal : C.line, 0.05, i === 2 ? 1.2 : 0.7);
    addText(slide, st[1], x + 0.13, 2.78, 1.92, 0.30, { fontFace: 'Arial', fontSize: 11, color: i === 2 ? C.tealDark : C.ink, bold: true, align: 'center' });
    addText(slide, st[2], x + 0.17, 3.22, 1.84, 0.62, { fontSize: 8.5, color: C.text, align: 'center', valign: 'top' });
  });

  addText(slide, '平台级共享边界', 0.69, 4.67, 2.15, 0.30, { fontSize: 13.4, color: C.ink, bold: true });
  const shared = ['统一状态 / 动作 / 转移契约', '不确定性与证据边界', 'TWM / UWM adapters', 'Simulator / Planner 接口'];
  shared.forEach((p, i) => addPill(slide, p, 3.02 + i * 2.31, 4.62, 2.08, i % 2 === 0 ? C.blueSoft : C.greenSoft, i % 2 === 0 ? C.blue : C.green, i % 2 === 0 ? C.blueSoft : C.greenSoft, 7.8));
  addBox(slide, 0.69, 5.61, 11.93, 0.83, C.goldSoft, C.gold, 0.05, 0.7);
  addText(slide, '当前工程状态', 0.93, 5.84, 1.42, 0.26, { fontSize: 11.4, color: C.gold, bold: true });
  addText(slide, 'GWM 研究范式、领域实例和局部 Kernel 证据已存在；共享 GWM Runtime Kernel 尚未完成平台级抽取。', 2.50, 5.78, 9.77, 0.38, { fontSize: 10.2, color: C.ink, bold: true, align: 'center' });
  addNote(slide,
    'Runtime Kernel 的价值是把模型调用变成有状态、有版本、有证据的运行生命周期。',
    [
      '一次模型推理不等于世界模型运行；必须记录输入状态、动作、转移来源、模型版本和输出谱系。',
      '多步推演必须真实写回状态，并传播不确定性和误差。',
      'EvidenceClaimLedger 使系统能够在证据不足时自动降级主张，而不是照常输出高置信结论。',
      '当前项目最需要补齐的是共享 Runtime 的抽取和跨领域契约稳定性。'
    ],
    ['docs/research/GWM_RUNTIME_KERNEL_AND_GEOSPATIAL_KERNEL_RELATIONSHIP.md', 'docs/research/GWM_RESEARCH_PRINCIPLES.md']
  );
}

function slide11() {
  const slide = pptx.addSlide();
  addHeader(slide, 17, '计算世界', 'GWM Simulator：组合转移、状态写回与递归推演', '任务相关世界被表达为有限状态，Transition Router 组合确定性、规则型和可学习转移，并持续写回状态。', '来源：twm_computational_world_state_simulation_mechanism_2026-07-21.md；GWM Runtime / Geospatial Kernel relationship');

  const chain = [
    ['现实世界', '图层 / 业务表 / 文书\n遥感 / 规则 / 人工证据', C.graySoft, C.text],
    ['状态 Sₜ', '对象 + 关系 + 规则\n证据 + 质量 + 版本', C.blueSoft, C.blue],
    ['动作 Aₜ', '保护 / 调整 / 审批\n补正 / 修复 / 管控', C.goldSoft, C.gold],
    ['组合转移 F', 'GIS / 规则 / 机理\nKernel / 残差 / UQ', C.tealSoft, C.tealDark],
    ['未来 Sₜ₊₁', '状态写回 / 关系重算\n风险 + 效用 + 证据门', C.greenSoft, C.green]
  ];
  chain.forEach((st, i) => {
    const x = 0.55 + i * 2.55;
    addBox(slide, x, 2.05, 2.06, 1.42, st[2], st[3], 0.06, 0.8);
    addText(slide, st[0], x + 0.14, 2.27, 1.78, 0.32, { fontSize: 12.5, color: st[3], bold: true, align: 'center' });
    addText(slide, st[1], x + 0.16, 2.77, 1.74, 0.50, { fontSize: 8.5, color: C.text, align: 'center', valign: 'top' });
    if (i < chain.length - 1) addFlowArrow(slide, x + 2.12, 2.76, 0.32, C.teal);
  });

  addText(slide, '递归推演', 0.71, 4.05, 1.63, 0.30, { fontSize: 13.2, color: C.ink, bold: true });
  addText(slide, 'Sₜ', 2.60, 4.04, 0.54, 0.31, { fontFace: 'Arial', fontSize: 17, color: C.blue, bold: true, align: 'center' });
  addFlowArrow(slide, 3.22, 4.18, 0.72, C.teal);
  addPill(slide, 'Aₜ', 4.06, 4.04, 0.76, C.goldSoft, C.gold, C.gold, 9.3);
  addFlowArrow(slide, 4.97, 4.18, 0.72, C.teal);
  addText(slide, 'Ŝₜ₊₁', 5.79, 4.04, 0.78, 0.31, { fontFace: 'Arial', fontSize: 17, color: C.green, bold: true, align: 'center' });
  addFlowArrow(slide, 6.72, 4.18, 0.72, C.teal);
  addPill(slide, 'Aₜ₊₁', 7.56, 4.04, 0.90, C.goldSoft, C.gold, C.gold, 9.3);
  addFlowArrow(slide, 8.62, 4.18, 0.72, C.teal);
  addText(slide, 'Ŝₜ₊₂ … Ŝₜ₊H', 9.46, 4.04, 1.56, 0.31, { fontFace: 'Arial', fontSize: 17, color: C.green, bold: true, align: 'center' });
  addLine(slide, 10.90, 4.50, -8.02, 0.79, C.violet, 1.2, undefined, 'triangle', 'dash');
  addText(slide, '状态写回并重新计算关系', 4.88, 5.17, 3.50, 0.24, { fontSize: 8.5, color: C.violet, bold: true, align: 'center' });

  addBox(slide, 0.70, 5.68, 5.72, 0.83, C.paper, C.line, 0.05, 0.7);
  addText(slide, '基准轨迹', 0.95, 5.88, 1.17, 0.25, { fontSize: 11.2, color: C.muted, bold: true });
  addText(slide, '不干预 → S₁ → S₂ → S₃', 2.16, 5.86, 3.88, 0.28, { fontFace: 'Arial', fontSize: 12, color: C.text, bold: true, align: 'center' });
  addBox(slide, 6.65, 5.68, 5.98, 0.83, C.tealSoft, C.teal, 0.05, 0.7);
  addText(slide, '干预轨迹', 6.92, 5.88, 1.17, 0.25, { fontSize: 11.2, color: C.tealDark, bold: true });
  addText(slide, '保护 / 调整 → S₁′ → S₂′ → S₃′', 8.10, 5.86, 4.18, 0.28, { fontFace: 'Arial', fontSize: 12, color: C.tealDark, bold: true, align: 'center' });
  addText(slide, '比较累计风险、效用、可行性、证据完整性与不确定性', 3.02, 6.69, 7.30, 0.20, { fontSize: 8.7, color: C.ink, bold: true, align: 'center' });
  addNote(slide,
    'GWM Simulator 是 Runtime 管理的组合式状态转移接口，不等同于 DAM-GK，也不是一个端到端生成模型。',
    [
      'StateBuilder 把地块、项目、控制线、审批、规则和证据组织成版本化状态。',
      '行动被编码为类型、目标、空间范围、强度、政策意图和执行约束。',
      'Transition Router 按变量调用 GIS 确定性计算、版本化规则、专业机理模型、Geospatial Kernel 或残差校准，并保留来源 trace。',
      '预测状态真实写回，随后重新计算对象关系、规则命中、可行动作和不确定性，形成递归 rollout。',
      '反事实 rollout 比较基准与干预轨迹，但它是模型条件下的模拟，不自动等于因果识别。'
    ],
    ['docs/reports/twm_computational_world_state_simulation_mechanism_2026-07-21.md', 'data_agent/territory_world_model/state_builder.py', 'data_agent/territory_world_model/planner.py']
  );
}

function slideSimulatorComparison() {
  const slide = pptx.addSlide();
  addHeader(slide, 18, 'Simulator 对比', 'GWM Simulator：组合式状态转移与可追溯写回', '其差异体现在状态对象、行动接口、空间关系重算、递归消费和证据审计五个方面。', '来源：GWM Runtime / Geospatial Kernel relationship；TWM simulator technical core；world-model landscape references');

  addBox(slide, 0.55, 1.61, 2.11, 1.41, C.blueSoft, C.blue, 0.05, 0.8);
  addText(slide, '输入契约', 0.76, 1.82, 1.69, 0.28, { fontSize: 12.4, color: C.blue, bold: true, align: 'center' });
  addText(slide, 'StateSnapshot + Action\nContext + Spatial Graph\n规则版本 + 证据等级', 0.78, 2.20, 1.65, 0.58, { fontFace: 'Arial', fontSize: 7.9, color: C.text, align: 'center', valign: 'top' });
  addFlowArrow(slide, 2.76, 2.32, 0.28, C.teal);

  addBox(slide, 3.16, 1.61, 2.08, 1.41, C.tealSoft, C.teal, 0.05, 0.9);
  addText(slide, 'Transition Router', 3.37, 1.82, 1.66, 0.28, { fontFace: 'Arial', fontSize: 12.0, color: C.tealDark, bold: true, align: 'center' });
  addText(slide, '按对象、变量、证据等级\n选择转移来源并记录 trace', 3.44, 2.22, 1.51, 0.52, { fontSize: 8.0, color: C.text, align: 'center', valign: 'top' });
  addFlowArrow(slide, 5.34, 2.32, 0.28, C.teal);

  addBox(slide, 5.74, 1.61, 4.27, 1.41, C.paper, C.line, 0.05, 0.8);
  addText(slide, '组合转移来源', 5.98, 1.76, 3.78, 0.25, { fontSize: 11.2, color: C.ink, bold: true, align: 'center' });
  const sources = [
    ['GIS 确定性', C.blueSoft, C.blue],
    ['规则 / Action Mask', C.goldSoft, C.gold],
    ['专业机理模型', C.greenSoft, C.green],
    ['DAM-GK / Learned', C.tealSoft, C.tealDark],
    ['残差校准 / Unknown Gate', C.redSoft, C.red]
  ];
  sources.forEach((s, i) => {
    const x = i < 3 ? 5.97 + i * 1.25 : 6.58 + (i - 3) * 1.53;
    const y = i < 3 ? 2.13 : 2.54;
    addPill(slide, s[0], x, y, i < 3 ? 1.10 : 1.39, s[1], s[2], s[1], i < 3 ? 6.3 : 6.1);
  });
  addFlowArrow(slide, 10.10, 2.32, 0.28, C.teal);

  addBox(slide, 10.50, 1.61, 2.28, 1.41, C.greenSoft, C.green, 0.05, 0.8);
  addText(slide, '输出与写回', 10.72, 1.82, 1.84, 0.28, { fontSize: 12.4, color: C.green, bold: true, align: 'center' });
  addText(slide, 'State / Graph Delta\nRisk / Utility / UQ\nTrace → 写回 → 重算', 10.77, 2.20, 1.74, 0.58, { fontFace: 'Arial', fontSize: 7.8, color: C.text, align: 'center', valign: 'top' });

  addText(slide, '与其他 Simulator 的直接差异', 0.64, 3.37, 3.32, 0.29, { fontSize: 13.2, color: C.ink, bold: true });
  const families = [
    ['视觉 / 机器人 WM', C.violet, C.violetSoft, [
      ['状态', '像素、latent frame、局部物体或 3D 状态'],
      ['行动', '控制量、运动指令或弱条件'],
      ['输出', '下一帧、轨迹、控制价值'],
      ['验证', '视觉一致性、控制成功率、物理安全']
    ]],
    ['科学模拟 / 数字孪生', C.blue, C.blueSoft, [
      ['状态', '连续物理场、设备状态、方程域'],
      ['行动', 'forcing、边界条件或操作参数'],
      ['输出', '未来场、风险场、设备响应'],
      ['验证', '守恒、方程误差、传感器回放']
    ]],
    ['GeoSOS-FLUS', C.gold, C.goldSoft, [
      ['状态', '土地利用栅格与驱动因子'],
      ['行动', '情景需求、转换规则和数量约束'],
      ['输出', '未来土地利用格局'],
      ['验证', 'OA、Kappa、FoM、变化识别']
    ]],
    ['GWM Simulator', C.teal, C.tealSoft, [
      ['状态', '对象 + 场 + 关系 + 规则 + 证据'],
      ['行动', '指向具体对象的治理行动与可行域'],
      ['输出', 'GIS 状态、风险、效用、UQ 与 trace'],
      ['验证', '留出 + 消融 + 负对照 + 证据主张门']
    ]]
  ];
  families.forEach((family, i) => {
    const x = 0.56 + i * 3.13;
    addBox(slide, x, 3.78, 2.83, 2.36, C.paper, family[1], 0.05, i === 3 ? 1.1 : 0.75);
    addBox(slide, x, 3.78, 2.83, 0.43, family[2], family[1], 0.05, 0.7);
    addText(slide, family[0], x + 0.13, 3.88, 2.57, 0.23, { fontSize: 9.6, color: family[1], bold: true, align: 'center' });
    family[3].forEach((row, j) => {
      const y = 4.38 + j * 0.43;
      addText(slide, row[0], x + 0.15, y, 0.45, 0.22, { fontSize: 7.0, color: family[1], bold: true });
      addText(slide, row[1], x + 0.66, y - 0.01, 2.01, 0.28, { fontFace: j === 0 && i < 2 ? 'Arial' : 'Hiragino Sans GB', fontSize: 6.8, color: C.text, valign: 'top' });
    });
  });

  addBox(slide, 0.72, 6.42, 11.88, 0.47, C.goldSoft, C.gold, 0.04, 0.7);
  addText(slide, '因果适用边界：rollout 提供行动条件预测；因果效应主张需通过专门识别设计与负对照验证。', 0.94, 6.51, 11.44, 0.26, { fontSize: 8.5, color: C.ink, bold: true, align: 'center' });
  addNote(slide,
    'GWM Simulator 的实现主体是 Runtime 中的组合转移与写回协议，DAM-GK 只是其中一个可学习的空间动力学来源。',
    [
      '对面积、叠加和拓扑等确定变量直接使用 GIS；对法定边界使用规则；对水文生态过程优先调用专业模型。',
      '只有无法确定性表达、且有数据支持的局部转移与残差才交给 Geospatial Kernel 或其他 learned backend。',
      '每个变量都要记录使用了哪一种转移来源、模型版本和证据等级，未知项必须扩大不确定性或停止推演。',
      '视觉和机器人 simulator 主要消费 observation 与控制；科学 simulator 消费物理场；FLUS 消费土地格局；GWM 额外承担治理动作、规则、证据与 GIS 交付责任。',
      'GWM 的条件推演可用于方案比较，但真实因果效果仍需对照、混杂处理和外部验证。'
    ],
    ['docs/research/GWM_RUNTIME_KERNEL_AND_GEOSPATIAL_KERNEL_RELATIONSHIP.md', 'docs/twm-renderer-simulator-planner-technical-core.md', 'docs/reports/GWM小样本数据使用与推演机制说明_2026-07-22.md']
  );
}

function slide12() {
  const slide = pptx.addSlide();
  addHeader(slide, 19, '理论与方法', 'GWM / TWM 的理论基础与方法映射', '状态、空间关系、行动、约束和证据分别对应成熟理论，并在地理治理任务中形成统一机制。', '理论来源：state-space / MDP / model-based RL / graph learning / GIScience / uncertainty / causal inference');

  const rows = [
    ['受控随机动力系统', 'Sₜ₊₁ = Fθ(Sₜ,Aₜ,Cₜ,Gₜ) + ε', '递归状态演化、外部扰动与不确定性'],
    ['MDP / Model-based RL', '状态-动作-转移-效用', 'Kernel 学转移，Planner 比较行动与长期收益'],
    ['动态多关系图学习', 'typed edges + message passing', '邻接、网络、相似、层级关系分别建模'],
    ['分布式时滞', 'learnable lag distribution', '影响何时到达，而非假定同步响应'],
    ['GIScience 对象-场-拓扑-尺度', 'object / field / topology / hierarchy', '保持地理身份、空间方向、层级与 MAUP 边界'],
    ['概率建模与约束动力学', 'heteroscedastic UQ + simplex / conservation', '同时评价点预测、校准、质量守恒与尺度一致性'],
    ['空间因果推断纪律', 'confounding / spillover / negative control', '不把行动相关性直接表述为政策因果效果']
  ];
  const x = 0.56, y = 1.62;
  const widths = [2.75, 4.00, 5.46];
  ['理论来源', '形式化抓手', '对 GWM / TWM 的直接约束'].forEach((h, i) => {
    addBox(slide, x + widths.slice(0, i).reduce((a, b) => a + b, 0), y, widths[i], 0.48, i === 0 ? C.dark : (i === 1 ? C.blueSoft : C.tealSoft), i === 0 ? C.dark : (i === 1 ? C.blue : C.teal), 0.02, 0.6);
    addText(slide, h, x + widths.slice(0, i).reduce((a, b) => a + b, 0) + 0.10, y + 0.09, widths[i] - 0.20, 0.25, { fontSize: 9.6, color: i === 0 ? 'FFFFFF' : (i === 1 ? C.blue : C.tealDark), bold: true, align: 'center' });
  });
  rows.forEach((r, idx) => {
    const yy = y + 0.48 + idx * 0.65;
    const fill = idx % 2 === 0 ? C.paper : C.graySoft;
    let xx = x;
    widths.forEach((w, i) => {
      addBox(slide, xx, yy, w, 0.65, fill, C.line, 0, 0.45);
      addText(slide, r[i], xx + 0.13, yy + 0.08, w - 0.26, 0.45, {
        fontFace: i === 1 ? 'Arial' : 'Hiragino Sans GB',
        fontSize: i === 0 ? 8.8 : (i === 1 ? 8.4 : 8.3),
        color: i === 0 ? C.ink : C.text,
        bold: i === 0,
        align: i === 1 ? 'center' : 'left'
      });
      xx += w;
    });
  });
  addBox(slide, 0.74, 6.75, 11.85, 0.23, C.dark, C.dark, 0.03, 0);
  addText(slide, '研究门槛：提出可反驳命题 → 冻结协议 → 强基线 / 消融 / 负对照 → 真实或隐藏留出验证 → 再升级主张', 0.92, 6.78, 11.48, 0.14, { fontSize: 7.5, color: 'FFFFFF', bold: true, align: 'center' });
  addNote(slide,
    'GWM 的理论基础是成熟方法的组合，创新点在于地理治理语义下的统一形式化与严格验证。',
    [
      'State-space 提供递归动力系统；MDP 和 model-based RL 提供行动与规划语义。',
      '图学习和时滞模型处理空间传播；GIScience 约束对象、场、拓扑和尺度表达。',
      '概率建模处理不确定性，空间因果方法主要提供实验纪律，而不是让神经网络自动获得因果性。',
      '技术汇报中应主动说明这些理论来源，避免把工程组合误写成全新基础理论。'
    ],
    ['docs/twm-renderer-simulator-planner-theoretical-basis-2026-07-03.md', 'docs/twm-action-conditioned-multi-head-transition-theory.md', 'docs/reports/gwm_geospatial_kernel_core_architecture_design_theory_and_gis_relationship_2026-07-20.md']
  );
}

function slide13() {
  const slide = pptx.addSlide();
  addHeader(slide, 20, 'GWM → TWM', 'TWM：GWM 在自然资源治理中的领域实例', 'TWM 继承 GWM 的共享运行契约，并绑定国土空间治理对象、行动、规则、指标和证据。', '来源：GWM Research Principles；GWM Runtime relationship；TWM technical documents');

  addBox(slide, 0.66, 1.66, 12.02, 1.27, C.dark, C.dark, 0.06, 0);
  addText(slide, 'GWM 共享契约', 0.95, 1.92, 2.12, 0.33, { fontSize: 15, color: 'FFFFFF', bold: true, align: 'center' });
  const shared = ['StateSnapshot', 'CanonicalAction', 'Transition / Kernel', 'Write-back / Rollout', 'UQ / Evidence Ledger'];
  shared.forEach((s, i) => addPill(slide, s, 3.25 + i * 1.74, 1.89, 1.52, '234B50', 'D8E9E6', '4A7376', 6.8));
  addText(slide, '跨领域保持不变：状态可版本化、动作可执行、转移可追踪、未来可写回、主张可降级', 3.19, 2.42, 8.87, 0.22, { fontSize: 8.3, color: 'CDE3DF', align: 'center' });

  addLine(slide, 6.66, 2.97, 0, 0.53, C.teal, 2.0, undefined, 'triangle');
  addPill(slide, 'Domain Adapter', 5.75, 3.24, 1.83, C.tealSoft, C.tealDark, C.teal, 8.0);
  addLine(slide, 6.66, 3.52, 0, 0.43, C.teal, 2.0, undefined, 'triangle');

  addBox(slide, 0.66, 4.03, 12.02, 2.40, C.paper, C.teal, 0.06, 1.0);
  addText(slide, 'TWM 自然资源领域专门化', 0.97, 4.28, 3.02, 0.33, { fontSize: 15, color: C.tealDark, bold: true });
  const columns = [
    ['状态', '地块 / 图斑 / 项目\n规划分区 / 控制线\n规则 / 证据 / 复核'],
    ['行动', '保护 / 调整 / 转用\n审批 / 补正 / 修复\n执法 / 整治 / 监管'],
    ['转移与结果', '未来土地状态\n约束风险 / 规划效用\n不确定性 / 证据缺口'],
    ['规划与交付', 'action mask / beam plan\n方案排序 / 拒绝理由\nGIS 图层 / 审计报告']
  ];
  columns.forEach((col, i) => {
    const x = 4.15 + i * 2.05;
    addBox(slide, x, 4.32, 1.78, 1.55, i % 2 === 0 ? C.tealSoft : C.greenSoft, i % 2 === 0 ? C.teal : C.green, 0.05, 0.7);
    addText(slide, col[0], x + 0.16, 4.52, 1.46, 0.28, { fontSize: 10.8, color: i % 2 === 0 ? C.tealDark : C.green, bold: true, align: 'center' });
    addText(slide, col[1], x + 0.16, 4.94, 1.46, 0.69, { fontSize: 7.9, color: C.text, align: 'center', valign: 'top' });
  });
  addBox(slide, 0.88, 6.65, 11.58, 0.29, C.goldSoft, C.gold, 0.04, 0.6);
  addText(slide, '证据适用范围：单个 TWM 案例支持该领域实例；一般 GWM 主张需经跨领域 Runtime 与 Kernel 验证。', 1.08, 6.71, 11.17, 0.16, { fontSize: 7.8, color: C.ink, bold: true, align: 'center' });
  addNote(slide,
    'TWM 与 GWM 是“领域实例化”关系：共享世界模型语义，绑定自然资源对象和业务约束。',
    [
      '共享部分包括状态、动作、转移、写回、不确定性和证据契约。',
      'TWM 专门化土地对象、控制线、治理动作、法定规则、风险与规划效用。',
      'TWM 不应复制一套私有 Runtime；理想架构是通过 adapter 绑定共享 Runtime 与 Kernel。',
      '单个省或单个业务案例成功，不能反推一般 GWM 已经成立。'
    ],
    ['docs/research/GWM_RESEARCH_PRINCIPLES.md', 'docs/research/GWM_RUNTIME_KERNEL_AND_GEOSPATIAL_KERNEL_RELATIONSHIP.md', 'docs/twm-renderer-simulator-planner-technical-core.md']
  );
}

function slide14() {
  const slide = pptx.addSlide();
  addHeader(slide, 21, 'TWM 决策内核', 'TWM 决策内核：可执行输入、在线推演、轨迹规划与证据审查', 'Renderer、Simulator、Planner 与结论发布前证据审查共同形成可复演的治理决策链。', '来源：TWM renderer-simulator-planner technical core / theoretical basis；territory_world_model implementation');

  const components = [
    ['Renderer', '权威图层 + 动作成员 + 规则\n→ 准入审查与来源指纹\n不预生成供选优的未来状态', C.blueSoft, C.blue],
    ['Simulator', 'Sₜ + ΔAₜ → Sₜ₊₁\n在线递归写回并逐期重算\nGIS / rule / learned backend', C.tealSoft, C.teal],
    ['Planner', '合法动作空间 + 完整 trace\n硬约束优先 + 跨期累计排序\n旧汇总分仅作输入审计', C.greenSoft, C.green],
    ['发布前证据审查', '来源 / 规则 / holdout / 复演\n通过 / 复核 / 阻断\n结论降级 + 人工责任', C.goldSoft, C.gold]
  ];
  components.forEach((c, i) => {
    const x = 0.57 + i * 3.18;
    addBox(slide, x, 1.85, 2.70, 2.38, c[2], c[3], 0.06, 0.9);
    addText(slide, c[0], x + 0.19, 2.12, 2.32, 0.38, { fontFace: 'Arial', fontSize: 17, color: c[3], bold: true, align: 'center' });
    addText(slide, c[1], x + 0.23, 2.70, 2.24, 1.10, { fontSize: 8.6, color: C.text, align: 'center', valign: 'top' });
    if (i < components.length - 1) addFlowArrow(slide, x + 2.78, 3.03, 0.27, C.teal);
  });
  addLine(slide, 11.46, 4.35, -9.38, 0.58, C.violet, 1.2, undefined, 'triangle', 'dash');
  addText(slide, '人工决定与处置结果回到下一版本状态', 4.50, 4.79, 4.41, 0.22, { fontSize: 8.4, color: C.violet, bold: true, align: 'center' });

  addText(slide, '可支撑的核心任务', 0.70, 5.25, 2.23, 0.30, { fontSize: 13.2, color: C.ink, bold: true });
  const tasks = [
    ['规划体检', '三区三线 / 用途管制 / 审批一致性'],
    ['风险预警', '违法占地候选 / 耕地流失 / 生态冲突'],
    ['方案比选', '项目选址 / 保护修复 / 土地整治'],
    ['滚动治理', '监测 → 处置 → 复核 → 再规划']
  ];
  tasks.forEach((t, i) => {
    const x = 2.90 + i * 2.42;
    addText(slide, t[0], x, 5.20, 2.12, 0.28, { fontSize: 10.8, color: i % 2 === 0 ? C.tealDark : C.green, bold: true, align: 'center' });
    addText(slide, t[1], x + 0.08, 5.60, 1.96, 0.47, { fontSize: 7.8, color: C.text, align: 'center', valign: 'top' });
  });
  addBox(slide, 0.72, 6.35, 11.88, 0.38, C.redSoft, C.red, 0.04, 0.6);
  addText(slide, '当前演示：7 个候选先准入，4 个硬阻断；3 个合法方案 × 3 期 = 9 次在线转移，缺动作几何或轨迹不完整即失败关闭。', 0.95, 6.43, 11.44, 0.20, { fontSize: 8.5, color: C.red, bold: true, align: 'center' });
  addNote(slide,
    'TWM 的四个角色共同保证推演结果既能计算，也能被业务审查和复演。',
    [
      'Renderer 不是前端画图；当前严格路径只编译候选准入、动作成员和来源指纹，不把预计算时期状态交给 Planner。',
      'Simulator 是执行核心；当前确定性 GIS / 规则后端按上一期状态和本期动作增量在线生成下一状态。',
      'Planner 只消费完整 simulator trace；父子状态不连续、缺少动作几何或任一期硬约束失败都不可选。',
      '结论发布前证据审查决定结果能否从受控演示升级为业务候选或生产主张。'
    ],
    ['docs/twm-renderer-simulator-planner-technical-core.md', 'docs/twm-renderer-simulator-planner-theoretical-basis-2026-07-03.md', 'data_agent/territory_world_model/']
  );
}

function slide15() {
  const slide = pptx.addSlide();
  addHeader(slide, 25, '需求映射', '空间智能能力现状与建设边界', '规划智能体检和治理动作推演已有基础；遥感、承载力、人口产业与人地耦合能力需通过专业模型补充。', '来源：twm_space_intelligence_core_algorithm_assessment_2026-07-21.md');

  const items = [
    ['规划智能体检', '较强', 0.78, C.green, '控制线 / 用途管制 / 审批一致性 / 复核任务'],
    ['治理动作推演', '较强', 0.72, C.teal, '状态-行动-风险-效用-不确定性闭环'],
    ['违法占地 / 耕地流失风险', '部分覆盖', 0.48, C.gold, '已支持既有图斑审查；独立遥感发现待闭环'],
    ['遥感智能解译', '接入基础', 0.27, C.gold, '已接 Sentinel / STAC / 指数；生产识别主干待建设'],
    ['承载力 AI 仿真', '待建设', 0.12, C.red, '需补充水土资源、生态容量、灾害与设施容量通道'],
    ['人口产业空间模拟', '待建设', 0.08, C.red, '需补充人口迁移、产业布局、就业与资源匹配动力学'],
    ['人地耦合评价 / 空间错配', '待建设', 0.08, C.red, '需建立统一目标函数、跨区流动与真实行动结果数据']
  ];
  addText(slide, '能力项', 0.72, 1.61, 3.20, 0.24, { fontSize: 8.5, color: C.muted, bold: true });
  addText(slide, '工程覆盖判断（非精度得分）', 4.05, 1.61, 4.10, 0.24, { fontSize: 8.5, color: C.muted, bold: true, align: 'center' });
  addText(slide, '当前能力说明', 8.63, 1.61, 3.58, 0.24, { fontSize: 8.5, color: C.muted, bold: true, align: 'center' });
  items.forEach((it, i) => {
    const y = 1.96 + i * 0.67;
    addText(slide, it[0], 0.72, y, 3.15, 0.29, { fontSize: 9.4, color: C.ink, bold: true });
    addBox(slide, 4.06, y + 0.03, 3.64, 0.20, C.graySoft, C.graySoft, 0.10, 0);
    addBox(slide, 4.06, y + 0.03, 3.64 * it[2], 0.20, it[3], it[3], 0.10, 0);
    addText(slide, it[1], 7.83, y - 0.01, 0.62, 0.27, { fontSize: 8.2, color: it[3], bold: true, align: 'center' });
    addText(slide, it[4], 8.62, y - 0.02, 3.75, 0.34, { fontSize: 7.6, color: C.text, align: 'left' });
    addLine(slide, 0.72, y + 0.48, 11.65, 0, C.line, 0.45);
  });

  addBox(slide, 0.72, 6.73, 11.89, 0.24, C.dark, C.dark, 0.03, 0);
  addText(slide, '建设定位：TWM 作为自然资源空间世界模型与决策内核，专业模型通过统一契约进入状态、转移和评价闭环。', 0.93, 6.77, 11.48, 0.15, { fontSize: 7.8, color: 'FFFFFF', bold: true, align: 'center' });
  addNote(slide,
    'TWM 与政策提出的空间智能方向高度一致，但目前覆盖集中在规划、规则与行动推演。',
    [
      '规划智能体检最成熟，因为已有控制线、规则、项目、证据和复核对象。',
      '遥感层当前偏数据接入和证据引用，尚无稳定的生产级变化检测与地类识别主干。',
      '资源环境承载力、人口产业和人地耦合需要独立专业 Kernel 与真实数据，不应通过扩大 TWM 术语来假装已经具备。',
      '最佳架构是遥感、政策文档、承载力和人口产业模型共同向 TWM 提供状态与动力学。'
    ],
    ['docs/reports/twm_space_intelligence_core_algorithm_assessment_2026-07-21.md']
  );
}

function slide16() {
  const slide = pptx.addSlide();
  addHeader(slide, 26, '证据成熟度', 'GWM / TWM 证据成熟度分层', '原型机制、已验证结果和待验证主张实行分层管理，并分别对应不同发布口径。', '来源：twm_runtime_benchmark_v1.json；twm_validation_bundle.json；DAM-GK v0.1 terminal adjudication');

  const cols = [
    ['已实现', C.green, C.greenSoft, [
      '对象-关系-规则-证据状态',
      'action-conditioned 多头预测',
      'counterfactual rollout / beam plan',
      '不确定性、模型注册、审计门',
      'DAM-GK 机制与负对照框架'
    ]],
    ['当前验证结果', C.gold, C.goldSoft, [
      'Runtime simulator gate：合成留出通过',
      'TWM 当前演示：Planner trace-only，通过',
      '共享 Runtime planner / negative controls：失败',
      'Validation bundle：review',
      'Claim ladder：L0 / unsupported'
    ]],
    ['待验证主张', C.red, C.redSoft, [
      '通用 Geospatial Kernel 的跨场景验证',
      '真实政策行动的因果识别验证',
      '跨区域 / 跨政策版本稳定泛化',
      '省域海量数据生产规模就绪',
      '省域辅助审批的权限与责任边界'
    ]]
  ];
  cols.forEach((col, i) => {
    const x = 0.62 + i * 4.17;
    addBox(slide, x, 1.70, 3.75, 3.88, C.paper, col[1], 0.06, 1.0);
    addBox(slide, x, 1.70, 3.75, 0.62, col[2], col[1], 0.06, 0.8);
    addText(slide, col[0], x + 0.20, 1.87, 3.35, 0.28, { fontSize: 14, color: col[1], bold: true, align: 'center' });
    col[3].forEach((p, j) => addBullet(slide, p, x + 0.29, 2.60 + j * 0.55, 3.17, 0.39, { fontSize: 8.8, bulletColor: col[1] }));
  });

  addBox(slide, 0.74, 5.89, 11.85, 0.80, C.redSoft, C.red, 0.05, 0.8);
  addText(slide, 'DAM-GK v0.1 终局审计', 0.98, 6.10, 2.09, 0.27, { fontSize: 11.3, color: C.red, bold: true });
  addText(slide, 'H1-H5 rejected；H6 out of scope。当前版本尚不支持通用 Kernel 主张，后续版本按预冻结协议重新验证。', 3.12, 6.03, 9.12, 0.39, { fontSize: 8.8, color: C.ink, bold: true, align: 'center' });
  addNote(slide,
    '当前项目已经证明计算机制能运行，但仍处于研究验证和生产数据准备阶段。',
    [
      'Runtime benchmark 的 simulator 指标来自 synthetic fixture，只能证明接口、追踪和小型候选模型可运行。',
      'TWM 当前多候选演示已把 Planner 强制绑定完整 simulator trace；这不等于共享 Runtime benchmark 已通过。',
      '共享 Runtime 的历史 Planner gate 与负对照仍为 fail，必须作为独立平台级缺口保留。',
      'TWM validation bundle 为 review，Claim ladder 处于 L0。',
      'DAM-GK v0.1 的严格假设审计未通过，应保留为负证据并推动新版本，而不是修改口径。'
    ],
    ['docs/reports/twm_runtime_benchmark_v1.json', 'docs/reports/twm_validation_bundle.json', 'docs/research/DAM_GK_RESEARCH_SPEC.md']
  );
}

function slide17() {
  const slide = pptx.addSlide();
  addHeader(slide, 27, '落地难点与路径', '省级落地的核心难点与实施路径', '从一条真实业务闭环切入，优先完成数据、行动、结果和基线建设，再逐步扩展模型与场景。', '来源：TWM production input requirements；space intelligence assessment；GWM benchmark governance');

  addText(slide, '五个硬难点', 0.68, 1.64, 2.05, 0.33, { fontSize: 14.5, color: C.ink, bold: true });
  const blockers = [
    ['01', '真实转移样本', '多期状态 + 真实动作 + 最终处置 / 结果'],
    ['02', '政策与因果边界', '动作选择偏差、空间溢出、政策版本变化'],
    ['03', '多尺度空间一致性', '图斑-项目-乡镇-区县的拓扑和尺度偏差'],
    ['04', '系统与证据集成', '一张图、遥感、审批、执法、规则、人工意见'],
    ['05', '生产工程', '省域数据规模、模型更新、审计、回滚与算力']
  ];
  blockers.forEach((b, i) => {
    const y = 2.08 + i * 0.79;
    addText(slide, b[0], 0.72, y, 0.50, 0.27, { fontFace: 'Arial', fontSize: 10, color: C.red, bold: true, align: 'center' });
    addText(slide, b[1], 1.38, y - 0.02, 1.66, 0.30, { fontSize: 10.2, color: C.ink, bold: true });
    addText(slide, b[2], 3.00, y - 0.02, 3.16, 0.38, { fontSize: 8.1, color: C.text });
    addLine(slide, 0.72, y + 0.47, 5.50, 0, C.line, 0.5);
  });

  addLine(slide, 6.52, 1.70, 0, 4.94, C.line, 0.8);
  addText(slide, '建议的省级三阶段路径', 6.88, 1.64, 4.95, 0.33, { fontSize: 14.5, color: C.ink, bold: true });
  const phases = [
    ['0-3 个月', '闭环定义与数据审计', '选择“建设项目用地预审 / 耕地保护审查”之一；冻结对象、动作、结果、政策版本、基线和指标。', C.blue, C.blueSoft],
    ['3-9 个月', '影子运行与同题验证', '接入多期遥感和审批处置历史；与人工 GIS 审查、规则引擎、FLUS / 传统优化做时间与区域留出。', C.teal, C.tealSoft],
    ['9-18 个月', '受控生产与能力扩展', '完成共享 Runtime 绑定；执行负对照与回滚；再增加承载力、人口产业和跨区域耦合 Kernel。', C.green, C.greenSoft]
  ];
  phases.forEach((p, i) => {
    const y = 2.14 + i * 1.36;
    addBox(slide, 6.88, y, 5.51, 1.07, p[4], p[3], 0.05, 0.8);
    addPill(slide, p[0], 7.08, y + 0.17, 1.12, C.paper, p[3], C.paper, 7.5);
    addText(slide, p[1], 8.43, y + 0.14, 3.63, 0.27, { fontSize: 10.8, color: p[3], bold: true });
    addText(slide, p[2], 7.10, y + 0.53, 5.05, 0.39, { fontSize: 7.8, color: C.text, valign: 'top' });
  });
  addBox(slide, 0.72, 6.58, 11.66, 0.34, C.dark, C.dark, 0.04, 0);
  addText(slide, '首期验收重点：数据可追溯、动作可定义、结果可验证、失败可复演、结论可降级。', 0.93, 6.65, 11.26, 0.17, { fontSize: 8.5, color: 'FFFFFF', bold: true, align: 'center' });
  addNote(slide,
    '省级落地应从一条可闭环业务入手，而不是先建设一个“大而全”的自然资源大模型。',
    [
      '最稀缺的数据不是影像本身，而是明确发生时间、作用对象和最终结果的治理行动历史。',
      '首选建设项目用地预审或耕地保护审查，因为对象、规则、处置和人工复核相对清晰。',
      '先影子运行并与人工 GIS 审查、规则引擎和传统模型同题比较，再进入受控生产。',
      '承载力、人口产业和跨区域耦合应在基础闭环验证后以独立 Kernel 增量接入。'
    ],
    ['docs/twm-production-input-data-requirements.md', 'docs/reports/twm_space_intelligence_core_algorithm_assessment_2026-07-21.md', 'docs/research/GWM_BENCHMARK_AND_KERNEL_COEVOLUTION_2026-07-19.md']
  );
}

function slide18() {
  const slide = pptx.addSlide();
  addHeader(slide, 27, '未来平台', 'LLM + WM：空间智能体平台的目标架构', 'LLM 负责语义理解、检索与编排，WM 负责状态转移、反事实推演和方案评价，GIS 与证据门控负责约束和审计。', '架构判断：GWM Research Principles；TWM technical basis；GIS Data Agent cognitive runtime');

  addBox(slide, 0.56, 1.70, 3.46, 3.82, C.blueSoft, C.blue, 0.06, 0.9);
  addText(slide, 'LLM / Agent Runtime', 0.86, 2.01, 2.86, 0.37, { fontFace: 'Arial', fontSize: 16, color: C.blue, bold: true, align: 'center' });
  const llm = ['理解用户目标与政策文本', '检索数据、规则与证据', '拆解任务并调用工具', '生成解释、报告与交互', '发现缺口并请求人工确认'];
  llm.forEach((p, i) => addBullet(slide, p, 0.93, 2.62 + i * 0.50, 2.70, 0.34, { fontSize: 8.6, bulletColor: C.blue }));
  addPill(slide, '语义理解与工具编排', 0.98, 5.02, 2.63, C.blueSoft, C.blue, C.blueSoft, 7.2);

  addFlowArrow(slide, 4.28, 3.41, 0.72, C.violet);
  addText(slide, '状态 / 动作\n证据契约', 4.04, 2.91, 1.16, 0.40, { fontSize: 6.6, color: C.violet, bold: true, align: 'center' });

  addBox(slide, 5.25, 1.70, 3.46, 3.82, C.tealSoft, C.teal, 0.06, 0.9);
  addText(slide, 'World Model Runtime', 5.55, 2.01, 2.86, 0.37, { fontFace: 'Arial', fontSize: 16, color: C.tealDark, bold: true, align: 'center' });
  const wm = ['维护版本化世界状态', '计算行动条件状态转移', '递归 rollout 与关系重算', '输出风险、效用与不确定性', '比较候选方案并保留 trace'];
  wm.forEach((p, i) => addBullet(slide, p, 5.62, 2.62 + i * 0.50, 2.70, 0.34, { fontSize: 8.6, bulletColor: C.teal }));
  addPill(slide, '数值推演与验证门控', 5.67, 5.02, 2.63, C.paper, C.tealDark, C.paper, 7.2);

  addFlowArrow(slide, 8.97, 3.41, 0.72, C.green);
  addText(slide, '工具调用\n回写 / 审计', 8.82, 2.91, 1.08, 0.40, { fontSize: 6.6, color: C.green, bold: true, align: 'center' });

  addBox(slide, 9.94, 1.70, 2.84, 3.82, C.greenSoft, C.green, 0.06, 0.9);
  addText(slide, 'GIS + Governance', 10.17, 2.01, 2.38, 0.37, { fontFace: 'Arial', fontSize: 15, color: C.green, bold: true, align: 'center' });
  const gov = ['权威数据与坐标拓扑', '硬规则与动作可行域', '证据来源与数据谱系', '人工复核与责任边界', '输出回写、审计与反馈'];
  gov.forEach((p, i) => addBullet(slide, p, 10.20, 2.62 + i * 0.50, 2.22, 0.34, { fontSize: 8.4, bulletColor: C.green }));
  addPill(slide, '法定责任不转移给模型', 10.27, 5.02, 2.09, C.goldSoft, C.gold, C.goldSoft, 7.2);

  addBox(slide, 0.74, 5.93, 12.00, 0.69, C.dark, C.dark, 0.05, 0);
  addText(slide, 'LLM 独立运行', 1.04, 6.11, 1.58, 0.22, { fontSize: 9.2, color: 'D7E7E4', bold: true, align: 'center' });
  addText(slide, '侧重语义理解与任务编排', 2.54, 6.09, 2.10, 0.25, { fontSize: 8.6, color: 'FFFFFF', bold: true, align: 'center' });
  addLine(slide, 4.93, 6.05, 0, 0.30, '56777A', 0.8);
  addText(slide, 'WM 独立运行', 5.23, 6.11, 1.58, 0.22, { fontSize: 9.2, color: 'D7E7E4', bold: true, align: 'center' });
  addText(slide, '侧重状态转移与方案评价', 6.77, 6.09, 2.45, 0.25, { fontSize: 8.6, color: 'FFFFFF', bold: true, align: 'center' });
  addLine(slide, 9.47, 6.05, 0, 0.30, '56777A', 0.8);
  addText(slide, 'LLM + WM + GIS', 9.75, 6.11, 1.58, 0.22, { fontFace: 'Arial', fontSize: 9.2, color: '8EE0CE', bold: true, align: 'center' });
  addText(slide, '形成可解释、可推演、可审计的智能体', 11.05, 6.09, 1.46, 0.25, { fontSize: 8.0, color: 'FFFFFF', bold: true, align: 'center' });
  addNote(slide,
    '未来智能体平台必须把语言智能和世界动力学分工，而不是让 LLM 同时承担理解、计算和事实责任。',
    [
      'LLM 擅长自然语言、文档理解、工具选择和解释，但不应直接编造数值未来。',
      'WM 维护结构化状态并通过受约束转移模型做 rollout；其输出必须有版本、trace 和不确定性。',
      'GIS 保证对象身份、坐标、拓扑和权威数据；规则与人工复核保证治理边界。',
      '三者通过统一状态、动作和证据契约协同，才构成可进入自然资源生产流程的智能体平台。'
    ],
    ['docs/research/GWM_RESEARCH_PRINCIPLES.md', 'docs/twm-renderer-simulator-planner-theoretical-basis-2026-07-03.md', 'docs/superpowers/specs/2026-07-15-gis-data-agent-cognitive-runtime-design.md']
  );
}

function slide19() {
  const slide = pptx.addSlide();
  addHeader(slide, 28, '结语与依据', '建设自然资源空间智能的公共决策内核', '以真实业务闭环验证 TWM，以跨领域 Runtime 与 Kernel 逐步建立 GWM，以 LLM + WM 形成下一代空间智能体平台。', '本页列出汇报使用的核心项目依据与外部理论来源');

  addBox(slide, 0.66, 1.62, 12.02, 1.16, C.dark, C.dark, 0.06, 0);
  addText(slide, '从“看见现在”到“比较未来”', 0.98, 1.92, 3.26, 0.35, { fontSize: 16.5, color: 'FFFFFF', bold: true, align: 'center' });
  addText(slide, '权威 GIS 状态  →  行动条件转移  →  多步世界推演  →  证据门控规划  →  人工负责决策', 4.24, 1.90, 7.95, 0.41, { fontSize: 11.3, color: 'D5E7E4', bold: true, align: 'center' });

  addText(slide, '核心项目依据', 0.71, 3.18, 2.25, 0.31, { fontSize: 13.4, color: C.ink, bold: true });
  const left = [
    'GWM_RESEARCH_PRINCIPLES.md',
    'DAM_GK_RESEARCH_SPEC.md',
    'GWM_RUNTIME_KERNEL_AND_GEOSPATIAL_KERNEL_RELATIONSHIP.md',
    'gwm_geospatial_kernel_core_architecture_design_theory_and_gis_relationship_2026-07-20.md',
    'twm-vs-geosos-flus-comparison.md',
    'twm-vs-geosos-flus-academic-positioning.md',
    'twm_runtime_benchmark_v1.json / twm_validation_bundle.json'
  ];
  left.forEach((p, i) => addBullet(slide, p, 0.78, 3.66 + i * 0.42, 5.60, 0.28, { fontFace: 'Arial', fontSize: 7.7, bulletColor: C.teal }));

  addLine(slide, 6.53, 3.21, 0, 2.80, C.line, 0.8);
  addText(slide, '核心理论与基线', 6.90, 3.18, 2.25, 0.31, { fontSize: 13.4, color: C.ink, bold: true });
  const right = [
    'Sutton & Barto: Reinforcement Learning / Dyna',
    'Moerland et al.: Model-based Reinforcement Learning Survey',
    'Ha & Schmidhuber: World Models; Schrittwieser et al.: MuZero',
    'Caruana: Multitask Learning; Altman: Constrained MDP',
    'Pearl: Causality / do-calculus',
    'Liu et al. 2017: FLUS; Li et al. 2011: GeoSOS'
  ];
  right.forEach((p, i) => addBullet(slide, p, 6.97, 3.66 + i * 0.42, 5.42, 0.28, { fontFace: 'Arial', fontSize: 7.7, bulletColor: C.blue }));

  addBox(slide, 0.72, 6.36, 11.88, 0.45, C.tealSoft, C.teal, 0.05, 0.7);
  addText(slide, '建议启动项：选定一条省级真实业务闭环，联合冻结数据契约、基线、留出协议与主张升级门槛。', 0.96, 6.46, 11.43, 0.23, { fontSize: 9.5, color: C.tealDark, bold: true, align: 'center' });
  addNote(slide,
    '汇报的最终落点是建立公共决策内核，而不是替代现有自然资源信息化体系。',
    [
      '对标 FLUS 的意义是证明新路线至少能解决经典土地利用变化问题，并进一步扩展到行动、证据和规划。',
      'GWM 的科学价值取决于 Kernel 是否在冻结协议和真实留出上稳定成立。',
      'TWM 的业务价值取决于能否接入真实治理动作与结果，形成可复演的闭环。',
      '建议会后优先确定首个业务闭环及数据负责人，而不是先讨论模型参数规模。'
    ],
    ['本汇报结语页所列项目文档与外部文献']
  );
}

function slideWorldModelLandscape() {
  const slide = pptx.addSlide();
  addHeader(slide, 3, '全局综述', '世界模型技术谱系与 GWM 的定位', '各类世界模型共享状态表示与动力学，其差异主要体现在建模对象、行动接口和决策消费方。', '代表性来源：Dyna；World Models；PlaNet / Dreamer；MuZero；TD-MPC2；Sora / Genie / V-JEPA / Cosmos；GAIA-1；scientific emulators');

  const families = [
    ['控制与规划', 'Dyna / PlaNet / Dreamer\nMuZero / TD-MPC2', '学习潜在状态转移，在想象轨迹中选择动作', '秒-回合', C.blue, C.blueSoft],
    ['视觉与生成', 'Sora / Genie / V-JEPA\nCosmos', '生成或预测视觉世界，支持交互环境与物理表征', '帧-分钟', C.violet, C.violetSoft],
    ['具身与机器人', 'robotics world models\naction-conditioned video', '预测操作、接触、运动后的局部物理结果', '毫秒-分钟', C.green, C.greenSoft],
    ['自动驾驶', 'GAIA-1 等', '融合道路、交通参与者和车辆动作，预测驾驶场景', '秒-分钟', C.gold, C.goldSoft],
    ['科学模拟与孪生', '气象 / 气候 / 流体\n工业数字孪生', '以物理场、边界条件和 forcing 预测系统演化', '小时-年代', C.teal, C.tealSoft],
    ['地理治理', 'GWM / TWM', '以空间对象、关系、规则、证据和治理行动推演区域状态', '月-规划期', C.red, C.redSoft]
  ];
  addText(slide, '主要谱系', 0.63, 1.60, 1.58, 0.24, { fontSize: 8.6, color: C.muted, bold: true });
  addText(slide, '代表工作', 2.45, 1.60, 2.45, 0.24, { fontSize: 8.6, color: C.muted, bold: true, align: 'center' });
  addText(slide, '核心任务', 5.13, 1.60, 4.26, 0.24, { fontSize: 8.6, color: C.muted, bold: true, align: 'center' });
  addText(slide, '典型时间', 9.70, 1.60, 1.25, 0.24, { fontSize: 8.6, color: C.muted, bold: true, align: 'center' });
  addText(slide, '主要消费方', 11.05, 1.60, 1.63, 0.24, { fontSize: 8.6, color: C.muted, bold: true, align: 'center' });
  const consumers = ['policy / planner', 'human / agent', 'robot policy', 'driving policy', 'scientist / operator', 'planner / reviewer'];
  families.forEach((f, i) => {
    const y = 1.93 + i * 0.73;
    const fill = i % 2 === 0 ? C.paper : C.graySoft;
    addBox(slide, 0.59, y, 12.10, 0.62, fill, C.line, 0.02, 0.5);
    addBox(slide, 0.59, y, 0.12, 0.62, f[4], f[4], 0, 0);
    addText(slide, f[0], 0.83, y + 0.13, 1.47, 0.28, { fontSize: 9.5, color: f[4], bold: true });
    addText(slide, f[1], 2.42, y + 0.08, 2.50, 0.42, { fontFace: 'Arial', fontSize: 7.7, color: C.ink, bold: true, align: 'center', valign: 'top' });
    addText(slide, f[2], 5.15, y + 0.08, 4.23, 0.42, { fontSize: 8.2, color: C.text, align: 'center', valign: 'top' });
    addText(slide, f[3], 9.70, y + 0.16, 1.25, 0.24, { fontSize: 8.1, color: C.text, bold: true, align: 'center' });
    addText(slide, consumers[i], 11.04, y + 0.13, 1.44, 0.29, { fontFace: 'Arial', fontSize: 7.5, color: C.muted, align: 'center' });
  });
  addBox(slide, 0.72, 6.49, 11.86, 0.42, C.dark, C.dark, 0.04, 0);
  addText(slide, '决策型世界模型的共同要求：行动进入状态转移，预测结果能够被规划器和验证闭环持续消费。', 0.96, 6.57, 11.40, 0.24, { fontSize: 8.7, color: 'FFFFFF', bold: true, align: 'center' });
  addNote(slide,
    '“世界模型”目前没有唯一统一定义，最稳妥的综述方式是按功能与服务对象划分谱系。',
    [
      '控制路线强调 learned dynamics 与 latent imagination，直接服务策略或规划器。',
      '视觉生成路线强调 observation synthesis；其中部分工作被称为 world simulator，但是否具备显式行动和决策闭环需要逐项判断。',
      '科学模拟器与数字孪生强调物理场、边界条件和高保真预测，未必包含智能体规划。',
      'GWM 位于地理治理谱系：预测对象不是下一帧，而是治理行动作用后的多尺度空间状态。'
    ],
    ['Sutton 1991 Dyna', 'Ha & Schmidhuber 2018 World Models', 'Hafner et al. PlaNet / Dreamer', 'Schrittwieser et al. 2020 MuZero', 'Hansen et al. TD-MPC / TD-MPC2', 'docs/twm-authoritative-references.md', 'docs/twm-feifei-functional-taxonomy-alignment.md']
  );
}

function slideGwmDistinctivePosition() {
  const slide = pptx.addSlide();
  addHeader(slide, 4, '定义与融合', '地理空间世界模型（GWM）的定义与能力构成', 'GWM 将 GIScience 的对象、场、CRS、拓扑、网络方向、尺度层级和治理约束纳入状态、转移、验证与交付契约。', '来源：GWM Research Principles；TWM scale and novelty；TWM authoritative references；GIScience / provenance / constrained decision making');

  const rows = [
    ['世界表征', '像素 / latent frame', '局部物体与物理状态', '网格化物理场', '对象 + 场 + 关系 + 规则 + 证据'],
    ['空间结构', '隐含在视觉特征中', '局部坐标 / 3D 几何', '规则网格 / 方程域', 'CRS、拓扑、网络方向、行政层级'],
    ['行动语义', '提示词或弱条件', '控制量 / 运动指令', 'forcing / 边界条件', '选址、审批、保护、整治、修复、管控'],
    ['约束来源', '生成一致性', '物理与安全', '守恒律与方程', '法律政策、用途管制、权属、生态与数量底线'],
    ['时间尺度', '帧到分钟', '毫秒到分钟', '小时到年代', '月度、年度、规划周期'],
    ['可用输出', '视频 / observation', '轨迹 / 控制价值', '未来场 / 风险场', 'GIS 图层、方案排序、风险、效用、不确定性、证据任务']
  ];
  const x = [0.48, 2.04, 4.59, 7.13, 9.66];
  const w = [1.56, 2.55, 2.54, 2.53, 3.17];
  const headers = [
    ['维度', C.dark, 'FFFFFF'],
    ['视觉 / 生成 WM', C.violetSoft, C.violet],
    ['具身 / 驾驶 WM', C.greenSoft, C.green],
    ['科学模拟 / 孪生', C.blueSoft, C.blue],
    ['GWM / TWM', C.tealSoft, C.tealDark]
  ];
  headers.forEach((h, i) => {
    addBox(slide, x[i], 1.60, w[i], 0.50, h[1], i === 0 ? C.dark : h[2], 0.02, 0.6);
    addText(slide, h[0], x[i] + 0.06, 1.72, w[i] - 0.12, 0.25, { fontSize: 9.0, color: h[2], bold: true, align: 'center' });
  });
  rows.forEach((r, ri) => {
    const y = 2.10 + ri * 0.68;
    r.forEach((cell, ci) => {
      const fill = ci === 4 ? (ri % 2 === 0 ? 'EDF8F5' : C.tealSoft) : (ri % 2 === 0 ? C.paper : C.graySoft);
      addBox(slide, x[ci], y, w[ci], 0.68, fill, ci === 4 ? C.teal : C.line, 0, ci === 4 ? 0.8 : 0.45);
      addText(slide, cell, x[ci] + 0.08, y + 0.10, w[ci] - 0.16, 0.44, { fontSize: ci === 0 ? 8.6 : 7.7, color: ci === 4 ? C.tealDark : (ci === 0 ? C.ink : C.text), bold: ci === 0 || ci === 4, align: 'center', valign: 'top' });
    });
  });
  addBox(slide, 0.72, 6.40, 11.88, 0.48, C.goldSoft, C.gold, 0.04, 0.7);
  addText(slide, '形式化定义：GWM = 可版本化地理状态 + 行动条件空间转移 + 受约束递归推演 + GIS 可操作输出 + 证据门控规划。', 0.96, 6.50, 11.40, 0.25, { fontSize: 9.0, color: C.ink, bold: true, align: 'center' });
  addNote(slide,
    'GWM 是把地理空间结构作为世界模型的状态、动力学、约束、验证和输出契约，而不是给普通模型追加经纬度字段。',
    [
      '世界表征同时包含对象、连续场、空间关系、规则和证据；CRS、方向、拓扑与尺度不能只留在数据预处理阶段。',
      '视觉世界模型主要输出 observation；GWM 主要输出 GIS-operational state、风险、效用和证据缺口。',
      '具身和驾驶模型重点是局部物理安全；GWM 还必须显式处理行政层级、用途管制、权利边界和政策版本。',
      '科学模拟器可以作为 GWM 的专业 transition source；GWM 额外负责治理行动、方案比较与证据门控。',
      'GWM 不替代物理模型、遥感模型或规则系统，而是让它们通过统一契约共同服务决策。'
    ],
    ['docs/twm-scale-and-novelty-analysis.md', 'docs/twm-authoritative-references.md', 'docs/research/GWM_RESEARCH_PRINCIPLES.md']
  );
}

function slidePaper9Deployment() {
  const slide = pptx.addSlide();
  addHeader(slide, 6, '落地证据', 'Paper9：真实数据离线部署与硬约束验证', '双县真实数据已完成 prepare → sample → train → plan → audit 全流程，并形成内网候选部署包。', '来源：paper9-mnr-offline-package；Paper9v2 Docker 双数据 E2E 报告；Paper9v2.1 legacy-amd64 E2E 报告（2026-07-01）');

  addText(slide, '解决的业务问题', 0.67, 1.60, 2.28, 0.30, { fontSize: 13.8, color: C.ink, bold: true });
  addBox(slide, 0.67, 2.02, 3.20, 3.91, C.paper, C.line, 0.06, 0.8);
  addText(slide, '县域耕地布局优化', 0.94, 2.30, 2.66, 0.31, { fontSize: 14.2, color: C.tealDark, bold: true, align: 'center' });
  const problem = [
    '输入：权威 DLTB 图斑、坡度属性、行政边界',
    '动作：耕地与非耕地候选图斑的约束置换',
    '目标：降低坡度、提升连片度，尽量形成百亩方',
    '底线：县域耕地总面积不减少',
    '输出：优化图斑、指标汇总、运行清单与审计结论'
  ];
  problem.forEach((p, i) => addBullet(slide, p, 0.95, 2.90 + i * 0.52, 2.66, 0.36, { fontSize: 8.3, bulletColor: i === 3 ? C.red : C.teal }));

  addText(slide, '算法与运行链路', 4.25, 1.60, 3.22, 0.30, { fontSize: 13.8, color: C.ink, bold: true });
  const stages = [
    ['prepare', '建立区县环境与候选块'],
    ['sample', '采集转移与候选排序样本'],
    ['train', 'ensemble：状态/奖励 MSE + pairwise ranking'],
    ['plan', 'MPC：horizon=5 / top-k=50 的约束前瞻搜索'],
    ['audit', '文件完整性 + 三项 hard gate']
  ];
  stages.forEach((st, i) => {
    const y = 2.03 + i * 0.77;
    addPill(slide, st[0], 4.27, y, 1.12, i === 4 ? C.greenSoft : C.blueSoft, i === 4 ? C.green : C.blue, i === 4 ? C.greenSoft : C.blueSoft, 7.7);
    addText(slide, st[1], 5.61, y + 0.01, 3.20, 0.31, { fontFace: i === 2 ? 'Arial' : 'Hiragino Sans GB', fontSize: 8.1, color: C.text, bold: i === 4 });
    if (i < stages.length - 1) addLine(slide, 4.83, y + 0.31, 0, 0.40, C.blue, 1.2, undefined, 'triangle');
  });

  addLine(slide, 8.90, 1.71, 0, 4.70, C.line, 0.8);
  addText(slide, '真实数据与离线部署证据', 9.22, 1.60, 3.41, 0.30, { fontSize: 13.8, color: C.ink, bold: true });
  const stats = [
    ['2 套', '四川省内江市东兴区\n重庆市璧山区'],
    ['均通过', '面积不减、坡度下降、连片度上升'],
    ['101,657', '重庆市璧山区输入图斑规模'],
    ['134,369', '四川省内江市东兴区输入图斑规模'],
    ['61 passed', 'legacy-amd64 代码侧验证']
  ];
  stats.forEach((st, i) => {
    const y = 2.06 + i * 0.69;
    addText(slide, st[0], 9.17, y, 1.33, 0.33, { fontFace: 'Arial', fontSize: 13.2, color: i === 1 ? C.green : C.violet, bold: true, align: 'right' });
    addText(slide, st[1], 10.68, y + 0.01, 1.72, i === 0 ? 0.48 : 0.35, { fontSize: i === 0 ? 7.4 : 7.8, color: C.text, bold: i === 1, breakLine: false });
  });
  addBox(slide, 9.18, 5.66, 3.20, 0.49, C.goldSoft, C.gold, 0.04, 0.7);
  addText(slide, '已形成自然资源部内网下一轮测试候选包，并完成目标老旧 x86_64 兼容适配', 9.30, 5.72, 3.00, 0.34, { fontSize: 7.7, color: C.gold, bold: true, align: 'center', valign: 'mid' });
  addBox(slide, 0.73, 6.35, 11.85, 0.46, C.redSoft, C.red, 0.04, 0.7);
  addText(slide, '当前验收状态：候选包已完成真实数据 E2E 和 Intel Windows 重建验证；最终结论以目标内网机器 run / audit 结果为准。', 0.96, 6.44, 11.42, 0.27, { fontSize: 8.3, color: C.red, bold: true, align: 'center' });
  addNote(slide,
    'Paper9 是 GWM 研究主线的工程落地点：已经证明模型式空间规划可以在真实权威图斑和离线环境中运行。',
    [
      'Paper9v2 将县域耕地面积不减少、平均坡度降低、连片度提升设为 hard gate，百亩方为软目标。',
      '双数据集 Docker E2E 中，四川省内江市东兴区和重庆市璧山区均完成 prepare、sample、train、plan、audit 并通过 hard gate。',
      '现场目标机为 Deepin server 16 / 老 x86_64，候选包已针对缺少 sse4_1 和 popcnt 的 CPU 做 legacy 兼容。',
      '汇报中应明确：这是离线部署测试与候选交付证据，不等于自然资源部最终验收结论。'
    ],
    ['/Users/zhouning/paper9-mnr-offline-package/README.md', '/Users/zhouning/paper9-mnr-offline-package/outputs/paper9v2_docker_bishan_dongxing_report_20260627/REPORT.md', '/Users/zhouning/paper9-mnr-offline-package/docs/reports/paper9v21_legacy_amd64_e2e_20260701/REPORT.md']
  );
}

function slideConventionalLimits() {
  const slide = pptx.addSlide();
  addHeader(slide, 7, '方法必要性', '多期约束场景需要模型式规划', 'Paper9 以局部转移学习表达非线性影响，并通过受约束前瞻规划处理组合动作和硬约束。', '理论来源：MDP / model-based RL / MPC / constrained optimization；项目来源：Paper9v2 algorithm and versioning；双数据 E2E 报告');

  const methods = [
    ['加权叠加 / MCE', '静态适宜性清晰、解释直观', '不描述动作后的状态写回；权重难覆盖时滞与相互作用', C.blue],
    ['数学规划', '目标和约束已知时可给强基线甚至最优解', '县域图斑组合巨大；真实转移函数往往不完整或非线性', C.violet],
    ['CA / FLUS', '土地利用格局与多地类空间分配成熟', '主要模拟地类转化，难直接表达逐宗治理动作与审计门槛', C.gold],
    ['贪心 / 元启发式', '易部署，局部搜索成本较低', '偏重即时收益，容易错过延迟效应和动作序列组合', C.red],
    ['Model-free DRL', '可学习复杂策略', '样本效率低；没有显式未来状态，反事实解释和复演较弱', C.green]
  ];
  addText(slide, '方法', 0.58, 1.63, 2.02, 0.24, { fontSize: 8.5, color: C.muted, bold: true, align: 'center' });
  addText(slide, '适用优势', 2.72, 1.63, 3.62, 0.24, { fontSize: 8.5, color: C.muted, bold: true, align: 'center' });
  addText(slide, '复杂场景局限', 6.55, 1.63, 5.92, 0.24, { fontSize: 8.5, color: C.muted, bold: true, align: 'center' });
  methods.forEach((m, i) => {
    const y = 1.94 + i * 0.74;
    const fill = i % 2 === 0 ? C.paper : C.graySoft;
    addBox(slide, 0.56, y, 12.00, 0.63, fill, C.line, 0.02, 0.45);
    addBox(slide, 0.56, y, 0.11, 0.63, m[3], m[3], 0, 0);
    addText(slide, m[0], 0.78, y + 0.14, 1.80, 0.28, { fontFace: i === 4 ? 'Arial' : 'Hiragino Sans GB', fontSize: 9.0, color: m[3], bold: true, align: 'center' });
    addText(slide, m[1], 2.77, y + 0.09, 3.50, 0.40, { fontSize: 8.0, color: C.text, align: 'center', valign: 'top' });
    addText(slide, m[2], 6.52, y + 0.09, 5.82, 0.40, { fontSize: 8.0, color: C.text, align: 'center', valign: 'top' });
  });

  addText(slide, 'Paper9 方法组合', 0.71, 5.87, 2.04, 0.29, { fontSize: 12.7, color: C.ink, bold: true });
  const solution = [
    ['学习转移', 'ensemble 预测状态与奖励'],
    ['候选排序', 'pairwise margin loss 区分近似候选'],
    ['多步规划', 'MPC 比较 H=5 的动作序列'],
    ['硬约束门控', 'action mask + area floor + audit gate']
  ];
  solution.forEach((s, i) => {
    const x = 2.77 + i * 2.39;
    addBox(slide, x, 5.73, 2.14, 0.82, i === 3 ? C.greenSoft : C.tealSoft, i === 3 ? C.green : C.teal, 0.05, 0.7);
    addText(slide, s[0], x + 0.11, 5.88, 1.92, 0.24, { fontSize: 9.3, color: i === 3 ? C.green : C.tealDark, bold: true, align: 'center' });
    addText(slide, s[1], x + 0.12, 6.20, 1.90, 0.22, { fontFace: i === 1 ? 'Arial' : 'Hiragino Sans GB', fontSize: 7.2, color: C.text, align: 'center' });
  });
  addText(slide, '工程原则：传统优化、FLUS 与启发式仍应保留为基线；当目标与约束可完全形式化时，经典运筹方法可能更合适。', 1.39, 6.73, 10.54, 0.19, { fontSize: 7.9, color: C.muted, bold: true, align: 'center' });
  addNote(slide,
    '采用 model-based DRL 的理由是问题结构，而不是“深度学习一定优于传统方法”。',
    [
      '耕地布局动作会改变下一步候选空间、坡度组合、连片结构和面积底线，属于序列决策。',
      '贪心策略只看当前一步，可能为了短期坡度收益破坏后续连片机会。',
      'Paper9 同时学习数值转移和候选相对排序，MPC 再在硬约束下搜索动作序列。',
      '经典数学规划、FLUS 和启发式必须作为强基线；没有同题比较就不能主张新方法更优。'
    ],
    ['/Users/zhouning/paper9-mnr-offline-package/docs/16_paper9v2_algorithm_and_image_versioning.md', '/Users/zhouning/paper9-mnr-offline-package/outputs/paper9v2_docker_bishan_dongxing_report_20260627/REPORT.md']
  );
}

function slideTwmBusinessPanorama() {
  const slide = pptx.addSlide();
  addHeader(slide, 22, '业务全景', 'TWM 的自然资源业务价值与应用场景', '支持规划体检、用地审查、土地整治、生态修复和执法督察中的方案比较与证据组织。', '来源：TWM space-intelligence assessment；production input requirements；自然资源规划、用途管制、耕地保护与执法业务语义');

  const rows = [
    ['国土空间规划体检', '规划版本、现状、监测指标、三区三线', '延续 / 调整 / 纠偏 / 重点复核', '偏离趋势、约束风险、受影响单元', '从年度汇总走向滚动诊断'],
    ['建设项目用地预审', '项目范围、用途、控制线、权属与规则', '原案 / 缩减 / 移位 / 补正 / 退回', '硬阻断、替代方案、证据缺口', '减少反复叠加与无效往返'],
    ['耕地保护与土地整治', 'DLTB、坡度、连片、产能、行政单元', '置换 / 整治 / 恢复 / 保护', '可行布局、指标变化、硬门槛', '从单目标评分走向约束方案集'],
    ['执法督察与变化处置', '遥感变化、审批、巡查、历史处置', '核查 / 整改 / 恢复 / 持续监测', '风险排序、扩散轨迹、复核任务', '把有限核查力量投向高风险对象'],
    ['生态保护修复', '生态红线、连通性、退化、项目与资金', '保护 / 修复 / 开发限制 / 时序安排', '生态收益、冲突、外溢与不确定性', '比较多期组合而非只列项目库']
  ];
  const xs = [0.43, 2.53, 5.29, 7.99, 10.50];
  const ws = [2.10, 2.76, 2.70, 2.51, 2.39];
  const heads = ['业务闭环', '权威输入', '候选治理行动', 'TWM 输出', '可衡量价值'];
  heads.forEach((h, i) => {
    addBox(slide, xs[i], 1.57, ws[i], 0.48, i === 0 ? C.dark : C.tealSoft, i === 0 ? C.dark : C.teal, 0.02, 0.6);
    addText(slide, h, xs[i] + 0.05, 1.69, ws[i] - 0.10, 0.24, { fontSize: 8.8, color: i === 0 ? 'FFFFFF' : C.tealDark, bold: true, align: 'center' });
  });
  rows.forEach((r, ri) => {
    const y = 2.05 + ri * 0.88;
    r.forEach((cell, ci) => {
      const fill = ci === 4 ? (ri % 2 === 0 ? C.greenSoft : 'F2F8F3') : (ri % 2 === 0 ? C.paper : C.graySoft);
      addBox(slide, xs[ci], y, ws[ci], 0.88, fill, ci === 4 ? C.green : C.line, 0, ci === 4 ? 0.65 : 0.45);
      addText(slide, cell, xs[ci] + 0.08, y + 0.13, ws[ci] - 0.16, 0.58, { fontSize: ci === 0 ? 8.4 : 7.2, color: ci === 4 ? C.green : (ci === 0 ? C.ink : C.text), bold: ci === 0 || ci === 4, align: 'center', valign: 'top' });
    });
  });
  addBox(slide, 0.72, 6.56, 11.87, 0.33, C.goldSoft, C.gold, 0.04, 0.7);
  addText(slide, '责任边界：模型生成候选与证据任务，业务人员确认规则解释、材料真实性、裁量事项和最终行政决定。', 0.96, 6.63, 11.39, 0.18, { fontSize: 8.4, color: C.ink, bold: true, align: 'center' });
  addNote(slide,
    'TWM 对业务的核心增量，是把静态识别和叠加审查升级为行动后的后果比较。',
    [
      '每个业务场景都必须明确 authoritative inputs、candidate actions、model outputs、human responsibility 和 measurable value。',
      '规划体检与建设项目预审最适合作为首批试点，因为对象、规则、动作和复核结果相对清晰。',
      '违法占地的独立遥感发现仍需要专业遥感模型；TWM 负责接收变化证据并推演处置方案。',
      '生态修复、承载力和人口产业需要额外专业 Kernel，不应被当前 TWM 能力表述覆盖。'
    ],
    ['docs/reports/twm_space_intelligence_core_algorithm_assessment_2026-07-21.md', 'docs/twm-production-input-data-requirements.md']
  );
}

function slideConstructionPreReview() {
  const slide = pptx.addSlide();
  addHeader(slide, 23, '场景一', '建设项目用地预审：可审查替代方案生成与比选', '在统一界面比较原方案、调整方案、风险变化、证据缺口和人工复核任务，最终行政决定仍由业务人员作出。', '场景设计依据：TWM object-relation-rule-evidence state；action-conditioned rollout；evidence gate；用途管制与三区三线业务语义');

  addText(slide, '当前常见工作方式', 0.64, 1.62, 2.42, 0.30, { fontSize: 13.3, color: C.ink, bold: true });
  addBox(slide, 0.64, 2.04, 2.78, 3.99, C.paper, C.line, 0.06, 0.8);
  const current = ['项目红线叠加控制线', '逐条查规则与材料', '发现冲突后退回修改', '新方案再次叠加与核对', '过程依赖经验，替代方案不显式'];
  current.forEach((p, i) => addBullet(slide, p, 0.92, 2.42 + i * 0.60, 2.24, 0.39, { fontSize: 8.8, bulletColor: i === 4 ? C.red : C.muted }));
  addText(slide, '现状：冲突识别较成熟，替代方案生成与后果比较仍依赖人工经验。', 0.91, 5.49, 2.27, 0.32, { fontSize: 7.8, color: C.red, bold: true, align: 'center' });

  addFlowArrow(slide, 3.62, 3.77, 0.47, C.teal);
  addBox(slide, 4.34, 1.82, 5.10, 4.45, C.tealSoft, C.teal, 0.06, 1.0);
  addText(slide, 'TWM 推演闭环', 4.63, 2.08, 4.52, 0.32, { fontSize: 14.3, color: C.tealDark, bold: true, align: 'center' });
  const stages = [
    ['状态', '项目范围 + 永久基本农田 + 生态保护红线 + 城镇开发边界 + 权属 + 规则版本'],
    ['行动', 'A 原案  /  B 缩减  /  C 移位  /  D 补正  /  E 退回'],
    ['推演', '逐方案计算控制线命中、相邻影响、用途一致性、证据完整性与不确定性'],
    ['门控', '硬规则阻断不可行方案；软冲突进入条件支持；证据不足生成 review task'],
    ['结果', '形成方案排序、冲突变化、依据清单、差异图层和复核待办']
  ];
  stages.forEach((st, i) => {
    const y = 2.55 + i * 0.67;
    addPill(slide, st[0], 4.60, y, 0.74, i === 4 ? C.greenSoft : C.paper, i === 4 ? C.green : C.tealDark, i === 4 ? C.greenSoft : C.paper, 7.6);
    addText(slide, st[1], 5.54, y - 0.01, 3.51, 0.43, { fontSize: 7.6, color: C.text, bold: i === 4, valign: 'top' });
  });

  addFlowArrow(slide, 9.68, 3.77, 0.47, C.green);
  addText(slide, '业务输出', 10.31, 1.62, 2.37, 0.30, { fontSize: 13.3, color: C.ink, bold: true });
  const outcomes = [
    ['硬阻断项', '哪些规则不可突破'],
    ['可调整项', '缩减或移位后冲突是否消除'],
    ['代价与收益', '功能保留、用地规模、生态与耕地风险'],
    ['证据缺口', '缺哪份材料、哪条数据需复核'],
    ['全过程 trace', '谁用什么版本数据得出何种判断']
  ];
  outcomes.forEach((o, i) => {
    const y = 2.06 + i * 0.79;
    addBox(slide, 10.26, y, 2.48, 0.62, i === 4 ? C.greenSoft : C.paper, i === 4 ? C.green : C.line, 0.04, 0.7);
    addText(slide, o[0], 10.39, y + 0.10, 0.86, 0.24, { fontSize: 8.1, color: i === 4 ? C.green : C.tealDark, bold: true });
    addText(slide, o[1], 11.22, y + 0.08, 1.37, 0.37, { fontSize: 6.9, color: C.text, valign: 'top' });
  });
  addBox(slide, 0.72, 6.53, 12.00, 0.38, C.dark, C.dark, 0.04, 0);
  addText(slide, '业务价值指标建议：平均往返轮次、单项目 GIS 叠加工时、替代方案采用率、遗漏规则数、复核任务闭环率。', 0.96, 6.61, 11.52, 0.20, { fontSize: 8.6, color: 'FFFFFF', bold: true, align: 'center' });
  addNote(slide,
    '建设项目用地预审是 TWM 最容易被业务理解的场景，因为输入、冲突、动作和最终处置都相对清晰。',
    [
      '传统叠加分析擅长发现项目与控制线的空间冲突，但通常不自动形成可比较的替代方案轨迹。',
      'TWM 把原方案、缩减、移位、补正和退回定义为 canonical actions，在统一状态上推演。',
      '硬规则直接阻断，软规则与证据不足进入 review_required，行政裁量仍由审批人员承担。',
      '试点成效不应只看模型精度，还应看往返轮次、审查工时、遗漏规则和 trace 完整性。'
    ],
    ['docs/twm-complete-world-model-contracts-and-research-discipline-2026-07-03.md', 'docs/twm-production-input-data-requirements.md', 'data_agent/territory_world_model/']
  );
}

function slideFarmlandTwm() {
  const slide = pptx.addSlide();
  addHeader(slide, 24, '场景二', '耕地保护与土地整治：从优化候选到在线多期推演', 'Paper9 提供布局优化候选，TWM 用严格状态转移、硬约束重算和轨迹规划形成可审计方案比较。', '来源：Paper9v2 workflow / reports；TWM spatial simulator / planner；GWM Runtime relationship');

  addBox(slide, 0.58, 1.71, 4.07, 4.68, C.blueSoft, C.blue, 0.06, 0.9);
  addText(slide, 'Paper9：优化与规划组件', 0.89, 2.01, 3.45, 0.33, { fontSize: 14.3, color: C.blue, bold: true, align: 'center' });
  const paper9 = [
    ['状态', '县域图斑、坡度、连片、百亩方'],
    ['动作', '受约束的耕地 / 非耕地图斑置换'],
    ['模型', '转移 ensemble + pairwise ranking'],
    ['规划', 'MPC 搜索多步候选动作'],
    ['审计', '面积不减、坡度下降、连片提升']
  ];
  paper9.forEach((p, i) => {
    const y = 2.62 + i * 0.58;
    addPill(slide, p[0], 0.91, y, 0.73, C.paper, C.blue, C.paper, 7.3);
    addText(slide, p[1], 1.84, y - 0.01, 2.45, 0.30, { fontFace: i === 2 || i === 3 ? 'Arial' : 'Hiragino Sans GB', fontSize: 8.1, color: C.text, bold: i === 4 });
  });
  addBox(slide, 0.93, 5.67, 3.38, 0.44, C.paper, C.blue, 0.04, 0.7);
  addText(slide, '产物：优化图斑 + MPC summary + audit summary', 1.07, 5.77, 3.10, 0.22, { fontFace: 'Arial', fontSize: 7.6, color: C.blue, bold: true, align: 'center' });

  addFlowArrow(slide, 4.89, 3.88, 0.61, C.violet);
  addText(slide, '作为 planner / transition backend 接入', 4.77, 3.29, 0.87, 0.47, { fontFace: 'Arial', fontSize: 6.8, color: C.violet, bold: true, align: 'center' });

  addBox(slide, 5.76, 1.71, 6.98, 4.68, C.tealSoft, C.teal, 0.06, 1.0);
  addText(slide, 'TWM：自然资源治理世界模型', 6.12, 2.01, 6.25, 0.33, { fontSize: 14.3, color: C.tealDark, bold: true, align: 'center' });
  const twm = [
    ['候选准入', '7 个候选先做空间与法定硬约束审查；4 个阻断，3 个进入合法可行域'],
    ['在线转移', '3 个合法方案各执行 3 期：Sₜ + ΔAₜ → Sₜ₊₁，共 9 次状态转移'],
    ['逐期重算', '每期重建累计几何，重算空间关系、永久基本农田、生态红线与空间目标'],
    ['轨迹规划', 'Planner 只读取完整 trace 做跨期累计排序；旧分数和人为高分不参与选优'],
    ['失败关闭', '缺少动作几何、父子状态不连续或轨迹不完整时不产生该方案推荐']
  ];
  twm.forEach((t, i) => {
    const y = 2.58 + i * 0.62;
    addPill(slide, t[0], 6.08, y, 1.02, i === 4 ? C.greenSoft : C.paper, i === 4 ? C.green : C.tealDark, i === 4 ? C.greenSoft : C.paper, 7.2);
    addText(slide, t[1], 7.31, y - 0.01, 4.92, 0.39, { fontSize: 7.5, color: C.text, bold: i === 4, valign: 'top' });
  });
  addBox(slide, 6.10, 5.78, 6.22, 0.33, C.greenSoft, C.green, 0.04, 0.6);
  addText(slide, '当前后端：确定性 GIS / 规则机制；在线递归执行，不消费预计算时期状态', 6.29, 5.85, 5.83, 0.18, { fontSize: 8.1, color: C.green, bold: true, align: 'center' });

  addBox(slide, 0.72, 6.58, 11.89, 0.32, C.goldSoft, C.gold, 0.04, 0.7);
  addText(slide, '当前验证范围：TWM 严格执行链已完成工程验收；真实政策效果、学习型动力学与省域泛化仍待业务历史验证。', 0.95, 6.64, 11.43, 0.18, { fontSize: 8.3, color: C.ink, bold: true, align: 'center' });
  addNote(slide,
    'Paper9 与 TWM 是组件和系统的关系，不应把 Paper9 直接等同于完整世界模型。',
    [
      'Paper9 已经提供可部署的 transition ensemble、MPC planner、业务硬约束和 audit。',
      '当前 TWM 演示不把 Paper9 置换次数冒充 TWM 推演次数；本次严格执行为 3 个合法方案乘 3 期，共 9 次转移。',
      'Simulator 在线写回父子状态并重算关系、约束和目标；Planner 只消费完整 trace。',
      '当前结果证明工程机制真实执行，不证明政策因果效果或生产最优；新增主张仍需真实行动-结果和跨区留出。'
    ],
    ['/Users/zhouning/paper9-mnr-offline-package/README.md', 'docs/twm-renderer-simulator-planner-technical-core.md', 'docs/research/GWM_RUNTIME_KERNEL_AND_GEOSPATIAL_KERNEL_RELATIONSHIP.md']
  );
}

function slideEvidenceAndLanding() {
  const slide = pptx.addSlide();
  addHeader(slide, 26, '证据与落地', '省级试点：证据分层与分阶段实施路径', '现有工程和研究证据已具备联合试点基础，省域通用能力需通过真实业务闭环逐级验证。', '来源：Paper9v2 E2E；TWM runtime benchmark / validation bundle；DAM-GK terminal adjudication；production input requirements');

  const evidence = [
    ['已有工程证据', C.green, C.greenSoft, ['Paper9 双县真实数据 E2E hard gate 通过', 'TWM：3 个合法方案 × 3 期在线递归转移', '9 次状态写回、约束重算与 trace-only 选优通过']],
    ['已有研究证据', C.gold, C.goldSoft, ['TWM / FLUS 多协议比较已报告正负结果', 'Runtime 合成留出证明原型机制可运行', 'DAM-GK v0.1：H1-H5 rejected；H6 超出本版范围']],
    ['试点补充项', C.red, C.redSoft, ['真实审批 / 整治的状态-行动-结果链', '跨区域、跨政策版本 temporal / spatial holdout', '共享 Runtime / Kernel 验证、负对照、因果与不确定性校准']]
  ];
  evidence.forEach((col, i) => {
    const x = 0.60 + i * 4.18;
    addBox(slide, x, 1.63, 3.75, 2.10, C.paper, col[1], 0.05, 0.9);
    addBox(slide, x, 1.63, 3.75, 0.49, col[2], col[1], 0.05, 0.7);
    addText(slide, col[0], x + 0.14, 1.76, 3.47, 0.24, { fontSize: 11.2, color: col[1], bold: true, align: 'center' });
    col[3].forEach((p, j) => addBullet(slide, p, x + 0.24, 2.34 + j * 0.43, 3.25, 0.31, { fontSize: 7.7, bulletColor: col[1] }));
  });

  addText(slide, '建议省级试点路径', 0.67, 4.08, 2.42, 0.30, { fontSize: 13.4, color: C.ink, bold: true });
  const phases = [
    ['0-3 个月', '闭环与数据契约', '选建设用地预审或耕地保护；冻结对象、动作、结果、政策版本、基线与权限。', C.blue, C.blueSoft],
    ['3-9 个月', '影子运行与同题验证', '接入历史处置；对照人工 GIS、规则引擎、FLUS / 传统优化；做时间与区域留出。', C.teal, C.tealSoft],
    ['9-18 个月', '受控生产与扩展', '只输出辅助结论；上线回滚和审计；完成共享 Runtime / Kernel 绑定后再扩展专业 Kernel。', C.green, C.greenSoft]
  ];
  phases.forEach((p, i) => {
    const x = 0.70 + i * 4.17;
    addBox(slide, x, 4.53, 3.77, 1.45, p[4], p[3], 0.05, 0.8);
    addPill(slide, p[0], x + 0.18, 4.69, 1.04, C.paper, p[3], C.paper, 7.2);
    addText(slide, p[1], x + 1.40, 4.69, 2.12, 0.24, { fontSize: 9.7, color: p[3], bold: true, align: 'center' });
    addText(slide, p[2], x + 0.22, 5.15, 3.33, 0.55, { fontSize: 7.4, color: C.text, align: 'center', valign: 'top' });
    if (i < phases.length - 1) addFlowArrow(slide, x + 3.82, 5.24, 0.28, C.muted);
  });
  addBox(slide, 0.72, 6.36, 11.87, 0.51, C.dark, C.dark, 0.04, 0);
  addText(slide, '首期验收重点：数据可追溯、动作可定义、结果可验证、失败可复演、结论可降级。', 0.95, 6.47, 11.43, 0.25, { fontSize: 8.7, color: 'FFFFFF', bold: true, align: 'center' });
  addNote(slide,
    '当前证据足以支撑联合试点和影子运行，不足以支撑省域生产通用主张。',
    [
      'Paper9 的真实数据离线 E2E 是当前最扎实的落地证据，但它验证的是特定耕地优化流程。',
      'TWM 已有完整 schema 与原型运行链路，核心 trainable dynamics 仍缺自然资源真实行动结果训练。',
      'DAM-GK v0.1 的 H1-H5 终局状态为 rejected；H6 为 out_of_scope_for_this_release，后续必须在新版本、预冻结协议和负对照下重试。',
      '省级试点应先锁定一条业务闭环，以影子运行积累行动-结果样本，再决定生产主张升级。'
    ],
    ['/Users/zhouning/paper9-mnr-offline-package/outputs/paper9v2_docker_bishan_dongxing_report_20260627/REPORT.md', 'docs/reports/twm_runtime_benchmark_v1.json', 'docs/reports/twm_validation_bundle.json', 'docs/research/DAM_GK_RESEARCH_SPEC.md']
  );
}

async function main() {
  [
    slide01, slideAgenda, slide02, slideWorldModelLandscape, slideGwmDistinctivePosition,
    slide03, slideConventionalLimits, slidePaper9Deployment, slide04,
    slideStateActionOutcomeDifference, slideStateActionOutcomeDataContract,
    slide05, slide06, slide07, slide08, slide09, slide10,
    slide11, slideSimulatorComparison, slide12, slide13, slide14, slideTwmBusinessPanorama,
    slideConstructionPreReview, slideFarmlandTwm, slide15,
    slideEvidenceAndLanding, slide18, slide19
  ].forEach((makeSlide) => makeSlide());
  await pptx.writeFile({ fileName: PPTX_OUT });
  process.stdout.write(`${PPTX_OUT}\n`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
