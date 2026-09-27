from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.llm import get_stage_llm_client
from app.main import create_app


def test_health_check() -> None:
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_deepdoc_runtime_status_endpoint() -> None:
    client = TestClient(create_app())
    response = client.get("/api/files/ocr/deepdoc/status")

    assert response.status_code == 200
    payload = response.json()
    assert "available" in payload
    assert payload["package"] == "ocr"
    assert "configured_engine" in payload
    assert "deepdoc_available" in payload
    assert "rapidocr_available" in payload


def test_deepdoc_runtime_status_uses_configured_subprocess(monkeypatch) -> None:
    monkeypatch.setenv("OCR_ENGINE", "deepdoc")
    monkeypatch.setenv("DEEPDOC_PYTHON", "/tmp/deepdoc-python")
    get_settings.cache_clear()

    monkeypatch.setattr("pathlib.Path.exists", lambda self: str(self) == "/tmp/deepdoc-python")
    monkeypatch.setattr(
        "app.documents.ocr._run_deepdoc_subprocess",
        lambda arguments: {"status": "ok", "package": "deepdoc-lib", "version": "0.2.2", "parsers": ["PdfParser"]},
    )

    client = TestClient(create_app())
    response = client.get("/api/files/ocr/deepdoc/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deepdoc_available"] is True
    assert payload["active_engine"] == "deepdoc"
    assert payload["metadata"]["runtime"] == "subprocess"

    get_settings.cache_clear()


def test_stage_llm_client_uses_stage_specific_model(monkeypatch) -> None:
    monkeypatch.setenv("ROUTER_LLM_MODEL", "router-fast-model")
    get_settings.cache_clear()

    client = get_stage_llm_client("router")

    assert client.default_model == "router-fast-model"
    get_settings.cache_clear()
