import pytest
import math
from backend.services.validation_engine import ValidationEngine
from backend.services.confidence_scoring import (
    compute_composite_confidence,
    auto_detect_document_type,
    ConfidenceScoringService
)
from backend.services.audit_chain import AuditChainService
from backend.services.gov_gateway import (
    MockGovApiAdapter,
    RealGovApiAdapter,
    get_gov_gateway
)
from backend.services.teammate_parser import (
    classify_document,
    parse_document_ocr
)

# ============================================================================
# 1. VALIDATION ENGINE UNIT TESTS
# ============================================================================

class TestValidationEngine:
    def test_share_fractions_half_plus_half(self):
        """Test share sum 0.5 + 0.5 equals 1.0 (passes)."""
        res = ValidationEngine.validate_share_fractions([0.5, 0.5])
        assert res["passed"] is True
        assert "1.0 (100%)" in res["details"]

    def test_share_fractions_under_allocated(self):
        """Test share sum 0.5 + 0.3333 = 0.8333 (under-allocated, fails)."""
        res = ValidationEngine.validate_share_fractions([0.5, 0.3333])
        assert res["passed"] is False
        assert "Under-allocated" in res["details"]

    def test_share_fractions_over_allocated(self):
        """Test share sum 0.6 + 0.5 = 1.1 (over-allocated, fails)."""
        res = ValidationEngine.validate_share_fractions([0.6, 0.5])
        assert res["passed"] is False
        assert "Over-allocated" in res["details"]

    def test_share_fractions_empty(self):
        """Test empty share list fails."""
        res = ValidationEngine.validate_share_fractions([])
        assert res["passed"] is False
        assert "Missing" in res["details"]

    def test_share_fractions_rounding_float(self):
        """Test floating rounding: 1/3 + 1/3 + 1/3 sum rounded to 4 decimals."""
        res = ValidationEngine.validate_share_fractions([0.3333, 0.3333, 0.3334])
        assert res["passed"] is True
        assert res["passed"] is True

    def test_area_sum_balanced(self):
        """Test sub-plots sum matching parent parcel area within 2% tolerance."""
        res = ValidationEngine.validate_area_sum(1000.0, [500.0, 500.0], tolerance=0.02)
        assert res["passed"] is True
        assert "balanced" in res["details"]

    def test_area_sum_within_tolerance(self):
        """Test sub-plots sum 1015 vs parent 1000 (1.5% diff <= 2% tolerance)."""
        res = ValidationEngine.validate_area_sum(1000.0, [500.0, 515.0], tolerance=0.02)
        assert res["passed"] is True

    def test_area_sum_exceeds_tolerance(self):
        """Test sub-plots sum 1050 vs parent 1000 (5% diff > 2% tolerance)."""
        res = ValidationEngine.validate_area_sum(1000.0, [500.0, 550.0], tolerance=0.02)
        assert res["passed"] is False
        assert "Mismatch" in res["details"]

    def test_area_sum_empty_subplots(self):
        """Test single plot with empty sub-plots list passes."""
        res = ValidationEngine.validate_area_sum(1000.0, [])
        assert res["passed"] is True
        assert "Single plot" in res["details"]

    def test_ulpin_format_standard(self):
        """Test standard hyphenated ULPIN format: UP-LKO-421-9921."""
        res = ValidationEngine.validate_ulpin_format("UP-LKO-421-9921")
        assert res["passed"] is True

    def test_ulpin_format_14_alphanumeric_uppercase(self):
        """Test 14-char uppercase alphanumeric ULPIN: 14BW89201L9842."""
        res = ValidationEngine.validate_ulpin_format("14BW89201L9842")
        assert res["passed"] is True

    def test_ulpin_format_invalid_length_and_symbols(self):
        """Test invalid ULPIN formats."""
        assert ValidationEngine.validate_ulpin_format("UP123")["passed"] is False
        assert ValidationEngine.validate_ulpin_format("UP-LKO-421-9921-EXTRA")["passed"] is False
        assert ValidationEngine.validate_ulpin_format("")["passed"] is False
        assert ValidationEngine.validate_ulpin_format(None)["passed"] is False

    def test_prohibited_transfer_clean(self):
        """Test clean agricultural title has no prohibited transfer triggers."""
        res = ValidationEngine.check_prohibited_transfers(["Ramesh Kumar"], "Chahi (Irrigated)")
        assert res["passed"] is True

    def test_prohibited_transfer_encroachment_detected(self):
        """Test individual claiming Gram Sabha / Forest Reserve triggers alert."""
        res1 = ValidationEngine.check_prohibited_transfers(["Ramesh Kumar"], "Gram Sabha Communal")
        assert res1["passed"] is False
        assert "PROHIBITED TRANSFER ALERT" in res1["details"]

        res2 = ValidationEngine.check_prohibited_transfers(["Forest Reserve Encroacher"], "Barani (Rainfed)")
        assert res2["passed"] is False

    def test_prohibited_transfer_valid_gram_sabha(self):
        """Test legitimate Gram Sabha communal property owner passes."""
        res = ValidationEngine.check_prohibited_transfers(["Gram Sabha Communal Land"], "Gram Sabha Communal")
        assert res["passed"] is True
        assert "Verified official Gram Sabha" in res["details"]

    def test_lgd_master_known_codes(self):
        """Test LGD village master matching."""
        # Chinhat / Lucknow for 148205
        res_valid = ValidationEngine.validate_lgd_master("148205", "Chinhat", "Lucknow")
        assert res_valid["passed"] is True

        # Chinhat code with wrong village Rampur
        res_invalid = ValidationEngine.validate_lgd_master("148205", "Rampur", "Lucknow")
        assert res_invalid["passed"] is False
        assert "mismatch" in res_invalid["details"].lower()

        # Unknown code fallback (assumes valid state registry)
        res_unknown = ValidationEngine.validate_lgd_master("999999", "SomeVillage", "SomeDistrict")
        assert res_unknown["passed"] is True

    def test_run_all_checks_aggregation(self):
        """Test running all checks aggregates pass rates correctly."""
        rec = {
            "owner_shares": [0.5, 0.5],
            "ulpin": "UP-LKO-421-9921",
            "owner_names": ["Ramesh Kumar", "Suresh Kumar"],
            "land_classification": "Chahi (Irrigated)",
            "lgd_code": "148201",
            "village": "Rampur",
            "district": "Lucknow"
        }
        res = ValidationEngine.run_all_checks(rec)
        assert res["pass_rate"] == 100.0
        assert res["passed_count"] == 4
        assert res["total_rules"] == 4


