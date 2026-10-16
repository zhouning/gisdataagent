"""Public BIRD semantic contracts used by the NL2SQL grounding prompt.

These contracts describe the published database dictionaries and registered
keys.  They deliberately contain no benchmark questions, Gold SQL, answers,
or model outputs.  The goal is to make row grain and commonly confused public
concepts explicit before SQL generation.
"""
from __future__ import annotations

import re

_DATABASE_TABLES: dict[str, set[str]] = {
    "california_schools": {"frpm", "satscores", "schools"},
    "card_games": {"cards", "foreign_data", "legalities", "rulings", "sets", "set_translations"},
    "codebase_community": {"badges", "comments", "postHistory", "postLinks", "posts", "tags", "users", "votes"},
    "european_football_2": {"Country", "League", "Match", "Player", "Player_Attributes", "Team", "Team_Attributes"},
    "financial": {"account", "card", "client", "disp", "district", "loan", "order", "trans"},
    "formula_1": {"circuits", "constructorResults", "constructors", "constructorStandings", "drivers", "driverStandings", "lapTimes", "pitStops", "qualifying", "races", "results", "seasons", "status"},
    "superhero": {"alignment", "attribute", "colour", "gender", "hero_attribute", "hero_power", "publisher", "race", "superhero", "superpower"},
    "thrombosis_prediction": {"Examination", "Laboratory", "Patient"},
    "toxicology": {"atom", "bond", "connected", "molecule"},
}

_DATABASE_CONTRACTS: dict[str, dict[str, object]] = {
    "california_schools": {
        "population": "schools is the school directory entity; frpm and satscores are reporting observations keyed to a school.",
        "rules": (
            "FRPM Enrollment (K-12) and Enrollment (Ages 5-17) are different populations.",
            "satscores AvgScrRead/AvgScrMath/AvgScrWrite are reported averages; NumGE1500 is a count, not an average.",
            "School address and DOC/Virtual/FundingType belong to schools; do not infer them from FRPM or SAT rows.",
        ),
    },
    "card_games": {
        "population": "cards is one stored card printing; uuid identifies the printing and name can repeat across printings.",
        "rules": (
            "cards.type is the complete visible type line; cards.types is the category list. Do not substitute one for the other.",
            "foreign_data and set_translations are language-detail rows; legalities are one row per printing and format; rulings are official ruling rows.",
            "Join card detail tables through cards.uuid and set translations through cards.setCode -> sets.code.",
            "A card printing count must use cards.id/uuid at card grain; detail joins can multiply printings.",
        ),
    },
    "codebase_community": {
        "population": "posts and users are entities; comments, votes, badges and postHistory are event/detail rows.",
        "rules": (
            "posts.OwnerUserId is the post author; comments.UserId is the comment author; postHistory.UserId is the history editor.",
            "posts.ViewCount/CommentCount/AnswerCount/Score are stored post measures and are not counts of detail rows or user fields.",
            "postHistory is revision/event history, not the current post body or comments; votes are vote events and may repeat a post/user.",
        ),
    },
    "european_football_2": {
        "population": "Player, Team, League and Country are entities; Match, Player_Attributes and Team_Attributes are observations.",
        "rules": (
            "Match has separate home_team_api_id and away_team_api_id roles and a stored season label; do not collapse home and away.",
            "Player_Attributes and Team_Attributes can contain multiple dated observations per entity; rating fields are not interchangeable.",
            "Player_Attributes.overall_rating is overall ability; strength, finishing and potential are distinct attributes.",
            "Match goals are match observations; team and player identity names come from Team and Player.",
        ),
    },
    "financial": {
        "population": "client is the person entity; account, loan, card, order and trans are different contract/account/event grains; disp is the client-account relationship.",
        "rules": (
            "The client.district_id field identifies the client's residential district; account.district_id identifies the account branch location.",
            "Use disp to connect client and account/card roles; one-to-many joins can duplicate clients and accounts.",
            "loan.amount, loan.payments, trans.balance and trans.amount are different measures; trans.type and operation are separate code dimensions.",
        ),
    },
    "formula_1": {
        "population": "drivers, constructors, races and circuits are entities; results/lapTimes/pitStops/qualifying are race observations.",
        "rules": (
            "results.position is finishing position; results.rank is the driver's fastest-lap rank in that race. Do not swap them.",
            "results.points and constructorResults.points are points earned in one race; driverStandings/constructorStandings.points are cumulative snapshots after a race.",
            "Do not sum championship standing snapshots across rounds. Join race observations to races by raceId and identities by driverId/constructorId.",
            "lapTimes.milliseconds is elapsed lap duration; smaller is faster. A driver has many lap observations across races and laps.",
        ),
    },
    "superhero": {
        "population": "superhero is the hero entity; hero_attribute and hero_power are many-to-many/detail relationships; lookup tables provide labels.",
        "rules": (
            "hero_attribute.attribute_value is meaningful only with attribute.attribute_name; Intelligence, Strength, Speed and Power are distinct attributes.",
            "alignment, publisher, colour and other lookup labels must be joined through their respective foreign-key roles.",
            "eye_colour_id, hair_colour_id and skin_colour_id are separate roles even when they use the same colour lookup table.",
            "Count heroes by superhero.id after detail joins; do not count attribute or power rows as heroes.",
        ),
    },
    "thrombosis_prediction": {
        "population": "Patient is the patient entity; Laboratory and Examination are repeated observations keyed by patient ID.",
        "rules": (
            "Patient.Diagnosis is the patient-record diagnosis; Examination.Diagnosis is the diagnosis recorded for an examination observation.",
            "Laboratory grain is (ID, Date); Examination has no declared one-row-per-patient key. Observation joins can multiply a patient.",
            "For a patient count after observation filters use COUNT(DISTINCT Patient.ID); count observation rows only when the question asks for records/tests/examinations.",
            "Laboratory reference ranges published in the dictionary are strict bounds; NULL does not satisfy a normal-range predicate.",
        ),
    },
    "toxicology": {
        "population": "molecule is the molecule entity; atom and bond are child entities; connected stores bond endpoint pairs.",
        "rules": (
            "atom.molecule_id and bond.molecule_id identify the parent molecule; connected.atom_id and connected.atom_id2 are the two endpoint roles.",
            "To filter a bond by its endpoints, join bond -> connected by bond_id and atom -> connected by the relevant endpoint column; molecule_id alone does not identify endpoints.",
            "Queries asking for a bond between two atoms must test both endpoint orientations in connected.",
            "Count molecules, atoms, bonds and endpoint rows at their own keys; joins can multiply each other.",
        ),
    },
}


