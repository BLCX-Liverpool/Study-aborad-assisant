import re
from functools import lru_cache

from app.schemas.chat import ChatTurn


class TokenCounter:
    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model

    def count_text(self, text: str) -> int:
        encoding = _encoding_for_model(self.model)
        if encoding is not None:
            return max(1, len(encoding.encode(text)))
        return max(1, len(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]|[^\s]", text)))

    def count_messages(self, messages: list[ChatTurn]) -> int:
        return sum(self.count_text(message.content) + 4 for message in messages)


@lru_cache(maxsize=8)
def _encoding_for_model(model: str):
    try:
        import tiktoken
    except ImportError:
        return None
    try:
        return tiktoken.encoding_for_model(model)
    except Exception:
        try:
            return tiktoken.get_encoding("cl100k_base")
        except Exception:
            return None
