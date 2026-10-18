"""Training-resume checkpoints for the baseline categorical PPO policies."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import torch


CHECKPOINT_SCHEMA = "n02-baseline-learning-checkpoint/1"


def _hash_value(digest: Any, value: Any) -> None:
    if isinstance(value, torch.Tensor):
        tensor = value.detach().cpu().contiguous()
        digest.update(b"tensor\0")
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(repr(tuple(tensor.shape)).encode("ascii"))
        digest.update(tensor.numpy().tobytes())
    elif isinstance(value, np.ndarray):
        array = np.ascontiguousarray(value)
        digest.update(b"ndarray\0")
        digest.update(array.dtype.str.encode("ascii"))
        digest.update(repr(array.shape).encode("ascii"))
        digest.update(array.tobytes())
    elif isinstance(value, dict):
        digest.update(b"dict\0")
        for key in sorted(value, key=lambda item: (type(item).__name__, repr(item))):
            _hash_value(digest, key)
            _hash_value(digest, value[key])
    elif isinstance(value, (list, tuple)):
        digest.update(b"tuple\0" if isinstance(value, tuple) else b"list\0")
        digest.update(str(len(value)).encode("ascii"))
        for item in value:
            _hash_value(digest, item)
    elif isinstance(value, bytes):
        digest.update(b"bytes\0")
        digest.update(value)
    elif value is None or isinstance(value, (str, int, float, bool)):
        digest.update(type(value).__name__.encode("ascii"))
        digest.update(b"\0")
        digest.update(json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode("utf-8"))
    else:
        raise TypeError(f"BASELINE_CHECKPOINT_UNHASHABLE:{type(value).__name__}")


def stable_digest(value: Any) -> str:
    digest = hashlib.sha256()
    _hash_value(digest, value)
    return digest.hexdigest()


def state_digest(state: dict[str, Any]) -> str:
    return stable_digest(state)


def _identities(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ValueError("BASELINE_IDENTITIES_REQUIRED")
    encoded = json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))
    if re.search(r"(?:^|[\"'=: ])(?:[A-Za-z]:[\\/]|/Users/|/home/|\\Users\\)", encoded, re.IGNORECASE):
        raise ValueError("BASELINE_IDENTITY_MUST_NOT_CONTAIN_PERSONAL_ABSOLUTE_PATH")
    return copy.deepcopy(value)


def _rng_state(trainer) -> dict[str, Any]:
    return {
        "python": __import__("random").getstate(),
        "numpy": np.random.get_state(),
        "torch_cpu": torch.get_rng_state().clone(),
        "torch_cuda_all": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
        "minibatch": trainer.minibatch_generator.get_state().clone(),
    }


def _probe_prediction(policy, probe: dict[str, Any]) -> dict[str, Any]:
    result = policy.act(
        probe["observation"], probe["candidates"], probe["candidate_mask"],
        probe.get("wm_critic"), deterministic=True,
    )
    return {key: result[key] for key in ("candidate_index", "candidate_key", "logits", "log_probability", "value", "base_value", "auxiliary_value")}


def save_trainer_checkpoint(trainer, path: str | os.PathLike[str], *, identities: dict[str, Any], fixed_input: dict[str, Any] | None = None) -> dict[str, Any]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    identity_value = _identities(identities)
    if fixed_input is None:
        raise ValueError("BASELINE_FIXED_PROBE_REQUIRED")
    probe = copy.deepcopy(fixed_input)
    for required in ("observation", "candidates", "candidate_mask"):
        if required not in probe:
            raise ValueError(f"BASELINE_FIXED_PROBE:{required}")
    probe_output = _probe_prediction(trainer.policy, probe)
    rng = _rng_state(trainer)
    payload = {
        "schema": CHECKPOINT_SCHEMA,
        "method_id": trainer.method_id,
        "seed": trainer.seed,
        "device_at_save": str(trainer.device),
        "config": copy.deepcopy(trainer.config),
        "architecture": copy.deepcopy(trainer.architecture_metadata),
        "identities": identity_value,
        "model_state": trainer.policy.state_dict(),
        "optimizer_state": trainer.optimizer.state_dict(),
        "rng_state": rng,
        "counters": copy.deepcopy(trainer.counters),
        "fixed_input": probe,
        "fixed_prediction": probe_output,
        "model_state_sha256": state_digest(trainer.policy.state_dict()),
        "optimizer_state_sha256": stable_digest(trainer.optimizer.state_dict()),
        "rng_state_sha256": stable_digest(rng),
    }
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(prefix=target.name + ".", suffix=".tmp", dir=target.parent, delete=False) as handle:
            temp_name = handle.name
            torch.save(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        if temp_name is not None and os.path.exists(temp_name):
            os.unlink(temp_name)
    return {
        "path": target.name if target.is_absolute() else target.as_posix(),
        "schema": CHECKPOINT_SCHEMA,
        "model_state_sha256": payload["model_state_sha256"],
        "optimizer_state_sha256": payload["optimizer_state_sha256"],
        "rng_state_sha256": payload["rng_state_sha256"],
        "fixed_prediction_verified": probe_output is not None,
    }


def restore_trainer_checkpoint(path: str | os.PathLike[str], *, expected_identities: dict[str, Any], device: str | torch.device = "cpu", fixed_input: dict[str, Any] | None = None):
    try:
        from .baseline_learning import make_trainer
    except ImportError:
        from baseline_learning import make_trainer
    source = Path(path)
    payload = torch.load(source, map_location="cpu", weights_only=False)
    if payload.get("schema") != CHECKPOINT_SCHEMA:
        raise ValueError("BASELINE_CHECKPOINT_SCHEMA")
    expected = _identities(expected_identities)
    if payload.get("identities") != expected:
        raise ValueError("BASELINE_CHECKPOINT_IDENTITY_MISMATCH")
    trainer = make_trainer(payload["method_id"], int(payload["seed"]), device=device, config=payload["config"])
    if trainer.architecture_metadata != payload.get("architecture"):
        raise ValueError("BASELINE_CHECKPOINT_ARCHITECTURE")
    trainer.policy.load_state_dict(payload["model_state"], strict=True)
    trainer.optimizer.load_state_dict(payload["optimizer_state"])
    trainer.counters = copy.deepcopy(payload["counters"])
    if state_digest(trainer.policy.state_dict()) != payload.get("model_state_sha256"):
        raise ValueError("BASELINE_CHECKPOINT_MODEL_DIGEST")
    if stable_digest(trainer.optimizer.state_dict()) != payload.get("optimizer_state_sha256"):
        raise ValueError("BASELINE_CHECKPOINT_OPTIMIZER_DIGEST")
    rng = payload.get("rng_state")
    if not isinstance(rng, dict) or stable_digest(rng) != payload.get("rng_state_sha256"):
        raise ValueError("BASELINE_CHECKPOINT_RNG_DIGEST")
    import random
    random.setstate(rng["python"])
    np.random.set_state(rng["numpy"])
    torch.set_rng_state(rng["torch_cpu"])
    if rng["torch_cuda_all"]:
        if not torch.cuda.is_available():
            raise RuntimeError("BASELINE_CHECKPOINT_CUDA_RNG_UNAVAILABLE")
        torch.cuda.set_rng_state_all(rng["torch_cuda_all"])
    trainer.minibatch_generator.set_state(rng["minibatch"])
    if stable_digest(_rng_state(trainer)) != payload["rng_state_sha256"]:
        raise ValueError("BASELINE_CHECKPOINT_RNG_RESTORE_MISMATCH")
    probe = copy.deepcopy(fixed_input if fixed_input is not None else payload.get("fixed_input"))
    if probe is None or payload.get("fixed_prediction") is None:
        raise ValueError("BASELINE_CHECKPOINT_FIXED_PROBE_REQUIRED")
    observed = _probe_prediction(trainer.policy, probe)
    expected_prediction = payload["fixed_prediction"]
    if observed["candidate_index"] != expected_prediction["candidate_index"] or observed["candidate_key"] != expected_prediction["candidate_key"]:
        raise ValueError("BASELINE_CHECKPOINT_PROBE_ACTION_MISMATCH")
    for key in ("logits", "log_probability", "value", "base_value", "auxiliary_value"):
        if not np.allclose(np.asarray(observed[key]), np.asarray(expected_prediction[key]), rtol=1e-6, atol=1e-6):
            raise ValueError(f"BASELINE_CHECKPOINT_PROBE_MISMATCH:{key}")
    prediction_ok = True
    return trainer, {
        "status": "complete",
        "model_state_sha256": payload["model_state_sha256"],
        "optimizer_state_sha256": payload["optimizer_state_sha256"],
        "rng_state_sha256": payload["rng_state_sha256"],
        "fixed_prediction_verified": prediction_ok,
        "counters": copy.deepcopy(trainer.counters),
    }


def restore_trainer(path, *, expected_identities, device="cpu", fixed_input=None):
    return restore_trainer_checkpoint(path, expected_identities=expected_identities, device=device, fixed_input=fixed_input)


_WM_RESTORE_CHILD = r"""
import json,os,random,sys
from pathlib import Path
import numpy as np
import torch
sys.path.insert(0,sys.argv[1])
import event_models
from baseline_checkpoints import stable_digest
request=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
device=torch.device(request['device'])
if device.type=='cuda':
    if not torch.cuda.is_available(): raise RuntimeError('BASELINE_WM_CHILD_CUDA_UNAVAILABLE')
    torch.cuda.set_device(device)
