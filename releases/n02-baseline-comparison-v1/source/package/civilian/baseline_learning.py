"""Matched categorical PPO and relational graph PPO baselines."""

from __future__ import annotations

import copy
import math
import random
from typing import Any, Sequence

import numpy as np
import torch
from torch import nn
from torch.distributions import Categorical

try:
    from .event_models import (
        CANDIDATE_FEATURE_DIM, NODE_FEATURE_DIM, RELATION_COUNT,
        WORLD_MODEL_HEADS, _candidate_features, _node_features,
    )
    from .event_policy import _GraphEncoder, _world_model_critic_features, POLICY_HIDDEN_DIM
except ImportError:
    from event_models import (
        CANDIDATE_FEATURE_DIM, NODE_FEATURE_DIM, RELATION_COUNT,
        WORLD_MODEL_HEADS, _candidate_features, _node_features,
    )
    from event_policy import _GraphEncoder, _world_model_critic_features, POLICY_HIDDEN_DIM


NODE_CAP = 128
FLAT_OBSERVATION_DIM = NODE_CAP * (NODE_FEATURE_DIM + 5 + 1) + RELATION_COUNT * NODE_CAP * NODE_CAP
METHODS = (
    "PPO", "GPPO", "Periodic-GPPO", "Event-GPPO",
    "Event-GPPO-WM", "Periodic-GPPO-WM",
)


def _seeded_module(module: nn.Module, seed: int) -> None:
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(int(seed) % (2**63 - 1))
        for child in module.modules():
            if isinstance(child, nn.Linear):
                child.reset_parameters()


class _FlatEncoder(nn.Module):
    """Fixed-size representation preserving every public node and typed edge."""

    def __init__(self, hidden_dim: int):
        super().__init__()
        self.node_cap = NODE_CAP
        self.input_dim = FLAT_OBSERVATION_DIM
        self.network = nn.Sequential(
            nn.Linear(self.input_dim, hidden_dim), nn.Tanh(),
            nn.Linear(hidden_dim, hidden_dim), nn.Tanh(),
        )

    def encode_input(self, observation: dict[str, Any], device: torch.device) -> torch.Tensor:
        rows, types, edges = _node_features(observation)
        count = len(rows)
        if count > self.node_cap:
            raise ValueError(f"BASELINE_FLAT_NODE_CAP:{count}>{self.node_cap}")
        node_features = torch.zeros((self.node_cap, NODE_FEATURE_DIM), dtype=torch.float32, device=device)
        type_features = torch.zeros((self.node_cap, 5), dtype=torch.float32, device=device)
        node_mask = torch.zeros((self.node_cap, 1), dtype=torch.float32, device=device)
        adjacency = torch.zeros((RELATION_COUNT, self.node_cap, self.node_cap), dtype=torch.float32, device=device)
        if count:
            node_features[:count] = torch.as_tensor(rows, dtype=torch.float32, device=device)
            type_ids = torch.as_tensor(types, dtype=torch.long, device=device)
            type_features[:count] = torch.nn.functional.one_hot(type_ids, num_classes=5).to(torch.float32)
            node_mask[:count] = 1.0
            for source, target, relation in edges:
                adjacency[relation, target, source] = 1.0
            adjacency = adjacency / adjacency.sum(dim=-1, keepdim=True).clamp_min(1.0)
        return torch.cat((node_features.flatten(), type_features.flatten(), node_mask.flatten(), adjacency.flatten()))

    def forward(self, observation: dict[str, Any]) -> torch.Tensor:
        device = next(self.parameters()).device
        return self.network(self.encode_input(observation, device))