# ============================================================================
# 2. CONFIDENCE SCORING & DECISION GATING UNIT TESTS
# ============================================================================

class TestConfidenceScoring:
    def test_formula_weights_calculation(self):
        """
        Verify Composite Formula:
        C = 0.35 * C_OCR + 0.30 * C_Rules + 0.20 * C_DB + 0.15 * C_Dup
        With C_OCR=1.0, C_Rules=1.0, C_DB=1.0, C_Dup=1.0 -> C = 1.00 (AUTO_APPROVED).
        """
        record = {
            "plot_area": 1000.0,
            "owner_shares": [1.0],
            "plot_area_sqm": 1000.0
        }
        res = compute_composite_confidence(
            ocr_confidence=1.0,
            parsed_record=record,
            gis_polygon_area=1000.0,
            is_duplicate=False
        )
        assert res["composite_confidence"] == 1.0
        assert res["composite_pct"] == 100.0
        assert res["routing_status"] == "AUTO_APPROVED"
        assert res["status_flag"] == "VALID"
        assert res["priority_level"] == "LOW_PRIORITY"

    def test_boundary_auto_approved_at_85(self):
        """Score >= 0.85 with C_Rules=1.0 routes to AUTO_APPROVED."""
        # OCR = 0.85, Rules = 1.0, DB = 0.8 (fallback), Dup = 1.0
        # C = 0.35*0.85 (0.2975) + 0.30*1.0 (0.30) + 0.20*0.8 (0.16) + 0.15*1.0 (0.15) = 0.9075 -> 0.91
        record = {"owner_shares": [1.0]}
        res = compute_composite_confidence(
            ocr_confidence=0.85,
            parsed_record=record,
            gis_polygon_area=0.0, # fallback DB = 0.8
            is_duplicate=False
        )
        assert res["composite_confidence"] >= 0.85
        assert res["routing_status"] == "AUTO_APPROVED"

    def test_boundary_requires_review_at_60_to_84(self):
        """Score between 0.60 and 0.849 with C_Rules=1.0 routes to REQUIRES_REVIEW."""
        # OCR = 0.50, Rules = 1.0, DB = 0.5 (variance > 2%), Dup = 1.0
        # C = 0.35*0.5 (0.175) + 0.30*1.0 (0.30) + 0.20*0.5 (0.10) + 0.15*1.0 (0.15) = 0.725 -> 0.73
        record = {
            "plot_area": 1000.0,
            "plot_area_sqm": 1000.0,
            "owner_shares": [1.0]
        }
        res = compute_composite_confidence(
            ocr_confidence=0.50,
            parsed_record=record,
            gis_polygon_area=1200.0, # 20% variance -> C_DB=0.5
            is_duplicate=False
        )
        assert 0.60 <= res["composite_confidence"] < 0.85
        assert res["routing_status"] == "REQUIRES_REVIEW"
        assert res["status_flag"] == "FLAGGED_WARNING"
        assert res["priority_level"] == "MEDIUM_PRIORITY"

    def test_boundary_rejected_below_60(self):
        """Score < 0.60 routes to REJECTED_CRITICAL."""
        # OCR = 0.20, Rules = 1.0, DB = 0.5, Dup = 0.0 (duplicate)
        # C = 0.35*0.2 (0.07) + 0.30*1.0 (0.30) + 0.20*0.5 (0.10) + 0.15*0.0 (0.0) = 0.47
        record = {
            "plot_area": 1000.0,
            "plot_area_sqm": 1000.0,
            "owner_shares": [1.0]
        }
        res = compute_composite_confidence(
            ocr_confidence=0.20,
            parsed_record=record,
            gis_polygon_area=1200.0,
            is_duplicate=True
        )
        assert res["composite_confidence"] < 0.60
        assert res["routing_status"] == "REJECTED_CRITICAL"
        assert res["status_flag"] == "FAILED_CRITICAL"
        assert res["priority_level"] == "HIGH_PRIORITY"

    def test_rule_failure_hard_rejection_override(self):
        """Rule invariant failure drops C_Rules to 0.0 and rejects regardless of high OCR."""
        # Share sum is 0.5 + 0.2 = 0.7 != 1.0. Even with OCR = 1.0, must reject.
        record = {
            "plot_area": 1000.0,
            "owner_shares": [0.5, 0.2]
        }
        res = compute_composite_confidence(
            ocr_confidence=1.0,
            parsed_record=record,
            gis_polygon_area=1000.0,
            is_duplicate=False
        )
        assert res["breakdown"]["rules_score"] == 0.0
        assert res["breakdown"]["share_rule_passed"] is False
        assert res["routing_status"] == "REJECTED_CRITICAL"
        assert res["status_flag"] == "FAILED_CRITICAL"

    def test_duplicate_penalty(self):
        """Duplicate record must set deduplication_score to 0.0."""
        record = {"owner_shares": [1.0]}
        res = compute_composite_confidence(
            ocr_confidence=0.95,
            parsed_record=record,
            is_duplicate=True
        )
        assert res["breakdown"]["deduplication_score"] == 0.0

    def test_no_gis_fallback(self):
        """When no GIS polygon area is available, C_DB defaults to 0.8."""
        record = {"owner_shares": [1.0]}
        res = compute_composite_confidence(
            ocr_confidence=0.90,
            parsed_record=record,
            gis_polygon_area=0.0
        )
        assert res["breakdown"]["database_gis_score"] == 0.8

    def test_fraction_string_parsing_in_shares(self):
        """Test owner shares passed as fraction strings like '1/2'."""
        record = {
            "plot_area": 1000.0,
            "owner_shares": ["1/2", "1/2"]
        }
        res = compute_composite_confidence(0.95, record)
        assert res["breakdown"]["share_rule_passed"] is True

    def test_auto_detect_document_type(self):
        """Test document classifier detects all 4 land record document types."""
        assert auto_detect_document_type("Execution of absolute sale deed at SRO") == "CONVEYANCE_DEED"
        assert auto_detect_document_type("Mutation order issued by Tehsildar dakhil-kharij") == "MUTATION_REGISTER"
        assert auto_detect_document_type("Cadastral map bhu-naksha sheet EPSG:4326") == "CADASTRAL_MAP"
        assert auto_detect_document_type("தமிழ்நாடு அரசு புல எண் 5 பரப்பளவு") == "CADASTRAL_MAP"
        assert auto_detect_document_type("Jamabandi Khata number and Patta") == "RECORD_OF_RIGHTS"

    def test_confidence_scoring_service_wrapper(self):
        """Test ConfidenceScoringService evaluate_record wrapper."""
        rec = {"owner_shares": [1.0], "plot_area": 500.0}
        fields = {"owner": 92.0, "khasra": 96.0}
        res = ConfidenceScoringService.evaluate_record(rec, fields)
        assert res["composite_confidence"] >= 0.85


