import json
from typing import TypeVar

from pydantic import BaseModel

from app.core.config import get_settings


MessageModel = TypeVar("MessageModel", bound=BaseModel)


class MessageTooLarge(ValueError):
    pass


def serialize_message(message: BaseModel | dict) -> bytes:
    payload = message.model_dump(mode="json") if isinstance(message, BaseModel) else message
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    limit = get_settings().rabbitmq_message_max_bytes
    if len(body) > limit:
        raise MessageTooLarge(f"RabbitMQ message is {len(body)} bytes; limit is {limit}")
    return body


def deserialize_message(body: bytes, model: type[MessageModel]) -> MessageModel:
    if len(body) > get_settings().rabbitmq_message_max_bytes:
        raise MessageTooLarge("RabbitMQ message exceeds configured size limit")
    return model.model_validate_json(body)
