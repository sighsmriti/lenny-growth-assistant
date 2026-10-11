from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend import main
from backend.artifacts import render_markdown


def test_markdown_renderer_supports_common_elements_and_removes_unsafe_markup():
    rendered = render_markdown(
        "# A heading\n\n- one\n- two\n\n[good](https://example.test) [bad](javascript:alert(1))\n\n"
        "```python\nprint('safe')\n```\n\n<script>alert(1)</script>"
    )
    assert "<h1>A heading</h1>" in rendered
    assert "<ul>" in rendered and "<li>one</li>" in rendered
    assert 'href="https://example.test"' in rendered
    assert 'href="javascript:' not in rendered
    assert "<script" not in rendered
    assert "<pre><code" in rendered and "print('safe')" in rendered


def test_artifact_api_persists_markdown_and_html_and_serves_viewer():
    main.ensure_rag_schema()
    marker = uuid4().hex
    title = f"test-viewer-{marker}"
    try:
        with TestClient(main.app) as client:
            markdown_response = client.post("/api/artifacts", json={
                "title": title, "format": "markdown", "content": "# Test\n\nSafe **content**"
            })
            assert markdown_response.status_code == 201
            markdown_id = markdown_response.json()["id"]
            listed = client.get("/api/artifacts")
            assert any(item["id"] == markdown_id for item in listed.json())
            detail = client.get(f"/api/artifacts/{markdown_id}")
            assert detail.status_code == 200
            assert detail.json()["rendered_html"] == "<h1>Test</h1>\n<p>Safe <strong>content</strong></p>\n"

            html_content = "<script>parent.pwned=true</script><h1>Untrusted</h1>"
            html_response = client.post("/api/artifacts", json={
                "title": title + " html", "format": "html", "content": html_content
            })
            assert html_response.status_code == 201
            html_id = html_response.json()["id"]
            html_detail = client.get(f"/api/artifacts/{html_id}").json()
            assert html_detail["content"] == html_content
            assert html_detail["rendered_html"] is None

            assert client.get("/api/artifacts/not-a-uuid").status_code == 422
            missing_id = str(uuid4())
            assert client.get(f"/api/artifacts/{missing_id}").status_code == 404
            viewer = client.get("/viewer")
            assert viewer.status_code == 200
            assert "Artifact viewer" in viewer.text
    finally:
        with main.SessionLocal() as db:
            db.execute(delete(main.Artifact).where(main.Artifact.title.like(f"{title}%")))
            db.commit()
