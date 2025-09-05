import os
import sys
import json

os.environ['TP_CONFIG'] = os.path.join(os.path.dirname(__file__), 'test.config.yml')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import api  # noqa: E402


def reset_nodes():
    with api.DB_LOCK:
        api.DB.execute('DELETE FROM nodes')
        api.DB.commit()


def test_admin_can_view_and_edit_nodes():
    reset_nodes()
    with api.DB_LOCK:
        api.DB.execute('INSERT INTO nodes(node_id, short_name) VALUES(?, ?)', ('n1', 'old'))
        api.DB.commit()
    res = api.api_nodes()
    data = json.loads(res.body)
    assert data[0]['node_id'] == 'n1'
    assert data[0]['short_name'] == 'old'
    api.api_admin_update_node('n1', {'short_name': 'new'})
    with api.DB_LOCK:
        cur = api.DB.execute('SELECT short_name FROM nodes WHERE node_id=?', ('n1',))
        assert cur.fetchone()[0] == 'new'


def test_admin_can_delete_nodes():
    reset_nodes()
    with api.DB_LOCK:
        api.DB.execute('INSERT INTO nodes(node_id, short_name) VALUES(?, ?)', ('n1', 'old'))
        api.DB.commit()
    api.api_admin_delete_node('n1')
    with api.DB_LOCK:
        cur = api.DB.execute('SELECT COUNT(*) FROM nodes WHERE node_id=?', ('n1',))
        assert cur.fetchone()[0] == 0


def test_admin_can_prune_empty_nodes():
    reset_nodes()
    with api.DB_LOCK:
        api.DB.execute('INSERT INTO nodes(node_id, short_name) VALUES(?, ?)', ('n1', 'info'))
        api.DB.execute('INSERT INTO nodes(node_id) VALUES(?)', ('n2',))
        api.DB.execute('INSERT INTO nodes(node_id, last_seen, info_packets) VALUES(?, ?, ?)', ('n3', 123, 4))
        api.DB.execute('INSERT INTO nodes(node_id, short_name, long_name, nickname) VALUES(?, ?, ?, ?)', ('n4', '', '  ', ''))
        api.DB.commit()
    from starlette.routing import Match

    def first_match(path: str) -> str:
        scope = {'type': 'http', 'path': path, 'method': 'DELETE'}
        for r in api.app.router.routes:
            if hasattr(r, 'path'):
                m, _ = r.matches(scope)
                if m == Match.FULL:
                    return r.path
        return ''

    assert first_match('/api/admin/nodes/empty') == '/api/admin/nodes/empty'
    res = api.api_admin_delete_empty_nodes()
    data = json.loads(res.body)
    assert data['deleted'] == 3
    with api.DB_LOCK:
        cur = api.DB.execute('SELECT COUNT(*) FROM nodes WHERE node_id=?', ('n1',))
        assert cur.fetchone()[0] == 1
        cur = api.DB.execute('SELECT COUNT(*) FROM nodes WHERE node_id=?', ('n2',))
        assert cur.fetchone()[0] == 0
        cur = api.DB.execute('SELECT COUNT(*) FROM nodes WHERE node_id=?', ('n3',))
        assert cur.fetchone()[0] == 0
        cur = api.DB.execute('SELECT COUNT(*) FROM nodes WHERE node_id=?', ('n4',))
        assert cur.fetchone()[0] == 0