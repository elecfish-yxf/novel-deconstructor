from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..config import get_settings
from ..schemas import DirectoryPickRequest, DirectoryPickResponse


router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/config/public")
def public_config():
    settings = get_settings()
    return {
        "deepseek_base_url": settings.deepseek_base_url,
        "deepseek_model": settings.deepseek_model,
        "has_deepseek_api_key": False,
        "doubao_base_url": settings.doubao_base_url,
        "doubao_model": settings.doubao_model,
        "has_doubao_api_key": False,
        "default_writing_model": settings.doubao_model,
        "writing_models": [
            {
                "id": "deepseek-v4-flash",
                "label": "DeepSeek V4 Flash",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "available": True,
            },
            {
                "id": "deepseek-v4-pro",
                "label": "DeepSeek V4 Pro",
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "available": True,
            },
            {
                "id": settings.doubao_model,
                "label": "豆包 Seed 2.0 Pro",
                "provider": "doubao",
                "model": settings.doubao_model,
                "available": True,
            },
        ],
        "knowledge_chunk_size": settings.knowledge_chunk_size,
        "knowledge_chunk_overlap": settings.knowledge_chunk_overlap,
        "retrieval_top_k": settings.retrieval_top_k,
        "max_upload_size_mb": settings.max_upload_size_mb,
        "auth_required": settings.app_require_auth,
        "privacy_note": "应用和知识库存储在服务器。使用模型调用时，必须由当前使用者在页面填写自己的 API Key；服务器不会默认使用站长的 Key。",
    }


@router.post("/pick-directory", response_model=DirectoryPickResponse)
def pick_directory(payload: DirectoryPickRequest):
    settings = get_settings()
    if not settings.enable_directory_picker:
        raise HTTPException(status_code=400, detail="服务器环境不支持打开本机文件夹选择器；请留空使用默认输出目录。")

    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # noqa: BLE001 - reported to UI as environment capability.
        raise HTTPException(status_code=500, detail="当前运行环境无法打开系统文件夹选择器") from exc

    initial_dir = Path(payload.initial_dir or settings.app_output_dir).expanduser()
    if not initial_dir.exists():
        initial_dir = settings.output_dir.resolve()
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(title="选择默认输出目录", initialdir=str(initial_dir))
    finally:
        root.destroy()
    if not selected:
        return DirectoryPickResponse(path=None, message="未选择目录")
    return DirectoryPickResponse(path=str(Path(selected).resolve()), message="已选择目录")
