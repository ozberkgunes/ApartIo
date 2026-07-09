import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import models, scoping
from ..auth import get_current_user, require_role
from ..config import MAX_UPLOAD_SIZE, UPLOAD_DIR
from ..database import get_db
from ..models import ROLE_BUILDING_MANAGER, ROLE_SITE_MANAGER
from ..templating import templates
from .dues import parse_scope, scope_options

router = APIRouter()

managers_only = require_role(ROLE_SITE_MANAGER, ROLE_BUILDING_MANAGER)


@router.get("/documents")
def list_documents(
    request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    documents = scoping.scoped_documents(db, user)
    options = scope_options(db) if user.role == ROLE_SITE_MANAGER else []
    return templates.TemplateResponse(
        request,
        "documents/list.html",
        {"user": user, "documents": documents, "scope_options": options},
    )


@router.post("/documents/upload")
async def upload_document(
    scope: str = Form(""),
    title: str = Form(...),
    category: str = Form("other"),
    is_public: str = Form(""),
    file: UploadFile = File(...),
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    if user.role == ROLE_BUILDING_MANAGER:
        if user.block is None:
            raise HTTPException(403, "Size atanmış bir blok yok.")
        site_id, block_id = user.block.site_id, user.block_id
    else:
        site_id, block_id = parse_scope(db, scope)
    if category not in models.DOC_CATEGORY_LABELS:
        raise HTTPException(400, "Geçersiz kategori")

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        return RedirectResponse("/documents?err=Dosya 10 MB sınırını aşıyor", status_code=303)
    if not content:
        return RedirectResponse("/documents?err=Boş dosya yüklenemez", status_code=303)

    UPLOAD_DIR.mkdir(exist_ok=True)
    extension = Path(file.filename or "").suffix[:16]
    stored_name = f"{uuid.uuid4().hex}{extension}"
    (UPLOAD_DIR / stored_name).write_bytes(content)

    db.add(
        models.Document(
            site_id=site_id,
            block_id=block_id,
            title=title.strip(),
            category=category,
            original_name=file.filename or stored_name,
            stored_name=stored_name,
            content_type=file.content_type,
            size=len(content),
            is_public=bool(is_public),
            uploaded_by=user.id,
        )
    )
    db.commit()
    return RedirectResponse("/documents?msg=Belge yüklendi", status_code=303)


@router.get("/documents/{document_id}/download")
def download_document(
    document_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = db.get(models.Document, document_id)
    if document is None:
        raise HTTPException(404, "Belge bulunamadı")
    if not scoping.can_access_document(db, user, document):
        raise HTTPException(403, "Bu belgeye erişim yetkiniz yok.")
    file_path = UPLOAD_DIR / document.stored_name
    if not file_path.exists():
        raise HTTPException(404, "Dosya sunucuda bulunamadı")
    return FileResponse(
        file_path,
        filename=document.original_name,
        media_type=document.content_type or "application/octet-stream",
    )


@router.post("/documents/{document_id}/delete")
def delete_document(
    document_id: int,
    user: models.User = Depends(managers_only),
    db: Session = Depends(get_db),
):
    document = db.get(models.Document, document_id)
    if document is None:
        raise HTTPException(404, "Belge bulunamadı")
    if user.role != ROLE_SITE_MANAGER and document.uploaded_by != user.id:
        raise HTTPException(403, "Sadece kendi yüklediğiniz belgeyi silebilirsiniz.")
    (UPLOAD_DIR / document.stored_name).unlink(missing_ok=True)
    db.delete(document)
    db.commit()
    return RedirectResponse("/documents?msg=Belge silindi", status_code=303)
