from pathlib import Path
import json,sys,hashlib,copy,math,collections
ROOT=Path(r'[REDACTED_LOCAL_PATH]')
OUT=Path(r'[REDACTED_LOCAL_PATH]')
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'source/package/civilian'))
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')).hexdigest()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
checks=[]
def check(name,condition,detail=None):
 checks.append({'check':name,'pass':bool(condition),'detail':detail})
 if not condition:print('FAIL',name,str(detail)[:400])
def equal(a,b):
 if isinstance(a,bool) or isinstance(b,bool):return a is b
 if isinstance(a,(float,int)) and isinstance(b,(float,int)):return math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-7)
 if isinstance(a,dict) and isinstance(b,dict):return a.keys()==b.keys() and all(equal(v,b[k]) for k,v in a.items())
 if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(equal(v,z) for v,z in zip(a,b))
 return a==b
source_manifest=ROOT/'source/SOURCE_MANIFEST.json';evidence_manifest=ROOT/'EVIDENCE_MANIFEST.json'
check('source_manifest_sha256',sha(source_manifest)=='c21be3cf1889b41584eb1eaf3697407840dd986996d1214436b58501909a5f3b',sha(source_manifest))
check('evidence_manifest_sha256',sha(evidence_manifest)=='f76241bc27c995aa308c383ed70298c780c375e4f0f9e84cdd7c50d74b6130fd',sha(evidence_manifest))
for group,manifest,base in [('source',read(source_manifest),ROOT/'source'),('evidence',read(evidence_manifest),ROOT/'evidence')]:
 errors=[p for p,h in manifest['files'].items() if not (base/p).is_file() or sha(base/p)!=h]
 check(group+'_all_manifest_entries',not errors,{'count':len(manifest['files']),'mismatches':errors})
from chapter1_adapter import generate_public_c1_initial_assignment
from event_environment import EventReliefEnv,generate_reconstruction_candidates,repair_action
from event_trigger import TriggerEngine,identify_affected_scope
from region_scenarios import build_s0_local_repair_fixture,s0_fixture_receipt
from scenario_schema import validate_region_event_scenario
# A: independently derive every coordinate membership and region metadata.
A=next((ROOT/'evidence').rglob('REPLAY_INDEX.json')).parent
variants=['baseline','hidden_task_change','future_event_tape_change','preset_snapshot_queue_change','public_priority_control']
assignments={}; region_summary=[]
for name in variants:
 wrapper=read(A/name/'SCENARIO_WRAPPER.json');base=wrapper['base_scenario'];validate_region_event_scenario(wrapper)
 platforms=base['platforms'];tasks=base['tasks'];regions=base['regions'];edges=[0,33,66,100]
 def rid(pos):
  x,y=pos;assert 0<=x<100 and 0<=y<100
  return 'r'+str(sum(y>=e for e in edges[1:-1]))+str(sum(x>=e for e in edges[1:-1]))
 spatial=[]
 for entity in platforms+tasks:
  actual=rid(entity['position'])
  if entity.get('type')=='helicopter':
   spatial.append(entity.get('region_id') is None and entity.get('region_center') is None and entity.get('support_scope')=='global')
  else:
   rr,cc=int(actual[1]),int(actual[2]);spatial.append(entity['region_id']==actual and entity['region_center']==[(edges[cc]+edges[cc+1])/2,(edges[rr]+edges[rr+1])/2])
 for reg in regions:
  rr,cc=int(reg['region_id'][1]),int(reg['region_id'][2]);neighbors=[f'r{r}{c}' for r in range(3) for c in range(3) if (r,c)!=(rr,cc) and abs(r-rr)<=1 and abs(c-cc)<=1]
  spatial.append(reg['bounds']==[edges[cc],edges[rr],edges[cc+1],edges[rr+1]] and reg['neighbors']==neighbors)
 matrix=[[sum(p.get('type')=='uav' and p.get('region_id')==f'r{r}{c}' for p in platforms) for c in range(3)] for r in range(3)]
 centers={((edges[c]+edges[c+1])/2,(edges[r]+edges[r+1])/2) for r in range(3) for c in range(3) if r!=c}
 counts=all(sum(t['region_id']==f'r{r}{c}' and t['known_initial'] for t in tasks)==4 and sum(t['region_id']==f'r{r}{c}' and not t['known_initial'] for t in tasks)==1 for r in range(3) for c in range(3))
 ids=[x['id'] for x in platforms+tasks]+[x['region_id'] for x in regions]
 check('A_contract_'+name,all(spatial) and matrix==[[2,3,3],[3,2,3],[3,3,2]] and len(platforms)==30 and len(tasks)==45 and len(set(ids))==len(ids) and counts and {tuple(p['position']) for p in platforms if p['type']=='helicopter'}==centers and base['map']['rows']==base['map']['cols']==100 and base['map']['grid_cells']==10000,{'platforms':len(platforms),'tasks':len(tasks),'hidden_coordinates_checked':sum(not t['known_initial'] for t in tasks),'uav_matrix':matrix})
 assignment=generate_public_c1_initial_assignment(base,seed=8201,schedule_backlog=True);assignments[name]=assignment
 check('A_actual_backlog_replay_'+name,assignment['public_input']==read(A/name/'C1_PUBLIC_INPUT.json') and assignment['queues']==read(A/name/'C1_QUEUES.json'),{'public_input_digest':digest(assignment['public_input']),'queue_digest':digest(assignment['queues']),'algorithm':assignment['receipt'].get('queue_planning_algorithm'),'assigned':sum(map(len,assignment['queues'].values()))})
 check('A_no_hidden_tasks_in_input_'+name,set(t['id'] for t in assignment['public_input']['single_step_input']['known_tasks'])==set(t['id'] for t in tasks if t['known_initial']))
