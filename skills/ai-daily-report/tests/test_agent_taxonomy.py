"""Current taxonomy behavior, mixed history, and discovery coverage (synthetic data)."""
from copy import deepcopy
from datetime import date, timedelta
import json

from bs4 import BeautifulSoup
import pytest

from test_agent_editorial import bundle, action_for
from agent_editorial import (validate_agent_discovery, validate_agent_weekly, validate_batch_version,
                            validate_candidate_contract, validate_decision_refs, validate_report_schema)
from discovery import build_discovery_manifest, iter_named_sources, load_whitelist
from editorial import (validate_daily_artifacts, validate_major_event_consistency,
                       validate_market_signals_consistency, validate_sparse_day_restraint,
                       validate_weekly_references, validate_weekly_item_refs)
from evidence import save_response, read_response, receipt_from_output, review_coverage
from render_html import render
from render_markdown import render_markdown
from report_runner import run_daily_finalize


@pytest.fixture
def current_bundle(bundle):
    report, ledger, root = bundle
    report['version'] = '1.3'
    ledger['version'] = '1.2'
    sections = report['sections']
    del sections['coding_agents']
    sections['general_agents']['title'] = '通用 Agent'
    general = sections['general_agents']['items'][0]
    general.update(task_domain='跨领域', capability_layer='execution')
    ledger['items'][0].update(task_domain='跨领域', capability_layer='execution')
    vertical = deepcopy(general)
    vertical.update(product='Fixture PM', headline='合成样例：需求交接更新', task_domain='产品管理',
                    capability_layer='platform', use_case='产品经理审查需求并交接任务',
                    what_changed='合成需求交接能力', dedup_key='fixture-pm-handoff')
    sections['vertical_agents'] = {'title':'垂直领域 Agent','items':[vertical],'empty_message':'本窗口未确认新增垂直领域 Agent 产品变化'}
    candidate = deepcopy(ledger['items'][0])
    candidate.update(candidate_id='fixture-pm', headline=vertical['headline'], proposed_section='vertical_agents',
                     task_domain='产品管理', capability_layer='platform', section_reason='面向产品经理的需求交接流程')
    ledger['items'].append(candidate)
    manifest = build_discovery_manifest(report['date'], report['window'], load_whitelist())
    day = date.fromisoformat(report['date'])
    vertical_source = next(s for s in manifest['required_sources'] if s['name']=='Vertical Agent Search Queries')
    groups = {'General Agent Search Queries':manifest['general_agent_search_queries'],
              vertical_source['name']:vertical_source['fetch_chain'][0]['queries']}
    cache = root/'cache'/report['date']
    for name, queries in groups.items():
        attempts = []
        for index, query in enumerate(queries):
            target = query.replace('{date}', day.isoformat()).replace('{yesterday}', (day-timedelta(days=1)).isoformat())
            raw = 'SYNTHETIC query response: '+target
            artifact = save_response(cache, raw, collected_at=report['generated_at'], batch_id=f'taxonomy-{name}-{index}',query_ids=[target],limitations=[])
            output = read_response(cache, artifact, start=0, end=len(raw))
            receipt = receipt_from_output(cache, artifact, returned_output=json.dumps(output, ensure_ascii=False))
            attempts.append({'layer_index':0,'layer_type':'websearch_broad','target':target,'result':'empty',
                'evidence_artifact':artifact,'review':{'status':'complete','receipts':[receipt],'coverage':review_coverage(raw,[receipt])}})
        report['fetch_status']['source_details'][name] = {'final_layer_index':0,'final_layer_type':'websearch_broad',
            'via_broad_search':True,'confidence_policy':'force_medium_plus_flag','attempts':attempts}
    return report, ledger, root, manifest


def test_current_daily_passes_all_gates(current_bundle):
    report, ledger, root, manifest = current_bundle
    assert validate_batch_version(report,manifest)==[]
    assert validate_daily_artifacts(report,ledger,load_whitelist(),root,None,manifest)==[]


@pytest.mark.parametrize('section',['general_agents','vertical_agents'])
@pytest.mark.parametrize('field',['task_domain','capability_layer','use_case','what_changed','availability','usage_mode','impact','evidence_limits'])
def test_both_agent_sections_require_complete_task_cards(current_bundle,section,field):
    report,_,_,_=current_bundle
    del report['sections'][section]['items'][0][field]
    assert validate_report_schema(report)


