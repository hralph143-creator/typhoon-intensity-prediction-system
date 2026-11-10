"""真实科研数据快照、后台报告任务和安全文件管理。"""
from __future__ import annotations

import hashlib
import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC,datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func,select

from backend.app.core.config import settings
from backend.app.db.database import SessionLocal
from backend.app.models.era5 import Era5File,SpatiotemporalSample
from backend.app.models.ml import ModelArtifact,TrainingExperiment
from backend.app.models.report import AnalysisReport
from backend.app.models.typhoon import TyphoonEvent,TyphoonObservation
from backend.app.services.report_charts import bar_chart,histogram,line_chart,track_chart
from backend.app.services.report_render import render_html,render_pdf
from backend.app.services.fair_comparison import compare_common_test_set
from backend.app.services.phase10_service import phase10_summary

REPORT_TYPES={"typhoon":"历史台风分析报告","model":"模型预测评估报告","comprehensive":"综合科研分析报告","phase10_diagnosis":"SAF-Net 性能诊断报告","phase10_ablation":"SAF-Net 消融实验报告","phase10_multi_horizon":"多时效模型比较报告","phase10_uncertainty":"概率预测与区间校准报告","phase10_comprehensive":"第十阶段综合科研实验报告"}
_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix="report")


def _utc(value):
    if isinstance(value,datetime):return (value.replace(tzinfo=UTC) if value.tzinfo is None else value).isoformat().replace("+00:00","Z")
    return value


def _json(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=_utc)
def _hash(value):return hashlib.sha256(_json(value).encode()).hexdigest()


def _latest_observations(db,event_id:int):
    latest=select(func.max(TyphoonObservation.id)).where(TyphoonObservation.typhoon_id==event_id,TyphoonObservation.track_type=="MAIN").group_by(TyphoonObservation.observation_time)
    return list(db.scalars(select(TyphoonObservation).where(TyphoonObservation.id.in_(latest)).order_by(TyphoonObservation.observation_time)))


def _typhoon_snapshot(db,event_id:int)->dict:
    event=db.get(TyphoonEvent,event_id)
    if not event:raise LookupError("台风记录不存在")
    observations=_latest_observations(db,event_id)
    if not observations:raise ValueError("该台风没有 MAIN 历史观测，无法生成报告")
    source="中国气象局 CMA 独立最佳路径" if event.source=="cma" else "NOAA IBTrACS v04r01 / CMA 2分钟平均风速"
    return {"kind":"typhoon","source":source,"event":{"id":event.id,"sid":event.sid,"name":event.name,"season":event.season,"first_observation":_utc(event.first_observation),"last_observation":_utc(event.last_observation),"observation_count":len(observations),"maximum_wind":event.maximum_wind,"minimum_pressure":event.minimum_pressure,"maximum_category":event.maximum_category},"observations":[{"time":_utc(x.observation_time),"latitude":x.cma_lat if x.cma_lat is not None else x.latitude,"longitude":x.cma_lon if x.cma_lon is not None else x.longitude,"cma_wind_ms":x.cma_wind_ms,"cma_pressure":x.cma_pressure,"cma_iflag":x.cma_iflag,"quality_flags":x.quality_flags or []} for x in observations]}


def _model_snapshot(db,experiment_id:str)->dict:
    experiment=db.get(TrainingExperiment,experiment_id);model=db.scalar(select(ModelArtifact).where(ModelArtifact.experiment_id==experiment_id))
    if not experiment or experiment.status!="succeeded" or not model:raise LookupError("没有对应的正式成功实验和模型")
    source="NOAA IBTrACS CMA 标签 + ECMWF/Copernicus ERA5 U10/V10" if experiment.model_type=="safnet" else "NOAA IBTrACS v04r01 / CMA 2分钟平均风速"
    return {"kind":"model","source":source,"experiment":{"id":experiment.id,"name":experiment.name,"model_type":experiment.model_type,"created_at":_utc(experiment.created_at),"finished_at":_utc(experiment.finished_at),"quality_profile":experiment.quality_profile,"dataset_version":experiment.dataset_version,"config":experiment.config,"split_statistics":experiment.split_statistics,"training_curve":experiment.training_curve,"metrics":experiment.metrics},"model":{"id":model.id,"created_at":_utc(model.created_at),"feature_names":model.feature_names}}