class CategoricalCandidatePolicy(nn.Module):
    """Single categorical action head with disjoint actor and critic encoders."""

    def __init__(self, *, graph: bool, use_wm_aux: bool, seed: int, hidden_dim: int = POLICY_HIDDEN_DIM):
        super().__init__()
        self.graph = bool(graph)
        self.use_wm_aux = bool(use_wm_aux)
        self.hidden_dim = int(hidden_dim)
        encoder_class = _GraphEncoder if graph else _FlatEncoder
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(int(seed) + 101)
            self.actor_encoder = encoder_class(hidden_dim)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(int(seed) + 211)
            self.critic_encoder = encoder_class(hidden_dim)
        self.candidate_encoder = nn.Sequential(
            nn.Linear(CANDIDATE_FEATURE_DIM, hidden_dim), nn.Tanh(),
            nn.Linear(hidden_dim, hidden_dim), nn.Tanh(),
        )
        self.actor_head = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim), nn.Tanh(), nn.Linear(hidden_dim, 1),
        )
        self.value_head = nn.Sequential(nn.Linear(hidden_dim, hidden_dim), nn.Tanh(), nn.Linear(hidden_dim, 1))
        self.auxiliary_critic = (
            nn.Sequential(nn.Linear(hidden_dim + 2 * len(WORLD_MODEL_HEADS), hidden_dim), nn.Tanh(), nn.Linear(hidden_dim, 1))
            if self.use_wm_aux else None
        )
        _seeded_module(self.candidate_encoder, int(seed) + 307)
        _seeded_module(self.actor_head, int(seed) + 401)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(int(seed) + 503)
            for child in self.value_head.modules():
                if isinstance(child, nn.Linear):
                    child.reset_parameters()
            if self.auxiliary_critic is not None:
                for child in self.auxiliary_critic.modules():
                    if isinstance(child, nn.Linear):
                        child.reset_parameters()

    def actor_logits(self, observation: dict, candidates: Sequence[dict]) -> torch.Tensor:
        if not candidates or len(candidates) > 16:
            raise ValueError("BASELINE_CANDIDATE_COUNT")
        device = next(self.parameters()).device
        context = self.actor_encoder(observation)
        rows = [_candidate_features(item, observation) for item in candidates]
        if any(len(row) != CANDIDATE_FEATURE_DIM for row in rows):
            raise ValueError("BASELINE_CANDIDATE_FEATURE_DIM")
        encoded = self.candidate_encoder(torch.as_tensor(rows, dtype=torch.float32, device=device))
        repeated = context.unsqueeze(0).expand(len(candidates), -1)
        return self.actor_head(torch.cat((repeated, encoded), dim=-1)).squeeze(-1)

    def critic_values(self, observation: dict, wm_critic: dict[str, Any] | None = None, *, allow_missing_wm: bool = False) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        device = next(self.parameters()).device
        context = self.critic_encoder(observation)
        base = self.value_head(context).reshape(())
        if self.use_wm_aux:
            if wm_critic is None:
                if not allow_missing_wm:
                    raise ValueError("EVENT_POLICY_WM_PREDICTIONS_REQUIRED")
                wm_features = torch.zeros(2 * len(WORLD_MODEL_HEADS), dtype=torch.float32, device=device)
            else:
                wm_features = _world_model_critic_features(wm_critic, device=device)
            auxiliary = self.auxiliary_critic(torch.cat((context, wm_features.detach()), dim=-1)).reshape(())
        else:
            if wm_critic is not None:
                raise ValueError("BASELINE_NON_WM_RECEIVED_WM")
            auxiliary = base.new_zeros(())
        return base + auxiliary, base, auxiliary

    @staticmethod
    def _masked_distribution(logits: torch.Tensor, candidates: Sequence[dict], candidate_mask: Sequence[bool] | None) -> Categorical:
        if candidate_mask is None:
            mask = [bool(item.get("legal", True)) for item in candidates]
        else:
            if len(candidate_mask) != len(candidates):
                raise ValueError("BASELINE_CANDIDATE_MASK_LENGTH")
            mask = [bool(item.get("legal", True)) and bool(flag) for item, flag in zip(candidates, candidate_mask)]
        if not mask or not any(mask):
            raise ValueError("BASELINE_NO_LEGAL_CANDIDATE")
        return Categorical(logits=logits.masked_fill(~torch.tensor(mask, dtype=torch.bool, device=logits.device), torch.finfo(logits.dtype).min))

    def act(self, observation, candidates, candidate_mask=None, wm_critic=None, deterministic=False) -> dict[str, Any]:
        logits = self.actor_logits(observation, candidates)
        distribution = self._masked_distribution(logits, candidates, candidate_mask)
        index = int(torch.argmax(distribution.logits).item()) if deterministic else int(distribution.sample().item())
        action = torch.tensor(index, device=logits.device)
        value, base, auxiliary = self.critic_values(observation, wm_critic)
        return {
            "candidate_index": index,
            "candidate_key": str(candidates[index].get("candidate_key", candidates[index].get("id", index))),
            "logits": logits.detach().cpu().tolist(),
            "log_probability": float(distribution.log_prob(action).detach().cpu()),
            "entropy": float(distribution.entropy().detach().cpu()),
            "value": float(value.detach().cpu()),
            "base_value": float(base.detach().cpu()),
            "auxiliary_value": float(auxiliary.detach().cpu()),
        }

    def evaluate_action(self, observation, candidates, candidate_mask, action_index, wm_critic=None) -> dict[str, torch.Tensor]:
        logits = self.actor_logits(observation, candidates)
        distribution = self._masked_distribution(logits, candidates, candidate_mask)
        action = torch.as_tensor(action_index, dtype=torch.long, device=logits.device)
        if int(action.item()) < 0 or int(action.item()) >= len(candidates) or not bool(distribution.probs[action].detach() > 0):
            raise ValueError("BASELINE_ACTION_NOT_LEGAL")
        value, base, auxiliary = self.critic_values(observation, wm_critic)
        return {
            "log_probability": distribution.log_prob(action),
            "entropy": distribution.entropy(),
            "value": value,
            "base_value": base,
            "auxiliary_value": auxiliary,
            "logits": logits,
        }

    def value(self, observation, wm_critic=None) -> float:
        with torch.no_grad():
            return float(self.critic_values(observation, wm_critic, allow_missing_wm=wm_critic is None)[0].cpu())


