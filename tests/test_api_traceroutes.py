import os
import sys
import json
import time

# Configure test environment
os.environ['TP_CONFIG'] = os.path.join(os.path.dirname(__file__), 'test.config.yml')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import api  # noqa: E402


def reset_traceroutes():
    with api.DB_LOCK:
        api.DB.execute('DELETE FROM traceroutes')
        api.DB.commit()


def test_api_traceroutes_deduplication():
    reset_traceroutes()
    with api.DB_LOCK:
        api.DB.executemany(
            'INSERT INTO traceroutes(ts, src_id, dest_id, route, hop_count) VALUES(?,?,?,?,?)',
            [
                (1, 'a', 'b', json.dumps(['c']), 2),
                (2, 'a', 'b', json.dumps(['c', 'd']), 3),
                (3, 'a', 'd', json.dumps(['e']), 2),
            ],
        )
        api.DB.commit()
    res = api.api_traceroutes(limit=10, max_age=0)
    data = json.loads(res.body)
    assert len(data) == 2
    entry = next(r for r in data if r['dest_id'] == 'b')
    assert entry['ts'] == 2
    assert entry['hop_count'] == 3
    assert entry['route'] == ['c', 'd']
    reset_traceroutes()


def test_api_traceroutes_limit_after_dedup():
    reset_traceroutes()
    with api.DB_LOCK:
        api.DB.executemany(
            'INSERT INTO traceroutes(ts, src_id, dest_id, route, hop_count) VALUES(?,?,?,?,?)',
            [
                (1, 'a', 'c', json.dumps(['x']), 2),
                (2, 'a', 'b', json.dumps(['y']), 2),
                (3, 'a', 'b', json.dumps(['z']), 3),
            ],
        )
        api.DB.commit()
    res = api.api_traceroutes(limit=2, max_age=0)
    data = json.loads(res.body)
    assert len(data) == 2
    assert {r['dest_id'] for r in data} == {'b', 'c'}
    entry_b = next(r for r in data if r['dest_id'] == 'b')
    assert entry_b['ts'] == 3
    reset_traceroutes()


def test_api_traceroutes_max_age():
    reset_traceroutes()
    now = int(time.time())
    with api.DB_LOCK:
        api.DB.executemany(
            'INSERT INTO traceroutes(ts, src_id, dest_id, route, hop_count) VALUES(?,?,?,?,?)',
            [
                (now - 100, 'a', 'b', json.dumps(['x']), 2),
                (now, 'a', 'c', json.dumps(['y']), 2),
            ],
        )
        api.DB.commit()
    res = api.api_traceroutes(limit=10, max_age=50)
    data = json.loads(res.body)
    assert {r['dest_id'] for r in data} == {'c'}
    reset_traceroutes()