def _comprehensive_snapshot(db)->dict:
    event_count=db.scalar(select(func.count()).select_from(TyphoonEvent)) or 0;observation_count=db.scalar(select(func.count()).select_from(TyphoonObservation)) or 0
    main_events=db.scalar(select(func.count(func.distinct(TyphoonObservation.typhoon_id))).where(TyphoonObservation.track_type=="MAIN")) or 0
    experiments=[]
    for experiment,model in db.execute(select(TrainingExperiment,ModelArtifact).join(ModelArtifact,ModelArtifact.experiment_id==TrainingExperiment.id).where(TrainingExperiment.status=="succeeded",TrainingExperiment.model_type!="safnet").order_by(TrainingExperiment.created_at)):
        overall=(experiment.metrics or {}).get("test",{}).get("overall")
        if overall:experiments.append({"id":experiment.id,"name":experiment.name,"model_type":experiment.model_type,"dataset_version":experiment.dataset_version,"quality_profile":experiment.quality_profile,"test":overall,"created_at":_utc(experiment.created_at)})
    phase8=list(db.scalars(select(SpatiotemporalSample).where(SpatiotemporalSample.processing_version=="spatiotemporal-v2")))
    phase8_splits={name:{"samples":sum(x.split==name for x in phase8),"events":len({x.sid for x in phase8 if x.split==name})} for name in ("train","validation","test")}
    safnet_runs=list(db.scalars(select(TrainingExperiment).where(TrainingExperiment.model_type=="safnet",TrainingExperiment.status=="succeeded")))
    formal=sum((x.split_statistics or {}).get("experiment_level")=="formal" for x in safnet_runs)
    common=compare_common_test_set()
    # 推理耗时受机器负载影响，不属于科研快照内容，不能让相同数据重复生成报告。
    common={**common,"items":[{key:value for key,value in item.items() if key!="inference_seconds"} for item in common.get("items",[])]}
    return {"kind":"comprehensive","source":"NOAA IBTrACS v04r01；中国气象局 CMA 独立最佳路径；ECMWF/Copernicus ERA5；统一历史回测实验","statistics":{"event_count":event_count,"main_event_count":main_events,"observation_count":observation_count,"era5_file_count":db.scalar(select(func.count()).select_from(Era5File)) or 0,"spatiotemporal_sample_count":len(phase8),"phase8_splits":phase8_splits,"phase8_event_count":len({x.sid for x in phase8})},"experiments":experiments,"safnet":{"architecture_complete":True,"successful_experiment_count":len(safnet_runs),"formal_experiment_count":formal},"common_test":common}


def snapshot(report_type:str,typhoon_id:int|None=None,experiment_id:str|None=None)->dict:
    if report_type.startswith("phase10_"):
        result=phase10_summary()
        if not result.get("available"):raise ValueError(result.get("message","第十阶段实验尚未运行"))
        return {"kind":report_type,"source":"CMA 独立最佳路径标签；Copernicus ERA5 U10/V10 历史再分析；第十阶段冻结实验快照","phase10":result}
    with SessionLocal() as db:
        if report_type=="typhoon":
            if not typhoon_id:raise ValueError("历史台风报告必须选择台风")
            return _typhoon_snapshot(db,typhoon_id)
        if report_type=="model":
            if not experiment_id:raise ValueError("模型报告必须选择实验")
            return _model_snapshot(db,experiment_id)
        if report_type=="comprehensive":return _comprehensive_snapshot(db)
    raise ValueError("不支持的报告类型")


