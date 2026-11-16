"""Explicit nested candidates and guards; unsupported outputs fail before work."""
import contextlib
import copy
import io
import ipaddress
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import yaml

from isp_geofeed_generator.adapters import SOURCES, TARGETS
from isp_geofeed_generator.cli import main, load_config
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.contracts import SourceAdapter, TargetAdapter
from isp_geofeed_generator.extensions import load_extensions
from isp_geofeed_generator.feed import build_records, change_guard, digest, parse_feed, render_csv
from isp_geofeed_generator.inputs import combine_inputs
from isp_geofeed_generator.locations import COARSE_FIELDS
from isp_geofeed_generator.overlap import LONGEST_PREFIX, REJECT, require_target_policy
from isp_geofeed_generator.records import encode_records, parse_records
from isp_geofeed_generator.relocation import effective_change_guard
from bogon_fixture import files


def row(prefix, city='A', **extra):
    return {'prefix':prefix,'location':{'country':'US','region':'US-IL','city':city,**extra}}


def wire(rows):return render_csv(rows,overlap_policy=LONGEST_PREFIX)


def inventory(records):
    return {'pools':[{'id':str(i+1),'ip_range':r['prefix'],'subnet':{'subnet':r['prefix']},'site_id':str(i+1)}
                     for i,r in enumerate(records)],
            'sites':[{'id':str(i+1),'addresses':[{'id':'1','country':r['location']['country'],
                      'subdivision':r['location']['region'],'city':r['location']['city']}]} for i,r in enumerate(records)]}


PARENT=row('11.22.33.0/24');CHILD=row('11.22.33.0/25','B')