for name in variants[1:4]:check('A_noninterference_'+name,assignments[name]['public_input']==assignments['baseline']['public_input'] and assignments[name]['queues']==assignments['baseline']['queues'])
check('A_public_priority_positive_control',assignments['public_priority_control']['public_input']!=assignments['baseline']['public_input'] and digest(assignments['public_priority_control']['public_input'])!=digest(assignments['baseline']['public_input']),{'queues_changed':assignments['public_priority_control']['queues']!=assignments['baseline']['queues'],'interpretation':'input sensitivity demonstrated; queue reordering is not required'})
# B: independently replay current fixture; do not import any producer label oracle.
B=next((ROOT/'evidence').rglob('WINDOW.json')).parent;wrapper=read(B/'SCENARIO_WRAPPER.json');w=read(B/'WINDOW.json');labels=read(B/'PRODUCER_LABELS_FOR_REVIEW.json');catalog=read(B/'CANDIDATE_CATALOG_PRODUCER.json');selected=read(B/'SELECTED_ACTION_CHAIN.json')
check('B_fixture_regeneration',build_s0_local_repair_fixture()==wrapper)
source_before=read(B/'SOURCE_HASHES_BEFORE.json');source_after=read(B/'SOURCE_HASHES_AFTER.json');check('B_producer_source_hashes_unchanged_and_frozen',source_before==source_after and all(sha(ROOT/'source'/rel)==h for rel,h in source_before.items()),{'count':len(source_before)})
receipt=s0_fixture_receipt(wrapper)
check('B_disclosed_diagnostic_only',receipt['production_9_region_evidence'] is False and receipt['timeline_disclosure']['event_time']==4 and receipt['timeline_disclosure']['event_kind']=='priority_change',receipt)
c1=generate_public_c1_initial_assignment(wrapper['base_scenario'],seed=8201,schedule_backlog=True)
check('B_C1_public_generated_not_preset',c1['queues']==wrapper['queue_plan']==wrapper['base_scenario']['chapter1_snapshot']['queues'] and c1['public_input']==read(B/'C1_PUBLIC_INPUT.json') and c1['receipt']==read(B/'C1_RECEIPT.json'))
env=EventReliefEnv(wrapper);obs=env.reset();check('B_initial_public_observation',obs==read(B/'INITIAL_PUBLIC_OBSERVATION.json'))
config=read(B/'TRIGGER_CONFIG_AND_THRESHOLD.json');tr=TriggerEngine(config['trigger_config'],config['threshold_manifest']);hist=[copy.deepcopy(obs)]
noop={'action_type':'reconstruct','scope':'NOOP','noop':True,'queue_operations':[],'dispatches':[]}
while env.time<4:
 prev=obs;obs,*_=env.step(copy.deepcopy(noop));hist.append(copy.deepcopy(obs));detect=tr.detect(prev,obs,history=hist[-4:])
decision=tr.decide(detect,4,mode='event');scope=identify_affected_scope(obs,detect)
private_payload={'time':env.time,'event_tape_id':env.event_tape_id}
for key,owner,attr,default in [('base_tasks',env._base,'_tasks',{}),('base_platforms',env._base,'_platforms',{}),('base_queues',env._base,'_queues',{}),('task_specs',env,'_task_specs',{}),('queues',env,'_queues',{}),('environment',env,'_environment',[]),('communication',env,'_communication',[]),('pending_communications',env,'_pending_communications',[]),('reported_platforms',env,'_reported_platforms',{}),('reported_tasks',env,'_reported_tasks',{}),('reported_depots',env,'_reported_depots',{}),('reported_progress_counts',env,'_reported_progress_counts',{}),('reported_energy_used',env,'_reported_energy_used',{}),('extension_events',env,'_extension_events',[])]:private_payload[key]=getattr(owner,attr,default)
private_payload['event_ids_applied']=sorted(str(x) for x in env._event_ids_applied)
check('B_private_snapshot_hash_from_replayed_state',digest(private_payload)==w['private_binding']['simulator_snapshot_sha256'],digest(private_payload))
check('B_public_snapshot_hash_from_raw_observation',digest({k:v for k,v in obs.items() if k!='provenance'})==obs['provenance']['snapshot_hash'])
check('B_public_prefix_hash_from_full_replayed_history',digest([{k:v for k,v in x.items() if k!='provenance'} for x in hist])==obs['provenance']['public_prefix_hash'])
check('B_snapshot_and_prefix_replay',obs==read(B/'PUBLIC_OBSERVATION.json')==w['public_observation'] and hist[-4:]==read(B/'PUBLIC_HISTORY.json'))
check('B_link1_local_eligible',scope==read(B/'AFFECTED_SCOPE.json') and scope['local_eligible'])
check('B_link2_triggered',detect==read(B/'TRIGGER_DETECTION.json') and decision==read(B/'TRIGGER_DECISION.json') and decision['triggered'])
regenerated=generate_reconstruction_candidates(obs,scope,env=env)
check('B_catalog_exact_replay',regenerated==catalog)
locals_=[c for c in catalog if c['legal'] and not c['full_environment_action']['noop'] and c['scope']=='LOCAL_REPAIR']
check('B_link3_two_legal_local_candidates',len(locals_)>=2,{'count':len(locals_)})
rule=read(B/'SELECTION_RULE.json')

# R5 plan fidelity and no-outcome-selection audit. Producer helpers are isolated
# from their module: no oracle/environment module or producer import is executed.
import ast,difflib
R3=ROOT.parent/'s0-frozen-20261019-r3'
PREVIOUS=ROOT.parent/'s0-frozen-20261019-r4'
old_manifest=read(PREVIOUS/'source/SOURCE_MANIFEST.json');new_manifest=read(source_manifest)
changed=[rel for rel,h in new_manifest['files'].items() if old_manifest['files'].get(rel)!=h]
check('R5_only_intended_manifest_sources_changed',set(changed)=={'tools/run_v3_mechanism.py','package/tests/test_v3_mechanism_evidence.py'},changed)
check('R5_new_release_identity',read(ROOT/'FREEZE_RECEIPT.json')['release']=='n02-v3-s0-cc048803057b43c49b94449117476de8' and read(ROOT/'source/REQUEST_CANDIDATE.json')['release']=='n02-v3-s0-cc048803057b43c49b94449117476de8')
diff=''
for rel in changed:
 diff+=''.join(difflib.unified_diff((PREVIOUS/'source'/rel).read_text(encoding='utf-8').splitlines(True),(ROOT/'source'/rel).read_text(encoding='utf-8').splitlines(True),fromfile='R4/'+rel,tofile='R5/'+rel))
