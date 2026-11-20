import json
from unittest.mock import Mock
import web_api


def test_migrate_plaintext_and_dpapi(tmp_path, monkeypatch):
    path = tmp_path / 'config.json'
    monkeypatch.setattr(web_api, 'CONFIG', path)
    path.write_text(json.dumps({'key': 'private-example-key', 'url': 'https://example.test'}), encoding='utf-8')
    assert web_api.read_config()['key'] == 'private-example-key'
    assert 'private-example-key' not in path.read_text(encoding='utf-8')
    assert web_api.read_config()['key'] == 'private-example-key'


def test_update_versions_and_url(monkeypatch, tmp_path):
    monkeypatch.setattr(web_api, 'CONFIG', tmp_path / 'empty.json')
    api = web_api.AgentAPI(lambda _: [], 'device')
    response = Mock(); response.json.return_value = {'version':'2.10.0', 'download_url':web_api.UPDATE_URL, 'release_notes':'Changes'}
    api.http.get = Mock(return_value=response)
    api.check_update()
    assert api.update_info['version'] == '2.10.0'
    api.update_info = None
    response.json.return_value = {'version':'99.0.0', 'download_url':'https://example.test/setup.exe'}
    api.check_update()
    assert api.update_info is None
    api.shutdown()