@pytest.mark.parametrize('field',['task_domain','capability_layer'])
def test_ledger_and_report_classification_must_agree(current_bundle,field):
    report,ledger,_,_=current_bundle
    ledger['items'][-1][field]='different'
    assert any(field+' mismatch' in e for e in validate_candidate_contract(report,ledger))


def test_new_report_cannot_retain_retired_section(current_bundle):
    report,_,_,_=current_bundle
    report['sections']['coding_agents']={}
    assert validate_report_schema(report)


def test_new_batch_cannot_downgrade_report_or_ledger(current_bundle):
    report,ledger,_,manifest=current_bundle
    ledger['version']='1.1'
    assert any('requires candidate ledger' in e for e in validate_candidate_contract(report,ledger))
    report['version']='1.2'
    assert validate_batch_version(report,manifest)


def test_vertical_references_resolve_across_consumers(current_bundle,sample_daily_report):
    report,ledger,root,manifest=current_bundle
    item=report['sections']['vertical_agents']['items'][0]
    report['reading_guide']=[{'text':'合成产品管理变化','ref':'vertical_agents[0]'}]
    experiment=deepcopy(sample_daily_report['sections']['experiments_this_week']['items'][0])
    experiment['related_item_refs']=['vertical_agents[0]']
    report['sections']['experiments_this_week']['items']=[experiment]
    report['sections']['action_items']['items']=[action_for(report,'vertical_agents',item,'monitor')]
    assert validate_daily_artifacts(report,ledger,load_whitelist(),root,None,manifest)==[]
    experiment['related_item_refs']=['coding_agents[0]']
    assert validate_decision_refs(report)
    experiment['related_item_refs']=['vertical_agents[1]']
    assert validate_decision_refs(report)


def test_vertical_guards_do_not_get_skipped(current_bundle):
    report,ledger,root,manifest=current_bundle
    item=report['sections']['vertical_agents']['items'][0]
    ledger['items'][-1]['action_eligibility']='monitor'
    report['sections']['action_items']['items']=[action_for(report,'vertical_agents',item,'adopt')]
    assert any('exceeds eligibility' in e for e in validate_candidate_contract(report,ledger))
    report['sections']['action_items']['items']*=2
    assert validate_sparse_day_restraint(report)
    item['major_event']=True
    assert validate_major_event_consistency(report)
    item['what_changed']='API pricing $2/Mtok'
    assert validate_market_signals_consistency(report,'daily')
    item['published_at']=ledger['items'][-1]['published_at']='1900-01-01T10:00:00+08:00'
    assert any('vertical_agents[0].published_at' in e for e in validate_daily_artifacts(report,ledger,load_whitelist(),root,None,manifest))


def test_vertical_event_can_be_opened_and_followed(current_bundle):
    from test_tracking import _write_tracking
    from tracking import active_tracking_events, load_tracking_events, validate_tracking_refs

    report, _, root, _ = current_bundle
    day = report['date']
    path = _write_tracking(root, 'vertical-launch', day, day)
    event = json.loads(path.read_text())
    event['origin']['section'] = 'vertical_agents'
    path.write_text(json.dumps(event), encoding='utf-8')
    assert load_tracking_events(root)[1] == []
    assert active_tracking_events(root, day) == [event]
    report['sections']['vertical_agents']['items'][0]['tracking_ref'] = 'vertical-launch'
    assert validate_tracking_refs(report, root) == []
    report['sections']['vertical_agents']['items'][0]['tracking_ref'] = 'missing-launch'
    assert any('missing-launch' in error for error in validate_tracking_refs(report, root))


def test_missing_one_vertical_query_blocks_but_recorded_failure_does_not(current_bundle):
    report,_,_,manifest=current_bundle
    attempts=report['fetch_status']['source_details']['Vertical Agent Search Queries']['attempts']
    removed=attempts.pop()
    assert any(removed['target'] in e for e in validate_agent_discovery(report,manifest))
    attempts.append({**removed,'result':'error','reason':'synthetic unavailable service'})
    assert validate_agent_discovery(report,manifest)==[]