class NestedCoreTests(unittest.TestCase):
    def test_default_csv_builder_and_json_refuse_and_explicit_mode_accepts(self):
        rows=[PARENT,CHILD];snapshot=inventory(rows)
        config={'allowed_prefixes':['11.22.0.0/16']}
        for call in (lambda:build_records(snapshot,config),lambda:render_csv(rows),lambda:encode_records(rows)):
            with self.assertRaises(GeofeedError):call()
        records,_=build_records(snapshot,{**config,'overlap_policy':LONGEST_PREFIX})
        self.assertEqual(records,rows)
        self.assertEqual(len(parse_feed(wire(records),overlap_policy=LONGEST_PREFIX)),2)
        rich=encode_records(rows,overlap_policy=LONGEST_PREFIX)
        self.assertEqual(parse_records(rich,overlap_policy=LONGEST_PREFIX)[0],rows)
        with self.assertRaises(GeofeedError):parse_records(rich)
        with self.assertRaises(GeofeedError):parse_feed(wire(rows))

    def test_duplicate_is_always_refused_even_when_locations_match(self):
        for other in (PARENT,{**PARENT,'location':CHILD['location']}):
            rows=[PARENT,other]
            for call in (lambda:build_records(inventory(rows),{'allowed_prefixes':['11.22.0.0/16'],'overlap_policy':LONGEST_PREFIX}),
                         lambda:wire(rows),lambda:encode_records(rows,overlap_policy=LONGEST_PREFIX)):
                with self.assertRaises(GeofeedError):call()

    def test_design_vectors_enforce_exact_union_withdrawal_and_fallback_moves(self):
        vectors=json.loads((Path(__file__).parent/'fixtures/nested-prefix-design.json').read_text())
        for vector in vectors:
            old,new=([row(*r) for r in vector[name]] for name in ('before','after'))
            expected=vector['expected']
            counts=change_guard(wire(old),wire(new),1,max_relocated_fraction=1,overlap_policy=LONGEST_PREFIX)[4]
            self.assertEqual({k:getattr(counts,k) for k in expected},expected)
            if expected['relocated']:
                with self.assertRaisesRegex(GeofeedError,'location changes'):
                    change_guard(wire(old),wire(new),1,max_relocated_fraction=0,overlap_policy=LONGEST_PREFIX)
            if expected['removed']:
                with self.assertRaisesRegex(GeofeedError,'feed removal'):
                    change_guard(wire(old),wire(new),0,max_relocated_fraction=1,overlap_policy=LONGEST_PREFIX)
        change_guard(wire([PARENT,CHILD]),wire([CHILD]),0.5,max_relocated_fraction=0,overlap_policy=LONGEST_PREFIX)
        change_guard(wire([PARENT,CHILD]),wire([PARENT]),0,max_relocated_fraction=0.5,overlap_policy=LONGEST_PREFIX)

    def test_approval_of_moves_cannot_bypass_withdrawal(self):
        with self.assertRaisesRegex(GeofeedError,'feed removal'):
            change_guard(wire([PARENT,CHILD]),wire([CHILD]),0.49,max_relocated_fraction=1,overlap_policy=LONGEST_PREFIX)

    def test_ipv6_one_address_above_half_cannot_round_away(self):
        net=ipaddress.ip_network('2001:4860::/32');low,high=list(net.subnets())
        old=[row(str(net))];half=old+[row(str(low),'B')]
        change_guard(wire(old),wire(half),max_relocated_fraction=0.5,overlap_policy=LONGEST_PREFIX)
        with self.assertRaisesRegex(GeofeedError,'IPv6 location changes'):
            change_guard(wire(old),wire(half+[row(f'{high.network_address}/128','B')]),
                         max_relocated_fraction=0.5,overlap_policy=LONGEST_PREFIX)

    def test_address_families_still_have_separate_guards(self):
        old=[PARENT,row('2001:4860::/32')];new=[row(PARENT['prefix'],'B'),old[1]]
        with self.assertRaisesRegex(GeofeedError,'IPv4 location changes'):
            change_guard(wire(old),wire(new),overlap_policy=LONGEST_PREFIX)

    def test_coordinate_changes_use_whole_requested_profile(self):
        fields=COARSE_FIELDS|{'latitude','longitude'}
        old=[row(PARENT['prefix'],latitude=42,longitude=-88)]
        new=old+[row(CHILD['prefix'],latitude=43,longitude=-88)]
        with self.assertRaisesRegex(GeofeedError,'location changes'):effective_change_guard(old,new,fields=fields)
        self.assertEqual(effective_change_guard(old,new,1,0.5,fields=fields)[4].relocated,128)
        incomplete=copy.deepcopy(new);del incomplete[1]['location']['longitude']
        with self.assertRaises(GeofeedError):encode_records(incomplete,overlap_policy=LONGEST_PREFIX)

    def test_invalid_shadowed_parent_location_and_ownership_are_not_hidden(self):
        rows=[PARENT,CHILD,row('11.22.33.128/25','B')];snapshot=inventory(rows)
        snapshot['sites'][0]['addresses'][0]['country']='XX'
        config={'allowed_prefixes':['11.22.0.0/16'],'overlap_policy':LONGEST_PREFIX}
        with self.assertRaises(GeofeedError):build_records(snapshot,config)
        with self.assertRaisesRegex(GeofeedError,'outside allowed_prefixes'):
            build_records(inventory(rows),{**config,'allowed_prefixes':[CHILD['prefix']]})
        bad=[row('8.0.0.0/6'),row('8.0.0.0/8')]
        with self.assertRaisesRegex(GeofeedError,'nonpublic or special'):
            build_records(inventory(bad),{**config,'allowed_prefixes':['8.0.0.0/6']})

    def test_combined_inputs_nest_only_when_explicit_and_duplicates_name_both_inputs(self):
        results={name:{'snapshot':inventory([value]),'source_type':'sonar' if name=='customers' else 'netbox'}
                 for name,value in [('customers',PARENT),('infrastructure',CHILD)]}
        config={'inputs':{name:{} for name in results},'allowed_prefixes':['11.22.0.0/16']}
        with self.assertRaisesRegex(GeofeedError,'customers/1 and infrastructure/1'):combine_inputs(results,config,COARSE_FIELDS)
        config['overlap_policy']=LONGEST_PREFIX
        self.assertEqual(combine_inputs(results,config,COARSE_FIELDS)[0],[PARENT,CHILD])
        results['infrastructure']['snapshot']=inventory([PARENT])
        with self.assertRaisesRegex(GeofeedError,'customers/1 and infrastructure/1'):combine_inputs(results,config,COARSE_FIELDS)

    def test_unknown_policy_and_nested_record_budget_fail_closed(self):
        for value in (None,True,False,'prefer_source','LONGEST_PREFIX'):
            with self.assertRaisesRegex(GeofeedError,'overlap_policy'):parse_feed(wire([PARENT]),overlap_policy=value)
        with patch('isp_geofeed_generator.overlap.MAX_RECORDS',1),self.assertRaises(GeofeedError):wire([PARENT,CHILD])