# ============================================================================
# 3. AUDIT HASH CHAIN & DIGITAL SIGNATURE UNIT TESTS
# ============================================================================

class TestAuditChainService:
    def test_genesis_hash_format(self):
        """Genesis hash must be 64 hexadecimal zeros (256 bits)."""
        assert AuditChainService.GENESIS_HASH == "0" * 64
        assert len(AuditChainService.GENESIS_HASH) == 64

    def test_block_hash_calculation(self):
        """Test SHA-256 block hash computation is deterministic and sorted."""
        payload = {
            "record_id": "REC-001",
            "action": "CREATE",
            "field_changed": "status",
            "new_value": "VALID",
            "actor_name": "Rajesh Sharma"
        }
        h1 = AuditChainService.calculate_block_hash(AuditChainService.GENESIS_HASH, payload)
        h2 = AuditChainService.calculate_block_hash(AuditChainService.GENESIS_HASH, payload)
        assert h1 == h2
        assert len(h1) == 64

    def test_digital_signature_generation(self):
        """Test Ed25519 digital signature simulator format."""
        sig = AuditChainService.generate_digital_signature("tehsildar", "abcdef1234567890")
        assert sig.startswith("Ed25519-SIG:")
        assert len(sig) > 20

    def test_verify_clean_chain(self):
        """Test verifying an un-tampered 3-block audit chain."""
        chain = []
        prev = AuditChainService.GENESIS_HASH

        for i in range(3):
            payload = {
                "record_id": f"REC-00{i+1}",
                "action": f"ACTION_{i}",
                "field_changed": "status",
                "new_value": f"VALUE_{i}",
                "actor_name": "Rajesh Sharma"
            }
            h = AuditChainService.calculate_block_hash(prev, payload)
            chain.append({
                "history_id": i + 1,
                "record_id": f"REC-00{i+1}",
                "action": f"ACTION_{i}",
                "field_changed": "status",
                "new_value": f"VALUE_{i}",
                "actor_name": "Rajesh Sharma",
                "previous_hash": prev,
                "current_hash": h
            })
            prev = h

        res = AuditChainService.verify_chain_integrity(chain)
        assert res["valid"] is True
        assert res["total_blocks"] == 3
        assert res["latest_block_hash"] == prev

    def test_tamper_detection_modified_payload(self):
        """Test tampering with a payload field triggers tampering alert."""
        chain = []
        prev = AuditChainService.GENESIS_HASH

        for i in range(2):
            payload = {
                "record_id": f"REC-00{i+1}",
                "action": "APPROVE",
                "field_changed": "status",
                "new_value": "VALID",
                "actor_name": "Rajesh Sharma"
            }
            h = AuditChainService.calculate_block_hash(prev, payload)
            chain.append({
                "history_id": i + 1,
                "record_id": f"REC-00{i+1}",
                "action": "APPROVE",
                "field_changed": "status",
                "new_value": "VALID",
                "actor_name": "Rajesh Sharma",
                "previous_hash": prev,
                "current_hash": h
            })
            prev = h

        # Malicious modification: change new_value on block 1
        chain[1]["new_value"] = "TAMPERED_FRAUDULENT_TRANSFER"
        res = AuditChainService.verify_chain_integrity(chain)
        assert res["valid"] is False
        assert res["tampered_at_index"] == 1
        assert "Data Tampering Detected" in res["details"]

    def test_tamper_detection_broken_previous_hash(self):
        """Test corrupting previous_hash link breaks the chain."""
        chain = []
        prev = AuditChainService.GENESIS_HASH

        for i in range(2):
            payload = {
                "record_id": f"REC-00{i+1}",
                "action": "APPROVE",
                "field_changed": "status",
                "new_value": "VALID",
                "actor_name": "Rajesh Sharma"
            }
            h = AuditChainService.calculate_block_hash(prev, payload)
            chain.append({
                "history_id": i + 1,
                "record_id": f"REC-00{i+1}",
                "action": "APPROVE",
                "field_changed": "status",
                "new_value": "VALID",
                "actor_name": "Rajesh Sharma",
                "previous_hash": prev,
                "current_hash": h
            })
            prev = h

        # Corrupt previous_hash of block 1
        chain[1]["previous_hash"] = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
        res = AuditChainService.verify_chain_integrity(chain)
        assert res["valid"] is False
        assert res["tampered_at_index"] == 1
        assert "Chain Broken" in res["details"]

    def test_tamper_detection_deleted_middle_block(self):
        """Test deleting a middle block breaks the previous_hash link of next block."""
        chain = []
        prev = AuditChainService.GENESIS_HASH

        for i in range(3):
            payload = {
                "record_id": f"REC-00{i+1}",
                "action": "APPROVE",
                "field_changed": "status",
                "new_value": "VALID",
                "actor_name": "Rajesh Sharma"
            }
            h = AuditChainService.calculate_block_hash(prev, payload)
            chain.append({
                "history_id": i + 1,
                "record_id": f"REC-00{i+1}",
                "action": "APPROVE",
                "field_changed": "status",
                "new_value": "VALID",
                "actor_name": "Rajesh Sharma",
                "previous_hash": prev,
                "current_hash": h
            })
            prev = h

        # Delete middle block index 1
        del chain[1]
        res = AuditChainService.verify_chain_integrity(chain)
        assert res["valid"] is False
        assert res["tampered_at_index"] == 1
        assert "Chain Broken" in res["details"]

    def test_empty_chain_is_valid_zero_state(self):
        """Test empty chain returns valid zero state."""
        res = AuditChainService.verify_chain_integrity([])
        assert res["valid"] is True
        assert "valid zero state" in res["details"]