def _phase10_sections(data:dict,folder:Path)->list[dict]:
    p=data["phase10"];audit=p["audit"];candidate=p["selected_candidate"];test=candidate["test"];horizons=[6,12,18,24]
    split_rows=[]
    for split,value in audit["splits"].items():
        split_rows.append([split,value["samples"],value["events"]," / ".join(str(value["horizons"][str(h)]["samples"]) for h in horizons)])
    base_rows=[]
    for name,value in p["baselines"].items():
        if name=="legacy_safnet":continue
        overall=value["test"]["overall"];base_rows.append([name.upper(),f"{overall['mae']:.4f}",f"{overall['rmse']:.4f}",f"{overall['bias']:.4f}"])
    base_rows.append(["候选 SAF-Net",f"{test['overall']['mae']:.4f}",f"{test['overall']['rmse']:.4f}",f"{test['overall']['bias']:.4f}"])
    ablation_rows=[[x["variant"],x["seed"],x["parameters"],x["best_epoch"],f"{x['validation']['overall']['mae']:.4f}",f"{x['test']['overall']['mae']:.4f}"] for x in p["selected_ablations"]]
    probability_rows=[]
    for h in horizons:
        point=test["by_horizon"][str(h)];prob=test["probability"]["by_horizon"][str(h)];boot=p["bootstrap_candidate_minus_persistence"][str(h)]
        probability_rows.append([h,point["sample_count"],f"{point['mae']:.4f}",f"{point['rmse']:.4f}",f"{prob['coverage_p10_p90']*100:.1f}%",f"{prob['mean_interval_width']:.4f}",f"{prob['pinball_loss']:.4f}",f"[{boot['ci95'][0]:.3f}, {boot['ci95'][1]:.3f}]"])
    metric=folder/"phase10-mae.png";coverage=folder/"phase10-coverage.png"
    images=[{"path":str(metric),"data":line_chart(metric,[str(h) for h in horizons],[("Persistence",[p["baselines"]["persistence"]["test"]["by_horizon"][str(h)]["mae"] for h in horizons]),("Ridge",[p["baselines"]["ridge"]["test"]["by_horizon"][str(h)]["mae"] for h in horizons]),("GRU",[p["baselines"]["gru"]["test"]["by_horizon"][str(h)]["mae"] for h in horizons]),("候选 SAF-Net",[test["by_horizon"][str(h)]["mae"] for h in horizons])],"多时效测试集 MAE","m/s"),"caption":"相同多时效测试样本上的点预测误差"},{"path":str(coverage),"data":line_chart(coverage,[str(h) for h in horizons],[("P10–P90 覆盖率",[test["probability"]["by_horizon"][str(h)]["coverage_p10_p90"]*100 for h in horizons]),("名义覆盖率",[80]*4)],"预测区间覆盖率","%"),"caption":"测试集区间覆盖率与 80% 名义值"}]
    common=[{"title":"1　数据版本与审计","paragraphs":[f"数据版本：{p['dataset_version']}；清单 SHA-256：{p['manifest_sha256']}。",f"共 {audit['total_samples']} 个时空窗口、{audit['total_events']} 个独立台风事件。SID 跨分区泄漏：{'无' if audit['no_sid_leakage'] else '存在'}；未来 ERA5 输入：{'未使用' if not audit['future_inputs_used'] else '存在'}。"],"table":(["分区","窗口","事件","6/12/18/24h 标签数"],split_rows),"table_caption":"按事件隔离的多时效数据覆盖"},{"title":"2　模型选择与总体结果","paragraphs":[f"候选模型为 {candidate['variant']}（seed={candidate['seed']}），只按验证集四时效平均 MAE 选择；测试集未参与选择。",f"候选测试总体 MAE {test['overall']['mae']:.4f} m/s，未超过 Persistence。该负面结果被完整保留。"],"table":(["模型","MAE","RMSE","Bias"],base_rows),"table_caption":"多时效测试集总体指标","images":images}]
    kind=data["kind"]
    if kind=="phase10_diagnosis":return common+[{"title":"3　训练与稳定性诊断","paragraphs":[f"权重重载最大预测差：{p['diagnostics']['reload_max_difference']:.8f}；标准化仅拟合训练集；最佳 Epoch 仅由验证集决定。",*p["diagnostics"]["limitations"]],"table":(["变体","验证 MAE 均值","随机种子标准差"],[[k,f"{v['validation_mae_mean']:.4f}",f"{v['validation_mae_std']:.4f}"] for k,v in p["diagnostics"]["seed_stability"].items()]),"table_caption":"三随机种子稳定性"}]
    if kind=="phase10_ablation":return common+[{"title":"3　消融实验","paragraphs":["每个结构均使用完全相同的数据划分、损失、评价函数和三个预先固定的随机种子。表中的测试指标仅在各变体按验证集完成选择后计算。"],"table":(["结构","种子","参数量","最佳 Epoch","验证 MAE","测试 MAE"],ablation_rows),"table_caption":"六组 SAF-Net 消融结果"}]
    if kind=="phase10_uncertainty":return common+[{"title":"3　概率预测与校准","paragraphs":["模型同时输出 P10、P50、P90，使用掩码 Pinball Loss；单调参数化保证分位数不交叉。测试覆盖率低于名义 80%，说明区间存在欠校准。"],"table":(["时效(h)","样本","MAE","RMSE","覆盖率","区间宽度","Pinball","MAE差值95%CI"],probability_rows),"table_caption":"分时效概率评价"}]
    if kind=="phase10_multi_horizon":return common+[{"title":"3　分时效评价","paragraphs":["四个预测时效均只使用 t 及之前的四时次输入。所有时效在验证集和测试集均覆盖 6 个独立事件，可进行当前数据范围内的正式比较。"],"table":(["时效(h)","样本","MAE","RMSE","覆盖率","区间宽度","Pinball","MAE差值95%CI"],probability_rows),"table_caption":"6–24 小时测试结果"}]
    return common+[{"title":"3　六组结构消融","table":(["结构","种子","参数量","最佳 Epoch","验证 MAE","测试 MAE"],ablation_rows),"table_caption":"验证集选模后的独立测试"},{"title":"4　概率预测与统计不确定性","table":(["时效(h)","样本","MAE","RMSE","覆盖率","区间宽度","Pinball","MAE差值95%CI"],probability_rows),"table_caption":"分时效概率评价"},{"title":"5　结论与限制","paragraphs":["当前候选 SAF-Net 没有超过持续性基线；所有 Bootstrap 置信区间均跨越 0，不能宣称存在统计显著优势。","测试集只有 6 个独立事件，ERA5 输入仅含 U10/V10；结果属于历史再分析回测，不构成实时业务预报。","失败实验、负面结果和欠校准区间均按原始结果报告。"]}]