(OUT/'SOURCE_DIFF_R4_R5.patch').write_text(diff,encoding='utf-8')
toolpath=ROOT/'source/tools/run_v3_mechanism.py';tree=ast.parse(toolpath.read_text());nodes={n.name:n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
helper_names=['_owner_queues','_project_owner_queues','_selection_plan'];helper_nodes=[nodes[n] for n in helper_names]
loaded=set();attributes=set();calls=[]
for node in helper_nodes:
 for n in ast.walk(node):
  if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load):loaded.add(n.id)
  if isinstance(n,ast.Attribute):attributes.add(n.attr)
  if isinstance(n,ast.Call):calls.append(ast.unparse(n.func))
forbidden={'env','snapshot_env','branch_env','raw_truth','event_tape','producer_rows','branches','recompute_consequence_labels','open','Path','eval','exec','getattr','globals','locals','__import__'}
check('R5_projection_helpers_no_private_or_outcome_access',not(loaded&forbidden) and not any(x.startswith('_') for x in attributes) and all(not isinstance(n,(ast.Import,ast.ImportFrom,ast.Global,ast.Nonlocal)) for node in helper_nodes for n in ast.walk(node)),{'loaded_names':sorted(loaded),'attributes':sorted(attributes),'calls':calls})
check('R5_projection_helper_signatures',[a.arg for a in nodes['_project_owner_queues'].args.args]==['observation','action'] and [a.arg for a in nodes['_selection_plan'].args.args]==['observation','candidates'])
namespace={'copy':copy,'Any':object}
exec(compile(ast.Module(body=helper_nodes,type_ignores=[]),str(toolpath)+':isolated_public_helpers','exec'),namespace)
plan=read(B/'SELECTION_PLAN.json');request=read(B/'REQUEST.json');baseline={'owners':{t['id']:t.get('assignee') for t in obs['tasks']},'queues':copy.deepcopy(obs['queues'])}
def independent_public_projection(c):
 # Interpret the disclosed planning convention, not persisted branch outcomes.
 state=copy.deepcopy(baseline)
 for op in c['full_environment_action']['queue_operations']:
  kind=op['op'];tid=op['task_id']
  if kind=='swap':
   other=op['other_task_id'];state['queues']={pid:[other if x==tid else tid if x==other else x for x in q] for pid,q in state['queues'].items()};state['owners'][tid],state['owners'][other]=state['owners'][other],state['owners'][tid]
  elif kind in ('transfer','insert'):
   state['queues']={pid:[x for x in q if x!=tid] for pid,q in state['queues'].items()};dst=op['to_platform'];q=state['queues'].setdefault(dst,[]);anchor=op.get('before_task_id') if kind=='insert' else None;q.insert(q.index(anchor) if anchor in q else len(q),tid);state['owners'][tid]=dst
  else:return None
 for d in c['full_environment_action']['dispatches']:
  tid=d['task_id'];pid=d['platform_id'];state['queues']={owner:[x for x in q if x!=tid or owner==pid] for owner,q in state['queues'].items()};q=state['queues'].setdefault(pid,[])
  if tid not in q:q.append(tid)
  state['owners'][tid]=pid
 return state
projections=[]
for c in catalog:
 projected=independent_public_projection(c);row=dict(candidate_key=c['candidate_key'],legal=c['legal'] is True,scope=c['full_environment_action']['scope'],projection_supported=projected is not None,projection_reason=None if projected is not None else 'unsupported_queue_operation',projected_owner_queue_state=projected,effective_planned_mutation=projected is not None and projected!=baseline);projections.append(row)
