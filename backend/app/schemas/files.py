from pydantic import BaseModel


class FileUploadResponse(BaseModel):
    file_id: str
    filename: str
    mime_type: str | None
    source_type: str
    storage_path: str
    checksum: str
    status: str = "uploaded"

