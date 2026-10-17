import pytest
import os
import json
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.main import app
from backend.models.database import Base, LandRecord, AuditTrail, Document
from backend.routers.records import get_db as get_records_db
from backend.routers.teammate_ocr import get_db as get_ocr_db

TEST_DB_FILE = "test_api_integration.db"
TEST_DATABASE_URL = f"sqlite:///./{TEST_DB_FILE}"

test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    app.dependency_overrides[get_records_db] = override_get_db
    app.dependency_overrides[get_ocr_db] = override_get_db
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except:
            pass
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    # Seed sample test records
    rec1 = LandRecord(
        id="REC-TEST-001",
        doc_type="RECORD_OF_RIGHTS",
        khasra_no="42/1",
        khata_no="108",
        ulpin="UP-LKO-421-9921",
        village="Rampur",
        tehsil="Sadar",
        district="Lucknow",
        plot_area=2428.11,
        owner_names=["Ramesh Kumar", "Suresh Kumar"],
        owner_shares=[0.5, 0.5],
        confidence_score=94.5,
        status_flag="VALID",
        routing="AUTO_APPROVED"
    )
    rec2 = LandRecord(
        id="REC-TEST-002",
        doc_type="RECORD_OF_RIGHTS",
        khasra_no="108/B",
        khata_no="489",
        ulpin="UP-LKO-108-4421",
        village="Chinhat",
        tehsil="Sadar",
        district="Lucknow",
        plot_area=4050.00,
        owner_names=["Harish Chandra", "Mahesh Chandra"],
        owner_shares=[0.6, 0.5],
        confidence_score=72.0,
        status_flag="FLAGGED_WARNING",
        routing="REQUIRES_REVIEW",
        warning_reason="Ownership shares sum to 1.1000 (> 1.0)"
    )
    db.add(rec1)
    db.add(rec2)
    db.commit()
    db.close()
    yield
    app.dependency_overrides.clear()
    test_engine.dispose()
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except:
            pass

@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ============================================================================
# API INTEGRATION TESTS
# ============================================================================

def test_health_check(client):
    """Test /health and /api/v1/health return HTTP 200 with service metadata."""
    res1 = client.get("/health")
    assert res1.status_code == 200
    assert res1.json()["status"] == "ok"
    assert res1.json()["sih_problem_statement"] == "26018"

    res2 = client.get("/api/v1/health")
    assert res2.status_code == 200
    assert res2.json()["status"] == "ok"

def test_root_endpoint(client):
    """Test / returns operational status and gateway states."""
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "Operational"
    assert "gateways" in data

def test_docs_endpoint(client):
    """Test /docs OpenAPI Swagger UI is accessible."""
    res = client.get("/docs")
    assert res.status_code == 200
    assert "swagger" in res.text.lower() or "openapi" in res.text.lower()

def test_auth_login_tehsildar(client):
    """Test /api/v1/auth/login with tehsildar role returns mock bearer token."""
    payload = {
        "email": "tehsildar@digiland.gov.in",
        "password": "Password@123",
        "role": "tehsildar"
    }
    res = client.post("/api/v1/auth/login", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["user"]["role"] == "tehsildar"
    assert data["user"]["name"] == "Rajesh Sharma, IRS"

def test_auth_login_patwari(client):
    """Test /api/v1/auth/login with patwari role."""
    payload = {
        "email": "patwari@digiland.gov.in",
        "password": "Password@123",
        "role": "patwari"
    }
    res = client.post("/api/v1/auth/login", json=payload)
    assert res.status_code == 200
    assert res.json()["user"]["name"] == "Vikram Singh Patwari"

def test_documents_upload_multipart(client):
    """Test multipart file upload to /api/v1/documents/upload."""
    dummy_file_content = b"%PDF-1.4 Mock Land Deed Scanned Content"
    files = {"file": ("test_deed.pdf", dummy_file_content, "application/pdf")}
    res = client.post("/api/v1/documents/upload", files=files)
    assert res.status_code == 200
    data = res.json()
    assert data["file_name"] == "test_deed.pdf"
    assert data["size_bytes"] == len(dummy_file_content)
    assert "sha256_hash" in data
    assert data["status"] == "QUEUED_FOR_CV_OCR"

def test_documents_process_document_success(client):
    """
    Test POST /api/v1/documents/process-document.
    VERIFICATION OF BUG-01 FIX:
    Verifies that upstream OCR ingestion returns HTTP 200 with proper confidence_score,
    routing_status, rules_breakdown, and priority_level fields without crashing.
    """
    payload = {
        "doc_id": "DOC-TEST-001",
        "source_document_sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        "extracted_fields": {
            "plot_area": 1000.0,
            "owner_shares": [0.5, 0.5]
        },
        "field_confidence": {
            "plot_area": 95.0,
            "owner_shares": 92.0
        },
        "bounding_boxes": {
            "plot_area": [10, 20, 100, 40]
        }
    }
    res = client.post("/api/v1/documents/process-document", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "PROCESSED"
    assert data["routing"] == "AUTO_APPROVED"
    assert "confidence_score" in data
    assert "rules_breakdown" in data

def test_get_all_records(client):
    """Test GET /api/v1/records returns seeded records."""
    res = client.get("/api/v1/records")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] >= 2
    assert len(data["records"]) >= 2