check('R5_independent_public_projection_reproduces_plan',projections==plan['candidate_projections'])
producer_selected,producer_projections=namespace['_selection_plan'](copy.deepcopy(obs),copy.deepcopy(catalog))
check('R5_isolated_helper_replay_without_private_inputs',producer_projections==projections and producer_selected['candidate_key']==plan['selected_candidate_key'])
expected_selected=next(c for c,row in zip(catalog,projections) if row['legal'] and row['scope']=='LOCAL_REPAIR' and not c['full_environment_action']['noop'] and row['effective_planned_mutation'])
check('B_link4_rule_policy_requests_local',rule['selected_candidate_key']==expected_selected['candidate_key']==selected['candidate_key_producer']==plan['selected_candidate_key'] and rule['selected_action']==expected_selected['full_environment_action'] and rule['selected_action']['scope']=='LOCAL_REPAIR',{'policy':'public projection + first effective catalog local; deterministic diagnostic selector, not trained actor','selected_key':rule['selected_candidate_key']})
check('R5_plan_request_hash_binding',request['selection_plan']['sha256']==rule['selection_plan_sha256']==sha(B/'SELECTION_PLAN.json') and request['selection_plan']['selected_candidate_key']==plan['selected_candidate_key'] and request['wrapper_sha256']==sha(B/'SCENARIO_WRAPPER.json') and plan['catalog_order_keys']==[c['candidate_key'] for c in catalog])
export=nodes['export_branches'];branchloop=next(n for n in ast.walk(export) if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='producer_candidate')
def writes_of(name):
 return sorted(n.lineno for n in ast.walk(export) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_write_json' and n.args and any(isinstance(v,ast.Constant) and v.value==name for v in ast.walk(n.args[0])))
planline=writes_of('SELECTION_PLAN.json')[0];requestlines=writes_of('REQUEST.json');ruleline=writes_of('SELECTION_RULE.json')[0]
check('R5_plan_and_hash_request_written_before_all_branches',planline<max(requestlines)<ruleline<branchloop.lineno and not any(isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store) and n.id=='selection_candidate' for n in ast.walk(branchloop)),{'plan_write_line':planline,'bound_request_write_line':max(requestlines),'rule_write_line':ruleline,'first_branch_loop_line':branchloop.lineno,'assurance':'Static execution ordering and frozen bindings; not an external trusted timestamp'})
oldcatalog=read(R3/'evidence/input-01/CANDIDATE_CATALOG_PRODUCER.json');oldwindow=read(R3/'evidence/input-01/WINDOW.json')
check('R5_original_three_candidates_and_raw_branches_preserved',catalog==oldcatalog and len(w['branches'])==3 and [b['candidate_key'] for b in w['branches']]==[b['candidate_key'] for b in oldwindow['branches']] and all(b['trajectory']==z['trajectory'] for b,z in zip(w['branches'],oldwindow['branches'])),{'catalog_keys':plan['catalog_order_keys']})
check('R5_duplicate_dispatch_retained_and_marked_false',plan['candidate_projections'][1]['effective_planned_mutation'] is False and plan['candidate_projections'][1]['projected_owner_queue_state']==baseline)
planned_selected=next(r for r in projections if r['candidate_key']==plan['selected_candidate_key'])['projected_owner_queue_state'];executed_selected=selected['action_audit'][0]['owner_queue_after']
check('R5_selected_projected_owners_match_actual',planned_selected['owners']==executed_selected['owners'])
queue_projection_mismatches={pid:{'projected':q,'actual':executed_selected['queues'].get(pid)} for pid,q in planned_selected['queues'].items() if q!=executed_selected['queues'].get(pid)}
check('R5_selected_complete_queue_projection_matches_execution',not queue_projection_mismatches,queue_projection_mismatches)

check('B_link5_selected_repair_preserves_action_scope',all(a['requested_action']==a['repaired_action']==a['executed_action'] and a['repair_receipt']['postrepair_legal'] for a in selected['action_audit']))
first=selected['action_audit'][0]
check('B_link6_selected_real_queue_or_owner_change',first['owner_queue_before']!=first['owner_queue_after'],first['owner_queue_diff'])
# Read original event slices; compute labels without producer functions.
def task_outcome(t,end):
 status=str(t.get('status','')).lower();deadline=t.get('deadline');completed=t.get('completed_at');complete=bool(t.get('delivered')) or status in {'completed','delivered'};failed=status in {'failed','expired'} or bool(t.get('failed')) or bool(t.get('failure_reason'))
 progress=next((min(1.,max(0.,float(t[k]))) for k in ('progress','service_progress','completion_fraction') if isinstance(t.get(k),(int,float))),1. if complete else None)
 on=t.get('on_time')
 if not isinstance(on,bool):
  on=(completed<=deadline) if complete and completed is not None and deadline is not None else False if t.get('deadline_missed') or (deadline is not None and end>=deadline and not complete) or failed else None
 delay=max(0.,completed-deadline) if completed is not None and deadline is not None else float(max(0,end-int(deadline))) if on is False and deadline is not None and end>=deadline else None
 return dict(id=t['id'],kind=t.get('kind'),status=status or None,progress=progress,progress_valid=progress is not None,complete=complete,complete_valid=bool(status) or 'delivered' in t,on_time=on,on_time_valid=on is not None,delay_minutes=delay,delay_valid=delay is not None,failed=failed,failure_valid=bool(status) or 'failed' in t or 'failure_reason' in t,deadline=deadline)
