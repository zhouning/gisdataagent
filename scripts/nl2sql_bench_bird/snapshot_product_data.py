"""Fingerprint authorized source tables without exporting customer rows.

The ordered multiset of per-row hashes retains duplicates. This snapshot is
an audit artifact, not model input. Taking it mid-run does not prove that data
was frozen before the snapshot; callers must record that timing accurately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def fingerprint_sources(db_ids: list[str] | None = None, *, progress: bool = False) -> dict:
    """Use the caller's current identity; no metadata or source mutations."""
    from sqlalchemy import text
    from data_agent.bird_source import query_rows, registered_database
    from data_agent.db_engine import get_engine
    started = datetime.now(timezone.utc).isoformat()
    with get_engine().connect() as conn:
        names = [tuple(r) for r in conn.execute(text(
            'SELECT db_id,table_name FROM agent_bird_tables ORDER BY db_id,table_name'))]
    if db_ids is not None:
        selected = set(db_ids)
        names = [(db,table) for db,table in names if db in selected]
        if {db for db,table in names} != selected:
            raise ValueError('Not all requested sources have registered tables')
    records = []
    for db_id, table in names:
        registered_database(db_id)
        quoted = '"' + table.replace('"','""') + '"'
        sql = ('SELECT COUNT(*), MD5(COALESCE(STRING_AGG(_digest, \'\' ORDER BY _digest), \'\')) '
               'FROM (SELECT MD5(ROW_TO_JSON(_source)::text) AS _digest FROM ' + quoted + ' AS _source) AS _hashed')
        _, rows, truncated = query_rows(db_id, sql)
        if truncated or len(rows) != 1:
            raise RuntimeError('Source fingerprint returned an unexpected shape')
        records.append({'db_id': db_id, 'table': table, 'rows': rows[0][0], 'ordered_row_md5': rows[0][1]})
        if progress:
            print(f'Fingerprint {len(records)}/{len(names)} {db_id}.{table}', flush=True)
    return {'version': 'ordered-row-json-md5-v1',
        'started_at': started, 'completed_at': datetime.now(timezone.utc).isoformat(), 'tables': records,
        'fingerprint_sha256': hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest(),
        'scope': 'Current authorized BIRD tables; row order ignored, duplicate multiplicity preserved; source rows not exported.',
        'limitations': 'MD5 is a data-change detector, not adversarial tamper-proof attestation. Tables are read sequentially, not in one cross-database snapshot.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--compare', type=Path)
    parser.add_argument('--phase', choices=['before_run','during_run','after_run'], required=True)
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / 'data_agent/.env', override=False)
    load_dotenv(ROOT / 'data_agent/.bird.env', override=False)
    from data_agent.user_context import current_user_id, current_user_role
    current_user_id.set('bird_benchmark')
    current_user_role.set('analyst')
    result = {**fingerprint_sources(progress=True), 'phase': args.phase}
    if args.compare:
        previous = json.loads(args.compare.read_text())
        if previous.get('version') != result['version']:
            raise ValueError('Fingerprint algorithm changed')
        by_table = {(r['db_id'],r['table']):r for r in previous['tables']}
        result['changed_tables'] = [f"{r['db_id']}.{r['table']}" for r in result['tables']
                                    if by_table.pop((r['db_id'],r['table']),None) != r]
        result['changed_tables'] += ['.'.join(k) for k in by_table]
        result['compared_with'] = str(args.compare)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'tables'},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
