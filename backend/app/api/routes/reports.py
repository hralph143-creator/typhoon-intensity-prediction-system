from fastapi import APIRouter,HTTPException
from fastapi.responses import FileResponse,HTMLResponse
from pydantic import BaseModel,Field

from backend.app.services.report_service import REPORT_TYPES,create_report,delete_report,get_report,list_reports,report_file

router=APIRouter(prefix="/reports",tags=["科研分析报告"])
def ok(data,message="请求成功"):return {"success":True,"message":message,"data":data}


class ReportCreate(BaseModel):
    report_type:str=Field(pattern="^(typhoon|model|comprehensive)$")
    title:str|None=Field(default=None,max_length=200)
    typhoon_id:int|None=None
    experiment_id:str|None=Field(default=None,max_length=36)
    charts:list[str]=Field(default_factory=lambda:["all"])
    force:bool=False


@router.get("/types")
def types():return ok([{"code":key,"name":value} for key,value in REPORT_TYPES.items()])
@router.get("")
def reports():return ok(list_reports())
@router.post("",status_code=202)
def create(payload:ReportCreate):
    try:return ok(create_report(payload.model_dump()),"报告任务已创建")
    except LookupError as exc:raise HTTPException(404,str(exc))
    except ValueError as exc:raise HTTPException(409,str(exc))
@router.get("/{report_id}")
def detail(report_id:str):
    try:return ok(get_report(report_id))
    except LookupError as exc:raise HTTPException(404,str(exc))
@router.get("/{report_id}/preview",response_class=HTMLResponse)
def preview(report_id:str):
    try:return HTMLResponse(report_file(report_id,"html").read_text("utf-8"))
    except LookupError as exc:raise HTTPException(404,str(exc))
@router.get("/{report_id}/download/{kind}")
def download(report_id:str,kind:str):
    if kind not in {"html","pdf"}:raise HTTPException(422,"仅支持 HTML 或 PDF")
    try:
        path=report_file(report_id,kind);return FileResponse(path,media_type="text/html" if kind=="html" else "application/pdf",filename=f"research-report-{report_id}.{kind}")
    except LookupError as exc:raise HTTPException(404,str(exc))
@router.delete("/{report_id}")
def remove(report_id:str,confirmed:bool=False):
    try:delete_report(report_id,confirmed);return ok({"id":report_id},"报告已删除")
    except LookupError as exc:raise HTTPException(404,str(exc))
    except ValueError as exc:raise HTTPException(409,str(exc))