def test_new_sources_are_in_manifest_and_initial_coverage(sample_whitelist):
    from discovery import initial_fetch_status
    names={s['name'] for s in iter_named_sources(sample_whitelist)}
    wanted={'Devin Release Notes','ChatPRD Product Releases','Fin Product Updates','Kortix','Multica Changelog','ChatGPT Release Notes','Vertical Agent Search Queries'}
    assert wanted <= names
    assert wanted <= initial_fetch_status(sample_whitelist)['source_details'].keys()
    assert len(names)==len(list(iter_named_sources(sample_whitelist)))


def test_current_daily_dry_run_renders_without_sender(current_bundle,monkeypatch):
    report,ledger,root,manifest=current_bundle
    cache=root/'cache'/report['date']
    for name,value in [('report.json',report),('candidate_ledger.json',ledger),('discovery_manifest.json',manifest)]:
        (cache/name).write_text(json.dumps(value,ensure_ascii=False))
    env=root/'fixture.env'
    env.write_text('GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=synthetic\nREPORT_RECIPIENTS=target@example.com\n')
    monkeypatch.setattr('report_runner._send_mail',lambda *a,**kw:pytest.fail('must not send'))
    code,message=run_daily_finalize(root,report['date'],True,env)
    assert code==0,message
    soup=BeautifulSoup((cache/'report.html').read_text(),'html.parser')
    headings=[h.get_text() for h in soup.select('h2')]
    assert headings[1:3]==['二、通用 Agent','三、垂直领域 Agent']
    assert soup.select_one('#vertical_agents-0')
    assert not soup.select_one('#coding')
    assert '产品管理' in soup.get_text() and '平台与协作' in soup.get_text()
    md=render_markdown(cache/'report.html',cache/'report.md').read_text()
    assert '垂直领域 Agent' in md and '工作任务' in md and '证据边界' in md


def make_weekly(report,sample_weekly_report):
    weekly=deepcopy(sample_weekly_report);weekly['version']='1.2'
    sections=weekly['sections'];del sections['coding_agents']
    sections['frontier_models']['vendor_groups']=[]
    for name in ['action_items','pattern_observations','experiments_this_week','practice_digest','methodology_radar']:
        sections[name]['items']=[]
    for key,value in sections['market_signals'].items():
        if isinstance(value,list):sections['market_signals'][key]=[]
    for name,title in [('general_agents','通用 Agent'),('vertical_agents','垂直领域 Agent')]:
        product=report['sections'][name]['items'][0]
        ref=action_for(report,name,product,'monitor')['references'][0]
        item={key:product[key] for key in ['product','task_domain','capability_layer','use_case']}
        item.update(weekly_changes=product['what_changed'],implication=product['impact'],references=[ref])
        sections[name]={'title':title,'items':[item],'trend_judgment':'','implication':'','empty_message':'无新增'}
    sections['policy_risk']={'title':'政策与风险观察','items':[],'empty_message':'无新增'}
    return weekly


def test_mixed_weekly_preserves_original_references(current_bundle,sample_weekly_report):
    report,ledger,root,_=current_bundle
    weekly=make_weekly(report,sample_weekly_report)
    for day in weekly['source_days']['daily_reports_used']:
        cache=root/'cache'/day;cache.mkdir(parents=True,exist_ok=True)
        daily=deepcopy(report);daily['date']=day
        if day!=report['date']:
            daily['version']='1.2'
            item=daily['sections'].pop('vertical_agents')['items'][0]
            # Historical engineering bucket; new weekly editor reclassifies by task.
            daily['sections']['coding_agents']={'title':'Coding Agent 专项','items':[item]}
        (cache/'report.json').write_text(json.dumps(daily,ensure_ascii=False))
    previous=weekly['source_days']['daily_reports_used'][0]
    ref=weekly['sections']['vertical_agents']['items'][0]['references'][0]
    ref.update(date=previous,section='coding_agents',origin_classification_note='历史编码栏中的产品管理流程，按交付任务重归类')
    assert validate_report_schema(weekly)==[]
    assert validate_agent_weekly(weekly,root)==[]
    assert validate_weekly_references(weekly,root)==[]
    assert validate_weekly_item_refs(weekly)==[]
    before=(root/'cache'/previous/'report.json').read_bytes()
    path=root/'weekly.json';path.write_text(json.dumps(weekly,ensure_ascii=False))
    html=render(path,root/'weekly.html').read_text()
    assert '三、通用 Agent' in html and '四、垂直领域 Agent' in html
    assert 'id="vertical_agents-0"' in html
    assert (root/'cache'/previous/'report.json').read_bytes()==before
    ref.pop('origin_classification_note')
    assert any('cross-section' in e for e in validate_agent_weekly(weekly,root))
    ref['section']='vertical_agents'
    assert any('cannot resolve' in e for e in validate_weekly_references(weekly,root))