metrics=[];recomputations=[];producer={x['candidate_key']:x for x in labels['candidate_labels']};weights=w['reward_weights'];all_audits=read(B/'BRANCH_EVIDENCE.json')
check('B_selected_chain_exact_branch_evidence',selected==next(x for x in all_audits if x['candidate_key_producer']==rule['selected_candidate_key']))
for branch in w['branches']:
 key=branch['candidate_key'];c=branch['candidate'];trace=branch['trajectory'];steps=trace['steps'];p=producer[key];end=trace['end_time'];events=[e for s in steps for e in s['raw_events']]
 expected_key='event-action-'+digest([obs['provenance']['public_prefix_hash'],obs['provenance']['snapshot_hash'],digest(c['full_environment_action'])])[:24]
 check('B_original_candidate_binding_'+key,key==c['candidate_key']==expected_key and c['public_prefix_hash']==obs['provenance']['public_prefix_hash'] and c['snapshot_hash']==obs['provenance']['snapshot_hash'] and branch['private_binding']==w['private_binding'] and branch['private_binding']['event_tape_sha256']==digest(wrapper['event_tape']) and trace['event_tape_id']==w['event_tape_id']==wrapper['event_tape_id'])
 # Replay each complete trajectory and independently check recorded owner/queue audit.
 replay=copy.deepcopy(env);aud=next(a for a in all_audits if a['candidate_key_producer']==key)
 check('B_branch_catalog_binding_'+key,aud['candidate']==c and aud['trajectory']==trace)
 for i,s in enumerate(steps):
  action=c['full_environment_action'] if i==0 else noop;before=replay.public_observation();repaired,rr=repair_action(replay,copy.deepcopy(action));after,reward,terminated,truncated,info=replay.step(copy.deepcopy(repaired));actual=replay.export_trajectory()['steps'][-1];aa=aud['action_audit'][i]
  check('B_step_replay_'+key+'_'+str(i),s['full_environment_action']==repaired==aa['executed_action'] and rr==aa['repair_receipt'] and equal(s['reward'],reward) and s['raw_events']==info['raw_events'] and s['public_observation']==before and s['next_public_observation']==after and aa['owner_queue_before']=={'owners':{t['id']:t.get('assignee') for t in before['tasks']},'queues':before['queues']} and aa['owner_queue_after']=={'owners':{t['id']:t.get('assignee') for t in after['tasks']},'queues':after['queues']},None)
 check('B_endpoint_replay_'+key,replay.export_trajectory()['raw_truth']==trace['raw_truth'] and events==trace['raw_events'])
 taskrows=[task_outcome(t,end) for t in sorted(trace['raw_truth']['tasks'],key=lambda x:x['id'])];check('B_all_task_labels_including_nontarget_'+key,equal(taskrows,p['task_outcomes']),{'task_count':len(taskrows),'non_target_count':sum(t['id'] not in c['task_ids'] for t in taskrows)})
 comps=[];rewards=[]
 for s in steps:
  co=dict(completion=0.,delay=0.,energy=0.,risk=0.,communication=0.,switch=0.,reconstruction=0.,reconstruction_size=0.,global_scope=0.);switch=set();owners=set();reorders=0
  for e in s['raw_events']:
   typ=e['type']
   if typ=='logical_task_completed':co['completion']+=1
   if typ=='delay_accrued':co['delay']+=e['minutes']
   if typ in {'move','service'}:co['energy']+=e['energy'];co['risk']+=e.get('environmental_risk',0.) if typ=='move' else 0.
   if typ in {'task_failed','platform_failure'}:co['risk']+=1
   if typ=='communication_tx':co['communication']+=e['message_count']
   if typ=='task_switch':switch.add(e['task_id'])
   if typ=='task_owner_change':owners.add(e['task_id'])
   if typ in {'queue_reorder','queue_reordered'}:reorders+=1
  co['switch']=float(len(switch));co['reconstruction_size']=float(len(owners)+reorders);co['reconstruction']=float(co['reconstruction_size']>0);co['global_scope']=float(s['full_environment_action']['scope']=='GLOBAL_REPLAN' and not s['full_environment_action']['noop'])
  reward=co['completion']*weights['completion']-sum(co[k]*weights['reconstruction_scale' if k=='reconstruction_size' else k] for k in co if k!='completion')
  check('B_reward_from_raw_'+key+'_'+str(s['time']),equal(reward,s['reward']))
  rewards.append(reward);comps.append(co)
 energy=sum(co['energy'] for co in comps);endpoint=sum(t['energy_used'] for t in trace['raw_truth']['platforms'])-sum(t['energy_used'] for t in obs['platforms']);totals={k:sum(co[k] for co in comps) for k in comps[0]};utility=sum(rewards)
 progress=sum(t['progress'] for t in taskrows)/len(taskrows);ont=[t for t in taskrows if t['on_time_valid']];dly=[t for t in taskrows if t['delay_valid']]
 globals_={'progress_rate':{'value':progress,'valid':True},'on_time_rate':{'value':sum(t['on_time'] for t in ont)/len(ont) if ont else 0.,'valid':len(ont)==len(taskrows) and bool(taskrows)},'mean_delay_minutes':{'value':sum(t['delay_minutes'] for t in dly)/len(dly) if dly else 0.,'valid':bool(dly) and len(dly)==sum(t['deadline'] is not None for t in taskrows)},'energy_used':{'value':energy,'valid':equal(energy,endpoint)},'failure_rate':{'value':sum(t['failed'] for t in taskrows)/len(taskrows),'valid':True},'utility':{'value':utility,'valid':True}}
 check('B_global_labels_energy_utility_unknown_'+key,all(equal(v,p['global_outcomes'][k]) for k,v in globals_.items()) and equal(energy,endpoint) and equal(totals,p['reward_recomputation']['component_totals']) and equal(rewards,p['reward_recomputation']['recomputed_step_rewards']),globals_)
 unresolved=[t['id'] for t in taskrows if not t['on_time_valid']];check('B_unknown_ids_'+key,unresolved==p['unknown']['unresolved_task_ids'],unresolved)
 # Remaining communication/constraint/next-state heads and model scalar fields.
 risks=[]
 for e in events:
  typ=e['type'].lower()
  if any(token in typ for token in ('comm','message','link','packet')):
   if isinstance(e.get('risk'),(int,float)):risks.append(min(1,max(0,e['risk'])))
   elif isinstance(e.get('quality'),(int,float)):risks.append(1-min(1,max(0,e['quality'])))
   elif e.get('connected') is False or e.get('dropped') is True or any(t in typ for t in ('drop','down','disconnect')):risks.append(1.)
   elif isinstance(e.get('packet_loss',e.get('loss_rate')),(int,float)):risks.append(min(1,max(0,e.get('packet_loss',e.get('loss_rate')))))
 for s in steps:
  for obkey in ('public_observation','next_public_observation'):
   for link in s[obkey].get('communication',[]):
    quality=link.get('quality',link.get('link_quality'));loss=link.get('packet_loss',link.get('loss_rate'))
    if quality is not None or loss is not None:risks.append(max(1-min(1,max(0,quality)) if quality is not None else 0.,min(1,max(0,loss)) if loss is not None else 0.))
 constraint=sum(1 if rec.get('postrepair_legal',rec.get('legal')) is False else len(rec.get('constraint_violations',rec.get('violations',[]))) for s in steps for rec in s['operation_receipts'])+sum('constraint' in e['type'] and any(k in e['type'] for k in ('violation','rejected','infeasible')) for e in events)
 globals_['communication_risk']={'value':sum(risks)/len(risks) if risks else 0.,'valid':True};globals_['constraint_violation_count']={'value':float(constraint),'valid':True}
 check('B_communication_constraint_labels_'+key,all(equal(v,p['global_outcomes'][k]) for k,v in globals_.items()))
 next_values=[];next_valid=[]
 for raw,t in zip(sorted(trace['raw_truth']['tasks'],key=lambda x:x['id']),taskrows):
  vals=[t['progress'],float(t['complete']) if t['complete_valid'] else None,float(t['failed']) if t['failure_valid'] else None,float(raw['on_time']) if isinstance(raw.get('on_time'),bool) else None]
  for value in vals:next_values.append(value if value is not None else 0.);next_valid.append(value is not None)
 for pl in sorted(trace['raw_truth']['platforms'],key=lambda x:x['id']):
  for value in [*pl['position'],pl['energy'],float(pl['failed'])]:next_values.append(value);next_valid.append(True)
 model={'next_state':{'values':next_values,'valid':next_valid}}
 for head,g in [('progress','progress_rate'),('delay','mean_delay_minutes'),('energy','energy_used'),('failure','failure_rate'),('communication_risk','communication_risk'),('constraint_risk','constraint_violation_count'),('utility','utility')]:model[head]={'values':globals_[g]['value'],'valid':globals_[g]['valid']}
 check('B_all_model_heads_'+key,equal(model,p['model_targets']))
 metrics.append(dict(candidate_key=key,action_type=c['action_type'],energy=energy,utility=utility,reassignment_events=sum(e['type']=='task_owner_change' for e in events),switch_events=sum(e['type']=='task_switch' for e in events),global_outcomes=globals_,unknown_task_ids=unresolved,physical_path_digest=digest([{k:e[k] for k in e if k not in {'task_id'}} for e in events if e['type']=='move']),task_outcomes=taskrows))
 recomputations.append({'candidate_key':key,'model_targets':model,'global_outcomes':globals_,'task_outcomes':taskrows,'reward_components':totals,'recomputed_step_rewards':rewards})
