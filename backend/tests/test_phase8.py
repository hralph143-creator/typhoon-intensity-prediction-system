from backend.app.services.phase8_service import data_quality_audit, event_cluster_bootstrap
from backend.app.services.fair_comparison import select_formal_safnet
from types import SimpleNamespace


def test_phase8_empty_audit_fails_truthfully():
    from backend.app.db.database import init_db
    init_db()
    result = data_quality_audit()
    assert result["passed"] is False
    assert result["formal_training_allowed"] is False
    assert result["samples"] == 0


def test_event_bootstrap_refuses_too_few_independent_storms():
    points = [{"sid":"A","actual":10.0,"safnet":11.0},{"sid":"B","actual":20.0,"safnet":18.0}]
    result = event_cluster_bootstrap(points, "safnet", iterations=500)
    assert result["reliable"] is False
    assert result["event_count"] == 2


def test_event_bootstrap_resamples_complete_events_deterministically():
    points=[]
    for event in range(6):
        for step in range(3):
            actual=float(10+event+step)
            points.append({"sid":f"S{event}","actual":actual,"safnet":actual+1,"lstm":actual+2})
    first=event_cluster_bootstrap(points,"safnet","lstm",iterations=500,seed=8)
    second=event_cluster_bootstrap(points,"safnet","lstm",iterations=500,seed=8)
    assert first == second
    assert first["reliable"] is True
    assert abs(first["estimate"] + 1.0) < 1e-9
    assert first["resampling_unit"] == "typhoon_event"


def test_formal_safnet_selection_uses_validation_and_rejects_exploratory_dataset():
    def artifact(identifier, version, validation_mae, test_mae):
        return SimpleNamespace(id=identifier,model_type="safnet",dataset_version=version,metrics={"validation":{"overall":{"mae":validation_mae}},"test":{"overall":{"mae":test_mae}}})
    exploratory=artifact("old","era5-phase8-small",.1,.1)
    validation_best=artifact("chosen","era5-phase8-final-a",1.0,4.0)
    test_best=artifact("not-chosen","era5-phase8-final-a",1.2,2.0)
    assert select_formal_safnet([exploratory,test_best,validation_best]).id=="chosen"
