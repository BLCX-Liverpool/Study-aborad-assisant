from app.rag.bm25 import InMemoryBM25Index, tokenize


def test_tokenize_lowercases_terms() -> None:
    assert tokenize("COMP702 Deadline: 10 October") == ["comp702", "deadline", "10", "october"]


def test_bm25_returns_relevant_document_first() -> None:
    index = InMemoryBM25Index(
        [
            "submission deadline is 10 october",
            "weekly reading list and lecture notes",
            "marking criteria includes structure and evidence",
        ]
    )

    ranked = index.top_k("deadline", k=2)
    assert ranked[0][0] == 0
    assert ranked[0][1] > 0

