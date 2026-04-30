"""Register Chinese aliases for BIRD tables and columns to enable
cross-lingual NL2SQL queries (Chinese question → English BIRD tables).

This script merges Chinese synonyms into existing agent_semantic_sources
and agent_semantic_registry rows for bird_* schemas. It does NOT replace
existing English synonyms — it appends Chinese ones.

Usage:
  cd D:\\adk
  $env:PYTHONPATH="D:\\adk"
  .venv\\Scripts\\python.exe scripts/nl2sql_bench_bird/register_chinese_aliases.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parents[2] / "data_agent" / ".env"), override=True)

from data_agent.db_engine import get_engine  # noqa: E402

OWNER = "bird_benchmark"


# Curated Chinese aliases for the most-queried BIRD tables. Aliases focus on
# tables where Chinese users are likely to ask domain-natural questions.
TABLE_ALIASES: dict[str, list[str]] = {
    # debit_card_specializing
    "bird_debit_card_specializing.customers": ["客户", "顾客", "持卡人"],
    "bird_debit_card_specializing.gasstations": ["加油站", "油站"],
    "bird_debit_card_specializing.products": ["产品", "商品"],
    "bird_debit_card_specializing.transactions_1k": ["交易", "交易记录"],
    "bird_debit_card_specializing.yearmonth": ["年月消费", "月度消费", "月度账单"],

    # california_schools
    "bird_california_schools.frpm": ["学校餐饮补贴", "免费午餐"],
    "bird_california_schools.satscores": ["SAT 成绩", "考试成绩"],
    "bird_california_schools.schools": ["学校", "加州学校"],

    # card_games (MTG)
    "bird_card_games.cards": ["卡牌", "卡片"],
    "bird_card_games.foreign_data": ["外文翻译", "多语言"],
    "bird_card_games.legalities": ["合法性", "赛制"],
    "bird_card_games.rulings": ["裁决", "规则"],
    "bird_card_games.sets": ["套组", "卡牌套组"],
    "bird_card_games.set_translations": ["套组翻译"],

    # codebase_community (Stack Exchange-like)
    "bird_codebase_community.posts": ["帖子", "问题", "回答"],
    "bird_codebase_community.users": ["用户", "社区用户"],
    "bird_codebase_community.comments": ["评论"],
    "bird_codebase_community.badges": ["徽章"],
    "bird_codebase_community.tags": ["标签"],
    "bird_codebase_community.votes": ["投票"],
    "bird_codebase_community.posthistory": ["帖子历史"],
    "bird_codebase_community.postlinks": ["帖子链接"],

    # european_football_2
    "bird_european_football_2.player": ["球员"],
    "bird_european_football_2.player_attributes": ["球员属性"],
    "bird_european_football_2.team": ["球队"],
    "bird_european_football_2.team_attributes": ["球队属性"],
    "bird_european_football_2.match": ["比赛"],
    "bird_european_football_2.league": ["联赛"],
    "bird_european_football_2.country": ["国家"],

    # financial
    "bird_financial.account": ["账户"],
    "bird_financial.client": ["客户", "金融客户"],
    "bird_financial.card": ["银行卡"],
    "bird_financial.disp": ["权限", "账户分配"],
    "bird_financial.district": ["地区"],
    "bird_financial.loan": ["贷款"],
    "bird_financial.order": ["订单", "转账订单"],
    "bird_financial.trans": ["交易", "银行交易"],

    # formula_1
    "bird_formula_1.drivers": ["车手"],
    "bird_formula_1.constructors": ["车队"],
    "bird_formula_1.races": ["比赛", "F1 比赛"],
    "bird_formula_1.seasons": ["赛季"],
    "bird_formula_1.circuits": ["赛道"],
    "bird_formula_1.results": ["比赛结果"],
    "bird_formula_1.qualifying": ["排位赛"],
    "bird_formula_1.laptimes": ["单圈时间"],
    "bird_formula_1.pitstops": ["进站"],
    "bird_formula_1.driverstandings": ["车手积分榜"],
    "bird_formula_1.constructorstandings": ["车队积分榜"],
    "bird_formula_1.constructorresults": ["车队成绩"],
    "bird_formula_1.status": ["完赛状态"],

    # student_club
    "bird_student_club.member": ["社员", "成员"],
    "bird_student_club.event": ["活动"],
    "bird_student_club.attendance": ["出勤"],
    "bird_student_club.budget": ["预算"],
    "bird_student_club.expense": ["支出"],
    "bird_student_club.income": ["收入"],
    "bird_student_club.major": ["专业"],
    "bird_student_club.zip_code": ["邮编"],

    # superhero
    "bird_superhero.superhero": ["超级英雄", "英雄"],
    "bird_superhero.superpower": ["超能力"],
    "bird_superhero.hero_power": ["英雄能力"],
    "bird_superhero.publisher": ["出版商"],
    "bird_superhero.race": ["种族"],
    "bird_superhero.gender": ["性别"],
    "bird_superhero.alignment": ["阵营"],
    "bird_superhero.colour": ["颜色"],
    "bird_superhero.attribute": ["属性"],
    "bird_superhero.hero_attribute": ["英雄属性"],

    # thrombosis_prediction
    "bird_thrombosis_prediction.patient": ["患者", "病人"],
    "bird_thrombosis_prediction.examination": ["检查", "体检"],
    "bird_thrombosis_prediction.laboratory": ["化验", "实验室检查"],

    # toxicology
    "bird_toxicology.molecule": ["分子"],
    "bird_toxicology.atom": ["原子"],
    "bird_toxicology.bond": ["化学键"],
    "bird_toxicology.connected": ["连接关系"],
}


# Common column-level aliases mapped by column-name suffix/keyword.
# Keys are matched as substrings of the column name (case-insensitive).
COLUMN_ALIAS_PATTERNS: dict[str, list[str]] = {
    "customerid": ["客户ID", "客户编号"],
    "consumption": ["消费", "消费量", "消费额"],
    "currency": ["货币", "币种"],
    "segment": ["分段", "客户分段", "细分"],
    "country": ["国家"],
    "date": ["日期"],
    "year": ["年份"],
    "month": ["月份"],
    "amount": ["金额"],
    "price": ["价格"],
    "name": ["名称", "名字"],
    "salary": ["薪水"],
    "balance": ["余额"],
    "loan": ["贷款"],
    "score": ["分数", "得分"],
    "team": ["球队"],
    "player": ["球员"],
    "race": ["种族"],
    "power": ["能力"],
    "publisher": ["出版商"],
    "patient": ["患者", "病人"],
    "diagnosis": ["诊断"],
    "molecule": ["分子"],
}


def _column_aliases(column_name: str) -> list[str]:
    aliases: list[str] = []
    cn_lower = column_name.lower()
    for key, vals in COLUMN_ALIAS_PATTERNS.items():
        if key in cn_lower:
            aliases.extend(vals)
    # dedup, preserve order
    seen = set()
    out = []
    for a in aliases:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def main() -> int:
    engine = get_engine()
    if engine is None:
        print("ERROR: get_engine() returned None.", file=sys.stderr)
        return 2

    updated_tables = 0
    updated_columns = 0

    with engine.begin() as conn:
        # Update table-level synonyms
        for table_name, cn_aliases in TABLE_ALIASES.items():
            row = conn.execute(text(
                "SELECT synonyms FROM agent_semantic_sources WHERE table_name = :t"
            ), {"t": table_name}).fetchone()
            if not row:
                continue
            existing = row[0] if isinstance(row[0], list) else json.loads(row[0] or "[]")
            merged = list(existing)
            for a in cn_aliases:
                if a not in merged:
                    merged.append(a)
            conn.execute(text("""
                UPDATE agent_semantic_sources
                SET synonyms = CAST(:syn AS jsonb), updated_at = NOW()
                WHERE table_name = :t
            """), {"syn": json.dumps(merged, ensure_ascii=False), "t": table_name})
            updated_tables += 1

        # Update column-level aliases for all bird_* tables
        col_rows = conn.execute(text("""
            SELECT table_name, column_name, aliases
            FROM agent_semantic_registry
            WHERE table_name LIKE 'bird_%'
        """)).fetchall()

        for tbl, col, aliases_raw in col_rows:
            extra = _column_aliases(col)
            if not extra:
                continue
            existing = aliases_raw if isinstance(aliases_raw, list) else json.loads(aliases_raw or "[]")
            merged = list(existing)
            for a in extra:
                if a not in merged:
                    merged.append(a)
            if len(merged) == len(existing):
                continue
            conn.execute(text("""
                UPDATE agent_semantic_registry
                SET aliases = CAST(:al AS jsonb), updated_at = NOW()
                WHERE table_name = :t AND column_name = :c
            """), {"al": json.dumps(merged, ensure_ascii=False), "t": tbl, "c": col})
            updated_columns += 1

    print(f"[cn-aliases] Updated {updated_tables} tables, {updated_columns} columns")

    try:
        from data_agent.semantic_layer import invalidate_semantic_cache
        invalidate_semantic_cache()
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