def _db_id(candidate_tables: list[dict]) -> str | None:
    values = {
        str(table.get("table_name") or "").split(".", 1)[0][5:]
        for table in candidate_tables
        if str(table.get("table_name") or "").startswith("bird_") and "." in str(table.get("table_name") or "")
    }
    return next(iter(values)) if len(values) == 1 else None


def semantic_hint_applies_to_candidates(scope_ref: str, hint_text: str,
                                        candidate_tables: list[dict]) -> bool:
    """Do not render a dataset rule unless its schema references are authorized."""
    if not str(scope_ref).startswith("bird_"):
        return False
    db_id = str(scope_ref)[5:]
    known_tables = _DATABASE_TABLES.get(db_id)
    if not known_tables:
        return False
    scoped = [
        table for table in candidate_tables or []
        if str(table.get("table_name") or "").startswith(f"bird_{db_id}.")
    ]
    if not scoped:
        return False
    candidate_by_name = {
        str(table.get("table_name") or "").rsplit(".", 1)[-1].casefold(): table
        for table in scoped
    }
    referenced = {
        name for name in known_tables
        if re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])",
                     hint_text, flags=re.IGNORECASE)
    }
    if referenced and not {name.casefold() for name in referenced}.issubset(candidate_by_name):
        return False
    if not referenced and not {name.casefold() for name in known_tables}.issubset(candidate_by_name):
        return False

    for table_name in known_tables:
        # Only explicit table.column references; a sentence ending in a table
        # name ("district. They ...") is prose, not a column reference.
        pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(table_name) + r"\.([A-Za-z_][A-Za-z0-9_]*)",
                             flags=re.IGNORECASE)
        field_names = [match.group(1).casefold() for match in pattern.finditer(hint_text)]
        if not field_names:
            continue
        table = candidate_by_name.get(table_name.casefold())
        if table is None:
            return False
        allowed_fields = {
            str(column.get("column_name") or "").casefold()
            for column in table.get("columns") or []
        }
        if not set(field_names).issubset(allowed_fields):
            return False
    return True


def contract_for_tables(candidate_tables: list[dict]) -> dict:
    """Return a prompt-safe contract for one authorized BIRD database."""
    db_id = _db_id(candidate_tables)
    contract = _DATABASE_CONTRACTS.get(db_id or "")
    if not contract:
        return {}
    table_names = {
        str(table.get("table_name") or "").rsplit(".", 1)[-1]
        for table in candidate_tables
    }
    scope_ref = f"bird_{db_id}"
    population_text = str(contract["population"])
    population = (population_text if semantic_hint_applies_to_candidates(
        scope_ref, population_text, candidate_tables) else "")
    rules = [str(rule) for rule in contract["rules"] if semantic_hint_applies_to_candidates(
        scope_ref, str(rule), candidate_tables)]
    relationships = []
    columns_by_table = {
        str(table.get("table_name") or "").rsplit(".", 1)[-1]: {
            str(column.get("column_name") or "").casefold()
            for column in table.get("columns") or []
        }
        for table in candidate_tables
    }
    for table in candidate_tables:
        source = str(table.get("table_name") or "").rsplit(".", 1)[-1]
        for fk in table.get("foreign_keys") or []:
            target = str(fk.get("target_table") or "")
            if (target in table_names
                    and str(fk.get("column") or "").casefold() in columns_by_table.get(source, set())
                    and str(fk.get("target_column") or "").casefold() in columns_by_table.get(target, set())):
                relationships.append(
                    f"{source}.{fk.get('column')} -> {target}.{fk.get('target_column')}"
                )
    return {
        "database": db_id,
        "population": population,
        "rules": rules,
        "relationships": list(dict.fromkeys(relationships)),
        "tables": sorted(table_names),
    }


def contract_prompt(candidate_tables: list[dict]) -> str:
    """Render a concise, deterministic semantic contract for the model."""
    contract = contract_for_tables(candidate_tables)
    if not contract:
        return ""
    lines = ["## BIRD public semantic contract", f"- database: {contract['database']}"]
    if contract["population"]:
        lines.append(f"- population model: {contract['population']}")
    if contract["relationships"]:
        lines.append("- governed relationship paths: " + "; ".join(contract["relationships"]))
    if contract["rules"]:
        lines.append("- apply these disambiguation rules before writing SQL:")
        lines.extend(f"  - {rule}" for rule in contract["rules"])
        lines.append("- These are semantic constraints, not benchmark examples; do not invent a different grain or join path.")
    return "\n".join(lines)