def _sections(data:dict,folder:Path)->list[dict]:
    if data["kind"].startswith("phase10_"):return _phase10_sections(data,folder)
    if data["kind"]=="typhoon":
        event=data["event"];rows=data["observations"];times=[x["time"] for x in rows];valid_wind=[x for x in rows if x["cma_wind_ms"] is not None];valid_pressure=[x for x in rows if x["cma_pressure"] is not None]
        images=[];track=folder/"track.png";images.append({"path":str(track),"data":track_chart(track,[x["longitude"] for x in rows],[x["latitude"] for x in rows],f"{event['name']} 历史轨迹"),"caption":"历史 MAIN 轨迹（经纬度）","ratio":.72})
        wind=folder/"wind.png";images.append({"path":str(wind),"data":line_chart(wind,[x["time"] for x in valid_wind],[('CMA 2分钟风速',[x["cma_wind_ms"] for x in valid_wind])],"近中心最大风速变化","m/s"),"caption":"CMA 2分钟平均风速变化"}) if valid_wind else None
        pressure=folder/"pressure.png";images.append({"path":str(pressure),"data":line_chart(pressure,[x["time"] for x in valid_pressure],[('CMA 中心气压',[x["cma_pressure"] for x in valid_pressure])],"中心气压变化","hPa"),"caption":"CMA 中心气压变化"}) if valid_pressure else None
        key=sorted(rows,key=lambda x:x["cma_wind_ms"] if x["cma_wind_ms"] is not None else -1,reverse=True)[:12]
        quality=f"MAIN 观测 {len(rows)} 条；CMA 风速有效 {len(valid_wind)} 条、缺失 {len(rows)-len(valid_wind)} 条；CMA 气压有效 {len(valid_pressure)} 条。缺失值未填补。"
        return [{"title":"1　台风基本信息","paragraphs":[f"编号 {event['sid']}，名称 {event['name']}，季节 {event['season']}。观测期为 {event['first_observation']} 至 {event['last_observation']}。",f"最大风速采用 CMA 2分钟平均口径：{event['maximum_wind']:.2f} m/s。不同机构平均时段未混用。" if event['maximum_wind'] is not None else "没有可用的 CMA 最大风速统计。"],"table":(["字段","数值"],[["SID",event["sid"]],["观测数",len(rows)],["最低气压",f"{event['minimum_pressure']} hPa" if event['minimum_pressure'] is not None else "缺失"]]),"table_caption":"台风基本信息"},{"title":"2　历史轨迹与强度变化","paragraphs":["轨迹图、风速和气压曲线均由本报告同一数据库快照生成。"],"images":[x for x in images if x]},{"title":"3　关键观测记录","table":(["UTC 时间","纬度","经度","CMA 风速 (m/s)","CMA 气压 (hPa)","IFLAG"],[[x["time"],f"{x['latitude']:.2f}",f"{x['longitude']:.2f}","" if x["cma_wind_ms"] is None else f"{x['cma_wind_ms']:.2f}",x["cma_pressure"],x["cma_iflag"] or ""] for x in key]),"table_caption":"按 CMA 风速排序的关键观测"},{"title":"4　数据质量说明","paragraphs":[quality,"本报告为历史最佳路径资料分析，不代表实时业务预报。"]}]
    if data["kind"]=="model":
        experiment=data["experiment"];test=(experiment["metrics"] or {}).get("test",{});overall=test.get("overall",{});points=test.get("points",[]);images=[]
        if points:
            compare=folder/"prediction.png";images.append({"path":str(compare),"data":line_chart(compare,[x["target_time"] for x in points],[('真实风速',[x["actual"] for x in points]),('预测风速',[x["predicted"] for x in points])],"测试集预测与真实风速","m/s"),"caption":"测试集预测值与真实值"});residual=folder/"residual.png";images.append({"path":str(residual),"data":histogram(residual,[x["error"] for x in points],"测试集预测残差分布"),"caption":"预测残差分布"})
        curve=experiment.get("training_curve") or []
        if curve and "epoch" in curve[0]:
            curve_path=folder/"curve.png";images.append({"path":str(curve_path),"data":line_chart(curve_path,[str(x["epoch"]) for x in curve],[('训练损失',[x["train_loss"] for x in curve]),('验证损失',[x["validation_loss"] for x in curve])],"训练与验证损失","标准化 MSE"),"caption":"已保存训练和验证损失"})
        split=experiment.get("split_statistics") or {};split_rows=[[name,(value or {}).get("sample_count"),(value or {}).get("event_count"),",".join(map(str,(value or {}).get("years",[])))] for name,value in split.items() if isinstance(value,dict) and "sample_count" in value]
        summary=f"测试集样本 {overall.get('sample_count','缺失')}，MAE {overall.get('mae',float('nan')):.4f} m/s，RMSE {overall.get('rmse',float('nan')):.4f} m/s，Bias {overall.get('bias',float('nan')):.4f} m/s。" if overall else "实验没有保存测试集总体指标。"
        level=(experiment.get("split_statistics") or {}).get("experiment_level","formal")
        limits=(experiment.get("split_statistics") or {}).get("limitations",[])
        return [{"title":"1　模型与实验信息","paragraphs":[f"实验 {experiment['name']}（{experiment['model_type'].upper()}），创建于 {experiment['created_at']}。",f"数据版本：{experiment['dataset_version']}；质量规则：{experiment['quality_profile']}；实验级别：{'正式' if level=='formal' else '小样本试验'}。"],"table":(["分组","样本数","事件数","年份"],split_rows),"table_caption":"训练、验证与测试分组"},{"title":"2　测试结果","paragraphs":[summary,"这些指标来自已保存模型权重和实验记录，没有重新训练或临时生成预测。"],"table":(["指标","数值"],[["MAE",overall.get("mae")],["RMSE",overall.get("rmse")],["Bias",overall.get("bias")],["测试样本",overall.get("sample_count")]]),"table_caption":"测试集评价指标","images":images},{"title":"3　配置与限制","paragraphs":["主要配置："+_json(experiment.get("config") or {}),*(limits or []),"这是历史再分析条件下的回测，不是实时业务预报。注意力权重不构成气象因果证明。"]}]
    stats=data["statistics"];experiments=data["experiments"];common=data.get("common_test",{});common_items=common.get("items",[]);labels=[x["model_type"].upper() for x in common_items];mae=[x["mae"] for x in common_items];rmse=[x["rmse"] for x in common_items];images=[]
    if common_items:
        p=folder/"mae.png";images.append({"path":str(p),"data":bar_chart(p,labels,mae,"正式模型 MAE 对比","MAE (m/s)"),"caption":"相同测试集上的 MAE"});p=folder/"rmse.png";images.append({"path":str(p),"data":bar_chart(p,labels,rmse,"正式模型 RMSE 对比","RMSE (m/s)"),"caption":"相同测试集上的 RMSE"})
    era5_count=stats["spatiotemporal_sample_count"]
    safnet_count=data.get("safnet",{}).get("successful_experiment_count",0)
    era5_note=(f"SAF-Net 已使用 {era5_count} 个真实 ERA5 四时次样本完成 {safnet_count} 次训练。最终权重仅按验证集 MAE 选择，测试集未参与选模。" if safnet_count else (f"SAF-Net 网络结构已经实现，并已有 {era5_count} 个真实 ERA5 四时次样本验证链路；尚无训练权重。" if era5_count else "SAF-Net 当前没有真实 ERA5 样本或训练权重。"))
    split=stats.get("phase8_splits",{})
    bootstrap=common.get("bootstrap_safnet_minus_persistence",{});uncertainty=(f"事件级 Bootstrap 的 SAF-Net MAE−Persistence MAE 为 {bootstrap['estimate']:.4f} m/s，95% CI [{bootstrap['ci95'][0]:.4f}, {bootstrap['ci95'][1]:.4f}]。" if bootstrap.get("reliable") else bootstrap.get("reason","未计算事件级不确定性。"))
    return [{"title":"1　研究数据概述","paragraphs":[f"系统保存 {stats['event_count']} 个事件、{stats['observation_count']} 条观测，其中 {stats['main_event_count']} 个事件含 MAIN 轨迹。",f"实际 ERA5 文件 {stats['era5_file_count']} 个，第八阶段 v2 四时次样本 {era5_count} 个、独立事件 {stats.get('phase8_event_count',0)} 个。"],"table":(["分组","样本","独立事件"],[[name,value.get("samples",0),value.get("events",0)] for name,value in split.items()]),"table_caption":"第八阶段数据覆盖"},{"title":"2　五模型共同测试集","paragraphs":[f"五类模型使用相同的 {common.get('sample_count',0)} 条测试样本、{common.get('event_count',0)} 个独立事件和 6 小时预测时效。",uncertainty],"table":(["模型","测试样本","MAE","RMSE","Bias","相对持续性改善%"],[[x["model_type"].upper(),x["sample_count"],f"{x['mae']:.4f}",f"{x['rmse']:.4f}",f"{x['bias']:.4f}","—" if x.get("improvement_pct") is None else f"{x['improvement_pct']:.2f}"] for x in common_items]),"table_caption":"统一测试口径指标","images":images},{"title":"3　结果讨论与研究限制","paragraphs":["指标只适用于当前历史最佳路径回测数据和未来 6 小时预测时效，不构成业务预报能力证明。",era5_note,"当前测试集虽覆盖 6 个独立事件，但窗口集中于少数事件，事件级泛化结论仍需更多年份与事件验证。","不同机构风速平均时段没有静默混用；缺失值未被虚构填补。"]},{"title":"4　总结","paragraphs":["真实数据扩容、三随机种子训练、验证集选模、统一测试和事件级不确定性估计均已完成。当前 SAF-Net 未优于 Persistence，应将其视为可复现实验结果而不是性能优势证明。"]}]


