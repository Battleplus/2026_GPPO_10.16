"""Read-only, standard-library audit of event V1 raw persisted branch traces.

No project module is imported. `compute` never opens CONSEQUENCE_LABELS; `compare`
is a separate process consuming the persisted independent result. This is trace
recomputation, not an independent simulator replay or proof of unrecorded state.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import math
from pathlib import Path
from collections import defaultdict

HEADS = ('next_state', 'progress', 'delay', 'energy', 'failure',
         'communication_risk', 'constraint_risk', 'utility')
PHYSICAL = HEADS[:-1]
WEIGHTS = {'completion': 1., 'delay': .2, 'energy': .01, 'risk': .25,
           'communication': .01, 'switch': .05, 'reconstruction': .05,
           'reconstruction_scale': .01}
PRIMITIVES = {'completion': 'completion_count', 'delay': 'delay_minutes',
              'energy': 'energy_units', 'risk': 'risk_units',
              'communication': 'communication_messages', 'switch': 'switch_count',
              'reconstruction': 'reconstruction_count',
              'reconstruction_size': 'reconstruction_size'}


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def digest(x):
    return hashlib.sha256(canonical(x)).hexdigest()


def filehash(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def number(x):
    return float(x) if type(x) in (int, float) and math.isfinite(x) else None


def close(a, b):
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-7)


def rows(path):
    with Path(path).open(encoding='utf-8') as f:
        for line_no, line in enumerate(f, 1):
            require(bool(line.strip()), f'blank JSONL line {path}:{line_no}')
            row = json.loads(line, parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
            require(isinstance(row, dict), f'JSONL object required {path}:{line_no}')
            yield row


def write_json(p, x):
    Path(p).write_text(json.dumps(x, indent=2, sort_keys=True, ensure_ascii=False,
                                allow_nan=False) + '\n', encoding='utf-8')


def truth_rows(x):
    if isinstance(x, dict):
        x = [dict(v, id=str(k)) for k, v in x.items()]
    require(isinstance(x, list) and x and all(isinstance(v, dict) for v in x), 'truth rows missing')
    ids = [v.get('id') for v in x]
    require(all(isinstance(i, str) and i for i in ids) and len(set(ids)) == len(ids), 'truth IDs missing/duplicate')
    return sorted(x, key=lambda v: v['id'])


def progress(task):
    for name in ('progress', 'service_progress', 'completion_fraction'):
        p = number(task.get(name))
        if p is not None:
            return min(1., max(0., p))
    return 1. if task.get('delivered') or task.get('status') in ('completed', 'delivered') else None


def task_result(task, endpoint):
    status = str(task.get('status', '')).lower()
    deadline, completed = number(task.get('deadline')), number(task.get('completed_at'))
    complete = bool(task.get('delivered')) or status in ('completed', 'delivered')
    failed = status in ('failed', 'expired') or bool(task.get('failed')) or bool(task.get('failure_reason'))
    p = progress(task)
    punctual = task.get('on_time') if type(task.get('on_time')) is bool else None
    if punctual is None:
        if complete and completed is not None and deadline is not None:
            punctual = completed <= deadline
        elif task.get('deadline_missed') or (deadline is not None and endpoint >= deadline and not complete) or failed:
            punctual = False
    delay = None
    if completed is not None and deadline is not None:
        delay = max(0., completed - deadline)
    elif punctual is False and deadline is not None and endpoint >= deadline:
        delay = float(max(0, endpoint - int(deadline)))
    return dict(id=task['id'], kind=task.get('kind'), status=status or None,
                progress=p, progress_valid=p is not None, complete=complete,
                complete_valid=bool(status) or 'delivered' in task,
                on_time=punctual, on_time_valid=punctual is not None,
                delay_minutes=delay, delay_valid=delay is not None, failed=failed,
                failure_valid=bool(status) or 'failed' in task or 'failure_reason' in task,
                deadline=deadline)


def event_components(events):
    c = dict.fromkeys(PRIMITIVES, 0.)
    switched, owners = set(), set()
    reorders = 0
    for e in events:
        k = str(e.get('type', '')).lower()
        if k == 'logical_task_completed':
            c['completion'] += 1
        elif k in ('delay_accrued', 'move', 'service', 'communication_tx'):
            key, field = {'delay_accrued': ('delay', 'minutes'), 'move': ('energy', 'energy'),
                          'service': ('energy', 'energy'),
                          'communication_tx': ('communication', 'message_count')}[k]
            v = number(e.get(field))
            require(v is not None and v >= 0, 'incomplete/negative raw event primitive ' + field)
            c[key] += v
            if k == 'move':
                risk = number(e.get('environmental_risk'))
                require(risk is not None and risk >= 0, 'missing move environmental_risk')
                c['risk'] += risk
        elif k in ('task_failed', 'platform_failure'):
            c['risk'] += 1
        elif k in ('task_switch', 'task_owner_change'):
            require(isinstance(e.get('task_id'), str), 'missing switch/owner task')
            (switched if k == 'task_switch' else owners).add(e['task_id'])
        elif k in ('queue_reorder', 'queue_reordered'):
            reorders += 1
    c['switch'] = float(len(switched))
    c['reconstruction_size'] = float(len(owners) + reorders)
    c['reconstruction'] = float(c['reconstruction_size'] > 0)
    return c


def reward_terms(c, weights):
    return {k: (1 if k == 'completion' else -1) * weights[k] *
            c['reconstruction_size' if k == 'reconstruction_scale' else k] for k in weights}


def communication(steps, events):
    scores, seen, links_seen = [], 0, 0
    clip = lambda x: min(1., max(0., x))
    for e in events:
        k = str(e.get('type', '')).lower()
        if not any(t in k for t in ('comm', 'message', 'link', 'packet')):
            continue
        seen += 1
        risk, quality = number(e.get('risk')), number(e.get('quality'))
        if risk is not None:
            scores.append(clip(risk))
        elif quality is not None:
            scores.append(1. - clip(quality))
        elif e.get('connected') is False or e.get('dropped') is True or any(t in k for t in ('drop', 'down', 'disconnect')):
            scores.append(1.)
        else:
            loss = number(e.get('packet_loss'))
            loss = number(e.get('loss_rate')) if loss is None else loss
            if loss is not None:
                scores.append(clip(loss))
    for s in steps:
        for name in ('public_observation', 'next_public_observation'):
            obs = s.get(name, {})
            links = obs.get('communication', obs.get('links', []))
            links = list(links.values()) if isinstance(links, dict) else links
            require(isinstance(links, list), 'communication samples schema')
            for link in links:
                q = number(link.get('quality', link.get('link_quality')))
                loss = number(link.get('packet_loss', link.get('loss_rate')))
                if q is not None or loss is not None:
                    scores.append(max(1 - clip(q) if q is not None else 0., clip(loss) if loss is not None else 0.))
                    links_seen += 1
    return (sum(scores) / len(scores) if scores else 0., bool(scores) or seen == 0,
            dict(communication_events=seen, link_samples=links_seen))


def constraints(steps, events):
    count, receipt_steps = 0, 0
    for s in steps:
        receipts = s.get('operation_receipts')
        receipts = [receipts] if isinstance(receipts, dict) else receipts
        if isinstance(receipts, list):
            receipt_steps += 1
            for receipt in receipts:
                require(isinstance(receipt, dict), 'operation receipt schema')
                legal = receipt.get('postrepair_legal', receipt.get('legal'))
                failures = receipt.get('constraint_violations', receipt.get('violations', []))
                count += 1 if legal is False else len(failures) if isinstance(failures, list) else 0
    event_count = sum('constraint' in str(e.get('type', '')).lower() and
                      any(v in str(e.get('type', '')).lower() for v in ('violation', 'rejected', 'infeasible')) for e in events)
    return float(count + event_count), receipt_steps == len(steps), dict(receipt_steps=receipt_steps, constraint_events=event_count)


def compute_branch(branch, weights):
    """Consume raw branch state/events only. Never accepts a producer label."""
    require(branch.get('schema') == 'event-branch-trajectory/1', 'branch schema')
    candidate, tr = branch['candidate'], branch['trajectory']
    require(tr.get('schema') == 'event-relief-window-trace/1', 'trace schema')
    key, action = branch['candidate_key'], candidate['full_environment_action']
    require(key == candidate['candidate_key'] == 'event-action-' + digest(action)[:24], 'candidate/action identity')
    scope = {'NOOP': 'noop', 'LOCAL_REPAIR': 'local', 'GLOBAL_REPLAN': 'global'}.get(action.get('scope'))
    require(scope and candidate.get('candidate_scope') == scope, 'candidate scope')
    require(type(action.get('noop')) is bool and action['noop'] == (scope == 'noop'), 'NOOP scope mismatch')
    require(isinstance(action.get('queue_operations'), list) and isinstance(action.get('dispatches'), list), 'action lists')
    if action['noop']:
        require(not action['queue_operations'] and not action['dispatches'], 'NOOP contains mutation')
    require(candidate.get('legal') is True, 'illegal candidate entered branch trace')
    require(branch['parent_id'] == tr['parent_id'] and branch['split'] == tr['split'], 'trace parent/split')
    require(candidate['event_tape_id'] == tr['event_tape_id'], 'trace tape mismatch')
    steps = tr['steps']
    require(isinstance(steps, list) and len(steps) == tr['end_time'] - tr['start_time'] > 0, 'trace length')
    obs = steps[0]['public_observation']
    prov = obs['provenance']
    require(digest({k: v for k, v in obs.items() if k != 'provenance'}) == prov['snapshot_hash'], 'public snapshot content hash')
    for k in ('snapshot_hash', 'public_prefix_hash', 'event_tape_id'):
        require(candidate[k] == prov[k], 'candidate public binding ' + k)
    events, rewards, recorded, components = [], [], [], []
    for i, s in enumerate(steps):
        require(s['time'] == tr['start_time'] + i, 'noncontiguous minute')
        submitted = s['full_environment_action']
        require(submitted == action if i == 0 else submitted.get('noop') is True and not submitted.get('queue_operations') and not submitted.get('dispatches'), 'first action/continuation binding')
        require(isinstance(s.get('raw_events'), list) and all(isinstance(e, dict) for e in s['raw_events']), 'raw events schema')
        events.extend(s['raw_events'])
        c = event_components(s['raw_events'])
        terms = reward_terms(c, weights)
        r = sum(terms.values())
        require(number(s.get('reward')) is not None and close(r, s['reward']), 'event-derived reward mismatch')
        for name, field in PRIMITIVES.items():
            require(number(s.get('reward_primitives', {}).get(field)) is not None and close(c[name], s['reward_primitives'][field]), 'reward primitive mismatch ' + field)
        for name, v in terms.items():
            require(number(s.get('reward_terms', {}).get(name)) is not None and close(v, s['reward_terms'][name]), 'reward term mismatch ' + name)
        rewards.append(r)
        recorded.append(float(s['reward']))
        components.append(c)
        require(any(v.get('postrepair_legal') is True for v in s.get('operation_receipts', [])), 'missing positive postrepair legality witness')
    require(events == tr.get('raw_events'), 'flattened raw-event trace mismatch')
    truth = tr['raw_truth']
    require(truth['time'] == tr['end_time'], 'endpoint truth time')
    tasks, platforms = truth_rows(truth['tasks']), truth_rows(truth['platforms'])
    task_rows = [task_result(t, tr['end_time']) for t in tasks]
    ps = [t['progress'] for t in task_rows if t['progress_valid']]
    ons = [t['on_time'] for t in task_rows if t['on_time_valid']]
    delays = [t['delay_minutes'] for t in task_rows if t['delay_valid']]
    progress_value, progress_valid = sum(ps) / len(ps) if ps else 0., len(ps) == len(tasks)
    on_value, on_valid = sum(bool(v) for v in ons) / len(ons) if ons else 0., len(ons) == len(tasks)
    delay_value = sum(delays) / len(delays) if delays else 0.
    delay_valid = bool(delays) and len(delays) == sum(t['deadline'] is not None for t in task_rows)
    failure = sum(t['failed'] for t in task_rows) / len(tasks)
    failure_valid = all(t['failure_valid'] for t in task_rows)
    energy = sum(c['energy'] for c in components)
    initial_platforms = truth_rows(obs['platforms'])
    require([p['id'] for p in initial_platforms] == [p['id'] for p in platforms], 'energy platform identity')
    energy_fields = [number(p.get('energy_used')) for p in initial_platforms + platforms]
    endpoint_valid = all(v is not None for v in energy_fields)
    endpoint_delta = sum(float(p['energy_used']) for p in platforms) - sum(float(p['energy_used']) for p in initial_platforms) if endpoint_valid else 0.
    require(not endpoint_valid or math.isclose(energy, endpoint_delta, rel_tol=1e-8, abs_tol=1e-6), 'energy event/endpoint mismatch')
    comm, comm_valid, comm_counts = communication(steps, events)
    constraint, constraint_valid, constraint_counts = constraints(steps, events)
    state, state_valid = [], []
    for t, raw in zip(task_rows, tasks):
        status = str(raw.get('status', '')).lower()
        values = [t['progress'], 1. if t['complete'] else 0. if status else None,
                  1. if t['failed'] else 0. if status or 'failure_reason' in raw else None,
                  1. if raw.get('on_time') is True else 0. if type(raw.get('on_time')) is bool else None]
        state.extend(0. if v is None else v for v in values)
        state_valid.extend(v is not None for v in values)
    for p in platforms:
        xy = p.get('position')
        values = [number(xy[0]) if isinstance(xy, list) and len(xy) >= 2 else None,
                  number(xy[1]) if isinstance(xy, list) and len(xy) >= 2 else None,
                  number(p.get('energy')), 1. if p.get('failed') is True else 0. if type(p.get('failed')) is bool else None]
        state.extend(0. if v is None else v for v in values)
        state_valid.extend(v is not None for v in values)
    model = {name: dict(values=value, valid=valid) for name, value, valid in
             [('next_state', state, state_valid), ('progress', progress_value, progress_valid),
              ('delay', delay_value, delay_valid), ('energy', energy, endpoint_valid),
              ('failure', failure, failure_valid), ('communication_risk', comm, comm_valid),
              ('constraint_risk', constraint, constraint_valid), ('utility', sum(rewards), True)]}
    global_values = [('progress_rate', 'progress'), ('mean_delay_minutes', 'delay'),
                     ('energy_used', 'energy'), ('failure_rate', 'failure'),
                     ('communication_risk', 'communication_risk'),
                     ('constraint_violation_count', 'constraint_risk'), ('utility', 'utility')]
    global_outcomes = {name: dict(value=model[h]['values'], valid=model[h]['valid']) for name, h in global_values}
    global_outcomes['on_time_rate'] = dict(value=on_value, valid=on_valid)
    result = dict(candidate_key=key, legal=True, task_outcomes=task_rows,
                  global_outcomes=global_outcomes, model_targets=model,
                  reward_recomputation=dict(formula='n02-configured-reward/1', weights=weights,
                      component_totals={k: sum(c[k] for c in components) for k in PRIMITIVES},
                      recomputed_step_rewards=rewards, recorded_step_rewards=recorded,
                      recomputed_utility=sum(rewards), recorded_utility=sum(recorded),
                      max_abs_step_error=max(abs(a-b) for a,b in zip(rewards,recorded))),
                  energy_cross_check=dict(event_energy=energy, endpoint_energy_used_delta=endpoint_delta, valid=endpoint_valid),
                  unknown=dict(unresolved_task_ids=[t['id'] for t in task_rows if not t['on_time_valid']],
                      invalid_heads=[h for h,t in model.items() if not (any(t['valid']) if isinstance(t['valid'],list) else t['valid'])],
                      communication_counts=comm_counts, constraint_counts=constraint_counts),
                  trace_sha256=digest(tr))
    targets = {v.get('task_id') for v in action['queue_operations'] + action['dispatches'] if v.get('task_id')}
    meta = dict(parent_id=branch['parent_id'], split=branch['split'], window_start=tr['start_time'],
                window_end=tr['end_time'], event_tape_id=tr['event_tape_id'],
                public_prefix_hash=candidate['public_prefix_hash'], snapshot_hash=candidate['snapshot_hash'],
                initial_public_sha256=digest(obs), private_binding=branch['private_binding'],
                public_task_ids=sorted(t['id'] for t in obs['tasks']), is_noop=action['noop'],
                non_action_task_ids=sorted(t['id'] for t in tasks if t['id'] not in targets),
                non_public_task_ids=sorted(t['id'] for t in tasks if t['id'] not in {v['id'] for v in obs['tasks']}))
    for k in ('simulator_snapshot_sha256', 'event_tape_sha256'):
        require(isinstance(meta['private_binding'].get(k), str) and len(meta['private_binding'][k]) == 64 and all(c in '0123456789abcdef' for c in meta['private_binding'][k]), 'private binding SHA schema')
    return result, meta


def physical_differences(a, b):
    out = []
    for h in PHYSICAL:
        l, r = a['model_targets'][h], b['model_targets'][h]
        if isinstance(l['values'], list):
            require(len(l['values']) == len(r['values']) == len(l['valid']) == len(r['valid']), 'state layout mismatch')
            different = any(lm and rm and not math.isclose(lv,rv,rel_tol=1e-9,abs_tol=1e-9)
                            for lv,rv,lm,rm in zip(l['values'],r['values'],l['valid'],r['valid']))
        else:
            different = l['valid'] and r['valid'] and not math.isclose(l['values'],r['values'],rel_tol=1e-9,abs_tol=1e-9)
        if different:
            out.append(h)
    return out


def any_physical_valid(label):
    return any(any(t['valid']) if isinstance(t['valid'], list) else t['valid']
               for h,t in label['model_targets'].items() if h in PHYSICAL)


def finish_window(window_id, entries):
    first = entries[0][1]
    binding_names = ('parent_id','split','window_start','window_end','event_tape_id',
                     'public_prefix_hash','snapshot_hash','initial_public_sha256','private_binding','public_task_ids')
    require(len(entries) <= 16 and len({v['candidate_key'] for v,m in entries}) == len(entries), 'candidate max/uniqueness')
    require(all(all(m[k] == first[k] for k in binding_names) for v,m in entries), 'common window prefix/snapshot/tape mismatch')
    require(all([t['id'] for t in v['task_outcomes']] == [t['id'] for t in entries[0][0]['task_outcomes']] for v,m in entries), 'branch endpoint task identity mismatch')
    noops = [v for v,m in entries if m['is_noop']]
    require(len(noops) == 1, 'exactly one executed NOOP required')
    noop, labels = noops[0], [v for v,m in entries]
    for label in labels:
        delta = {}
        for h in HEADS:
            target, baseline = label['model_targets'][h], noop['model_targets'][h]
            if isinstance(target['values'], list):
                masks = [a and b for a,b in zip(target['valid'],baseline['valid'])]
                delta[h] = dict(values=[a-b if valid else 0. for a,b,valid in zip(target['values'],baseline['values'],masks)], valid=masks)
            else:
                valid = target['valid'] and baseline['valid']
                delta[h] = dict(value=target['values']-baseline['values'] if valid else 0., valid=valid)
        label['delta_vs_noop'], label['reference_candidate_key'] = delta, noop['candidate_key']
    representatives = []
    for label in labels:
        if any_physical_valid(label) and not any(not physical_differences(label,r) for r in representatives):
            representatives.append(label)
    valid_count = sum(any_physical_valid(v) for v in labels)
    pairs = [dict(left_candidate_key=a['candidate_key'], right_candidate_key=b['candidate_key'], differing_physical_heads=physical_differences(a,b))
             for a,b in itertools.combinations(labels,2) if physical_differences(a,b)]
    return dict(window_id=window_id, **{k:first[k] for k in ('parent_id','split','window_start','window_end','event_tape_id')},
                explicit_noop_candidate_key=noop['candidate_key'], public_task_ids_at_start=first['public_task_ids'],
                all_truth_task_ids_including_non_targets=sorted({t['id'] for v in labels for t in v['task_outcomes']}),
                valid_candidate_count=valid_count, legal_candidate_count=len(labels),
                distinct_legal_outcome_count=len(representatives), valid_window=valid_count >= 2,
                valid_window_has_two_distinct_legal_outcomes=valid_count >= 2 and bool(pairs),
                candidate_labels=labels, outcome_pair_differences=pairs,
                independent_binding=first,
                non_target_audit=dict(non_action_task_rows=sum(len(m['non_action_task_ids']) for v,m in entries),
                                      non_public_task_rows=sum(len(m['non_public_task_ids']) for v,m in entries),
                                      branch_non_action_task_ids={v['candidate_key']:m['non_action_task_ids'] for v,m in entries}))


def compute(args):
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    root = Path(args.input)
    config_path = Path(args.config) if args.config else root / 'EVENT_TRIGGER_CONFIG.json'
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    weights = config['reward']
    require(set(weights) == set(WEIGHTS) and all(number(v) is not None and v >= 0 for v in weights.values()), 'reward config schema')
    catalog_path, branch_path = root/'CANDIDATE_TABLE.jsonl', root/'BRANCH_TRAJECTORIES.jsonl'
    catalog = {}
    for row in rows(catalog_path):
        require(row.get('schema') == 'event-candidate-table-row/1' and type(row.get('rejected')) is bool, 'catalog row schema')
        if row['rejected']:
            continue
        identity = row['window_id'], row['candidate']['candidate_key']
        require(identity not in catalog, 'duplicate accepted candidate table row')
        catalog[identity] = row
    groups, consumed = defaultdict(list), set()
    for branch in rows(branch_path):
        identity = branch['window_id'], branch['candidate_key']
        require(identity in catalog and identity not in consumed, 'branch missing/duplicate catalog binding')
        crow = catalog[identity]
        require(crow['candidate'] == branch['candidate'] and all(crow[k] == branch[k] for k in ('parent_id','split')), 'branch/catalog record mismatch')
        label, meta = compute_branch(branch, weights)
        require(crow['window_start'] == meta['window_start'] and crow['snapshot_hash'] == meta['snapshot_hash'] and crow['event_tape_id'] == meta['event_tape_id'], 'catalog window binding')
        require(meta['window_end'] == min(meta['window_start'] + config['collection']['branch_horizon'], config['scenario']['horizon']), 'planned common endpoint mismatch')
        groups[identity[0]].append((label,meta))
        consumed.add(identity)
    require(consumed == set(catalog), 'accepted catalog branches missing')
    results = [finish_window(w, entries) for w,entries in groups.items()]
    parents = defaultdict(list)
    for w in results:
        parents[(w['parent_id'],w['split'])].append(w['window_start'])
    require(len(parents) == 6 and sum(s == 'train' for p,s in parents) == 4, 'six-parent 4/2 split coverage')
    require(all(sorted(v) == sorted(config['collection']['windows']) for v in parents.values()), 'planned decision-window coverage')
    require(len(results) == args.expected_windows and len(consumed) == args.expected_branches, 'expected window/branch count mismatch')
    train = [r for r in results if r['split'] == 'train']
    qualifying = sum(r['valid_window_has_two_distinct_legal_outcomes'] for r in train)
    require(len(train) == 16, 'training window count')
    fraction = qualifying/len(train)
    computed_path = out/'INDEPENDENT_LABELS.jsonl'
    with computed_path.open('x',encoding='utf-8',newline='\n') as f:
        for row in results:
            f.write(canonical(row).decode('ascii')+'\n')
    receipt = dict(schema='sol-independent-event-trace-computation/1',
                   status='PASS' if fraction >= .8 else 'REPAIR_DIVERSITY_BELOW_80_PERCENT',
                   producer_label_file_opened=False, project_modules_imported=False,
                   computation_basis='raw endpoint tasks/platforms, per-minute raw events/actions/public observations; reported rewards/primitives crosschecked only',
                   scope_limit='No simulator transition re-execution; private snapshot/tape hash claims are checked for consistency, not reconstructed from unavailable private initial state.',
                   input_sha256={str(p.resolve()):filehash(p) for p in (branch_path,catalog_path,config_path)},
                   script_sha256=filehash(__file__), computed_labels_sha256=filehash(computed_path),
                   window_count=len(results), branch_count=len(consumed), train_window_count=len(train),
                   diverse_train_windows=qualifying, training_diversity_fraction=fraction,
                   overall_diverse_windows=sum(r['valid_window_has_two_distinct_legal_outcomes'] for r in results),
                   non_target_audit_rows=sum(r['non_target_audit']['non_action_task_rows'] for r in results),
                   non_public_task_rows=sum(r['non_target_audit']['non_public_task_rows'] for r in results),
                   noop_branch_count=len(results), independent_results_sha256=digest(results))
    write_json(out/'INDEPENDENT_COMPUTATION_RECEIPT.json',receipt)
    print(json.dumps(receipt,sort_keys=True))
    return 0 if receipt['status']=='PASS' else 2


def differences(expected, actual, path='', limit=200):
    """Compare expected independently derived fields, ignoring extra metadata."""
    out = []
    def visit(e,a,p):
        if len(out) >= limit:
            return
        if isinstance(e,dict):
            if not isinstance(a,dict):
                out.append(dict(path=p, expected=e, observed=a));return
            for k,v in e.items():
                if k in ('independent_binding','non_target_audit'):
                    continue
                if k not in a:
                    out.append(dict(path=p+'/'+k, error='missing'))
                else:
                    visit(v,a[k],p+'/'+k)
        elif isinstance(e,list):
            if not isinstance(a,list) or len(e)!=len(a):
                out.append(dict(path=p,error='list shape mismatch'));return
            for i,(l,r) in enumerate(zip(e,a)):
                visit(l,r,p+'/'+str(i))
        elif type(e) is bool or e is None or isinstance(e,str):
            if type(e)!=type(a) or e!=a:
                out.append(dict(path=p,expected=e,observed=a))
        elif number(e) is not None:
            if number(a) is None or not close(e,a):
                out.append(dict(path=p,expected=e,observed=a))
        elif e!=a:
            out.append(dict(path=p,expected=e,observed=a))
    visit(expected,actual,path)
    return out


def indexed_windows(path):
    result={}
    for w in rows(path):
        require(w['window_id'] not in result,'duplicate label window')
        result[w['window_id']]=w
    return result


def compare(args):
    root=Path(args.computed)
    computed_path=root/'INDEPENDENT_LABELS.jsonl'
    receipt=json.loads((root/'INDEPENDENT_COMPUTATION_RECEIPT.json').read_text())
    require(receipt['computed_labels_sha256']==filehash(computed_path), 'independent output hash changed')
    expected, observed=indexed_windows(computed_path), indexed_windows(args.labels)
    require(set(expected)==set(observed),'producer/independent window sets differ')
    errors=[]
    for wid,w in expected.items():
        actual=copy.deepcopy(observed[wid])
        # Ordering is binding to the branch stream; candidate key uniqueness is
        # checked explicitly so a duplicate cannot masquerade as a reorder.
        require(len({r['candidate_key'] for r in actual['candidate_labels']})==len(actual['candidate_labels']), 'duplicate producer candidate label')
        errors.extend(differences(w,actual,'/'+wid,max(1,200-len(errors))))
    mutations=mutation_checks(expected)
    report=dict(schema='sol-independent-event-label-comparison/1',status='PASS' if not errors else 'REPAIR_LABEL_MISMATCH',
                independent_computation_receipt_sha256=filehash(root/'INDEPENDENT_COMPUTATION_RECEIPT.json'),
                independent_labels_sha256=filehash(computed_path),producer_labels_sha256=filehash(args.labels),
                script_sha256=filehash(__file__),window_count=len(expected),
                branch_count=sum(len(w['candidate_labels']) for w in expected.values()),
                mismatches=errors, mismatch_output_capped_at=200,mutation_checks=mutations,
                producer_labels_used_as_truth=False)
    require(all(m['detected'] for m in mutations), 'mutation sensitivity failure')
    path=Path(args.output)
    require(not path.exists(),'comparison output already exists')
    write_json(path,report)
    print(json.dumps(report,sort_keys=True))
    return 0 if not errors and receipt['status']=='PASS' else 2


def mutation_checks(expected):
    """Inject realistic errors into copies, never the raw/producer files."""
    w=next(iter(expected.values()))
    cases=[]
    for name in ('wrong_global_utility','polluted_noop_delta','non_target_task_omission'):
        altered=copy.deepcopy(w)
        labels=altered['candidate_labels']
        if name=='wrong_global_utility':
            labels[0]['global_outcomes']['utility']['value']+=1.
        elif name=='polluted_noop_delta':
            noop=next(v for v in labels if v['candidate_key']==altered['explicit_noop_candidate_key'])
            noop['delta_vs_noop']['utility']['value']=1.
        else:
            non_targets=w['non_target_audit']['branch_non_action_task_ids']
            chosen=next((r,t) for r in labels for t in non_targets[r['candidate_key']])
            row,task_id=chosen
            row['task_outcomes']=[t for t in row['task_outcomes'] if t['id']!=task_id]
        found=differences(w,altered)
        cases.append(dict(name=name,detected=bool(found),witness=found[:2]))
    return cases


def self_test():
    """Raw primitive tests and endpoint perturbations, independent of labels."""
    c=event_components([dict(type='move',energy=2.,environmental_risk=.4),
        dict(type='logical_task_completed'),dict(type='delay_accrued',minutes=2),
        dict(type='communication_tx',message_count=3),dict(type='task_owner_change',task_id='t'),
        dict(type='task_switch',task_id='t')])
    require(close(sum(reward_terms(c,WEIGHTS).values()),.34),'reward formula sensitivity')
    t=dict(id='non-target',kind='delivery',status='pending',progress=.2,deadline=5)
    first=task_result(t,10)
    changed=task_result(dict(t,progress=.8,status='completed',delivered=True,completed_at=4,on_time=True),10)
    require(first['progress']!=changed['progress'] and first['on_time'] is False and changed['on_time'] is True,'non-target endpoint mutation ignored')
    bad=copy.deepcopy(c);bad['energy']+=1
    require(not close(sum(reward_terms(c,WEIGHTS).values()),sum(reward_terms(bad,WEIGHTS).values())), 'energy mutation ignored')
    expected=dict(window_id='test',explicit_noop_candidate_key='noop',
        candidate_labels=[dict(candidate_key='noop',task_outcomes=[first],global_outcomes={'utility':{'value':.34}},delta_vs_noop={'utility':{'value':0.}})],
        non_target_audit={'branch_non_action_task_ids':{'noop':['non-target']}})
    checks=mutation_checks({'test':expected})
    require(all(x['detected'] for x in checks),'comparison mutants not detected')
    print(json.dumps(dict(status='PASS_SELF_TEST',synthetic_only=True,mutation_checks=checks),sort_keys=True))
    return 0


def raw_mutations(args):
    """Actual snapshot mutations test the raw-computation path, not just diff."""
    root=Path(args.input)
    weights=json.loads((root/'EVENT_TRIGGER_CONFIG.json').read_text())['reward']
    # The first executed branch is sufficient for local sensitivity. No input
    # file is changed; the 194 MB stream is not materialized as a whole.
    branch=next(rows(root/'BRANCH_TRAJECTORIES.jsonl'))
    baseline,meta=compute_branch(branch,weights)
    tests=[]
    changed=copy.deepcopy(branch)
    changed['trajectory']['steps'][0]['reward']+=1
    try:
        compute_branch(changed,weights)
        caught=False;witness='not rejected'
    except ValueError as exc:
        caught=True;witness=str(exc)
    tests.append(dict(name='recorded_reward_pollution',detected=caught,witness=witness))
    noop_branch=branch if meta['is_noop'] else next(b for b in rows(root/'BRANCH_TRAJECTORIES.jsonl') if b['candidate']['full_environment_action'].get('noop') is True)
    changed=copy.deepcopy(noop_branch)
    changed['trajectory']['steps'][0]['full_environment_action']['noop']=False
    try:
        compute_branch(changed,weights)
        caught=False;witness='not rejected'
    except ValueError as exc:
        caught=True;witness=str(exc)
    tests.append(dict(name='executed_noop_action_pollution',detected=caught,witness=witness))
    changed=copy.deepcopy(branch)
    truth=changed['trajectory']['raw_truth']['tasks']
    truth=list(truth.values()) if isinstance(truth,dict) else truth
    available=meta['non_public_task_ids'] or meta['non_action_task_ids']
    require(available,'raw sensitivity needs a genuine non-target task')
    task_id=available[0]
    task=next(t for t in truth if t['id']==task_id)
    before=progress(task)
    task['progress']=.123456 if before != .123456 else .654321
    recomputed,_=compute_branch(changed,weights)
    diff=differences(baseline,recomputed)
    tests.append(dict(name='raw_non_target_endpoint_progress_pollution',
                      task_id=task_id, outside_public_start=task_id in meta['non_public_task_ids'],
                      detected=bool(diff),witness=diff[:4]))
    changed=copy.deepcopy(branch)
    changed['candidate']['event_tape_id']='mutated-tape'
    try:
        compute_branch(changed,weights)
        caught=False;witness='not rejected'
    except ValueError as exc:
        caught=True;witness=str(exc)
    tests.append(dict(name='candidate_tape_binding_pollution',detected=caught,witness=witness))
    report=dict(schema='sol-independent-raw-mutation-checks/1',
                status='PASS' if all(t['detected'] for t in tests) else 'REPAIR_MUTATION_NOT_DETECTED',
                input_branch_file_sha256=filehash(root/'BRANCH_TRAJECTORIES.jsonl'),
                script_sha256=filehash(__file__),source_files_modified=False,
                producer_labels_opened=False,checks=tests)
    require(not Path(args.output).exists(),'mutation report already exists')
    write_json(args.output,report)
    print(json.dumps(report,sort_keys=True))
    return 0 if report['status']=='PASS' else 2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='operation',required=True)
    p=subs.add_parser('compute');p.add_argument('--input',required=True);p.add_argument('--config')
    p.add_argument('--output',required=True);p.add_argument('--expected-windows',type=int,default=24)
    p.add_argument('--expected-branches',type=int,default=253)
    p=subs.add_parser('compare');p.add_argument('--computed',required=True)
    p.add_argument('--labels',required=True);p.add_argument('--output',required=True)
    p=subs.add_parser('raw-mutations');p.add_argument('--input',required=True);p.add_argument('--output',required=True)
    subs.add_parser('self-test')
    args=parser.parse_args()
    return (compute(args) if args.operation=='compute' else compare(args) if args.operation=='compare'
            else raw_mutations(args) if args.operation=='raw-mutations' else self_test())


if __name__=='__main__':
    raise SystemExit(main())