def test_get_all_records_with_search_query(client):
    """Test GET /api/v1/records?q=Rampur filters records correctly."""
    res = client.get("/api/v1/records?q=Rampur")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] >= 1
    assert any(r["village"] == "Rampur" for r in data["records"])

def test_get_all_records_search_no_match(client):
    """Test GET /api/v1/records?q=NonExistentPlace returns 0 records."""
    res = client.get("/api/v1/records?q=NonExistentPlaceXYZ")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 0

def test_get_flagged_records(client):
    """Test GET /api/v1/records/flagged returns only flagged/requires-review records."""
    res = client.get("/api/v1/records/flagged")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] >= 1
    assert all(r["routing"] in ["REQUIRES_REVIEW", "REJECTED_CRITICAL", "FLAGGED_WARNING"] for r in data["records"])

def test_get_record_by_id_success(client):
    """Test GET /api/v1/records/{id} for valid record ID."""
    res = client.get("/api/v1/records/REC-TEST-001")
    assert res.status_code == 200
    assert res.json()["id"] == "REC-TEST-001"
    assert res.json()["ulpin"] == "UP-LKO-421-9921"

def test_get_record_by_id_not_found(client):
    """Test GET /api/v1/records/{id} returns 404 for invalid ID."""
    res = client.get("/api/v1/records/REC-DOES-NOT-EXIST")
    assert res.status_code == 404
    assert res.json()["detail"] == "Record not found"

def test_commit_human_review_and_audit_block(client):
    """
    Test POST /api/v1/records/review/commit:
    1. Updates status to VALID & AUTO_APPROVED
    2. Writes a new block to audit_trails table with correct SHA-256 hash and Ed25519 signature
    """
    commit_payload = {
        "record_id": "REC-TEST-002",
        "corrected_fields": {
            "owner_shares": "0.5, 0.5"
        },
        "officer_name": "Rajesh Sharma, IRS",
        "officer_role": "tehsildar",
        "action": "APPROVE"
    }
    res = client.post("/api/v1/records/review/commit", json=commit_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "VERIFIED_AND_SIGNED"
    assert data["record_id"] == "REC-TEST-002"
    assert "current_hash" in data
    assert "digital_signature" in data
    assert data["digital_signature"].startswith("Ed25519-SIG:")

    # Verify record was updated in database
    rec_res = client.get("/api/v1/records/REC-TEST-002")
    assert rec_res.status_code == 200
    assert rec_res.json()["status_flag"] == "VALID"
    assert rec_res.json()["routing"] == "AUTO_APPROVED"

def test_get_audit_trail_all(client):
    """Test GET /api/v1/records/audit-trail/all returns blockchain blocks with ISO timestamps."""
    res = client.get("/api/v1/records/audit-trail/all")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] >= 1
    latest_block = data["blocks"][-1]
    assert latest_block["record_id"] == "REC-TEST-002"
    assert latest_block["action"] == "HUMAN_REVIEW_APPROVE"
    assert latest_block["current_hash"] is not None

def test_verify_hash_chain_endpoint_success(client):
    """
    Test GET /api/v1/records/{id}/verify-chain.
    VERIFICATION OF BUG-02 FIX:
    Verifies that the SHA-256 block hash calculation matches the persisted DBAuditTrail entity,
    and verify_chain_integrity confirms that all cryptographic blocks pass integrity checks without tampering.
    """
    res = client.get("/api/v1/records/REC-TEST-002/verify-chain")
    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is True
    assert "Hash Chain Verified" in data["details"]

def test_gis_parcels_endpoint(client):
    """Test GET /api/v1/gis/parcels returns valid GeoJSON FeatureCollection."""
    res = client.get("/api/v1/gis/parcels")
    assert res.status_code == 200
    data = res.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) >= 2
    f = data["features"][0]
    assert f["geometry"]["type"] == "Polygon"
    assert "khasra_no" in f["properties"]

def test_dashboard_metrics_endpoint(client):
    """Test GET /api/v1/dashboard/metrics returns four KPI metric cards."""
    res = client.get("/api/v1/dashboard/metrics")
    assert res.status_code == 200
    data = res.json()
    assert "archival_digitization" in data
    assert "ocr_nlp_accuracy" in data
    assert "pending_verification" in data
    assert "district_digitization" in data

def test_ocr_preset_payloads_endpoint(client):
    """Test GET /api/v1/ocr/preset-payloads returns all 4 doc types."""
    res = client.get("/api/v1/ocr/preset-payloads")
    assert res.status_code == 200
    data = res.json()
    assert "RECORD_OF_RIGHTS" in data
    assert "CONVEYANCE_DEED" in data
    assert "MUTATION_ORDER" in data
    assert "CADASTRAL_MAP" in data

