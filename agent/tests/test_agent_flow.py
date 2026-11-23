import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
import web_api


def test_csv_cp1251_and_hwid(tmp_path, monkeypatch):
    path = tmp_path / "products.csv"
    path.write_bytes("barcode;name;price\n123;milk;12,50\n".encode("cp1251"))
    assert agent.read_products(path) == [{"barcode": "123", "name": "milk", "price": "12.50", "unit": "\u0448\u0442."}]
    api = web_api.AgentAPI(agent.read_products, "test-machine")
    api.config.update(key="key", path=str(path))
    response = Mock(); response.json.return_value = {}
    api.http.post = Mock(return_value=response)
    assert api.sync()["count"] == 1
    assert api.http.post.call_args.kwargs["headers"]["X-Device-HWID"] == "test-machine"
    api.shutdown()


def test_failed_print_does_not_ack(monkeypatch):
    api = web_api.AgentAPI(lambda _: [], "machine")
    api.config.update(key="key", printer="printer")
    api.stop.wait = Mock(side_effect=[False, True])
    jobs = Mock(); jobs.json.return_value = [{"id": 7, "lock_token": "token", "file_url": "/file"}]
    pdf = Mock(); pdf.content = b"pdf"
    api.http.get = Mock(side_effect=[jobs, pdf])
    api.http.post = Mock()
    monkeypatch.setattr(web_api, "prepare_pdf", Mock(side_effect=RuntimeError("printer failure")))
    api.poll()
    api.http.post.assert_not_called()
    assert api.printed == 0
    assert api.http.get.call_args_list[0].kwargs["headers"]["X-Device-HWID"] == "machine"
    api.shutdown()


def test_a4_print_uses_noscale(monkeypatch):
    api = web_api.AgentAPI(lambda _: [], "machine")
    api.config.update(key="key", printer="printer")
    api.stop.wait = Mock(side_effect=[False, True])
    jobs = Mock(); jobs.json.return_value = [{"id": 7, "lock_token": "token", "file_url": "/file"}]
    pdf = Mock(); pdf.content = b"pdf"
    api.http.get = Mock(side_effect=[jobs, pdf]); api.http.post = Mock()
    monkeypatch.setattr(web_api, 'printer_geometry', lambda _: (210, 297))
    monkeypatch.setattr(web_api, 'prepare_pdf', lambda path, output, geometry: (path, False))
    monkeypatch.setattr(web_api.subprocess, 'run', Mock())
    api.poll()
    args = web_api.subprocess.run.call_args.args[0]
    assert args[args.index('-print-settings') + 1] == 'noscale'
    api.http.post.assert_called_once()
    api.shutdown()
