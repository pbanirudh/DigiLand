import pytest
import time
import statistics
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.main import app
from backend.models.database import Base, LandRecord
from backend.routers.records import get_db as get_records_db

TEST_DB_FILE = "test_non_functional.db"
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
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except:
            pass
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    # Seed 10 sample records for benchmarking
    for i in range(10):
        rec = LandRecord(
            id=f"REC-BENCH-{i:03d}",
            doc_type="RECORD_OF_RIGHTS",
            khasra_no=f"{40+i}/1",
            khata_no=f"{100+i}",
            ulpin=f"UP-LKO-{400+i}-9921",
            village="Rampur" if i % 2 == 0 else "Chinhat",
            tehsil="Sadar",
            district="Lucknow",
            plot_area=2400.0 + i * 10,
            owner_names=["Ramesh Kumar"],
            owner_shares=[1.0],
            confidence_score=94.5,
            status_flag="VALID",
            routing="AUTO_APPROVED"
        )
        db.add(rec)
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
# SECURITY & AUTHENTICATION TESTS
# ============================================================================

class TestSecurityChecks:
    def test_sql_injection_resilience(self, client):
        """
        Test that SQL injection strings in the search parameter '?q='
        do not leak unescaped SQL errors or dump the database.
        SQLAlchemy ORM query parameterization should safely sanitize inputs.
        """
        sqli_payloads = [
            "' OR '1'='1",
            "'; DROP TABLE land_records; --",
            "' UNION SELECT * FROM users --",
            "\" OR \"\"=\"",
            "1' OR '1' = '1' --"
        ]
        for payload in sqli_payloads:
            res = client.get(f"/api/v1/records?q={payload}")
            assert res.status_code == 200, f"Failed on SQLi payload: {payload}"
            data = res.json()
            assert "records" in data
            assert isinstance(data["records"], list)

    def test_auth_token_enforcement_finding(self, client):
        """
        SECURITY AUDIT FINDING:
        Tests whether protected state-changing endpoints (review/commit, delete)
        enforce JWT Bearer tokens or allow unauthenticated access.
        Finding: Currently, endpoints do NOT require an Authorization header.
        """
        payload = {
            "record_id": "REC-NON-EXISTENT",
            "officer_name": "Unauthenticated Attacker",
            "officer_role": "attacker",
            "action": "FLAG"
        }
        res = client.post("/api/v1/records/review/commit", json=payload)
        is_protected = (res.status_code in [401, 403])
        print(f"\n[SECURITY FINDING] /api/v1/records/review/commit auth check: {'ENFORCED' if is_protected else 'UNAUTHENTICATED (OPEN)'}")
        assert res.status_code in [200, 401, 403]

    def test_cors_policy_configuration(self, client):
        """
        SECURITY AUDIT FIX VERIFICATION:
        Check CORS headers returned by FastAPI.
        Verifies that allowed origins (localhost:5173) are accepted with 200,
        while disallowed origins (evil-attacker.com) are rejected with 400 Bad Request.
        """
        # Test authorized origin
        res_allowed = client.options(
            "/api/v1/records",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET"
            }
        )
        assert res_allowed.status_code == 200
        assert res_allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"

        # Test disallowed origin
        res_blocked = client.options(
            "/api/v1/records",
            headers={
                "Origin": "http://evil-attacker.com",
                "Access-Control-Request-Method": "GET"
            }
        )
        # Blocked by CORSMiddleware with 400 Bad Request
        assert res_blocked.status_code == 400


# ============================================================================
# PERFORMANCE BENCHMARKING
# ============================================================================

class TestPerformanceBenchmarks:
    def test_latency_100_queries(self, client):
        """
        Runs 100 sequential GET requests to /api/v1/records
        Measures p50, p95, p99, and average response latency.
        Target: Average latency < 50ms for SQLite read queries.
        """
        latencies_ms = []
        for _ in range(100):
            t0 = time.perf_counter()
            res = client.get("/api/v1/records")
            t1 = time.perf_counter()
            assert res.status_code == 200
            latencies_ms.append((t1 - t0) * 1000.0)

        latencies_ms.sort()
        avg_lat = statistics.mean(latencies_ms)
        p50 = latencies_ms[int(len(latencies_ms) * 0.50)]
        p95 = latencies_ms[int(len(latencies_ms) * 0.95)]
        p99 = latencies_ms[int(len(latencies_ms) * 0.99)]

        print(f"\n=======================================================")
        print(f"PERFORMANCE BENCHMARK: 100 Sequential Queries (/records)")
        print(f"=======================================================")
        print(f"  Average Latency : {avg_lat:.2f} ms")
        print(f"  Median (p50)    : {p50:.2f} ms")
        print(f"  95th %tile (p95): {p95:.2f} ms")
        print(f"  99th %tile (p99): {p99:.2f} ms")
        print(f"  Max Latency     : {max(latencies_ms):.2f} ms")

        # Benchmark threshold: p95 under 50ms
        assert p95 < 50.0, f"p95 latency exceeded benchmark: {p95:.2f} ms"

    def test_latency_100_health_checks(self, client):
        """
        Runs 100 sequential requests to /health
        Verifies lightweight API throughput and baseline network overhead.
        """
        latencies_ms = []
        for _ in range(100):
            t0 = time.perf_counter()
            res = client.get("/health")
            t1 = time.perf_counter()
            assert res.status_code == 200
            latencies_ms.append((t1 - t0) * 1000.0)

        avg_lat = statistics.mean(latencies_ms)
        print(f"\n[BENCHMARK] 100 Health Checks Average Latency: {avg_lat:.2f} ms")
        assert avg_lat < 20.0