# ============================================================================
# 4. GOVERNMENT GATEWAY ADAPTER UNIT TESTS
# ============================================================================

class TestGovGateway:
    def test_mock_adapter_verify_deed(self):
        gateway = get_gov_gateway(use_mock=True)
        res = gateway.verify_deed("DEED/2024/991", 2024)
        assert res["verified"] is True
        assert res["deed_no"] == "DEED/2024/991"
        assert "HMAC-SHA256" in res["hmac_signature"]

    def test_mock_adapter_validate_lgd(self):
        gateway = get_gov_gateway(use_mock=True)
        assert gateway.validate_village_lgd("09", "148201") is True
        assert gateway.validate_village_lgd("09", "999999") is False

    def test_mock_adapter_lookup_ulpin(self):
        gateway = get_gov_gateway(use_mock=True)
        res = gateway.lookup_ulpin("UP-LKO-421-9921")
        assert res["bhu_aadhaar_status"] == "Active"
        assert res["cadastral_match"] is True

    def test_real_adapter_instantiation(self):
        gateway = get_gov_gateway(use_mock=False)
        assert isinstance(gateway, RealGovApiAdapter)
        assert gateway.verify_deed("DEED/1", 2024)["mode"] == "API Setu Live"


# ============================================================================
# 5. OCR CLASSIFIER & PARSER UNIT TESTS
# ============================================================================

