import time
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pypdf import PdfReader

from backend.app.core.config import settings
from backend.app.db.database import init_db
from backend.app.main import app
from backend.app.services.export_service import comprehensive_workbook,safe_cell
from backend.app.services.report_render import render_html,render_pdf
from backend.app.services import system_management


def test_report_types_and_empty_comprehensive_api():
    with TestClient(app) as client:
        types=client.get("/api/reports/types").json()["data"]
        assert {x["code"] for x in types}=={"typhoon","model","comprehensive","phase10_diagnosis","phase10_ablation","phase10_multi_horizon","phase10_uncertainty","phase10_comprehensive"}
        assert client.post("/api/reports",json={"report_type":"typhoon"}).status_code==409


def test_standalone_html_escapes_and_pdf_opens(tmp_path):
    sections=[{"title":"真实结果","paragraphs":["<script>alert(1)</script> 中文"],"table":(["字段","值"],[["MAE","1.60 m/s"]])}]
    html=tmp_path/"report.html";pdf=tmp_path/"report.pdf"
    render_html(html,"科研报告","TEST-1",sections,"2026-10-26T00:00:00Z","真实测试快照")
    render_pdf(pdf,"科研报告","TEST-1",sections,"2026-10-26T00:00:00Z","真实测试快照")
    assert "<script>" not in html.read_text("utf-8")
    assert len(PdfReader(pdf).pages)>=1


def test_excel_sheets_and_formula_injection_protection():
    init_db();book=load_workbook(comprehensive_workbook())
    assert {"历史台风","历史观测","模型实验","评价指标","预测结果","综合统计"}<=set(book.sheetnames)
    assert safe_cell("=HYPERLINK('x')").startswith("'")


def test_system_status_logs_and_confirmations():
    with TestClient(app) as client:
        assert client.get("/api/system/status").json()["data"]["database"]=="connected"
        assert client.get("/api/system/logs",params={"limit":5}).status_code==200
        assert client.get("/api/system/backups/not-found/download").status_code==404
        assert client.post("/api/system/maintenance/cleanup").status_code==409


def test_log_reader_redacts_secrets(tmp_path,monkeypatch):
    log_dir=tmp_path/"logs";log_dir.mkdir();(log_dir/"backend.log").write_text("2026-01-01 00:00:00 | INFO | demo | token=private-value\n",encoding="utf-8")
    monkeypatch.setattr(system_management,"PROJECT_ROOT",tmp_path)
    assert system_management.read_logs()[0]["message"]=="token=***"
    assert b"private-value" not in system_management.exported_log()