def test_ocr_generate_synthetic_doc_endpoint(client):
    """Test POST /api/v1/ocr/generate-synthetic-doc renders base64 PNG."""
    payload = {
        "doc_type": "RECORD_OF_RIGHTS",
        "payload": {
            "khata_number": "489",
            "khasra_no": "142/3B",
            "ulpin": "14BW89201L9842"
        }
    }
    res = client.post("/api/v1/ocr/generate-synthetic-doc", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["image_base64"].startswith("data:image/png;base64,")

def test_ocr_classify_and_extract_endpoint(client):
    """Test POST /api/v1/ocr/classify-and-extract."""
    payload = {
        "text_lines": [
            "MUTATION REGISTER DAKHIL-KHARIJ",
            "CASE REFERENCE: REV/TEH/2024/782",
            "TEHSILDAR LUCKNOW SADAR"
        ]
    }
    res = client.post("/api/v1/ocr/classify-and-extract", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["classified_document_type"] == "MUTATION_ORDER"
    assert data["classification_confidence"] > 0

def test_ocr_process_full_pipeline_endpoint(client):
    """Test POST /api/v1/ocr/process-full-pipeline executes all 6 stages and commits to DB."""
    payload = {
        "doc_type": "RECORD_OF_RIGHTS",
        "record_data": {
            "khasra_no": "55/1",
            "khata_no": "220",
            "ulpin": "UP-LKO-055-1020",
            "village": "Rampur",
            "district": "Lucknow",
            "plot_area": 1820.0,
            "owner_names": ["Mohan Lal"],
            "owner_shares": [1.0]
        },
        "file_name": "ror_sample.pdf"
    }
    res = client.post("/api/v1/ocr/process-full-pipeline", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["routing"] == "AUTO_APPROVED"
    assert "current_hash" in data
    assert "record" in data
    assert data["record"]["khasra_no"] == "55/1"

def test_delete_record_by_id_and_audit(client):
    """Test DELETE /api/v1/records/{id} removes record and logs audit purge block."""
    del_res = client.delete("/api/v1/records/REC-TEST-001")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "DELETED"

    # Confirm record is gone
    get_res = client.get("/api/v1/records/REC-TEST-001")
    assert get_res.status_code == 404

    # Confirm deletion is logged to audit trail
    audit_res = client.get("/api/v1/records/audit-trail/all")
    assert audit_res.status_code == 200
    blocks = audit_res.json()["blocks"]
    assert any(b["action"] == "PURGE_DUPLICATE" and b["record_id"] == "REC-TEST-001" for b in blocks)

def test_purge_duplicates_endpoint(client):
    """Test POST /api/v1/records/purge-duplicates."""
    res = client.post("/api/v1/records/purge-duplicates")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "DEDUPLICATED"
    assert "purged_count" in data

def test_negative_invalid_payload_validation_error(client):
    """Test POST /api/v1/ocr/classify-and-extract returns 422 Unprocessable Entity when missing required body."""
    res = client.post("/api/v1/ocr/classify-and-extract", json={})
    assert res.status_code == 422

def test_check_duplicate_endpoint_detected(client):
    """Test POST /api/v1/records/check-duplicate identifies duplicate by ULPIN / Khasra."""
    payload = {
        "ulpin": "UP-LKO-108-4421",
        "khasra_no": "108/B",
        "village": "Chinhat"
    }
    res = client.post("/api/v1/records/check-duplicate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["is_duplicate"] is True
    assert data["matched_record_id"] == "REC-TEST-002"
    assert "already registered" in data["match_reason"]

def test_check_duplicate_endpoint_not_detected(client):
    """Test POST /api/v1/records/check-duplicate returns is_duplicate=False for new plot."""
    payload = {
        "ulpin": "NEW-ULPIN-9999-XXXX",
        "khasra_no": "999/99",
        "village": "BrandNewVillage"
    }
    res = client.post("/api/v1/records/check-duplicate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["is_duplicate"] is False
    assert data["matched_record_id"] is None

def test_ocr_process_full_pipeline_flags_duplicate_at_start(client):
    """Test full pipeline immediately flags duplicate upload and prevents AUTO_APPROVED."""
    payload = {
        "doc_type": "RECORD_OF_RIGHTS",
        "record_data": {
            "id": "REC-DUP-TEST-002",
            "khasra_no": "108/B",
            "khata_no": "489",
            "ulpin": "UP-LKO-108-4421",
            "village": "Chinhat",
            "district": "Lucknow",
            "plot_area": 4050.0,
            "owner_names": ["Harish Chandra"],
            "owner_shares": [1.0]
        },
        "file_name": "duplicate_scan.pdf"
    }
    res = client.post("/api/v1/ocr/process-full-pipeline", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["is_duplicate"] is True
    assert data["routing"] != "AUTO_APPROVED"
    assert data["routing"] in ["REQUIRES_REVIEW", "REJECTED_CRITICAL"]
    assert data["status_flag"] in ["FLAGGED_WARNING", "FAILED_CRITICAL"]
    assert data["priority_level"] == "HIGH_PRIORITY"
    assert data["duplicate_matched_id"] == "REC-TEST-002"

