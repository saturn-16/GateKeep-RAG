import os
import time
from io import BytesIO

import docx
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("qdrant_client")
pytest.importorskip("sqlalchemy")

from app.main import app

pytestmark = pytest.mark.real_stack


def _generate_pdf(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({
        NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'),
    })
    page[NameObject('/Resources')] = DictionaryObject({
        NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})
    })
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 20 200 Td ({text}) Tj ET".encode("latin-1"))
    page[NameObject('/Contents')] = stream
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _generate_docx(text: str) -> bytes:
    doc = docx.Document()
    doc.add_paragraph(text)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.mark.skipif(
    os.getenv("RUN_REAL_STACK") != "1"
    or os.getenv("PERSISTENCE_BACKEND") != "postgres"
    or os.getenv("VECTOR_BACKEND") != "qdrant",
    reason="requires live PostgreSQL and Qdrant API backends",
)
def test_end_to_end_multipart_ingestion_and_failure_handling() -> None:
    client = TestClient(app)
    bob_token = client.post("/v1/auth/login", json={"username": "bob", "password": "bob"}).json()["access_token"]
    dave_token = client.post("/v1/auth/login", json={"username": "dave", "password": "dave"}).json()["access_token"]
    hr_headers = {"Authorization": f"Bearer {bob_token}"}
    emp_headers = {"Authorization": f"Bearer {dave_token}"}

    from uuid import uuid4
    run_id = uuid4().hex[:8]
    uploads = [
        (
            f"benchmarks-{run_id}.pdf",
            _generate_pdf(f"Executive Compensation Benchmarks {run_id} for high-performing leaders"),
            "application/pdf",
            f"Executive Compensation Benchmarks {run_id}",
            f"Executive Compensation Benchmarks {run_id}",
        ),
        (
            f"severance-{run_id}.docx",
            _generate_docx(f"Confidential Severance Guidelines {run_id} and executive transition policies"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            f"Executive Severance Guidelines {run_id}",
            f"executive transition policies {run_id}",
        ),
        (
            f"ratings-{run_id}.md",
            f"# Leadership Performance Ratings {run_id}\n\nConfidential calibrated ratings {run_id} for leadership review.".encode(),
            "text/markdown",
            f"Leadership Performance Ratings {run_id}",
            f"calibrated ratings {run_id}",
        ),
        (
            f"medical-{run_id}.txt",
            f"Medical Benefit Exceptions {run_id} for executive management.".encode(),
            "text/plain",
            f"Medical Benefit Exceptions {run_id}",
            f"Medical Benefit Exceptions {run_id}",
        ),
    ]

    ingested_ids: dict[str, str] = {}

    for filename, content, mime_type, title, query_term in uploads:
        resp = client.post(
            "/v1/documents",
            headers=hr_headers,
            files={"file": (filename, content, mime_type)},
            data={
                "title": title,
                "allowed_roles": "hr",
                "sensitivity": "restricted",
            },
        )
        assert resp.status_code == 200, f"Upload failed for {filename}: {resp.text}"
        doc_id = resp.json()["id"]
        ingested_ids[filename] = doc_id

        # Wait for status=ready
        ready = False
        for _ in range(30):
            status_resp = client.get(f"/v1/documents/{doc_id}", headers=hr_headers)
            assert status_resp.status_code == 200
            if status_resp.json()["status"] == "ready":
                ready = True
                break
            time.sleep(0.5)
        assert ready, f"Document {filename} ({doc_id}) did not reach status=ready"

    # Confirm HR can retrieve each document and employee cannot
    for filename, _, _, _, query_term in uploads:
        doc_id = ingested_ids[filename]

        hr_query = client.post("/v1/query", headers=hr_headers, json={"question": query_term})
        assert hr_query.status_code == 200
        assert any(cit["doc_id"] == doc_id for cit in hr_query.json()["citations"]), f"HR could not retrieve {filename}"

        emp_query = client.post("/v1/query", headers=emp_headers, json={"question": query_term})
        assert emp_query.status_code == 200
        assert all(cit["doc_id"] != doc_id for cit in emp_query.json()["citations"]), f"Employee leaked {filename}"

    # Confirm a corrupt/unparseable file ends in status=failed and is never retrievable
    corrupt_resp = client.post(
        "/v1/documents",
        headers=hr_headers,
        files={"file": ("corrupt_payroll.pdf", b"%PDF-corrupted-bytes-cannot-parse\x00\xff", "application/pdf")},
        data={
            "title": "Corrupted Payroll Document",
            "allowed_roles": "hr",
            "sensitivity": "restricted",
        },
    )
    assert corrupt_resp.status_code == 200
    corrupt_id = corrupt_resp.json()["id"]

    failed = False
    for _ in range(30):
        status_resp = client.get(f"/v1/documents/{corrupt_id}", headers=hr_headers)
        assert status_resp.status_code == 200
        if status_resp.json()["status"] == "failed":
            failed = True
            break
        time.sleep(0.5)
    assert failed, f"Corrupt document {corrupt_id} did not reach status=failed"

    # Ensure failed document is never retrievable
    corrupt_query = client.post("/v1/query", headers=hr_headers, json={"question": "Corrupted Payroll Document"})
    assert corrupt_query.status_code == 200
    assert all(cit["doc_id"] != corrupt_id for cit in corrupt_query.json()["citations"])