class TestTeammateParser:
    def test_classify_record_of_rights(self):
        text = [
            "GOVERNMENT OF UTTAR PRADESH",
            "JAMABANDI / RECORD OF RIGHTS (KHATAUNI)",
            "KHATA NUMBER: 489",
            "BHU-AADHAAR ULPIN: 14BW89201L9842"
        ]
        doc_type, conf = classify_document(text)
        assert doc_type == "RECORD_OF_RIGHTS"
        assert conf > 50.0

    def test_classify_conveyance_deed(self):
        text = [
            "DEED OF ABSOLUTE SALE",
            "STAMP DUTY PAID: 105000",
            "PURCHASER AND EXECUTANT",
            "SRO OFFICE SADAR"
        ]
        doc_type, conf = classify_document(text)
        assert doc_type == "CONVEYANCE_DEED"
        assert conf > 50.0

    def test_classify_mutation_order(self):
        text = [
            "OFFICE OF THE TEHSILDAR",
            "MUTATION REGISTER DAKHIL-KHARIJ FORM VF-6",
            "SANCTIONING AUTHORITY ORDER",
            "SUCCESSION_INHERITANCE"
        ]
        doc_type, conf = classify_document(text)
        assert doc_type == "MUTATION_ORDER"
        assert conf > 50.0

    def test_classify_cadastral_map_tamil(self):
        text = [
            "வருவாய்த் துறை புல எல்லை படம் FIELD MEASUREMENT BOOK",
            "தஞ்சாவூர் மாவட்டம், பூதலூர் வட்டம், குருங்குளம் கிராமம்",
            "புல எண்: 5/1B",
            "அளவு: 1:2658"
        ]
        doc_type, conf = classify_document(text)
        assert doc_type == "CADASTRAL_MAP"
        assert conf > 50.0

    def test_parse_document_ocr_cadastral_tamil(self):
        text = [
            "FIELD MEASUREMENT BOOK",
            "தஞ்சாவூர் மாவட்டம்",
            "பூதலூர் வட்டம்",
            "குருங்குளம் கிராமம்",
            "புல எண்: 5",
            "அளவு: 1:2658",
            "ஹெக்டர் 5 ஏர் 40.50"
        ]
        parsed = parse_document_ocr(text)
        assert parsed["classified_document_type"] == "CADASTRAL_MAP"
        payload = parsed["structured_payload"]
        assert payload["district"] == "Thanjavur"
        assert payload["tehsil"] == "Budalur"
        assert payload["village"] == "Kurungulam"
        assert payload["khasra_survey_number"] == "5"
        assert payload["calculated_gis_area_sqm"] == 54050.0

    def test_parse_empty_or_garbage_text(self):
        """Test graceful handling of empty or unidentifiable text."""
        parsed = parse_document_ocr([])
        assert parsed["classified_document_type"] == "RECORD_OF_RIGHTS"
        assert "structured_payload" in parsed