class BaselineTrainer:
    def __init__(self, method_id: str, seed: int, device: str | torch.device = "cpu", config: dict[str, Any] | None = None):
        if method_id not in METHODS:
            raise ValueError(f"BASELINE_METHOD:{method_id}")
        self.method_id = method_id
        self.seed = int(seed)
        self.device = torch.device(device)
        if self.device.type == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("BASELINE_CUDA_UNAVAILABLE")
        self.config = {"learning_rate": 3e-4, "gamma": 0.99, "gae_lambda": 0.95, "clip_ratio": 0.2, "value_coefficient": 0.5, "entropy_coefficient": 0.01, "max_gradient_norm": 0.5, "hidden_dim": POLICY_HIDDEN_DIM, **(config or {})}
        if any(float(self.config[key]) <= 0 for key in ("learning_rate", "gamma", "gae_lambda", "clip_ratio", "max_gradient_norm")):
            raise ValueError("BASELINE_CONFIG_RANGE")
        random.seed(self.seed)
        np.random.seed(self.seed % (2**32))
        torch.manual_seed(self.seed)
        if self.device.type == "cuda":
            torch.cuda.manual_seed_all(self.seed)
        self.policy = CategoricalCandidatePolicy(
            graph=method_id != "PPO", use_wm_aux=method_id.endswith("-WM"),
            seed=self.seed, hidden_dim=int(self.config["hidden_dim"]),
        ).to(self.device)
        actor_modules = (self.policy.actor_encoder, self.policy.candidate_encoder, self.policy.actor_head)
        critic_modules = (self.policy.critic_encoder, self.policy.value_head) + ((self.policy.auxiliary_critic,) if self.policy.auxiliary_critic is not None else ())
        count_parameters = lambda modules: sum(parameter.numel() for module in modules for parameter in module.parameters())
        self.architecture_metadata = {
            "method_id": method_id,
            "observation_encoder": "typed_graph_message_passing" if self.policy.graph else "flat_mlp",
            "node_feature_dim": NODE_FEATURE_DIM,
            "node_type_count": 5,
            "typed_relation_count": RELATION_COUNT,
            "flat_node_cap": NODE_CAP if not self.policy.graph else None,
            "flat_input_dim": FLAT_OBSERVATION_DIM if not self.policy.graph else None,
            "flat_overflow_behavior": "raise_without_truncation" if not self.policy.graph else None,
            "candidate_feature_dim": CANDIDATE_FEATURE_DIM,
            "candidate_count_limit": 16,
            "hidden_dim": self.policy.hidden_dim,
            "actor_parameter_count": count_parameters(actor_modules),
            "critic_parameter_count": count_parameters(critic_modules),
            "total_parameter_count": sum(parameter.numel() for parameter in self.policy.parameters()),
        }
        self.optimizer = torch.optim.Adam(self.policy.parameters(), lr=float(self.config["learning_rate"]))
        self.minibatch_generator = torch.Generator(device="cpu").manual_seed(self.seed + 65537)
        self.counters = {"optimizer_steps": 0, "actor_optimizer_steps": 0, "critic_only_optimizer_steps": 0, "actor_rows": 0, "critic_rows": 0, "transitions_seen": 0}

    def _advantage_audit(self, transitions: Sequence[dict[str, Any]]) -> tuple[list[float], list[float], list[float]]:
        raw_gae = [0.0] * len(transitions)
        running = 0.0
        gamma, lam = float(self.config["gamma"]), float(self.config["gae_lambda"])
        for index in range(len(transitions) - 1, -1, -1):
            row = transitions[index]
            terminal = bool(row.get("terminated", False))
            boundary = terminal or bool(row.get("truncated", False))
            next_value = 0.0 if terminal else float(row.get("next_value", 0.0))
            delta = float(row["reward"]) + gamma * next_value - float(row["old_value"])
            running = delta + (0.0 if boundary else gamma * lam * running)
            raw_gae[index] = running
        returns = [advantage + float(row["old_value"]) for advantage, row in zip(raw_gae, transitions)]
        advantages = list(raw_gae)
        actor_adv = [value for value, row in zip(raw_gae, transitions) if row.get("actor_decision", True)]
        if actor_adv:
            mean, std = float(np.mean(actor_adv)), float(np.std(actor_adv))
            advantages = [((value - mean) / max(std, 1e-8)) if row.get("actor_decision", True) else value for value, row in zip(advantages, transitions)]
        return raw_gae, advantages, returns

    def _advantages(self, transitions: Sequence[dict[str, Any]]) -> tuple[list[float], list[float]]:
        _, advantages, returns = self._advantage_audit(transitions)
        return advantages, returns

    def train_update(self, transitions: Sequence[dict[str, Any]], *, epochs: int, minibatch_size: int, update_cap: int) -> list[dict[str, Any]]:
        if not transitions:
            return []
        if epochs <= 0 or minibatch_size <= 0 or update_cap < 0:
            raise ValueError("BASELINE_UPDATE_BUDGET")
        remaining_updates = max(0, int(update_cap) - int(self.counters["optimizer_steps"]))
        if remaining_updates == 0:
            return []
        rows = list(transitions)
        for row in rows:
            required = ("observation", "candidates", "candidate_mask", "action_index", "old_log_probability", "old_value", "reward", "terminated", "truncated", "next_value", "actor_decision")
            if any(key not in row for key in required):
                raise ValueError("BASELINE_TRANSITION_SCHEMA")
        raw_gae, advantages, returns = self._advantage_audit(rows)
        receipts: list[dict[str, Any]] = []
        for _epoch in range(epochs):
            permutation = torch.randperm(len(rows), generator=self.minibatch_generator).tolist()
            for start in range(0, len(rows), minibatch_size):
                if len(receipts) >= remaining_updates:
                    break
                indices = permutation[start:start + minibatch_size]
                minibatch = [rows[index] for index in indices]
                actor_indices = [local for local, row in enumerate(minibatch) if bool(row["actor_decision"])]
                actor_losses, entropies = [], []
                actor_row_records = []
                for local in actor_indices:
                    row = minibatch[local]
                    evaluated = self.policy.evaluate_action(
                        row["observation"], row["candidates"], row["candidate_mask"], row["action_index"], row.get("wm_critic"),
                    )
                    ratio = torch.exp(evaluated["log_probability"] - torch.tensor(float(row["old_log_probability"]), device=self.device))
                    adv = torch.tensor(float(advantages[indices[local]]), dtype=torch.float32, device=self.device)
                    unclipped = ratio * adv
                    clipped = torch.clamp(ratio, 1.0 - float(self.config["clip_ratio"]), 1.0 + float(self.config["clip_ratio"])) * adv
                    actor_losses.append(-torch.minimum(unclipped, clipped))
                    entropies.append(evaluated["entropy"])
                    actor_row_records.append({
                        "physical_index": int(indices[local]),
                        "old_log_probability": float(row["old_log_probability"]),
                        "new_log_probability": float(evaluated["log_probability"].detach().cpu()),
                        "ratio": float(ratio.detach().cpu()),
                        "old_logits": row.get("old_logits"),
                        "new_logits": evaluated["logits"].detach().cpu().tolist(),
                    })
                value_rows = [
                    self.policy.critic_values(
                        row["observation"], row.get("wm_critic"),
                        allow_missing_wm=self.policy.use_wm_aux and not bool(row["actor_decision"]),
                    )[0]
                    for row in minibatch
                ]
                target = torch.tensor([returns[index] for index in indices], dtype=torch.float32, device=self.device)
                predicted = torch.stack(value_rows)
                critic_loss = torch.nn.functional.mse_loss(predicted, target)
                actor_loss = torch.stack(actor_losses).mean() if actor_losses else critic_loss.new_zeros(())
                entropy = torch.stack(entropies).mean() if entropies else critic_loss.new_zeros(())
                auxiliary_loss = critic_loss.new_zeros(())
                if self.policy.use_wm_aux:
                    auxiliary = torch.stack([
                        self.policy.critic_values(row["observation"], row.get("wm_critic"), allow_missing_wm=not bool(row["actor_decision"]))[2]
                        for row in minibatch
                    ])
                    base = torch.stack([
                        self.policy.critic_values(row["observation"], row.get("wm_critic"), allow_missing_wm=not bool(row["actor_decision"]))[1]
                        for row in minibatch
                    ])
                    auxiliary_loss = torch.nn.functional.mse_loss(auxiliary, (target - base.detach()).detach())
                total_loss = actor_loss + float(self.config["value_coefficient"]) * critic_loss - float(self.config["entropy_coefficient"]) * entropy
                if not bool(torch.isfinite(total_loss)):
                    raise FloatingPointError("BASELINE_NONFINITE_LOSS")
                self.optimizer.zero_grad(set_to_none=True)
                total_loss.backward()
                actor_parameters = list(self.policy.actor_encoder.parameters()) + list(self.policy.candidate_encoder.parameters()) + list(self.policy.actor_head.parameters())
                critic_parameters = list(self.policy.critic_encoder.parameters()) + list(self.policy.value_head.parameters())
                auxiliary_parameters = []
                if self.policy.auxiliary_critic is not None:
                    auxiliary_parameters = list(self.policy.auxiliary_critic.parameters())
                    critic_parameters.extend(auxiliary_parameters)
                actor_grad = torch.nn.utils.clip_grad_norm_(actor_parameters, float(self.config["max_gradient_norm"])) if actor_indices else torch.tensor(0.0, device=self.device)
                auxiliary_grad = self._gradient_norm(auxiliary_parameters)
                critic_grad = torch.nn.utils.clip_grad_norm_(critic_parameters, float(self.config["max_gradient_norm"]))
                actor_snapshot = self._parameter_snapshot(actor_parameters)
                critic_snapshot = self._parameter_snapshot(critic_parameters)
                auxiliary_snapshot = self._parameter_snapshot(auxiliary_parameters)
                before = self._parameter_digest()
                actor_before = self._actor_digest()
                critic_before = self._critic_digest()
                auxiliary_before = self._auxiliary_critic_digest()
                self.optimizer.step()
                after = self._parameter_digest()
                actor_after = self._actor_digest()
                critic_after = self._critic_digest()
                auxiliary_after = self._auxiliary_critic_digest()
                actor_delta = self._parameter_delta_l2(actor_snapshot, actor_parameters)
                critic_delta = self._parameter_delta_l2(critic_snapshot, critic_parameters)
                auxiliary_delta = self._parameter_delta_l2(auxiliary_snapshot, auxiliary_parameters)
                actor_changed = actor_before != actor_after and bool(actor_indices)
                physical_transition_records = [
                    {
                        "physical_index": int(index),
                        "raw_gae": float(raw_gae[index]),
                        "return_target": float(returns[index]),
                        "normalized_advantage": float(advantages[index]),
                        "actor_decision": bool(rows[index]["actor_decision"]),
                    }
                    for index in indices
                ]
                self.counters["optimizer_steps"] += 1
                self.counters["actor_optimizer_steps"] += int(actor_changed)
                self.counters["critic_only_optimizer_steps"] += int(not actor_indices)
                self.counters["actor_rows"] += len(actor_indices)
                self.counters["critic_rows"] += len(minibatch)
                self.counters["transitions_seen"] += len(minibatch)
                receipts.append({
                    "optimizer_step": self.counters["optimizer_steps"], "epoch": _epoch + 1,
                    "transition_indices": indices, "optimizer_step_applied": True,
                    "eligible_actor_rows": len(actor_indices), "critic_rows": len(minibatch),
                    "actor_loss": float(actor_loss.detach().cpu()), "entropy_loss": float((-float(self.config["entropy_coefficient"]) * entropy).detach().cpu()),
                    "critic_loss": float(critic_loss.detach().cpu()), "auxiliary_critic_loss": float(auxiliary_loss.detach().cpu()),
                    "auxiliary_critic_loss_semantics": "diagnostic_only_not_in_total_loss",
                    "actor_gradient_norm_preclip": float(torch.as_tensor(actor_grad).detach().cpu()),
                    "critic_gradient_norm_preclip": float(torch.as_tensor(critic_grad).detach().cpu()),
                    "auxiliary_critic_gradient_norm_preclip": auxiliary_grad,
                    "parameter_digest_before": before, "parameter_digest_after": after,
                    "actor_parameter_digest_before": actor_before, "actor_parameter_digest_after": actor_after,
                    "critic_parameter_digest_before": critic_before, "critic_parameter_digest_after": critic_after,
                    "auxiliary_critic_parameter_digest_before": auxiliary_before,
                    "auxiliary_critic_parameter_digest_after": auxiliary_after,
                    "actor_parameter_digest_changed": actor_before != actor_after,
                    "critic_parameter_digest_changed": critic_before != critic_after,
                    "auxiliary_critic_parameter_digest_changed": auxiliary_before != auxiliary_after,
                    "actor_parameter_delta_l2": actor_delta,
                    "critic_parameter_delta_l2": critic_delta,
                    "auxiliary_critic_parameter_delta_l2": auxiliary_delta,
                    "actor_parameters_changed": actor_changed, "training_device": str(self.device),
                    "model_parameter_devices": sorted({str(parameter.device) for parameter in self.policy.parameters()}),
                    "optimizer_parameter_devices": sorted({str(parameter.device) for group in self.optimizer.param_groups for parameter in group["params"]}),
                    "optimizer_state_tensor_devices": self._optimizer_state_devices(),
                    "optimizer_moment_devices": self._optimizer_state_devices(exclude_step=True),
                    "optimizer_step_devices": self._optimizer_state_devices(only_step=True),
                    "physical_transition_records": physical_transition_records,
                    "actor_row_records": actor_row_records,
                })
            if len(receipts) >= remaining_updates:
                break
        return receipts

    def _parameter_digest(self) -> str:
        try:
            from .baseline_checkpoints import state_digest
        except ImportError:
            from baseline_checkpoints import state_digest
        return state_digest(self.policy.state_dict())

    def _actor_digest(self) -> str:
        try:
            from .baseline_checkpoints import state_digest
        except ImportError:
            from baseline_checkpoints import state_digest
        actor_state = {
            **{f"encoder.{key}": value for key, value in self.policy.actor_encoder.state_dict().items()},
            **{f"candidate.{key}": value for key, value in self.policy.candidate_encoder.state_dict().items()},
            **{f"head.{key}": value for key, value in self.policy.actor_head.state_dict().items()},
        }
        return state_digest(actor_state)

    def _critic_digest(self) -> str:
        return self._modules_digest((self.policy.critic_encoder, self.policy.value_head) + ((self.policy.auxiliary_critic,) if self.policy.auxiliary_critic is not None else ()))

    def _auxiliary_critic_digest(self) -> str | None:
        if self.policy.auxiliary_critic is None:
            return None
        return self._modules_digest((self.policy.auxiliary_critic,))

    @staticmethod
    def _gradient_norm(parameters: Sequence[nn.Parameter]) -> float:
        norms = [parameter.grad.detach().norm(2) for parameter in parameters if parameter.grad is not None]
        if not norms:
            return 0.0
        return float(torch.stack(norms).norm(2).detach().cpu())

    def _optimizer_state_devices(self, *, exclude_step: bool = False, only_step: bool = False) -> list[str]:
        return sorted({
            str(value.device)
            for state in self.optimizer.state.values()
            for name, value in state.items()
            if isinstance(value, torch.Tensor) and (name == "step" if only_step else name != "step" if exclude_step else True)
        })

    @staticmethod
    def _parameter_snapshot(parameters: Sequence[nn.Parameter]) -> list[torch.Tensor]:
        return [parameter.detach().clone() for parameter in parameters]

    @staticmethod
    def _parameter_delta_l2(before: Sequence[torch.Tensor], parameters: Sequence[nn.Parameter]) -> float:
        if not before:
            return 0.0
        squared = [torch.sum((old - parameter.detach()) ** 2) for old, parameter in zip(before, parameters)]
        return float(torch.stack(squared).sum().sqrt().cpu())

    @staticmethod
    def _modules_digest(modules: Sequence[nn.Module]) -> str:
        try:
            from .baseline_checkpoints import state_digest
        except ImportError:
            from baseline_checkpoints import state_digest
        state = {
            f"module_{module_index}.{key}": value
            for module_index, module in enumerate(modules)
            for key, value in module.state_dict().items()
        }
        return state_digest(state)

    def save_checkpoint(self, path, *, identities, fixed_input=None):
        try:
            from .baseline_checkpoints import save_trainer_checkpoint
        except ImportError:
            from baseline_checkpoints import save_trainer_checkpoint
        return save_trainer_checkpoint(self, path, identities=identities, fixed_input=fixed_input)


def make_trainer(method_id: str, seed: int, device: str | torch.device = "cpu", config: dict[str, Any] | None = None) -> BaselineTrainer:
    return BaselineTrainer(method_id, seed, device, config)
