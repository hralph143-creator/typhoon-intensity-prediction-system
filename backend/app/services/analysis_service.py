"""正式模型公平比较和已保存预测记录查询。"""
from __future__ import annotations

from sqlalchemy import asc,desc,func,select

from backend.app.db.database import SessionLocal
from backend.app.models.ml import ModelArtifact,PredictionRecord,TrainingExperiment
from backend.app.models.typhoon import TyphoonEvent


def comparison_analysis()->dict:
    rows=[]
    with SessionLocal() as db:
        for experiment,model in db.execute(select(TrainingExperiment,ModelArtifact).join(ModelArtifact,ModelArtifact.experiment_id==TrainingExperiment.id).where(TrainingExperiment.status=="succeeded").order_by(TrainingExperiment.created_at)):
            test=(experiment.metrics or {}).get("test",{});overall=test.get("overall")
            if not overall:continue
            points=test.get("points") or [];signature=sorted(f"{x.get('sid')}|{x.get('forecast_time')}" for x in points)
            rows.append({"experiment_id":experiment.id,"model_id":model.id,"name":experiment.name,"model_type":experiment.model_type,"train_count":(experiment.split_statistics or {}).get("train",{}).get("sample_count"),"validation_count":(experiment.split_statistics or {}).get("validation",{}).get("sample_count"),"test_count":overall["sample_count"],"mae":overall["mae"],"rmse":overall["rmse"],"bias":overall["bias"],"dataset_version":experiment.dataset_version,"quality_profile":experiment.quality_profile,"forecast_horizon_hours":6,"wind_unit":"m/s","evaluated_at":experiment.finished_at.isoformat()+"Z" if experiment.finished_at else None,"sample_signature":signature})
    trained_types={x["model_type"] for x in rows}
    if "safnet" not in trained_types:rows.append({"experiment_id":None,"model_id":None,"name":"SAF-Net","model_type":"safnet","status":"未完成正式评估","train_count":0,"validation_count":0,"test_count":0,"mae":None,"rmse":None,"bias":None,"dataset_version":None,"quality_profile":"strict","forecast_horizon_hours":6,"wind_unit":"m/s","evaluated_at":None,"sample_signature":[]})
    formal=[x for x in rows if x.get("experiment_id")];groups={}
    for item in formal:
        key=(item["dataset_version"],item["quality_profile"],item["forecast_horizon_hours"],item["wind_unit"],tuple(item["sample_signature"]))
        groups.setdefault(key,[]).append(item["experiment_id"])
    comparable=len(groups)==1 and len(formal)>1
    for item in rows:item["comparable"]=bool(item.get("experiment_id") and len(next((ids for ids in groups.values() if item["experiment_id"] in ids),[]))>1);item.pop("sample_signature",None)
    return {"items":rows,"formal_ranking_allowed":comparable,"comparison_groups":list(groups.values()),"notice":"仅数据版本、质量规则、6小时预测时效、m/s单位及测试样本标识全部一致的实验可正式排序。"}


def predictions(model_id=None,sid=None,date_from=None,date_to=None,min_abs_error=None,max_abs_error=None,page=1,page_size=50,sort_by="forecast_time",sort_order="desc"):
    with SessionLocal() as db:
        stmt=select(PredictionRecord,ModelArtifact,TyphoonEvent).join(ModelArtifact,ModelArtifact.id==PredictionRecord.model_id).join(TyphoonEvent,TyphoonEvent.id==PredictionRecord.typhoon_id)
        if model_id:stmt=stmt.where(PredictionRecord.model_id==model_id)
        if sid:stmt=stmt.where(PredictionRecord.sid.icontains(sid,autoescape=True))
        if date_from:stmt=stmt.where(PredictionRecord.forecast_time>=date_from)
        if date_to:stmt=stmt.where(PredictionRecord.forecast_time<=date_to)
        absolute=func.abs(PredictionRecord.error)
        if min_abs_error is not None:stmt=stmt.where(absolute>=min_abs_error)
        if max_abs_error is not None:stmt=stmt.where(absolute<=max_abs_error)
        total=db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        fields={"forecast_time":PredictionRecord.forecast_time,"absolute_error":absolute,"predicted_wind":PredictionRecord.predicted_wind};order=fields.get(sort_by,PredictionRecord.forecast_time);stmt=stmt.order_by((desc if sort_order=="desc" else asc)(order),PredictionRecord.id).offset((page-1)*page_size).limit(page_size)
        items=[]
        for record,model,event in db.execute(stmt):items.append({"id":record.id,"model_id":model.id,"model_name":model.name,"model_type":model.model_type,"typhoon_id":event.id,"sid":record.sid,"name":event.name,"forecast_time":record.forecast_time.isoformat()+"Z","target_time":record.target_time.isoformat()+"Z","predicted_wind":record.predicted_wind,"actual_wind":record.actual_wind,"error":record.error,"absolute_error":abs(record.error) if record.error is not None else None,"input_features":record.input_features,"quality_profile":record.quality_profile})
        return {"items":items,"total":total,"page":page,"page_size":page_size}
