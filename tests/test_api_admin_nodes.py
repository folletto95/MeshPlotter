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