# Compare deltas independently, preserving invalid masks.
base_metrics=recomputations[0]
for rr in recomputations:
 p=producer[rr['candidate_key']]
 for head,target in rr['model_targets'].items():
  base=base_metrics['model_targets'][head];value,valid=target['values'],target['valid']
  if isinstance(value,list):delta={'values':[v-base['values'][i] if valid[i] and base['valid'][i] else 0. for i,v in enumerate(value)],'valid':[v and base['valid'][i] for i,v in enumerate(valid)]}
  else:delta={'value':value-base['values'] if valid and base['valid'] else 0.,'valid':valid and base['valid']}
  check('B_delta_vs_NOOP_'+rr['candidate_key']+'_'+head,equal(delta,p['delta_vs_noop'][head]))
physical_pairs=[]
for i,l in enumerate(metrics):
 for r in metrics[i+1:]:
  energy_diff=not equal(l['energy'],r['energy']);path_diff=l['physical_path_digest']!=r['physical_path_digest'];utility_diff=not equal(l['utility'],r['utility'])
  physical_pairs.append({'left':l['candidate_key'],'right':r['candidate_key'],'energy_diff':energy_diff,'physical_path_diff_excluding_task_ids':path_diff,'utility_diff':utility_diff})
check('B_real_global_physical_difference_not_task_permutation',any(x['energy_diff'] and x['physical_path_diff_excluding_task_ids'] for x in physical_pairs),physical_pairs)
check('B_link7_independent_raw_recomputation',all(c['pass'] for c in checks if c['check'].startswith(('B_all_task_labels','B_global_labels','B_communication_constraint','B_all_model_heads','B_delta_vs_NOOP','B_unknown'))))
# R5 additional public-only probes independently target the R4 non-head boundary.
probe_obs={'tasks':[{'id':'A','assignee':'p1'},{'id':'B','assignee':'p1'},{'id':'C','assignee':'p2'},{'id':'D','assignee':'p2'}],'queues':{'p1':['A','B'],'p2':['C','D']}}
for tid in ['A','B']:
 candidate={'candidate_key':'probe-same-owner-'+tid,'legal':True,'full_environment_action':{'action_type':'reconstruct','scope':'LOCAL_REPAIR','noop':False,'queue_operations':[],'dispatches':[{'task_id':tid,'platform_id':'p1'}]}}
 before=copy.deepcopy(probe_obs);chosen,rows=namespace['_selection_plan'](probe_obs,[candidate]);expected={'owners':{'A':'p1','B':'p1','C':'p2','D':'p2'},'queues':{'p1':['A','B'],'p2':['C','D']}}
 check('R5_independent_same_owner_'+('head' if tid=='A' else 'nonhead')+'_dispatch_not_mutation',chosen is None and rows[0]['effective_planned_mutation'] is False and rows[0]['projected_owner_queue_state']==expected and probe_obs==before,rows)
transfer_probe={'candidate_key':'probe-transfer-B','legal':True,'full_environment_action':{'action_type':'reconstruct','scope':'LOCAL_REPAIR','noop':False,'queue_operations':[{'op':'transfer','task_id':'B','from_platform':'p1','to_platform':'p2'}],'dispatches':[{'task_id':'B','platform_id':'p2'}]}}
chosen,rows=namespace['_selection_plan'](copy.deepcopy(probe_obs),[transfer_probe]);expected={'owners':{'A':'p1','B':'p2','C':'p2','D':'p2'},'queues':{'p1':['A'],'p2':['C','D','B']}}
check('R5_independent_transfer_then_dispatch_appends_no_head_reorder',chosen==transfer_probe and rows[0]['projected_owner_queue_state']==expected and rows[0]['effective_planned_mutation'],rows)
for projected in projections:
 actual=next(a for a in all_audits if a['candidate_key_producer']==projected['candidate_key'])['action_audit'][0]['owner_queue_after']
 check('R5_all_candidate_full_projection_equals_raw_first_step_'+projected['candidate_key'],projected['projected_owner_queue_state']==actual)
