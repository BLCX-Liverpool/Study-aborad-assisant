from hashlib import sha256
from pathlib import Path
from re import sub
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import get_settings
from app.schemas.files import FileUploadResponse


def sanitize_filename(filename: str) -> str:
    safe = sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
    return safe or "uploaded_file"


async def save_uploaded_file(
    file: UploadFile,
    user_id: str,
    conversation_id: str | None,
    source_type: str,
) -> FileUploadResponse:
    settings = get_settings()
    file_id = str(uuid4())
    filename = sanitize_filename(file.filename or "uploaded_file")
    user_dir = Path(settings.upload_storage_dir) / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    storage_path = user_dir / f"{file_id}_{filename}"

    digest = sha256()
    with storage_path.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)

    return FileUploadResponse(
        file_id=file_id,
        filename=filename,
        mime_type=file.content_type,
        source_type=source_type,
        storage_path=str(storage_path),
        checksum=digest.hexdigest(),
    )