class NestedContractTests(unittest.TestCase):
    def test_v1_cannot_claim_nested_capability_and_v2_requires_explicit_discovery(self):
        factory=lambda s,c:None
        nested=TargetAdapter(factory,api_version=2,overlap_policies=frozenset({REJECT,LONGEST_PREFIX}))
        point=Mock();point.name='nested_output';point.load.return_value=nested
        with patch('isp_geofeed_generator.extensions.metadata.entry_points',return_value=[point]) as entries:
            _,targets=load_extensions({'targets_v2':['nested_output']},SOURCES,TARGETS)
            entries.assert_called_once_with(group='isp_geofeed_generator.targets.v2')
        require_target_policy(targets['nested_output'],LONGEST_PREFIX)
        for adapter,settings in [(nested,{'targets':['nested_output']}),
                                 (TargetAdapter(factory,overlap_policies=frozenset({LONGEST_PREFIX})),{'targets':['nested_output']}),
                                 (TargetAdapter(factory,api_version=2,overlap_policies=frozenset({'unknown'})),{'targets_v2':['nested_output']})]:
            point.load.return_value=adapter
            with patch('isp_geofeed_generator.extensions.metadata.entry_points',return_value=[point]),self.assertRaises(GeofeedError):
                load_extensions(settings,SOURCES,TARGETS)
        for name,adapter in TARGETS.items():
            require_target_policy(adapter,REJECT)
            if name=='wordpress':
                with self.assertRaisesRegex(GeofeedError,'does not support'):require_target_policy(adapter,LONGEST_PREFIX)
            else:require_target_policy(adapter,LONGEST_PREFIX)

    def test_cli_candidate_and_contract_forwarding_and_refusal_before_source_or_credentials(self):
        source=Mock();source.snapshot.return_value=inventory([PARENT,CHILD]);source.for_publication.side_effect=lambda value:value
        source_factory=Mock(return_value=source)
        output=Mock();output.publish.return_value={'changed':True};output_factory=Mock(return_value=output)
        adapter=TargetAdapter(output_factory,initial=False,api_version=2,overlap_policies=frozenset({REJECT,LONGEST_PREFIX}))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'config.yaml';candidate=root/'candidate.csv'
            config={'source':{'type':'contract_source'},'allowed_prefixes':['11.22.0.0/16'],
                    'overlap_policy':LONGEST_PREFIX,'bogons':files(root),'state_dir':str(root/'state'),
                    'publish':{'type':'contract_output'}}
            def run(command,*args):
                path.write_text(yaml.safe_dump(config));err=io.StringIO()
                with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(err):result=main([command,'--config',str(path),*args])
                return result,err.getvalue()
            with patch.dict(SOURCES,{'contract_source':SourceAdapter(source_factory,initial=False)}),patch.dict(TARGETS,{'contract_output':adapter}):
                self.assertEqual(run('generate','--output',str(candidate))[0],0)
                self.assertEqual(len(parse_feed(candidate.read_bytes(),overlap_policy=LONGEST_PREFIX)),2)
                self.assertEqual(run('publish')[0],0)
                self.assertEqual(output.publish.call_args.kwargs['overlap_policy'],LONGEST_PREFIX)
                output_factory.reset_mock();source_factory.reset_mock()
                for kind in ('wordpress',):
                    config['publish']={'type':kind,'path':str(root/'public.csv')} if kind!='wordpress' else {'type':kind}
                    result,error=run('publish','--approve-location-changes',digest(candidate.read_bytes()))
                    self.assertEqual(result,1);self.assertIn('does not support',error)
                source_factory.assert_not_called();output_factory.assert_not_called()
                self.assertFalse((root/'public.csv').exists());self.assertFalse((root/'state/before.csv').exists())

    def test_fullbogon_guard_checks_broad_raw_parent_even_under_override_and_approval(self):
        source=Mock();source.snapshot.return_value=inventory([row('14.0.0.0/8'),row('14.1.0.0/16','B')])
        source.for_publication.side_effect=lambda value:value
        output_factory=Mock()
        adapter=TargetAdapter(output_factory,initial=False,api_version=2,overlap_policies=frozenset({REJECT,LONGEST_PREFIX}))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'config.yaml'
            config={'source':{'type':'contract_source'},'allowed_prefixes':['14.0.0.0/8'],'overlap_policy':LONGEST_PREFIX,
                    'bogons':files(root),'state_dir':str(root/'state'),'publish':{'type':'contract_output'}}
            path.write_text(yaml.safe_dump(config));error=io.StringIO()
            candidate=wire([row('14.0.0.0/8'),row('14.1.0.0/16','B')])
            with patch.dict(SOURCES,{'contract_source':SourceAdapter(lambda s,c:source,initial=False)}),patch.dict(TARGETS,{'contract_output':adapter}),contextlib.redirect_stderr(error):
                self.assertEqual(main(['publish','--config',str(path),'--approve-location-changes',digest(candidate)]),1)
            self.assertIn('bogon',error.getvalue().lower());output_factory.assert_not_called()
            self.assertFalse((root/'state/before.csv').exists())
