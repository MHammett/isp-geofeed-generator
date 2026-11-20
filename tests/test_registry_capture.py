"""Capture receipts are consistency evidence, not authentication or authority."""
from datetime import datetime
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from isp_geofeed_generator import rdap_capture
from isp_geofeed_generator.registry_batch import check_file_set
from isp_geofeed_generator import registry_capture, registry_batch
from isp_geofeed_generator.client import GeofeedError, JsonHTTP
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.credentials import CredentialStore
from test_rdap_capture import bootstrap, reply, Response, PREFIXES

URL = 'https://feed.example/geofeed.csv'
STAMP = '2026-11-18T12:00:00.123456+00:00'
CSV = b'11.22.33.0/24,US,US-IL,Example City,\r\n'


class RegistryCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.feed=self.root/'feed.csv';self.feed.write_bytes(CSV)

    def test_saved_rdap_accepts_actual_capture_precision_without_rounding(self):
        body=self.root/'response.body';body.write_text(json.dumps(reply()))
        result=check_file_set([body],self.feed,URL,input_format='rdap',observed_at=[STAMP])
        self.assertTrue(result['comparison_consistent'])
        self.assertEqual(result['snapshot_observed_at'],STAMP)

    def make_capture(self, name='capture', prefix=PREFIXES[0], day=18, row=None, language=None):
        folder=self.root/name;source=self.root/(name+'-bootstrap.json');source.write_bytes(bootstrap(prefix))
        stamp=f'2026-11-{day:02d}T12:00:00.123456+00:00'
        plan_now=datetime.fromisoformat(f'2026-11-{day:02d}T11:59:59.123456+00:00')
        real_plan=rdap_capture.plan_bootstrap
        transport=Mock();transport.open.return_value=Response(json.dumps(row or reply(prefix)).encode())
        times=[f'2026-11-{day:02d}T12:00:00.{value}+00:00' for value in ('100000','110000','120000','123456')]
        with patch.object(rdap_capture,'opener',return_value=transport), \
             patch.object(rdap_capture,'utc',side_effect=times), \
             patch.object(rdap_capture,'plan_bootstrap',side_effect=lambda a,b,c:real_plan(a,b,c,now=plan_now)):
            rdap_capture.capture(source,prefix,'2026-11-16T00:00:00+00:00',folder,rdap_language=language)
        self.assertEqual(transport.open.call_count,1)
        return folder,stamp

    def check(self, paths, **kwargs):
        with patch.object(JsonHTTP,'request',side_effect=AssertionError('network read')), \
             patch.object(rdap_capture,'opener',side_effect=AssertionError('capture network read')):
            return check_file_set(paths,self.feed,URL,input_format='rdap-capture',**kwargs)

    def test_single_capture_uses_exact_receipt_date_and_body_manifest_without_authority_claim(self):
        folder,stamp=self.make_capture()
        before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in folder.iterdir()}
        result=self.check([folder])
        self.assertTrue(result['comparison_consistent'])
        self.assertEqual(result['coverage']['4']['this_feed'],'256')
        self.assertEqual(result['snapshot_observed_at'],stamp)
        self.assertEqual(result['snapshot_observed_at_source'],'capture_receipt_unverified')
        self.assertEqual(result['snapshot_inputs'][0]['capture_response_observed_at'],stamp)
        self.assertEqual(result['snapshot_inputs'][0]['capture_evidence_bytes'],sum(len(x[0]) for x in before.values()))
        self.assertEqual(result['capture_integrity'],'internally_consistent')
        self.assertEqual(result['capture_authenticity'], 'not_measured')
        self.assertNotIn('PRIVATE',json.dumps(result));self.assertNotIn('healthy',result)
        self.assertEqual({p:(p.read_bytes(),p.stat().st_mtime_ns) for p in before},before)

    def test_multiple_families_preserve_every_receipt_and_oldest_fractional_date(self):
        first,a=self.make_capture('first');second,b=self.make_capture('second',PREFIXES[1],17)
        self.feed.write_bytes(CSV+b'2001:4860:1234::/126,US,US-IL,Example City,\r\n')
        result=self.check([first,second])
        self.assertTrue(result['comparison_consistent'])
        self.assertEqual(result['coverage']['6']['this_feed'],'4')
        self.assertEqual(result['snapshot_observed_at'],b)
        self.assertEqual([row['capture_response_observed_at'] for row in result['snapshot_inputs']],[a,b])
        self.assertEqual(result['snapshot_observed_at_basis'],'oldest_capture_receipt')
        self.assertEqual(result['rdap_linked_inputs'],2)

    def test_refused_missing_partial_or_changed_members_stop_the_whole_set(self):
        first,_=self.make_capture('first');second,_=self.make_capture('second',PREFIXES[1])
        originals={p.name:p.read_bytes() for p in second.iterdir()}
        cases=[('validation.json',{'schema_version':1,'validation':'refused','reason':'requested_scope_not_covered'}),
               ('receipt.json',None),('response.body',b'PRIVATE replacement'),('response.partial',b'PRIVATE partial')]
        for name,value in cases:
            with self.subTest(member=name):
                if value is None:(second/name).unlink()
                else:(second/name).write_bytes(value if isinstance(value,bytes) else json.dumps(value).encode())
                with self.assertRaisesRegex(GeofeedError,'Registry input 2:.*no partial comparison'):
                    self.check([first,second])
                if name in originals:(second/name).write_bytes(originals[name])
                else:(second/name).unlink()

    def test_transport_flags_hashes_counts_and_lookup_url_are_not_trusted(self):
        folder,_=self.make_capture();path=folder/'receipt.json';original=json.loads(path.read_bytes())
        changes=[{'http_status':True},{'http_status':302},{'body_complete':False}, {'rdap_media_type':False},
                 {'identity_encoding':False},{'read_error':'transport_failure'},{'saved_bytes':True},
                 {'saved_bytes':999},{'saved_sha256':'0'*64},{'lookup_url':'https://foreign.example/PRIVATE'},
                 {'saved_body_file':'../../PRIVATE'},{'validation':'accepted'},{'schema_version':True}]
        for change in changes:
            with self.subTest(change=change):
                path.write_text(json.dumps({**original,**change}))
                with self.assertRaises(GeofeedError) as error:self.check([folder])
                self.assertNotIn('PRIVATE',str(error.exception))
        path.write_text(json.dumps(original))
        self.assertTrue(self.check([folder])['comparison_consistent'])

    def test_dates_are_utc_actual_ordered_and_cannot_be_overridden(self):
        folder,_=self.make_capture();path=folder/'receipt.json';original=json.loads(path.read_bytes())
        for value in ('2026-11-18T12:00:00.1234567Z','2026-11-18T12:00:00',
                      '2026-11-18T12:00:00-01:00','2099-01-01T00:00:00Z','PRIVATE'):
            path.write_text(json.dumps({**original,'response_observed_at':value}))
            with self.assertRaises(GeofeedError):self.check([folder])
        path.write_text(json.dumps({**original,'request_started_at':original['request_completed_at']}))
        with self.assertRaises(GeofeedError):self.check([folder])
        path.write_text(json.dumps(original))
        for changes in ({'observed_at':[STAMP]},{'rdap_language':'en'}):
            with patch.object(registry_capture,'read_capture') as reader,self.assertRaises(GeofeedError):
                self.check([folder],**changes)
            reader.assert_not_called()

    def test_receipt_observation_must_equal_completion_even_when_other_dates_are_ordered(self):
        folder,stamp=self.make_capture();path=folder/'receipt.json';saved=path.read_bytes()
        self.assertEqual(self.check([folder])['snapshot_observed_at'],stamp)
        receipt=json.loads(saved)
        receipt['response_observed_at']='2026-11-18T12:00:00.123455+00:00'
        # This valid past UTC instant lies between receipt and completion. The
        # ordered request times are unchanged, so only the equality guard refuses it.
        self.assertLess(datetime.fromisoformat(receipt['response_received_at']),
                        datetime.fromisoformat(receipt['response_observed_at']))
        self.assertLess(datetime.fromisoformat(receipt['response_observed_at']),
                        datetime.fromisoformat(receipt['request_completed_at']))
        path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(GeofeedError,'complete, consistent'):
            self.check([folder])
        path.write_bytes(saved)
        self.assertEqual(self.check([folder])['snapshot_observed_at'],stamp)

    def test_strict_parser_runs_again_even_when_hashes_and_acceptance_are_rewritten(self):
        from isp_geofeed_generator.feed import digest
        folder,_=self.make_capture();body=folder/'response.body';receipt=folder/'receipt.json'
        original=json.loads(body.read_bytes());saved=json.loads(receipt.read_bytes())
        rows=[{**original,'remarks':[{'type':'object truncated due to server policy'}]},
              {**original,'startAddress':'11.22.33.128'},
              {**original,'links':[{'rel':'geofeed','value':'https://rdap.example/ip/object','href':'http://user:PRIVATE@foreign.example/'}]}]
        for row in rows:
            data=json.dumps(row).encode();body.write_bytes(data)
            receipt.write_text(json.dumps({**saved,'saved_sha256':digest(data),'saved_bytes':len(data)}))
            with self.assertRaises(GeofeedError):self.check([folder])

    def test_bootstrap_and_plan_are_rechecked_not_accepted_as_a_stored_url(self):
        folder,_=self.make_capture();path=folder/'request.json';original=json.loads(path.read_bytes())
        for change in ({'rdap_lookup_url':'https://foreign.example/PRIVATE'}, {'requested_prefix':'10.0.0.0/24'},
                       {'bootstrap_sha256':'0'*64},{'planning_only':1}):
            value=copy.deepcopy(original);value['plan'].update(change);path.write_text(json.dumps(value))
            with self.subTest(change=change),self.assertRaises(GeofeedError):self.check([folder])
        path.write_text(json.dumps(original))
        (folder/'bootstrap.json').write_bytes(bootstrap().replace(b'11.22.33.0/24',b'11.22.34.0/24'))
        with self.assertRaises(GeofeedError):self.check([folder])

    def test_duplicate_json_keys_unknown_schema_and_nonfinite_values_are_refused(self):
        folder,_=self.make_capture();path=folder/'validation.json';original=path.read_bytes()
        for raw in (b'{"schema_version":1,"schema_version":1,"validation":"accepted","reason":null}',
                    b'{"schema_version":1,"validation":"accepted","reason":null,"extra":NaN}',
                    b'{"schema_version":1,"validation":"accepted","reason":null,"extra":1e999}'):
            path.write_bytes(raw)
            with self.assertRaises(GeofeedError):self.check([folder])
        path.write_bytes(original)
        self.assertTrue(self.check([folder])['comparison_consistent'])

    def test_all_evidence_bytes_count_toward_shared_input_budget(self):
        first,_=self.make_capture('first');second,_=self.make_capture('second',PREFIXES[1])
        size=sum(p.stat().st_size for folder in (first,second) for p in folder.iterdir())
        with patch.object(registry_batch,'MAX_BYTES',size-1),self.assertRaises(GeofeedError):self.check([first,second])
        self.feed.write_bytes(CSV+b'2001:4860:1234::/126,US,US-IL,Example City,\r\n')
        with patch.object(registry_batch,'MAX_BYTES',size):self.assertTrue(self.check([first,second])['comparison_consistent'])

    def test_changed_evidence_during_read_refuses_even_if_json_stays_valid(self):
        folder,_=self.make_capture();original=registry_capture.read_output;changed=[]
        def read(path,limit):
            result=original(path,limit)
            if Path(path).name=='validation.json' and not changed:
                changed.append(True);receipt=folder/'receipt.json';receipt.write_bytes(receipt.read_bytes()+b' ')
            return result
        with patch.object(registry_capture,'read_output',side_effect=read),self.assertRaises(GeofeedError):self.check([folder])
        self.assertTrue(changed)

    def test_duplicate_captures_and_invalid_utc_saved_dates_still_refuse(self):
        folder,_=self.make_capture()
        with self.assertRaisesRegex(GeofeedError,'unique safe IDs'):self.check([folder,folder])
        body=self.root/'raw.body';body.write_text(json.dumps(reply()))
        for date in ('2026-11-18T12:00:00.1234567Z','2026-11-18T12:00:00',
                     '2026-11-18T12:00:00+01:00','2099-01-01T00:00:00Z'):
            with self.assertRaises(GeofeedError):check_file_set([body],self.feed,URL,input_format='rdap',observed_at=[date])

    def test_cli_never_reads_config_credentials_or_network_and_preserves_files(self):
        folder,_=self.make_capture();sentinel=self.root/'status.json';sentinel.write_bytes(b'PRIVATE failed status')
        paths=[self.feed,sentinel,*folder.iterdir()];before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in paths}
        args=['check-registry','--config',str(self.root/'missing.yaml'),'--registry-format','rdap-capture',
              '--registry-records',str(folder),'--feed',str(self.feed),'--feed-url',URL]
        output=io.StringIO();error=io.StringIO()
        with patch('isp_geofeed_generator.cli.load_config',side_effect=AssertionError('config read')), \
             patch.object(CredentialStore,'get',side_effect=AssertionError('credential read')), \
             patch.object(rdap_capture,'opener',side_effect=AssertionError('network read')), \
             patch('isp_geofeed_generator.cli.atomic_write',side_effect=AssertionError('output write')), \
             contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):
            self.assertEqual(main(args),0)
            self.assertTrue(json.loads(output.getvalue())['comparison_consistent'])
            output.seek(0);output.truncate()
            self.assertEqual(main(args+['--registry-observed-at',STAMP]),1)
            self.assertEqual(output.getvalue(),'')
        self.assertNotIn('PRIVATE',error.getvalue())
        self.assertEqual({p:(p.read_bytes(),p.stat().st_mtime_ns) for p in paths},before)

    def test_recorded_language_selects_the_same_link_without_a_new_override(self):
        row=reply();original=row['links'][0]
        row['links']=[{**original,'hreflang':'en'}, {**original,'hreflang':'fr','href':'https://other.example/feed.csv'}]
        folder,_=self.make_capture(row=row,language='en')
        result=self.check([folder]);self.assertTrue(result['comparison_consistent'])
        self.assertEqual(result['snapshot_inputs'][0]['rdap_requested_language'],'en')
        self.assertEqual(result['rdap_language_choice_source'],'per_capture_intent')
        self.assertEqual(result['rdap_language_selected_inputs'],1)

    def test_raw_response_set_keeps_fractional_oldest_date_in_every_input(self):
        paths=[self.root/'v4.body',self.root/'v6.body']
        for path,prefix in zip(paths,PREFIXES):path.write_text(json.dumps(reply(prefix)))
        self.feed.write_bytes(CSV+b'2001:4860:1234::/126,US,US-IL,Example City,\r\n')
        older='2026-11-17T12:00:00.123455+00:00'
        result=check_file_set(paths,self.feed,URL,input_format='rdap',observed_at=[STAMP,older])
        self.assertEqual(result['snapshot_observed_at'],older)
        self.assertEqual([x['snapshot_observed_at'] for x in result['snapshot_inputs']],[STAMP,older])

    def test_final_symlink_members_or_non_directory_inputs_are_refused(self):
        folder,_=self.make_capture()
        with self.assertRaises(GeofeedError):self.check([self.feed])
        member=folder/'validation.json';saved=member.read_bytes();target=self.root/'other-validation.json';target.write_bytes(saved)
        member.unlink()
        try:member.symlink_to(target)
        except OSError:
            member.write_bytes(saved)
        else:
            with self.assertRaises(GeofeedError):self.check([folder])
        self.assertEqual(target.read_bytes(),saved)

    def test_private_guard_removals_cause_assertion_failures(self):
        text=Path(registry_capture.__file__).read_text()
        controls=[('receipt-completion',"or observed!=times[-1]",'or False',
                   'test_receipt_observation_must_equal_completion_even_when_other_dates_are_ordered'),
                  ('body-hash',"or receipt['saved_sha256']!=digest(body)",'or False',
                   'test_transport_flags_hashes_counts_and_lookup_url_are_not_trusted'),
                  ('whole-scope',"if (requested.version!=start.version or int(requested.network_address)<int(start)\n                or int(requested.broadcast_address)>int(end)):",'if False:',
                   'test_strict_parser_runs_again_even_when_hashes_and_acceptance_are_rewritten'),
                  ('read-stability',"if read_output(folder/name,limit)!=snapshots[name]:raise ValueError()",'if False:raise ValueError()',
                   'test_changed_evidence_during_read_refuses_even_if_json_stays_valid')]
        def run(method):
            result=unittest.TestResult();RegistryCaptureTests(method).run(result);return result
        positive='test_single_capture_uses_exact_receipt_date_and_body_manifest_without_authority_claim'
        for name,find,replacement,method in controls:
            self.assertTrue(run(positive).wasSuccessful());self.assertTrue(run(method).wasSuccessful())
            self.assertEqual(text.count(find),1)
            private=types.ModuleType('isp_geofeed_generator._private_capture_reader_control');private.__package__='isp_geofeed_generator'
            exec(compile(text.replace(find,replacement),'<private capture reader control>','exec'),private.__dict__)
            private.read_output=lambda *a,**kw:registry_capture.read_output(*a,**kw)
            with patch.object(registry_capture,'read_capture',private.read_capture):result=run(method)
            self.assertEqual(result.errors,[]);self.assertGreater(len(result.failures),0)
            self.assertTrue(run(positive).wasSuccessful());self.assertTrue(run(method).wasSuccessful())
            print('CAPTURE INPUT MUTATION OBSERVATION: '+json.dumps({'mutation':name,
                'assertion_failures':len(result.failures),'errors':0,'intact_before_after':True}))