selected_metrics=next(m for m in metrics if m['candidate_key']==plan['selected_candidate_key']);noop_metrics=next(m for m in metrics if m['action_type']=='NOOP')
check('R5_selected_real_global_physical_effect',selected_metrics['reassignment_events']>0 and selected_metrics['switch_events']>0 and not equal(selected_metrics['energy'],noop_metrics['energy']) and selected_metrics['physical_path_digest']!=noop_metrics['physical_path_digest'],{'owner_changes':selected_metrics['reassignment_events'],'switches':selected_metrics['switch_events'],'energy_delta':selected_metrics['energy']-noop_metrics['energy'],'utility_delta':selected_metrics['utility']-noop_metrics['utility']})
raw_transfer=next(e for e in selected['action_audit'][0]['raw_events'] if e['type']=='queue_operation')
check('R5_raw_transfer_receipt_agrees_with_replayed_actual_queue',raw_transfer['after_queues']==executed_selected['queues'],{'recorded_at_time':raw_transfer['time'],'uav2_queue':raw_transfer['after_queues']['n02-uav-2']})
check('R5_extra_frozen_scenario_copy_matches_execution',read(ROOT/'evidence/input-01/SCENARIO_WRAPPER.json')==wrapper)
log=next((ROOT/'evidence').rglob('pytest.log'));logtext=log.read_text(encoding='utf-8')
check('R5_final_success_log_retained','112 passed, 3 skipped, 2 warnings in 23.77s' in logtext and logtext.count('PytestCacheWarning')==2,{'sha256':sha(log),'result':'112 passed, 3 skipped, 2 warnings in 23.77s','warning_summary':'Two cache write permission warnings; no test failures'})
for revision,expected_hash in [('r3','b8af5b116325c5894eb96f050a0becff5607677c943a127e436359f1d6e336a7'),('r4','e57d5cace40579f01727b180b68e12e2b93e0ff6a95186bc52b5c21f1ccba111')]:
 prior_review=OUT.parent/(revision+'_audit')/'reviews'/('S0_'+revision.upper()+'_REVIEW.json');check(revision.upper()+'_REPAIR_review_unchanged',sha(prior_review)==expected_hash and read(prior_review)['verdict']=='REPAIR')
