import math
import re
from collections import Counter


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_PATTERN.finditer(text)]


class InMemoryBM25Index:
    """Small BM25 implementation for deterministic tests and local reranking.

    Production retrieval uses PostgreSQL full-text search first. This class is
    intentionally dependency-free and useful for unit tests or post-retrieval
    reranking without introducing another runtime.
    """

    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.documents = documents
        self.k1 = k1
        self.b = b
        self.term_frequencies = [Counter(tokenize(document)) for document in documents]
        self.doc_lengths = [sum(freq.values()) for freq in self.term_frequencies]
        self.avg_doc_length = sum(self.doc_lengths) / len(self.doc_lengths) if documents else 0.0
        self.document_frequency = Counter()
        for frequencies in self.term_frequencies:
            self.document_frequency.update(frequencies.keys())

    def score(self, query: str) -> list[float]:
        query_terms = tokenize(query)
        doc_count = len(self.documents)
        if doc_count == 0:
            return []

        scores: list[float] = []
        for frequencies, doc_length in zip(self.term_frequencies, self.doc_lengths, strict=True):
            score = 0.0
            for term in query_terms:
                term_frequency = frequencies.get(term, 0)
                if term_frequency == 0:
                    continue
                document_frequency = self.document_frequency.get(term, 0)
                idf = math.log(1 + (doc_count - document_frequency + 0.5) / (document_frequency + 0.5))
                denominator = term_frequency + self.k1 * (
                    1 - self.b + self.b * doc_length / (self.avg_doc_length or 1)
                )
                score += idf * (term_frequency * (self.k1 + 1)) / denominator
            scores.append(score)
        return scores

    def top_k(self, query: str, k: int) -> list[tuple[int, float]]:
        scores = self.score(query)
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        return [(index, score) for index, score in ranked[:k] if score > 0]

