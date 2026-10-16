"""Diagnose a user literal found in an authorized neighboring field.

A missing value alone is never a reason to change a valid empty query. Only
report observations that also have an exact match in a registered neighbor.
No SQL is automatically replaced and no remote values become instructions.
"""
from __future__ import annotations


def observed_literal_binding_issues(evidence: list[dict]) -> list[dict]:
    originals = {(e.get('table'), e.get('column'), e.get('requested_literal')): e for e in evidence
                 if not e.get('comparison_to_column') and e.get('exact_match') is False}
    issues = []
    for candidate in evidence:
        if candidate.get('exact_match') is not True or not candidate.get('comparison_to_column'):
            continue
        identity = (candidate.get('table'), candidate.get('comparison_to_column'), candidate.get('requested_literal'))
        if identity not in originals:
            continue
        issues.append({'kind':'literal_found_in_neighboring_field', 'table':identity[0],
            'draft_column':identity[1], 'literal':identity[2], 'matching_column':candidate['column'],
            'instruction':'The draft field has no exact match for this user-supplied literal, while this authorized neighboring field does. Recheck the field meaning against the question and dictionary. An exact value match is evidence, not permission to change the requested meaning.'})
    return issues
