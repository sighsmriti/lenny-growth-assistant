import asyncio

from backend import rag


def test_embed_texts_parses_current_ollama_embed_response(monkeypatch):
    calls = []
    vector = [0.125, -0.25, 0.5]

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            # Current POST /api/embed response: embeddings is a list of vectors.
            return {"embeddings": [vector]}

    class FakeClient:
        def __init__(self, *, timeout):
            assert timeout == 60.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, *, json):
            calls.append((url, json))
            return FakeResponse()

    monkeypatch.setattr(rag.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(rag.embed_texts(["How do startups find product-market fit?"]))

    assert result == [vector]
    assert calls == [(
        "http://localhost:11434/api/embed",
        {"model": "nomic-embed-text", "input": ["How do startups find product-market fit?"]},
    )]


def test_embed_texts_sends_multiple_texts_in_one_request(monkeypatch):
    calls = []
    inputs = ["first chunk", "second chunk", "third chunk"]
    vectors = [[float(index), 1.0] for index in range(len(inputs))]

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {"embeddings": vectors}

    class FakeClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, *, json):
            calls.append((url, json))
            return FakeResponse()

    monkeypatch.setattr(rag.httpx, "AsyncClient", FakeClient)
    assert asyncio.run(rag.embed_texts(inputs)) == vectors
    assert calls == [("http://localhost:11434/api/embed", {
        "model": "nomic-embed-text", "input": inputs,
    })]


def test_embed_chunks_splits_work_into_batches_of_16(monkeypatch):
    chunks = [rag.SourceChunk("title", "source.md", None, index, f"chunk {index}", [], str(index))
              for index in range(17)]
    batch_sizes = []

    async def fake_embed_texts(texts):
        batch_sizes.append(len(texts))
        return [[1.0, float(index)] for index, _ in enumerate(texts)]

    monkeypatch.setattr(rag, "embed_texts", fake_embed_texts)
    embedded = asyncio.run(rag.embed_chunks(chunks, batch_size=16))
    assert batch_sizes == [16, 1]
    assert len(embedded) == 17
    assert all(chunk.embedding for chunk in embedded)


def test_embed_texts_rejects_empty_or_non_numeric_first_vector(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"embeddings": [[]]}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(rag.httpx, "AsyncClient", FakeClient)

    try:
        asyncio.run(rag.embed_texts(["sample text"]))
    except rag.EmbeddingError as exc:
        assert "embeddings[0]" in str(exc)
    else:
        raise AssertionError("expected malformed embedding response to fail")


def test_embed_texts_rejects_wrong_vector_count(monkeypatch):
    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {"embeddings": [[1.0]]}

    class FakeClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): return FakeResponse()

    monkeypatch.setattr(rag.httpx, "AsyncClient", FakeClient)
    try:
        asyncio.run(rag.embed_texts(["first", "second"]))
    except rag.EmbeddingError as exc:
        assert "one vector per input" in str(exc)
    else:
        raise AssertionError("expected missing batch vector to fail")


def test_embed_texts_reports_timeout_and_http_errors(monkeypatch):
    class TimeoutClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): raise rag.httpx.TimeoutException("slow")

    monkeypatch.setattr(rag.httpx, "AsyncClient", TimeoutClient)
    try:
        asyncio.run(rag.embed_texts(["sample"]))
    except rag.EmbeddingError as exc:
        assert "Timed out" in str(exc)
    else:
        raise AssertionError("expected timeout to be reported")

    class StatusResponse:
        status_code = 404

    class HttpErrorClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            request = rag.httpx.Request("POST", "http://localhost:11434/api/embed")
            raise rag.httpx.HTTPStatusError("not found", request=request, response=StatusResponse())

    monkeypatch.setattr(rag.httpx, "AsyncClient", HttpErrorClient)
    try:
        asyncio.run(rag.embed_texts(["sample"]))
    except rag.EmbeddingError as exc:
        assert "HTTP 404" in str(exc)
    else:
        raise AssertionError("expected HTTP status failure to be reported")
