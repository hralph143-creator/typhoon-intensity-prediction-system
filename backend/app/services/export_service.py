"""统一科研数据 CSV、Excel 和静态比较图导出。"""
from __future__ import annotations

import csv
import io
from datetime import UTC

from openpyxl import Workbook
from openpyxl.styles import Font,PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select

from backend.app.db.database import SessionLocal
from backend.app.models.ml import ModelArtifact,PredictionRecord,TrainingExperiment
from backend.app.models.era5 import SpatiotemporalSample
from backend.app.models.typhoon import TyphoonEvent,TyphoonObservation
from backend.app.services.analysis_service import comparison_analysis,predictions
from backend.app.services.report_charts import bar_chart
from backend.app.services.fair_comparison import compare_common_test_set


def safe_cell(value):
    if isinstance(value,str) and value.startswith(("=","+","-","@")):return "'"+value
    return value


def _sheet(book,title,headers,rows):
    sheet=book.create_sheet(title);sheet.append(headers)
    for cell in sheet[1]:cell.font=Font(bold=True,color="FFFFFF");cell.fill=PatternFill("solid",fgColor="3C6782")
    for row in rows:sheet.append([safe_cell(x) for x in row])
    sheet.freeze_panes="A2";sheet.auto_filter.ref=sheet.dimensions
    for column in range(1,len(headers)+1):
        values=[str(sheet.cell(row=i,column=column).value or "") for i in range(1,min(sheet.max_row,300)+1)];sheet.column_dimensions[get_column_letter(column)].width=min(42,max(10,max(map(len,values))+2))
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value,float):cell.number_format="0.00"
    return sheet


def comprehensive_workbook()->io.BytesIO:
    book=Workbook();book.remove(book.active)
    with SessionLocal() as db:
        events=list(db.scalars(select(TyphoonEvent).order_by(TyphoonEvent.season,TyphoonEvent.sid)));_sheet(book,"历史台风",["SID","名称","季节","首次观测 UTC","末次观测 UTC","观测数","CMA最大风速(m/s)","最低气压(hPa)"],[[x.sid,x.name,x.season,x.first_observation,x.last_observation,x.observation_count,x.maximum_wind,x.minimum_pressure] for x in events])
        observations=db.execute(select(TyphoonObservation,TyphoonEvent.sid).join(TyphoonEvent).order_by(TyphoonObservation.id));_sheet(book,"历史观测",["SID","观测时间 UTC","纬度","经度","轨迹类型","CMA风速(m/s)","CMA气压(hPa)","CMA IFLAG"],[[sid,x.observation_time,x.latitude,x.longitude,x.track_type,x.cma_wind_ms,x.cma_pressure,x.cma_iflag] for x,sid in observations])
        experiments=list(db.scalars(select(TrainingExperiment).order_by(TrainingExperiment.created_at)));_sheet(book,"模型实验",["实验ID","名称","模型","状态","数据版本","创建时间 UTC","完成时间 UTC"],[[x.id,x.name,x.model_type,x.status,x.dataset_version,x.created_at,x.finished_at] for x in experiments])
        era5=list(db.scalars(select(SpatiotemporalSample).where(SpatiotemporalSample.processing_version=="spatiotemporal-v2").order_by(SpatiotemporalSample.split,SpatiotemporalSample.forecast_time)));_sheet(book,"ERA5时空样本",["样本ID","SID","分组","起报时间 UTC","目标时间 UTC","目标风速(m/s)","形状","处理版本"],[[x.id,x.sid,x.split,x.forecast_time,x.target_time,x.target_wind,str(x.shape),x.processing_version] for x in era5])
        metrics=[]
        for x in experiments:
            for split,detail in (x.metrics or {}).items():
                overall=detail.get("overall") if isinstance(detail,dict) else None
                if overall:metrics.append([x.id,x.model_type,split,overall.get("sample_count"),overall.get("mae"),overall.get("rmse"),overall.get("bias")])
        _sheet(book,"评价指标",["实验ID","模型","分组","样本数","MAE(m/s)","RMSE(m/s)","Bias(m/s)"],metrics)
        records=db.execute(select(PredictionRecord,ModelArtifact.name).join(ModelArtifact));_sheet(book,"预测结果",["记录ID","模型","SID","起报时间 UTC","目标时间 UTC","预测风速(m/s)","真实风速(m/s)","误差(m/s)"],[[x.id,name,x.sid,x.forecast_time,x.target_time,x.predicted_wind,x.actual_wind,x.error] for x,name in records])
        _sheet(book,"综合统计",["项目","数值"],[["历史台风事件",len(events)],["历史观测",db.query(TyphoonObservation).count()],["正式成功实验",sum(x.status=="succeeded" for x in experiments)],["SAF-Net正式实验",sum(x.status=="succeeded" and x.model_type=="safnet" for x in experiments)]])
    common=compare_common_test_set();_sheet(book,"五模型共同测试",["模型","模型ID","样本数","MAE(m/s)","RMSE(m/s)","Bias(m/s)","相对持续性改善%"],[[x["model_type"],x["model_id"],x["sample_count"],x["mae"],x["rmse"],x["bias"],x["improvement_pct"]] for x in common["items"]])
    output=io.BytesIO();book.save(output);output.seek(0);return output


def csv_bytes(kind:str,filters:dict)->bytes:
    output=io.StringIO();output.write("\ufeff");writer=csv.writer(output)
    if kind=="typhoons":
        writer.writerow(["SID","名称","季节","首次观测UTC","末次观测UTC","CMA最大风速(m/s)","最低气压(hPa)"])
        with SessionLocal() as db:
            for x in db.scalars(select(TyphoonEvent).order_by(TyphoonEvent.season,TyphoonEvent.sid)):writer.writerow([safe_cell(x.sid),safe_cell(x.name),x.season,x.first_observation,x.last_observation,x.maximum_wind,x.minimum_pressure])
    elif kind=="predictions":
        result=predictions(**filters,page=1,page_size=10000);writer.writerow(["模型","SID","台风名称","起报时间UTC","目标时间UTC","预测风速(m/s)","真实风速(m/s)","误差(m/s)"])
        for x in result["items"]:writer.writerow([safe_cell(x["model_name"]),safe_cell(x["sid"]),safe_cell(x["name"]),x["forecast_time"],x["target_time"],x["predicted_wind"],x["actual_wind"],x["error"]])
    else:raise ValueError("不支持的 CSV 类型")
    return output.getvalue().encode("utf-8")


def comparison_png(path):
    rows=[x for x in comparison_analysis()["items"] if x.get("mae") is not None];bar_chart(path,[x["model_type"].upper() for x in rows],[x["mae"] for x in rows],"正式模型 MAE 对比","MAE (m/s)");return path