records=[]
for expected in request['members']:
    payload=torch.load(expected['path'],map_location='cpu',weights_only=False)
    proof=payload.get('resume_proof')
    if not isinstance(proof,dict) or proof.get('schema')!=event_models.WM_RESUME_PROOF_SCHEMA: raise ValueError('BASELINE_WM_CHILD_PROOF_REQUIRED')
    config=payload['config']
    model=event_models.TemporalGraphWorldModel(config['head_dims'],hidden_dim=int(config['hidden_dim']))
    model.set_normalization(payload['normalization'])
    model.load_state_dict(payload['model_state'],strict=True)
    model.to(device).eval().requires_grad_(False)
    model_digest=event_models._state_digest(model.state_dict())
    if model_digest!=payload['model_state_sha256'] or model_digest!=proof['model_state_sha256']: raise ValueError('BASELINE_WM_CHILD_MODEL_DIGEST')
    normalization_digest=event_models._normalization_digest(payload['normalization'])
    if normalization_digest!=proof['normalization_sha256']: raise ValueError('BASELINE_WM_CHILD_NORMALIZATION_DIGEST')
    optimizer=torch.optim.Adam(model.parameters(),lr=float(payload['training_config']['learning_rate']))
    optimizer.load_state_dict(payload['optimizer_state'])
    optimizer_digest=stable_digest(optimizer.state_dict())
    if optimizer_digest!=payload['optimizer_state_sha256'] or optimizer_digest!=proof['optimizer_state_sha256']: raise ValueError('BASELINE_WM_CHILD_OPTIMIZER_RESTORE')
    rng={'python':payload['python_rng_state'],'numpy':payload['numpy_rng_state'],'torch_cpu':payload['torch_rng_state'],'torch_cuda_all':payload['torch_cuda_rng_state_all'],'minibatch':payload['minibatch_generator_state']}
    rng_digest=stable_digest(rng)
    if rng_digest!=payload['resume_rng_state_sha256'] or rng_digest!=proof['rng_state_sha256']: raise ValueError('BASELINE_WM_CHILD_RNG_DIGEST')
    random.setstate(rng['python']); np.random.set_state(rng['numpy']); torch.set_rng_state(rng['torch_cpu'])
    if rng['torch_cuda_all']:
        if not torch.cuda.is_available(): raise RuntimeError('BASELINE_WM_CHILD_CUDA_RNG_UNAVAILABLE')
        torch.cuda.set_rng_state_all(rng['torch_cuda_all'])
    minibatch=torch.Generator(device='cpu'); minibatch.set_state(rng['minibatch'])
    actual_rng={'python':random.getstate(),'numpy':np.random.get_state(),'torch_cpu':torch.get_rng_state(),'torch_cuda_all':torch.cuda.get_rng_state_all() if rng['torch_cuda_all'] else [],'minibatch':minibatch.get_state()}
    actual_rng_digest=stable_digest(actual_rng)
    if actual_rng_digest!=rng_digest: raise ValueError('BASELINE_WM_CHILD_RNG_RESTORE_MISMATCH')
    probe=proof['fixed_probe']
    if stable_digest(probe)!=proof['probe_identity_sha256'] or proof['data_identity']!=payload['data_identity'] or proof['source_identity']!=request['data_identity']: raise ValueError('BASELINE_WM_CHILD_PROBE_BINDING')
    prediction=event_models._model_probe_prediction(model,probe['history'],probe['candidates'])
    if prediction['candidate_keys']!=proof['reference_prediction']['candidate_keys']: raise ValueError('BASELINE_WM_CHILD_CANDIDATE_KEYS')
    for head in event_models.WORLD_MODEL_HEADS:
        if not np.allclose(np.asarray(prediction['heads'][head]),np.asarray(proof['reference_prediction']['heads'][head]),rtol=1e-6,atol=1e-6): raise ValueError('BASELINE_WM_CHILD_PREDICTION:'+head)
    records.append({'seed':payload['seed'],'model_state_sha256':model_digest,'normalization_sha256':normalization_digest,'optimizer_state_sha256':optimizer_digest,'rng_state_sha256':rng_digest,'actual_restored_rng_sha256':actual_rng_digest,'probe_identity_sha256':proof['probe_identity_sha256'],'prediction_sha256':stable_digest(prediction),'optimizer_updates':payload['optimizer_updates'],'parameter_devices':sorted({str(parameter.device) for parameter in model.parameters()}),'optimizer_moment_devices':sorted({str(value.device) for state in optimizer.state.values() for key,value in state.items() if key!='step' and isinstance(value,torch.Tensor)}),'optimizer_step_devices':sorted({str(state['step'].device) for state in optimizer.state.values() if isinstance(state.get('step'),torch.Tensor)})})
