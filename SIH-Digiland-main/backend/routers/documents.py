from fastapi import APIRouter, HTTPException, File, UploadFile, Depends
from pydantic import BaseModel
import hashlib
from sqlalchemy.orm import Session
from backend.models.database import SessionLocal, Document as DBDocument, LandRecord as DBLandRecord
from backend.services.confidence_scoring import ConfidenceScoringService

router = APIRouter(prefix="/api/v1/documents", tags=["Document Ingestion"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class UpstreamIngestionPayload(BaseModel):
    doc_id: str
    source_document_sha256: str
    extracted_fields: dict
    field_confidence: dict
    bounding_boxes: dict

@router.post("/upload")
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    file_hash = hashlib.sha256(content).hexdigest()
    doc_id = f"DOC-{file_hash[:8].upper()}"

    # Check database immediately for duplicate document hash or filename
    existing_doc = db.query(DBDocument).filter(
        (DBDocument.sha256_hash == file_hash) | (DBDocument.file_name == file.filename)
    ).first()

    is_duplicate = False
    matched_id = None
    if existing_doc:
        is_duplicate = True
        matched_rec = db.query(DBLandRecord).filter(DBLandRecord.document_id == existing_doc.id).first()
        matched_id = matched_rec.id if matched_rec else existing_doc.id

    return {
        "doc_id": doc_id,
        "file_name": file.filename,
        "size_bytes": len(content),
        "sha256_hash": file_hash,
        "status": "QUEUED_FOR_CV_OCR",
        "is_duplicate": is_duplicate,
        "duplicate_matched_id": matched_id,
        "warning": "Duplicate document already registered in database" if is_duplicate else None
    }

@router.post("/process-document")
def process_upstream_json(payload: UpstreamIngestionPayload):
    """
    Entry point consuming structured JSON from upstream CV/OCR teammate module.
    Runs validation engine, computes composite confidence score, and determines routing.
    """
    evaluation = ConfidenceScoringService.evaluate_record(
        record_data=payload.extracted_fields,
        field_confidence=payload.field_confidence
    )
    
    return {
        "status": "PROCESSED",
        "doc_id": payload.doc_id,
        "source_hash": payload.source_document_sha256,
        "confidence_score": evaluation.get("composite_pct", round(evaluation.get("composite_confidence", 0.0) * 100, 1)),
        "status_flag": evaluation.get("status_flag", "VALID"),
        "routing": evaluation.get("routing_status", "AUTO_APPROVED"),
        "priority_level": evaluation.get("priority_level", "LOW_PRIORITY"),
        "field_confidence": payload.field_confidence,
        "bounding_boxes": payload.bounding_boxes,
        "rules_breakdown": evaluation.get("breakdown", {})
    }
