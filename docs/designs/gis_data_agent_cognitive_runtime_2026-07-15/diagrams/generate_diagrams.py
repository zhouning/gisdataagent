#!/usr/bin/env python3
"""Render formal Chinese Cognitive Runtime diagrams to high-resolution PNG."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parent
FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"

NAVY = "#17324D"
BLUE = "#2F6B9A"
LIGHT_BLUE = "#DCEAF5"
CYAN = "#DDF3F4"
GREEN = "#DDEEDC"
YELLOW = "#FFF0C9"
ORANGE = "#F9DEC2"
RED = "#F4D7D7"
PURPLE = "#E8DFF2"
GRAY = "#EEF1F4"
DARK_GRAY = "#4D5B66"
WHITE = "#FFFFFF"


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size=size)


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            candidate = current + char
            box = draw.textbbox((0, 0), candidate, font=fnt)
            if current and box[2] - box[0] > width:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines


def title(draw, text: str, width: int, subtitle: str = "") -> None:
    f = font(46)
    box = draw.textbbox((0, 0), text, font=f)
    draw.text(((width - (box[2] - box[0])) / 2, 34), text, font=f, fill=NAVY)
    if subtitle:
        sf = font(23)
        sbox = draw.textbbox((0, 0), subtitle, font=sf)
        draw.text(((width - (sbox[2] - sbox[0])) / 2, 94), subtitle, font=sf, fill=DARK_GRAY)


def box(draw, xy, text: str, fill: str, outline: str = BLUE, radius: int = 20,
        text_fill: str = NAVY, fsize: int = 25, width_pad: int = 28) -> None:
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=3)
    f = font(fsize)
    lines = wrap(draw, text, f, max(20, x2 - x1 - width_pad * 2))
    line_h = fsize + 9
    total_h = len(lines) * line_h
    y = y1 + (y2 - y1 - total_h) / 2
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=f)
        draw.text((x1 + (x2 - x1 - (bb[2] - bb[0])) / 2, y), line, font=f, fill=text_fill)
        y += line_h


def arrow(draw, start, end, color: str = BLUE, width: int = 5, label: str = "") -> None:
    x1, y1 = start
    x2, y2 = end
    draw.line((x1, y1, x2, y2), fill=color, width=width)
    angle = math.atan2(y2 - y1, x2 - x1)
    size = 16
    pts = [
        (x2, y2),
        (x2 - size * math.cos(angle - 0.55), y2 - size * math.sin(angle - 0.55)),
        (x2 - size * math.cos(angle + 0.55), y2 - size * math.sin(angle + 0.55)),
    ]
    draw.polygon(pts, fill=color)
    if label:
        f = font(19)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        bb = draw.textbbox((0, 0), label, font=f)
        draw.rounded_rectangle((mx - (bb[2]-bb[0])/2 - 7, my - 16,
                                mx + (bb[2]-bb[0])/2 + 7, my + 16),
                               radius=6, fill=WHITE)
        draw.text((mx - (bb[2]-bb[0])/2, my - 13), label, font=f, fill=DARK_GRAY)


def canvas(title_text: str, subtitle: str = "", width: int = 2000, height: int = 1200):
    image = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(image)
    title(draw, title_text, width, subtitle)
    return image, draw


def save(image: Image.Image, name: str) -> None:
    image.save(ROOT / f"{name}.png", dpi=(180, 180), optimize=True)


def generate_contact_sheet() -> None:
    names = [
        "01_overall_architecture",
        "02_cognitive_loop_state",
        "03_knowledge_evidence_architecture",
        "04_standard_governance_sequence",
        "05_self_evolution_pipeline",
        "06_deployment_evolution",
        "07_core_data_model",
        "08_ontology_production_architecture",
        "09_operational_ontology_action_loop",
        "10_heavy_ontology_platform_architecture",
    ]
    sheet = Image.new("RGB", (2000, 3200), WHITE)
    draw = ImageDraw.Draw(sheet)
    label_font = font(22)
    for idx, name in enumerate(names):
        col = idx % 2
        row = idx // 2
        x = 25 + col * 990
        y = 25 + row * 630
        draw.text((x, y), name, font=label_font, fill=NAVY)
        source = Image.open(ROOT / f"{name}.png").convert("RGB")
        thumb = ImageOps.contain(source, (940, 560), method=Image.Resampling.LANCZOS)
        sheet.paste(thumb, (x, y + 38))
    sheet.save(ROOT / "contact_sheet.png", dpi=(120, 120), optimize=True)


def overall_architecture() -> None:
    im, d = canvas("GIS Data Agent Cognitive Runtime 总体架构", "目标设计：统一控制、共享工作区、专业执行与受控进化")
    box(d, (610, 135, 1390, 225), "UI / API / Queue / MCP / A2A / Bot", GRAY)
    box(d, (500, 270, 1500, 365), "Runtime Control Plane\nIdentity · Policy · Budget · Trace · Checkpoint", LIGHT_BLUE)
    box(d, (430, 410, 1570, 510), "Cognitive Workspace\nGoal · Plan · Evidence · Memory · Observations · Risk · Versions", CYAN)
    box(d, (700, 555, 1300, 635), "Deterministic Attention Router", YELLOW)
    modules = ["Perception", "Retrieval", "Planning", "Execution", "Evaluation", "HITL"]
    fills = [LIGHT_BLUE, PURPLE, CYAN, GREEN, ORANGE, RED]
    for i, (name, fill) in enumerate(zip(modules, fills)):
        x1 = 120 + i * 300
        box(d, (x1, 700, x1 + 250, 790), name, fill, fsize=23)
        arrow(d, (1000, 635), (x1 + 125, 700), width=3)
    box(d, (120, 860, 930, 960), "Knowledge Plane\nStandards · Domain Ontology · Semantic Layer · KB · Graph · APIs · Memory", PURPLE, fsize=22)
    box(d, (1070, 860, 1880, 960), "Execution Plane\nSQL · PostGIS · ArcPy · Governance · TWM · Reporting", GREEN)
    box(d, (430, 1020, 1570, 1125), "Learning & Evolution Plane\nCandidate → Eval → Shadow → Canary → Promotion / Rollback", ORANGE)
    arrow(d, (1000, 225), (1000, 270))
    arrow(d, (1000, 365), (1000, 410))
    arrow(d, (1000, 510), (1000, 555))
    arrow(d, (525, 860), (720, 790), width=4)
    arrow(d, (1475, 860), (1325, 790), width=4)
    arrow(d, (1000, 960), (1000, 1020))
    save(im, "01_overall_architecture")


def cognitive_loop() -> None:
    im, d = canvas("认知闭环状态机", "代码控制状态转移；LLM 只提出候选判断")
    nodes = {
        "感知": (120, 180, 400, 275, LIGHT_BLUE),
        "澄清": (120, 420, 400, 515, GRAY),
        "检索": (500, 180, 780, 275, PURPLE),
        "规划": (880, 180, 1160, 275, CYAN),
        "执行": (1260, 180, 1540, 275, GREEN),
        "评价": (1620, 420, 1900, 515, ORANGE),
        "HITL": (1260, 680, 1540, 775, RED),
        "响应": (880, 900, 1160, 995, GREEN),
        "安全结束": (1620, 900, 1900, 995, GRAY),
    }
    for name, (x1, y1, x2, y2, fill) in nodes.items():
        box(d, (x1, y1, x2, y2), name, fill, fsize=28)
    arrow(d, (400, 227), (500, 227), label="信息完整")
    arrow(d, (260, 275), (260, 420), label="缺少输入")
    arrow(d, (400, 467), (500, 260), label="补充后")
    arrow(d, (780, 227), (880, 227))
    arrow(d, (1160, 227), (1260, 227))
    arrow(d, (1540, 260), (1700, 420))
    arrow(d, (1620, 467), (1160, 245), label="重规划")
    arrow(d, (1620, 490), (780, 260), label="证据缺口")
    arrow(d, (1700, 515), (1400, 680), label="高风险/冲突")
    arrow(d, (1260, 727), (1160, 950), label="拒绝/升级")
    arrow(d, (1400, 680), (1400, 275), label="批准")
    arrow(d, (1620, 515), (1080, 900), label="通过")
    arrow(d, (1800, 515), (1800, 900), label="停滞/预算")
    save(im, "02_cognitive_loop_state")


def knowledge_architecture() -> None:
    im, d = canvas("多源知识与 EvidenceBundle 架构", "不同知识使用不同真值机制，统一以证据契约供认知模块消费")
    sources = [
        ("规范知识\n标准 · 法规 · 政策", LIGHT_BLUE),
        ("语义知识\n术语 · 本体 · 字段 · 血缘", CYAN),
        ("运行事实\nSQL · PostGIS · ArcPy · API", GREEN),
        ("程序知识\nWorkflow · Skill · Capability", YELLOW),
        ("经验知识\nEpisodic · Procedural Memory", PURPLE),
    ]
    for i, (text, fill) in enumerate(sources):
        y = 155 + i * 180
        box(d, (90, y, 560, y + 120), text, fill, fsize=24)
        arrow(d, (560, y + 60), (760, 520), width=3)
    box(d, (760, 370, 1180, 670), "Hybrid Retrieval + Ontology Resolver\nACL · Time · Region · Version\nFTS · Vector · SQL · Graph · Spatial\nBinding · Fusion · Conflict Check", ORANGE, fsize=23)
    box(d, (1300, 405, 1720, 635), "EvidenceBundle\nItems · Rules · Conflicts\nCoverage · Missing Evidence\nAuthority · Verification", LIGHT_BLUE, fsize=24)
    arrow(d, (1180, 520), (1300, 520))
    consumers = ["Planner", "Evaluator", "Report/HITL"]
    for i, name in enumerate(consumers):
        y = 230 + i * 290
        box(d, (1770, y, 1960, y + 100), name, GRAY, fsize=22)
        arrow(d, (1720, 520), (1770, y + 50), width=3)
    save(im, "03_knowledge_evidence_architecture")


def ontology_architecture() -> None:
    im, d = canvas(
        "领域本体生产架构",
        "PostgreSQL 保存权威写模型；本体包和检索/图/RDF均是可重建、可版本化的读投影",
    )
    sources = [
        ("Standards Platform\n条款 · 术语 · 数据元 · 值域", LIGHT_BLUE),
        ("现有本体原型\nGIS YAML · MMFE Ontology", CYAN),
        ("运行语义\n资产 · 字段 · Capability · 工具", GREEN),
    ]
    for i, (label, fill) in enumerate(sources):
        y = 150 + i * 210
        box(d, (70, y, 500, y + 130), label, fill, fsize=23)
        arrow(d, (500, y + 65), (660, 435), width=3)

    box(d, (660, 260, 1120, 420), "Ontology Knowledge Compiler\n提取 · 映射 · 冲突检测 · 安全 DSL 编译", ORANGE, fsize=23)
    box(d, (660, 490, 1120, 650), "Canonical Authority Store\nPostgreSQL · version · ACL\nprovenance · review", LIGHT_BLUE, fsize=23)
    arrow(d, (890, 420), (890, 490))

    projections = [
        ("Stage 1\nSQL / ltree / FTS / pgvector", CYAN),
        ("Stage 2\nSKOS · SHACL · JSON-LD/RDF", PURPLE),
        ("Stage 3（按门引入）\nSPARQL / Dedicated Graph Read Model", YELLOW),
    ]
    for i, (label, fill) in enumerate(projections):
        y = 150 + i * 220
        box(d, (1270, y, 1880, y + 140), label, fill, fsize=22)
        arrow(d, (1120, 570), (1270, y + 70), width=3)

    box(d, (470, 790, 1050, 940), "Immutable OntologyPackage\nconcepts · relations · constraints · mappings\nvalidity · authority · hash · parent version", PURPLE, fsize=22)
    box(d, (1160, 790, 1740, 940), "OntologyResolver\nidentity-aware · bounded traversal\nexplainable binding · conflict report", GREEN, fsize=22)
    arrow(d, (890, 650), (760, 790))
    arrow(d, (1050, 865), (1160, 865))

    consumers = ["EvidenceBundle", "Planner / TaskGraph", "Evaluator", "Capability Registry"]
    for i, label in enumerate(consumers):
        x = 110 + i * 465
        box(d, (x, 1020, x + 360, 1110), label, GRAY, fsize=20)
        arrow(d, (1450, 940), (x + 180, 1020), width=3)
    save(im, "08_ontology_production_architecture")


def operational_ontology() -> None:
    im, d = canvas(
        "Operational Ontology 与对象行动闭环",
        "把领域知识、真实业务对象、权限、Action、Capability、工具写回和评价连接为同一契约",
    )
    box(d, (70, 160, 470, 300), "Domain Ontology\nStandard · Concept · Rule · Evidence", PURPLE, fsize=22)
    box(d, (580, 130, 1010, 330), "Operational Object Model\nObjectType · PropertyType\nLinkType · ObjectInstanceRef · State", LIGHT_BLUE, fsize=20)
    box(d, (1120, 130, 1550, 330), "Action Model\nActionType · FunctionType\nInterfaceType · Precondition\nPolicy · Side Effect", ORANGE, fsize=20)
    box(d, (1660, 160, 1930, 300), "Capability Registry\nSpecialist\nTool Manifest", CYAN, fsize=19)
    arrow(d, (470, 230), (580, 230), label="grounds")
    arrow(d, (1010, 230), (1120, 230), label="acts on")
    arrow(d, (1550, 230), (1660, 230), label="binds")

    box(d, (220, 450, 650, 610), "Dynamic Policy Decision\nobject · property · link\naction · result", RED, fsize=21)
    box(d, (785, 450, 1215, 610), "Cognitive Runtime\nTaskGraph · Workspace\nEvidenceBundle · HITL\nBudget · Checkpoint", YELLOW, fsize=20)
    box(d, (1350, 450, 1780, 610), "Specialist Execution\nSQL · PostGIS · ArcPy\nStandards · TWM", GREEN, fsize=21)
    arrow(d, (435, 450), (795, 330), label="authorizes")
    arrow(d, (1000, 330), (1000, 450))
    arrow(d, (1215, 530), (1350, 530), label="typed invocation")

    box(d, (220, 750, 650, 900), "ChangeSet\nexpected transition · lineage\nidempotency · compensation", CYAN, fsize=21)
    box(d, (785, 750, 1215, 900), "ActionResult\nobservations · artifacts\nobject refs · actual changes · failures", LIGHT_BLUE, fsize=20)
    box(d, (1350, 750, 1780, 900), "Independent Evaluator / HITL\ncontract · evidence\ndomain · outcome", ORANGE, fsize=21)
    arrow(d, (1565, 610), (1000, 750), label="returns")
    arrow(d, (785, 825), (650, 825), label="compares")
    arrow(d, (1215, 825), (1350, 825), label="verifies")

    box(d, (120, 1010, 720, 1110), "Typed Consumption Layer\nPython SDK · TypeScript SDK · MCP/A2A Schema", GRAY, fsize=21)
    box(d, (1280, 1010, 1880, 1110), "Versioned Writeback\nnew object state · event · audit · rollback", GREEN, fsize=21)
    arrow(d, (420, 1010), (800, 610), width=3)
    arrow(d, (1565, 900), (1580, 1010), label="pass / approve")
    save(im, "09_operational_ontology_action_loop")


def heavy_ontology_platform() -> None:
    im, d = canvas(
        "重型本体生产平台架构",
        "条件目标：语义治理、形式推理、运营对象、安全策略和真实执行形成可发布、可对账、可恢复的平台",
        height=1400,
    )

    # Control and governance plane.
    box(d, (60, 145, 440, 285), "Ontology Studio / Governance\n术语 · 模型 · 映射 · 评审", LIGHT_BLUE, fsize=21)
    box(d, (525, 145, 980, 285), "Canonical Model Registry\nnamespace · version · provenance · ACL", LIGHT_BLUE, fsize=20)
    box(d, (1065, 145, 1460, 285), "Ontology CI/CD\nSHACL · 兼容性 · 安全 · 发布 · 回滚", LIGHT_BLUE, fsize=20)
    box(d, (1545, 145, 1940, 285), "Operations\nOTel · SLO · HA\nBackup/DR", GRAY, fsize=20)
    arrow(d, (440, 215), (525, 215))
    arrow(d, (980, 215), (1065, 215))

    # Ingestion and event propagation.
    box(d, (60, 385, 440, 535), "Ingestion / Mapping\nStandards · XMI · JSON-LD\n外部本体 · 业务元数据", YELLOW, fsize=20)
    box(d, (610, 385, 1010, 535), "Kafka / Redpanda + Outbox\n版本化变更事件 · 重放 · DLQ", ORANGE, fsize=20)
    box(d, (1180, 385, 1580, 535), "Projection Reconciler\nhash · checkpoint\nlag · rebuild", ORANGE, fsize=20)
    arrow(d, (250, 385), (745, 285), label="candidate")
    arrow(d, (1260, 285), (810, 385), label="release")
    arrow(d, (1010, 460), (1180, 460))

    # Semantic and operational read models.
    stores = [
        ("RDF / OWL / SHACL Store\nSKOS · PROV-O · GeoSPARQL\nOWL-Time · bounded reasoning", PURPLE),
        ("Operational Object Graph\nObject · Property · Link · State\nAction binding · lineage", CYAN),
        ("Search / Vector Projections\nFTS · embedding · rerank\n只读、可重建", YELLOW),
    ]
    for i, (label, fill) in enumerate(stores):
        x = 70 + i * 650
        box(d, (x, 650, x + 540, 835), label, fill, fsize=20)
        arrow(d, (1380, 535), (x + 270, 650), width=3)

    # Runtime serving and policy plane.
    box(d, (90, 965, 550, 1125), "Semantic Query Gateway\nSPARQL · Graph · SQL federation\nEvidenceBundle · query budget", LIGHT_BLUE, fsize=20)
    box(d, (770, 965, 1230, 1125), "Dynamic Policy Engine\nobject · property · link · action\ndeny / allow / requires-approval", RED, fsize=20)
    box(d, (1450, 965, 1910, 1125), "Object & Action Service\nAction · Function · Interface\nSDK · audit · writeback", GREEN, fsize=20)
    for x in (340, 990, 1640):
        arrow(d, (x, 835), (320, 965), width=3)
    arrow(d, (550, 1045), (770, 1045))
    arrow(d, (1230, 1045), (1450, 1045))

    # Truth and execution boundary.
    box(d, (60, 1240, 430, 1360), "PostgreSQL / PostGIS\n业务与事务真值", GREEN, fsize=21)
    box(d, (520, 1240, 890, 1360), "Standards Platform\n标准审定与发布权威", LIGHT_BLUE, fsize=21)
    box(d, (1050, 1240, 1420, 1360), "Cognitive Runtime\nPlanning · Evidence · HITL", YELLOW, fsize=20)
    box(d, (1510, 1240, 1940, 1360), "Capability Plane\nSQL · PostGIS · ArcPy\nTWM · MCP · controlled writeback", CYAN, fsize=18)
    arrow(d, (1240, 1240), (320, 1125), label="query")
    arrow(d, (1235, 1300), (1510, 1300), label="typed action")
    arrow(d, (1725, 1240), (1680, 1125), label="result")
    save(im, "10_heavy_ontology_platform_architecture")


def governance_sequence() -> None:
    im, d = canvas("数据标准驱动治理时序", "首条端到端验收链：知识、规划、执行、评价、HITL 和真实产物")
    actors = ["用户", "Cognitive\nRuntime", "标准知识", "Planner", "GIS\nSpecialist", "Evaluator\n/HITL"]
    xs = [140, 470, 800, 1130, 1460, 1790]
    for x, actor in zip(xs, actors):
        box(d, (x - 110, 145, x + 110, 235), actor, LIGHT_BLUE, fsize=22)
        d.line((x, 235, x, 1110), fill="#9AA7B2", width=3)
    messages = [
        (0, 1, "治理目标 + 数据资产", 290),
        (1, 2, "检索现行标准和规则", 390),
        (2, 1, "EvidenceBundle + KnowledgePack", 490),
        (1, 3, "生成 typed TaskGraph", 590),
        (3, 1, "计划 + 验证规则", 690),
        (1, 5, "高风险写入审批", 790),
        (5, 1, "批准 / 拒绝", 870),
        (1, 4, "画像、映射、治理和产物", 950),
        (4, 1, "版本化产物 + observations", 1030),
    ]
    for a, b, label, y in messages:
        arrow(d, (xs[a], y), (xs[b], y), width=4, label=label)
    save(im, "04_standard_governance_sequence")


def evolution_pipeline() -> None:
    im, d = canvas("受控自我进化流水线", "任何变化先成为候选，经过独立评测、灰度和可回滚晋级")
    steps = [
        ("生产 Trace\n反馈与结果", LIGHT_BLUE),
        ("失败归因", ORANGE),
        ("Evolution\nEvent", PURPLE),
        ("Candidate\nArtifact", CYAN),
        ("Regression\nReplay · Holdout", YELLOW),
        ("Promotion\nGovernor", RED),
        ("Shadow", GRAY),
        ("Canary", LIGHT_BLUE),
        ("Promote /\nRollback", GREEN),
    ]
    positions = []
    for i, (text, fill) in enumerate(steps):
        if i < 6:
            x, y = 55 + i * 320, 250
        else:
            x, y = 375 + (i - 6) * 520, 700
        positions.append((x, y))
        box(d, (x, y, x + 260, y + 130), text, fill, fsize=21)
    for i in range(5):
        arrow(d, (positions[i][0] + 260, positions[i][1] + 65),
              (positions[i+1][0], positions[i+1][1] + 65))
    arrow(d, (positions[5][0] + 130, 380), (positions[6][0] + 130, 700), label="通过")
    arrow(d, (positions[6][0] + 260, 765), (positions[7][0], 765))
    arrow(d, (positions[7][0] + 260, 765), (positions[8][0], 765))
    arrow(d, (positions[5][0], 315), (positions[3][0] + 260, 315), color="#B54545", label="拒绝/修订")
    arrow(d, (positions[8][0] + 130, 830), (positions[0][0] + 130, 900), color="#507A55", label="持续监控")
    save(im, "05_self_evolution_pipeline")


def deployment_evolution() -> None:
    im, d = canvas("Cognitive Runtime 部署演进", "按真实容量和隔离需求演进，不以微服务数量代表先进性")
    stages = [
        ("阶段 A\n模块化单体", "Runtime\nPostgreSQL + pgvector\n现有 Worker", LIGHT_BLUE),
        ("阶段 B\n后台 Worker", "索引构建\n记忆压缩\n候选评测", CYAN),
        ("阶段 C\n能力服务", "ArcPy · GIS\nTWM · 模型推理\n独立扩缩容", GREEN),
        ("阶段 D\n联邦 Specialist", "MCP / A2A\n跨组织能力\n统一身份与策略", PURPLE),
    ]
    for i, (head, body, fill) in enumerate(stages):
        x = 90 + i * 475
        box(d, (x, 220, x + 390, 390), head, fill, fsize=30)
        box(d, (x, 445, x + 390, 760), body, GRAY, fsize=25)
        if i < 3:
            arrow(d, (x + 390, 530), (x + 475, 530), width=6)
    box(d, (360, 870, 1640, 1030), "稳定不变的核心\nTyped Contracts · Workspace · Evidence · Policy\nEvaluation · Evolution Governance", YELLOW, fsize=22)
    save(im, "06_deployment_evolution")


def data_model() -> None:
    im, d = canvas("Cognitive Runtime 核心逻辑数据模型", "目标逻辑模型：最终物理 DDL、分区、索引和保留期需在 Runtime Kernel 子项目中确定")
    entities = {
        "agent_brain_run": (760, 160, LIGHT_BLUE),
        "agent_brain_event": (120, 390, GRAY),
        "agent_brain_checkpoint": (520, 390, CYAN),
        "agent_evidence_item": (920, 390, PURPLE),
        "agent_memory_item": (1320, 390, GREEN),
        "agent_evolution_event": (760, 660, ORANGE),
        "agent_evolution\n_candidate": (1180, 660, YELLOW),
        "agent_candidate_eval": (1520, 880, GRAY),
        "agent_promotion": (760, 880, RED),
        "agent_runtime_version": (260, 880, LIGHT_BLUE),
    }
    coords = {}
    for name, (x, y, fill) in entities.items():
        coords[name] = (x, y, x + 330, y + 110)
        box(d, coords[name], name, fill, fsize=20)
    run_center = (925, 270)
    for name in ["agent_brain_event", "agent_brain_checkpoint", "agent_evidence_item", "agent_memory_item", "agent_evolution_event"]:
        x1, y1, x2, y2 = coords[name]
        arrow(d, run_center, ((x1+x2)//2, y1), width=3)
    candidate_key = "agent_evolution\n_candidate"
    arrow(d, (1090, 715), (1180, 715), label="proposes")
    arrow(d, (1345, 770), (1685, 880), label="evaluated by")
    arrow(d, (coords[candidate_key][0], 715), (1090, 935), label="promoted by")
    arrow(d, (760, 935), (590, 935), label="creates")
    save(im, "07_core_data_model")


def main() -> None:
    overall_architecture()
    cognitive_loop()
    knowledge_architecture()
    governance_sequence()
    evolution_pipeline()
    deployment_evolution()
    data_model()
    ontology_architecture()
    operational_ontology()
    heavy_ontology_platform()
    generate_contact_sheet()
    print("Generated 10 diagrams in", ROOT)


if __name__ == "__main__":
    main()
