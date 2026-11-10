import json
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from backend.app.services.phase10_dataset import HORIZONS,MultiHorizonDataset,MultiHorizonSample,MultiNormalization,audit_multi_horizon
from backend.app.services.phase10_model import VARIANTS,Phase10Config,Phase10Net,pinball_loss
from backend.app.services import phase10_service


@pytest.mark.parametrize("variant",VARIANTS)
def test_all_ablation_variants_have_ordered_multi_horizon_output(variant):
    model=Phase10Net(Phase10Config(variant=variant,dropout=0))
    output=model(torch.zeros(2,4,2,31,31),torch.zeros(2,4,1))
    assert output.shape==(2,4,3)
    assert torch.all(output[:,:,0]<=output[:,:,1])
    assert torch.all(output[:,:,1]<=output[:,:,2])


def test_phase10_input_dimensions_are_explicitly_checked():
    model=Phase10Net()
    with pytest.raises(ValueError,match="空间输入"):
        model(torch.zeros(1,4,2,30,31),torch.zeros(1,4,1))
    with pytest.raises(ValueError,match="时间输入"):
        model(torch.zeros(1,4,2,31,31),torch.zeros(1,4))


def test_masked_pinball_loss_and_invalid_batches():
    prediction=torch.zeros(1,4,3);target=torch.tensor([[1.,99.,-1.,2.]]);mask=torch.tensor([[True,False,True,False]])
    value=pinball_loss(prediction,target,mask)
    expected=np.mean([.1,.5,.9,.9,.5,.1])
    assert float(value)==pytest.approx(expected)
    with pytest.raises(ValueError,match="没有有效目标"):
        pinball_loss(prediction,target,torch.zeros_like(mask))
    with pytest.raises(ValueError,match="输出形状"):
        pinball_loss(torch.zeros(1,4,2),target,mask)


def test_missing_targets_are_masked_without_default_labels(tmp_path):
    path=tmp_path/"sample.npz";np.savez_compressed(path,wind=np.ones((4,2,31,31),np.float32),temporal=np.arange(4,dtype=np.float32))
    row=SimpleNamespace(local_path=str(path),sid="TEST",split="train")
    sample=MultiHorizonSample("x",row,(10.,None,12.,None))
    norm=MultiNormalization((0.,0.),(1.,1.),(0.,),(1.,),(10.,10.,10.,10.),(1.,1.,1.,1.))
    item=MultiHorizonDataset([sample],norm)[0]
    assert item["mask"].tolist()==[True,False,True,False]
    assert item["target"].tolist()==pytest.approx([0.,0.,2.,0.])


def test_empty_audit_is_stable_and_truthful():
    result=audit_multi_horizon([])
    assert result["total_samples"]==0
    assert result["no_sid_leakage"] is True
    assert result["wind"]["minimum"] is None
    assert result["future_inputs_used"] is False


def test_public_summary_hides_absolute_model_paths(tmp_path,monkeypatch):
    path=tmp_path/"summary.json"
    path.write_text(json.dumps({"runs":[{"model_path":"C:/private/model.pt","metadata_path":"C:/private/meta.json"}],"selected_ablations":[{"model_path":"C:/private/model.pt"}],"selected_candidate":{"model_path":"C:/private/model.pt"}}),encoding="utf-8")
    monkeypatch.setattr(phase10_service,"_summary_path",lambda:path)
    result=phase10_service.phase10_summary()
    assert "model_path" not in result["runs"][0]
    assert "metadata_path" not in result["runs"][0]
    assert "model_path" not in result["selected_candidate"]
    assert "model_path" not in result["selected_ablations"][0]


def test_configuration_validation():
    with pytest.raises(ValueError,match="未知消融"):
        Phase10Config(variant="unknown").validate()
    with pytest.raises(ValueError,match="注意力头数"):
        Phase10Config(time_embedding=15,attention_heads=4).validate()
