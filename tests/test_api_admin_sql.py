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


def test_admin_sql_can_modify_db():
    reset_nodes()
    api.api_admin_sql({
        'query': 'INSERT INTO nodes(node_id, short_name) VALUES(?, ?)',
        'params': ['n1', 'short']
    })
    res = api.api_admin_sql({'query': 'SELECT node_id, short_name FROM nodes'})
    data = json.loads(res.body)
    assert data['rows'][0]['node_id'] == 'n1'
    assert data['rows'][0]['short_name'] == 'short'