print(json.dumps({'status':'complete','pid':os.getpid(),'device':str(device),'members':records},sort_keys=True,separators=(',',':'),allow_nan=False))
"""


def verify_wm_checkpoint_resume(checkpoint_paths, *, expected_data_identity: str, fixed_sample: dict[str, Any], device="cpu") -> dict[str, Any]:
    """Restore model, optimizer and actual RNG state in a fresh process; compare presave probes."""
    try:
        from .event_models import EVENT_MODEL_SCHEMA, WM_RESUME_PROOF_SCHEMA, _normalization_digest
    except ImportError:
        from event_models import EVENT_MODEL_SCHEMA, WM_RESUME_PROOF_SCHEMA, _normalization_digest
    if not expected_data_identity or not isinstance(fixed_sample, dict) or not fixed_sample.get("history") or not fixed_sample.get("candidates"):
        raise ValueError("BASELINE_WM_STRICT_PROBE_REQUIRED")
    if len(checkpoint_paths) != 3:
        raise ValueError("BASELINE_WM_THREE_CHECKPOINTS_REQUIRED")
    members, seeds = [], []
    for index, checkpoint_path in enumerate(checkpoint_paths):
        path = Path(checkpoint_path).resolve()
        payload = torch.load(path, map_location="cpu", weights_only=False)
        expected_seed = (8201, 8202, 8203)[index]
        if payload.get("schema") != EVENT_MODEL_SCHEMA or payload.get("seed") != expected_seed:
            raise ValueError("BASELINE_WM_CHECKPOINT_SCHEMA_OR_SEED")
        if payload.get("data_identity") != expected_data_identity:
            raise ValueError("BASELINE_WM_DATA_IDENTITY")
        proof = payload.get("resume_proof")
        if not isinstance(proof, dict) or proof.get("schema") != WM_RESUME_PROOF_SCHEMA:
            raise ValueError("BASELINE_WM_STRICT_RESUME_PROOF_REQUIRED")
        if proof.get("data_identity") != expected_data_identity or proof.get("source_identity") != expected_data_identity:
            raise ValueError("BASELINE_WM_PROOF_DATA_BINDING")
        if stable_digest(fixed_sample) != proof.get("probe_identity_sha256") or stable_digest(proof.get("fixed_probe")) != proof.get("probe_identity_sha256"):
            raise ValueError("BASELINE_WM_FIXED_PROBE_MISMATCH")
        if stable_digest(payload.get("optimizer_state")) != payload.get("optimizer_state_sha256") or proof.get("optimizer_state_sha256") != payload.get("optimizer_state_sha256"):
            raise ValueError("BASELINE_WM_OPTIMIZER_DIGEST")
        rng = {"python": payload.get("python_rng_state"), "numpy": payload.get("numpy_rng_state"), "torch_cpu": payload.get("torch_rng_state"), "torch_cuda_all": payload.get("torch_cuda_rng_state_all"), "minibatch": payload.get("minibatch_generator_state")}
        if any(rng[key] is None for key in rng):
            raise ValueError("BASELINE_WM_INCOMPLETE_RESUME_STATE")
        if stable_digest(rng) != payload.get("resume_rng_state_sha256") or proof.get("rng_state_sha256") != payload.get("resume_rng_state_sha256"):
            raise ValueError("BASELINE_WM_RNG_DIGEST")
        if _normalization_digest(payload.get("normalization")) != proof.get("normalization_sha256"):
            raise ValueError("BASELINE_WM_NORMALIZATION_DIGEST")
        if payload.get("model_state_sha256") != proof.get("model_state_sha256"):
            raise ValueError("BASELINE_WM_MODEL_PROOF_DIGEST")
        members.append({"path": str(path), "seed": expected_seed})
        seeds.append(expected_seed)
    request = {"device": str(torch.device(device)), "data_identity": expected_data_identity, "members": members}
    with tempfile.TemporaryDirectory(prefix="baseline-wm-restore-") as temp_dir:
        request_path = Path(temp_dir) / "request.json"
        request_path.write_text(json.dumps(request, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        child = subprocess.run([sys.executable, "-B", "-c", _WM_RESTORE_CHILD, str(Path(__file__).resolve().parent), str(request_path)], capture_output=True, text=True, timeout=600, check=False)
    if child.returncode != 0:
        raise ValueError("BASELINE_WM_FRESH_PROCESS_RESTORE_FAILED:" + child.stderr[-4000:])
    try:
        child_receipt = json.loads(child.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise ValueError("BASELINE_WM_FRESH_PROCESS_RECEIPT_INVALID") from exc
    if child_receipt.get("status") != "complete" or child_receipt.get("pid") == os.getpid():
        raise ValueError("BASELINE_WM_FRESH_PROCESS_NOT_CONFIRMED")
    if [row.get("seed") for row in child_receipt.get("members", [])] != seeds:
        raise ValueError("BASELINE_WM_FRESH_PROCESS_MEMBERS")
    return {"status": "complete", "seeds": seeds, "data_identity": expected_data_identity, "fresh_process_pid": child_receipt["pid"], "parent_pid": os.getpid(), "fresh_process_exit_status": child.returncode, "fresh_process_restore": child_receipt, "optimizer_digests": [row["optimizer_state_sha256"] for row in child_receipt["members"]], "rng_digests": [row["rng_state_sha256"] for row in child_receipt["members"]], "fixed_prediction_sha256": stable_digest([row["prediction_sha256"] for row in child_receipt["members"]]), "fixed_prediction_verified": True}
