import os
import sys
import json

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
                (2, 'a', 'b', json.dumps(['c']), 2),
                (3, 'a', 'd', json.dumps(['e']), 2),
            ],
        )
        api.DB.commit()
    res = api.api_traceroutes(limit=10)
    data = json.loads(res.body)
    assert len(data) == 2
    entry = next(r for r in data if r['dest_id'] == 'b')
    assert entry['ts'] == 2
    reset_traceroutes()
