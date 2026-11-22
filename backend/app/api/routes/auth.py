from fastapi import APIRouter, HTTPException, Query

from app.core.auth import create_access_token
from app.core.config import get_settings


router = APIRouter()


@router.post("/development-token")
async def development_token(user_id: str = Query("local_user")) -> dict[str, str]:
    if get_settings().app_env.lower() not in {"development", "dev", "local", "test"}:
        raise HTTPException(status_code=404, detail="Not found")
    return {"access_token": create_access_token(user_id), "token_type": "bearer"}