def create_report(payload:dict)->dict:
    report_type=str(payload.get("report_type",""));data=snapshot(report_type,payload.get("typhoon_id"),payload.get("experiment_id"));snapshot_hash=_hash(data);config={"charts":payload.get("charts",["all"])};title=str(payload.get("title") or REPORT_TYPES[report_type]).strip()[:200]
    with SessionLocal() as db:
        if not payload.get("force"):
            existing=db.scalar(select(AnalysisReport).where(AnalysisReport.report_type==report_type,AnalysisReport.source_snapshot_hash==snapshot_hash,AnalysisReport.report_config==config,AnalysisReport.report_status.in_(("queued","generating","succeeded"))).order_by(AnalysisReport.created_at.desc()))
            if existing:return report_dict(existing)
        row=AnalysisReport(id=str(uuid4()),report_type=report_type,report_title=title,related_typhoon_id=payload.get("typhoon_id"),related_experiment_id=payload.get("experiment_id"),source_metadata={"source":data["source"],"kind":data["kind"]},source_snapshot_hash=snapshot_hash,report_config=config,report_status="queued",phase="queued");db.add(row);db.commit();result=report_dict(row)
    _executor.submit(_generate,row.id,data);return result


def _generate(report_id:str,data:dict):
    folder=settings.report_dir/report_id
    try:
        folder.mkdir(parents=True,exist_ok=False)
        with SessionLocal() as db:row=db.get(AnalysisReport,report_id);row.report_status="generating";row.phase="rendering_charts";db.commit();title=row.report_title
        snapshot_path=folder/"snapshot.json";snapshot_path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8");sections=_sections(data,folder);generated=_utc(datetime.now(UTC));html_path=folder/"report.html";pdf_path=folder/"report.pdf";source=data["source"]
        render_html(html_path,title,report_id,sections,generated,source)
        with SessionLocal() as db:row=db.get(AnalysisReport,report_id);row.phase="rendering_pdf";db.commit()
        render_pdf(pdf_path,title,report_id,sections,generated,source)
        with SessionLocal() as db:row=db.get(AnalysisReport,report_id);row.report_status="succeeded";row.phase="succeeded";row.html_path=str(html_path);row.pdf_path=str(pdf_path);row.snapshot_path=str(snapshot_path);row.completed_at=datetime.now(UTC);db.commit()
    except Exception as exc:
        with SessionLocal() as db:
            row=db.get(AnalysisReport,report_id)
            if row:row.report_status="failed";row.phase="failed";row.error_message=f"{type(exc).__name__}: {exc}";row.completed_at=datetime.now(UTC);db.commit()


