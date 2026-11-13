import copy,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import community,store,engine,credentials,webserver,adapters,scholarone,scheduler,push_plans

class CommunityTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
  self.paths=patch.multiple(store,ROOT=str(root),DATA_DIR=str(root/'data'),LOG_DIR=str(root/'logs'),CONFIG=str(root/'data/config.json'),STATE=str(root/'data/state.json'),SETTINGS=str(root/'data/settings.json'))
  self.paths.start()
 def tearDown(self):self.paths.stop();self.temp.cleanup()
 def test_fresh_catalog_has_exactly_nine_disabled_modules(self):
  community.initialize();rows=store.monitors()
  self.assertEqual(len(rows),9);self.assertEqual(len({m['id'] for m in rows}),9)
  self.assertTrue(all(not m['enabled'] and m['setup_required'] for m in rows))
  serialized=json.dumps(rows)
  for key in ('credential_ref','cookie','password','token'):self.assertNotIn(key,serialized)
  self.assertEqual({m.get('journal_code') for m in rows if m['kind']=='scholarone'},{'TIFS','TDSC','ToN','TMC','JSAC'})
 def test_initialize_does_not_overwrite_existing_user_settings(self):
  store.save_monitors([{'id':'sentinel'}]);community.initialize()
  self.assertEqual(store.monitors(),[{'id':'sentinel'}])
 def test_nine_modules_enforce_origin_and_identity(self):
  for m in community.templates():
   bad=dict(m,url='https://example.com/login')
   with self.assertRaises(engine.MonitorError):community.validate_module(bad)
  with self.assertRaises(engine.MonitorError):community.validate_module(dict(community.templates()[0],id='unknown'))
 def test_disabled_templates_never_schedule_or_notify(self):
  community.initialize()
  with patch('engine.run_check') as remote,patch('notifier.notify') as notify:
   s=scheduler.Scheduler();s.tick()
  remote.assert_not_called();notify.assert_not_called()
 def test_public_api_does_not_return_secrets(self):
  m=dict(community.templates()[3],credential_ref='https://openreview.net',cookie='dummy-cookie',account_password='example-password')
  public=webserver.public_monitor(m)
  self.assertTrue(public['has_credentials']);self.assertTrue(public['has_cookie'])
  self.assertNotIn('dummy-cookie',json.dumps(public));self.assertNotIn('example-password',json.dumps(public))
 def test_credential_helper_has_community_namespace(self):
  m=next(m for m in community.templates() if m['kind']=='coremail')
  with patch('subprocess.run') as process:
   process.return_value.stdout='{"ok":true,"value":{}}';credentials.request('get',m)
  payload=json.loads(process.call_args.kwargs['input'])
  self.assertTrue(payload['service'].startswith('org.watchtower.community.'))
 def test_scholarone_synthetic_rows_and_partial_result_failure(self):
  for m in community.templates():
   if m['kind']!='scholarone':continue
   payload=dict(url=m['url'],authenticated=True,author=True,rows=[dict(headers=['Status','Manuscript ID','Title'],cells=['Under Review','DEMO-2030-00001','A fictional demonstration manuscript'])])
   result=scholarone.parse(m,payload)
   self.assertEqual(result['fields'],{'DEMO-2030-00001':'Under Review'})
   payload['rows'].append(dict(cells=['DEMO-2030-00002','Incomplete row']))
   with self.assertRaises(engine.MonitorError):scholarone.parse(m,payload)
 def test_scholar_synthetic_metrics_and_missing_auth(self):
  m=community.templates()[0]
  html='<div id="gsc_prf_in">Example Researcher</div><table id="gsc_rsb_st">'+''.join('<tr><td class="gsc_rsb_std">'+x+'</td></tr>' for x in ['42','3','2'])+'</table>'
  result=adapters.parse_google(m,html);self.assertEqual(result['total'],42)
  with self.assertRaises(engine.MonitorError):adapters.parse_google(m,'<p>Please log in</p>')
 def test_push_cadence_is_independent_and_validated(self):
  p=push_plans.validate({'mode':'times','times':['18:00','09:00','09:00']})
  self.assertEqual(p['times'],['09:00','18:00'])
  with self.assertRaises(engine.MonitorError):push_plans.validate({'mode':'interval','minutes':0})
 def test_lost_connection_keeps_previous_success(self):
  m=community.templates()[2];m.update(enabled=True,setup_required=False)
  store.save_monitors([m]);store.update_item_state(m['id'],{'ok':True,'last_success':1,'fields':{'sample':'Previous result'},'fingerprint':'example'})
  with patch('engine.run_check',side_effect=engine.MonitorError('Temporary failure')),patch('notifier.notify'):
   scheduler.Scheduler().check(m)
  result=store.state()['items'][m['id']]
  self.assertEqual(result['fields'],{'sample':'Previous result'});self.assertEqual(result['last_success'],1);self.assertTrue(result['error'])

if __name__=='__main__':unittest.main()
