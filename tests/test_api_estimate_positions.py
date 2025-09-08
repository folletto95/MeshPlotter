import os
import sys
import json
import pytest

# Configure test environment
os.environ['TP_CONFIG'] = os.path.join(os.path.dirname(__file__), 'test.config.yml')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import api  # noqa: E402


def reset_db():
    with api.DB_LOCK:
        api.DB.execute('DELETE FROM nodes')
        api.DB.execute('DELETE FROM traceroutes')
        api.DB.commit()


def test_estimate_position_single_neighbour():
    reset_db()
    with api.DB_LOCK:
        api.DB.execute('INSERT INTO nodes(node_id, lat, lon) VALUES(?,?,?)', ('n1', 10.0, 20.0))
        api.DB.execute('INSERT INTO nodes(node_id) VALUES(?)', ('n2',))
        api.DB.execute(
            'INSERT INTO traceroutes(ts, src_id, dest_id, route, hop_count) VALUES(?,?,?,?,?)',
            (0, 'n1', 'n2', json.dumps([]), 1),
        )
        api.DB.commit()
    res = api.api_nodes()
    data = json.loads(res.body)
    n2 = next(n for n in data if n['node_id'] == 'n2')
    assert n2['lat'] == pytest.approx(10.001)
    assert n2['lon'] == pytest.approx(20.001)
    with api.DB_LOCK:
        row = api.DB.execute('SELECT lat, lon FROM nodes WHERE node_id=?', ('n2',)).fetchone()
    assert row[0] == pytest.approx(10.001)
    assert row[1] == pytest.approx(20.001)


def test_estimate_position_multiple_neighbours():
    reset_db()
    with api.DB_LOCK:
        api.DB.execute('INSERT INTO nodes(node_id, lat, lon) VALUES(?,?,?)', ('n1', 10.0, 20.0))
        api.DB.execute('INSERT INTO nodes(node_id, lat, lon) VALUES(?,?,?)', ('n3', 20.0, 30.0))
        api.DB.execute('INSERT INTO nodes(node_id) VALUES(?)', ('n4',))
        api.DB.execute(
            'INSERT INTO traceroutes(ts, src_id, dest_id, route, hop_count) VALUES(?,?,?,?,?)',
            (0, 'n1', 'n3', json.dumps(['n4']), 2),
        )
        api.DB.commit()
    res = api.api_nodes()
    data = json.loads(res.body)
    n4 = next(n for n in data if n['node_id'] == 'n4')
    assert n4['lat'] == pytest.approx(15.0)
    assert n4['lon'] == pytest.approx(25.0)
    with api.DB_LOCK:
        row = api.DB.execute('SELECT lat, lon FROM nodes WHERE node_id=?', ('n4',)).fetchone()
    assert row[0] == pytest.approx(15.0)
    assert row[1] == pytest.approx(25.0)