check('frozen_bytes_unchanged_after_review',all(sha(ROOT/'source'/p)==h for p,h in read(source_manifest)['files'].items()) and all(sha(ROOT/'evidence'/p)==h for p,h in read(evidence_manifest)['files'].items()))
failures=[c for c in checks if not c['pass']];a_pass=all(c['pass'] for c in checks if c['check'].startswith('A_'));b_pass=all(c['pass'] for c in checks if c['check'].startswith(('B_','R5_')));execution_chain_pass=all(c['pass'] for c in checks if c['check'].startswith(('B_link1','B_link2','B_link3','B_link4','B_link5','B_link6','B_link7')))
result={'schema':'n02-independent-s0-r5-review/1','reviewer':'GPT-6.1 Sol High read-only audit; same model family independent review context, not external certification','assurance':'Provisional S0-only review. Selection source ordering and frozen hashes verified; no external trusted execution timestamp or external certification.','scope':'A contract/C1 + B S0 repaired diagnostic including R5 public selection-plan fidelity; no training','release':read(ROOT/'FREEZE_RECEIPT.json')['release'],'source_manifest_sha256':sha(source_manifest),'evidence_manifest_sha256':sha(evidence_manifest),'verdict':'PASS' if not failures else 'REPAIR','node_A':'PASS' if a_pass else 'REPAIR','node_B':'PASS' if b_pass else 'REPAIR','original_seven_execution_links':'PASS' if execution_chain_pass else 'FAIL','S0_chain_status':'ALL_SEVEN_EXECUTION_LINKS_AND_PUBLIC_SELECTION_PLAN_FIDELITY_PASS' if not failures else 'REPAIR_REQUIRED','S1':'NOT_RUN','S1_entry':'ALLOWED_CPU_MECHANISM_ONLY' if a_pass and b_pass and not failures else 'BLOCKED','S2':'BLOCKED_NOT_RUN','S3':'BLOCKED_NOT_RUN','spatial_2x2_causal':'NOT_RUN: priority-change diagnostic only; no patch-on/off pair','authorization':'A/B independently PASS permits S1 CPU mechanism evidence generation only. C/S1 acceptance, 2x2 causal verification, S2 GPU and S3 world-model/PPO remain unapproved and require their own raw evidence and independent gates.' if not failures else 'S1 blocked pending repair. S2/S3 blocked.','checks':checks,'branch_metrics':metrics,'physical_pairs':physical_pairs,'source_diff_from_R4':changed,'selection_plan':{'path':str(B/'SELECTION_PLAN.json'),'sha256':sha(B/'SELECTION_PLAN.json'),'request_bound_sha256':request['selection_plan']['sha256'],'selected_candidate_key':plan['selected_candidate_key'],'independent_projections':projections,'queue_projection_mismatches':queue_projection_mismatches,'selected_complete_projected_state':planned_selected,'selected_complete_executed_state':executed_selected},'findings':failures,'limitations':[{'kind':'scope','text':'PASS is limited to A contract/public C1 and B S0 6-platform/12-task isolated priority-change diagnostic. It does not pass C/S1, spatial 2x2 causality, 30-platform event execution, learned actor ranking, GPU, world-model or PPO training.'},{'kind':'candidate_coverage','text':'Frozen catalog retains 2 nominal legal non-NOOP locals, one of which is a repeated same-owner dispatch correctly marked no mutation; one alternative executes a real owner/queue change. S1 must provide its own repairable event witnesses and candidate evidence.'},{'kind':'unknowns','text':'Tasks09-12 unresolved at t34: on-time/delay unknown masks preserved. Aggregate partial on-time value 1.0 is invalid for all-task claims.'},{'kind':'test_log','text':'R5 frozen final log verifies 112 passed, 3 skipped, 2 cache permission warnings. Historical R3 initial collection failure stdout remains unavailable and was not reconstructed; R3/R4 REPAIR reports unchanged.'},{'kind':'assurance','text':'Static frozen runner writes plan, hash-bound REQUEST and selection rule before all branch executions. Persisted artifacts provide no external trusted historical timestamp.'},{'kind':'utility','text':'Selected action changes global physical energy and utility but has lower utility than NOOP in this diagnostic; no performance superiority claim.'}]}
evidence_paths=[B/'SELECTION_PLAN.json',B/'REQUEST.json',B/'SELECTION_RULE.json',B/'SELECTED_ACTION_CHAIN.json',B/'WINDOW.json',B/'BRANCH_EVIDENCE.json',B/'PRODUCER_LABELS_FOR_REVIEW.json',A/'REPLAY_INDEX.json',log]
result['evidence_hashes']={p.relative_to(ROOT/'evidence').as_posix():sha(p) for p in evidence_paths};result['review_script_sha256']=sha(Path(__file__));result['source_diff_sha256']=sha(OUT/'SOURCE_DIFF_R4_R5.patch')
(OUT/'reviews/S0_R5_REVIEW.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(OUT/'reviews/INDEPENDENT_RAW_RECOMPUTATION.json').write_text(json.dumps(recomputations,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
lines=['# S0 R5 independent review','','**Decision: '+result['verdict']+'. A '+result['node_A']+'; B '+result['node_B']+'. S1 CPU mechanism evidence may begin. S1 acceptance, 2x2 causality, S2 and S3 remain NOT_RUN / blocked as applicable.**','','Same-family independent-context Sol High audit, provisional for S0 only; not external certification. No reviewed source/evidence edits or training. Independent labels never import or call the producer oracle. R3/R4 remain REPAIR.','','| Requirement | Result | Independent verification |','|---|---|---|','| Immutable source/evidence | PASS | 93 source and 43 evidence entries hash verified before/after; new release identity |','| R4→R5 intended code diff | PASS | Only public projection tool and mechanism-evidence test among manifest source entries |','| A: 30/45/9 contract | PASS | Five wrappers: hidden coordinates, half-open membership, metadata/topology, fixed UAV matrix, global helicopters, map, IDs |','| A: actual backlog C1 boundary | PASS | All five public-input/queue replays exact; hidden tasks, future tape and preset snapshot queues do not interfere |','| A: public priority positive control | PASS with scope limit | Public input/hash change; queue stays equal, so no output-reordering claim |','| B1–B5 | PASS | Eligibility, threshold-triggered priority event, legal local alternatives, preplanned public selector requests local, repair preserves action |','| B6 selected actual mutation | PASS | task05 UAV1→UAV2, full owner/queue change matches plan |','| B7 independent consequences | PASS | All 3×30 steps replayed; all 12 task labels, 8 model heads, NOOP deltas, raw rewards and energy endpoint checks agree with producer |','| Public-only selection | PASS | Static helper dependency audit and isolated replay require public observation + full actions only |','| Selection before outcomes | PASS within static assurance | Plan/hash-bound REQUEST/rule write before first branch loop; no result-based reassignment |','| Full public plan vs execution | PASS | All three candidate projected owner/queue states equal raw first-step states; selected UAV2 queue [06,05] |','| Same-owner dispatch boundary | PASS | Frozen duplicate false; independent head and non-head multi-task public probes false with queue preserved |','| Transfer boundary | PASS | Independent transfer+dispatch probe appends after existing destination tasks |','| Candidate identity retention | PASS | Original three keys and raw trajectories preserved |','| C / S1 execution acceptance | NOT_RUN | A/B PASS permits generation of new S1 CPU evidence only |','| 2×2 patch causality | NOT_RUN | This S0 priority fixture has no spatial patch pair |','| S2 / S3 | BLOCKED / NOT_RUN | Require later independent C/S1 and training-stage gates |','','The R4 projection mismatch is resolved: selected plan and raw/replayed queue both contain `[n02-task-06,n02-task-05]`. The repeated same-owner candidate remains in the original catalog, marked `effective_planned_mutation=false`. The selected key is `'+plan['selected_candidate_key']+'`.','','| Branch | Energy | Utility | Owner changes | Switches |','|---|---:|---:|---:|---:|']
for m in metrics:lines.append(f"| {m['candidate_key']} | {m['energy']:.12f} | {m['utility']:.12f} | {m['reassignment_events']} | {m['switch_events']} |")
lines+=['','Selected versus NOOP energy delta '+str(selected_metrics['energy']-noop_metrics['energy'])+'; utility delta '+str(selected_metrics['utility']-noop_metrics['utility'])+'. Movement paths differ after removing task IDs. This is a real global physical consequence, not an improved-utility claim or evidence for spatial-patch causality.','','Tasks09–12 remain unresolved at t34; on-time/delay masks stay invalid. Partial on-time value 1.0 is not a fully valid all-task metric. Frozen final log: 112 passed, 3 skipped, 2 pytest cache-permission warnings in 23.77s. Historical R3 initial failure stdout remains lost and was not reconstructed. R3/R4 reviews are unchanged.','','## Hashes','','- Source manifest: `'+sha(source_manifest)+'`','- Evidence manifest: `'+sha(evidence_manifest)+'`','- Review script: `'+sha(Path(__file__))+'`','- R4→R5 source diff: `'+sha(OUT/'SOURCE_DIFF_R4_R5.patch')+'`','','| Evidence | SHA256 |','|---|---|']
for name,h in result['evidence_hashes'].items():lines.append(f'| {name} | `{h}` |')
lines+=['','Full per-item checks: S0_R5_REVIEW.json. Raw independent values: INDEPENDENT_RAW_RECOMPUTATION.json. Script and final stdout retained beside reviews/.']
(OUT/'reviews/S0_R5_MATRIX.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'verdict':result['verdict'],'node_A':result['node_A'],'node_B':result['node_B'],'checks':len(checks),'failures':failures,'selected_key':plan['selected_candidate_key'],'selected_full_plan_equals_execution':planned_selected==executed_selected,'selected_energy_delta':selected_metrics['energy']-noop_metrics['energy'],'S1_entry':result['S1_entry']},ensure_ascii=False,indent=2))
