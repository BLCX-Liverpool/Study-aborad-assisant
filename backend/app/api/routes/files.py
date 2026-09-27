from fastapi import APIRouter, File, Form, UploadFile

from app.documents.ocr import DeepdocRuntimeStatus, check_ocr_runtime
from app.schemas.files import FileUploadResponse
from app.services.file_service import save_uploaded_file

router = APIRouter()


@router.post("", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    conversation_id: str | None = Form(default=None),
    source_type: str = Form(default="uploaded_document"),
) -> FileUploadResponse:
    return await save_uploaded_file(
        file=file,
        user_id=user_id,
        conversation_id=conversation_id,
        source_type=source_type,
    )


@router.get("/ocr/deepdoc/status", response_model=DeepdocRuntimeStatus)
async def deepdoc_status() -> DeepdocRuntimeStatus:
    return check_ocr_runtime()