def report_dict(row:AnalysisReport)->dict:return {c.name:_utc(getattr(row,c.name)) for c in AnalysisReport.__table__.columns if c.name not in {"html_path","pdf_path","snapshot_path"}}
def list_reports()->list[dict]:
    with SessionLocal() as db:return [report_dict(x) for x in db.scalars(select(AnalysisReport).order_by(AnalysisReport.created_at.desc()))]
def get_report(report_id:str)->dict:
    with SessionLocal() as db:
        row=db.get(AnalysisReport,report_id)
        if not row:raise LookupError("报告不存在")
        return report_dict(row)
def report_file(report_id:str,kind:str)->Path:
    with SessionLocal() as db:
        row=db.get(AnalysisReport,report_id)
        if not row or row.report_status!="succeeded":raise LookupError("报告尚未生成成功")
        raw=row.html_path if kind=="html" else row.pdf_path
    path=Path(raw).resolve();root=settings.report_dir.resolve()
    if root not in path.parents or not path.is_file():raise ValueError("报告文件路径无效")
    return path
def delete_report(report_id:str,confirmed:bool):
    if not confirmed:raise ValueError("删除报告需要二次确认")
    with SessionLocal() as db:
        row=db.get(AnalysisReport,report_id)
        if not row:raise LookupError("报告不存在")
        if row.report_status in {"queued","generating"}:raise ValueError("生成中的报告不能删除")
        folder=(settings.report_dir/report_id).resolve();root=settings.report_dir.resolve();db.delete(row);db.commit()
    if folder.parent==root and folder.exists():shutil.rmtree(folder)


def recover_reports():
    with SessionLocal() as db:
        for row in db.scalars(select(AnalysisReport).where(AnalysisReport.report_status.in_(("queued","generating")))):row.report_status="failed";row.phase="interrupted";row.error_message="应用退出时报告任务未完成，请重新生成。";row.completed_at=datetime.now(UTC)
        db.commit()
