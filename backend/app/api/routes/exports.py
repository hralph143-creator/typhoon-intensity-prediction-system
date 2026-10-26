from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter,HTTPException,Query
from fastapi.responses import Response,StreamingResponse

from backend.app.services.export_service import comparison_png,comprehensive_workbook,csv_bytes

router=APIRouter(prefix="/exports",tags=["科研结果导出"])


@router.get("/workbook")
def workbook():return StreamingResponse(comprehensive_workbook(),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":"attachment; filename=research-results.xlsx"})
@router.get("/{kind}.csv")
def csv_export(kind:str,model_id:str|None=None,sid:str|None=None,min_abs_error:float|None=Query(None,ge=0),max_abs_error:float|None=Query(None,ge=0)):
    try:data=csv_bytes(kind,{"model_id":model_id,"sid":sid,"min_abs_error":min_abs_error,"max_abs_error":max_abs_error})
    except ValueError as exc:raise HTTPException(422,str(exc))
    return Response(data,media_type="text/csv; charset=utf-8",headers={"Content-Disposition":f"attachment; filename={kind}.csv"})
@router.get("/model-comparison.png")
def chart_png():
    temporary=NamedTemporaryFile(suffix=".png",delete=False);path=Path(temporary.name);temporary.close()
    comparison_png(path);data=path.read_bytes();path.unlink(missing_ok=True);return Response(data,media_type="image/png",headers={"Content-Disposition":"attachment; filename=model-comparison.png"})