@pytest.mark.parametrize('daily_version',['1.2','1.3'])
def test_current_weekly_dry_run_accepts_both_evidence_generations(current_bundle,sample_weekly_report,sample_daily_report,monkeypatch,daily_version):
    from report_runner import run_weekly_finalize
    report,ledger,root,_=current_bundle
    weekly=make_weekly(report,sample_weekly_report)
    if daily_version=='1.2':
        report['version']='1.2';ledger['version']='1.1'
        report['sections'].pop('vertical_agents')
        report['sections']['coding_agents']=deepcopy(sample_daily_report['sections']['coding_agents'])
        report['sections']['coding_agents']['items']=[]
        ledger['items']=ledger['items'][:1]
        weekly['sections']['vertical_agents']['items']=[]
    weekly['source_days']['recall_ack']=True  # Synthetic empty model week, not a real quiet-week assertion.
    item=report['sections']['general_agents']['items'][0]
    weekly['sections']['action_items']['items']=[action_for(report,'general_agents',item,'experiment')]
    for day in weekly['source_days']['daily_reports_used']:
        cache=root/'cache'/day;cache.mkdir(parents=True,exist_ok=True)
        daily=deepcopy(report);daily['date']=day
        (cache/'report.json').write_text(json.dumps(daily,ensure_ascii=False))
    cache=root/'cache'/report['date']
    (cache/'candidate_ledger.json').write_text(json.dumps(ledger,ensure_ascii=False))
    weekly_cache=root/'cache'/'weekly'/weekly['week_end'];weekly_cache.mkdir(parents=True,exist_ok=True)
    (weekly_cache/'report.json').write_text(json.dumps(weekly,ensure_ascii=False))
    (weekly_cache/'input_days.json').write_text(json.dumps({'expected_report_version':'1.2'}))
    env=root/'fixture.env';env.write_text('GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=synthetic\nREPORT_RECIPIENTS=target@example.com\n')
    monkeypatch.setattr('report_runner._send_mail',lambda *a,**kw:pytest.fail('must not send'))
    code,message=run_weekly_finalize(root,weekly['week_end'],True,env)
    assert code==0,message
    html=(weekly_cache/'report.html').read_text()
    assert '三、通用 Agent' in html and '四、垂直领域 Agent' in html
    ledger['items'][0]['action_eligibility']='monitor'
    (cache/'candidate_ledger.json').write_text(json.dumps(ledger,ensure_ascii=False))
    code,message=run_weekly_finalize(root,weekly['week_end'],True,env)
    assert code==1 and 'exceeds eligibility' in message


def test_empty_agent_sections_and_escaped_fields_render(current_bundle):
    report,_,root,_=current_bundle
    item=report['sections']['vertical_agents']['items'][0]
    item['task_domain']='<script>alert(1)</script>'
    path=root/'escape.json';path.write_text(json.dumps(report,ensure_ascii=False))
    html=render(path,root/'escape.html').read_text()
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;' in html
    for section in ['general_agents','vertical_agents']:
        report['sections'][section]['items']=[]
        report['sections'][section]['empty_message']=section+' 合成覆盖缺口说明'
    path.write_text(json.dumps(report,ensure_ascii=False))
    html=render(path,root/'empty.html').read_text()
    assert 'general_agents 合成覆盖缺口说明' in html
    assert 'vertical_agents 合成覆盖缺口说明' in html
    assert '深度观察：' not in html
