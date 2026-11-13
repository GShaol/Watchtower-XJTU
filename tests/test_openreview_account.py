import base64
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import integrations as app
import credentials
import engine
import webserver

class OpenReviewAccountTests(unittest.TestCase):
    def setUp(self):
        self.m=dict(id='or',kind='openreview',title='OpenReview',url='https://openreview.net/notifications')
        token='x.'+base64.urlsafe_b64encode(json.dumps({'exp':time.time()+3600}).encode()).decode().rstrip('=')+'.x'
        self.secret=dict(username='test@example.com',password='private-password')
        self.login=dict(token=token,user={'profile':{'id':'~Example1'}})
        self.profile={'profiles':[{'content':{'preferredEmail':'test@example.com','emailsConfirmed':['test@example.com']}}]}
        self.messages={'messages':[{'id':'msg1','content':{'subject':'New review','text':'private body'},'cdate':1793808000000,'vdate':123,'referrer':'Venue'}]}
    def test_direct_login_reads_notifications_without_browser_or_message_mutation(self):
        with patch('credentials.load',return_value=dict(self.secret)),patch('credentials.request') as keychain,patch('credentials.mark_verified'),patch.object(app,'request_json',side_effect=[(self.login,[]),(self.profile,[]),(self.messages,[])]) as request,patch('adapters.browser_evaluate') as browser:
            result=app.check_openreview(self.m)
        browser.assert_not_called()
        self.assertTrue(request.call_args_list[0].args[0].endswith('/login'))
        self.assertEqual(request.call_args_list[0].kwargs['body'],{'id':'test@example.com','password':'private-password'})
        self.assertIn('/messages?',request.call_args_list[-1].args[0])
        self.assertNotIn('viewed',request.call_args_list[-1].args[0])
        self.assertEqual(result['total'],1);self.assertEqual(result['baseline_version'],3)
        self.assertEqual(result['items'][0]['id'],'msg1')
        for text in ['private-password','private body','test@example.com','vdate']:self.assertNotIn(text,json.dumps(result))
        self.assertEqual(keychain.call_args.args[0],'put')
    def test_bad_password_blocks_automatic_retries(self):
        with patch('credentials.load',return_value=dict(self.secret)),patch('credentials.block') as block,patch.object(app,'request_json',side_effect=engine.SessionExpired('unauthorized')):
            with self.assertRaises(engine.SessionExpired):app.check_openreview(self.m)
        block.assert_called_once_with(self.m)
    def test_transport_failure_does_not_mark_password_wrong(self):
        with patch('credentials.load',return_value=dict(self.secret)),patch('credentials.block') as block,patch.object(app,'request_json',side_effect=engine.MonitorError('network')):
            with self.assertRaises(engine.MonitorError):app.check_openreview(self.m)
        block.assert_not_called()
    def test_openreview_credentials_are_origin_bound_and_private(self):
        self.assertEqual(credentials.connection_site(self.m),'https://openreview.net')
        with patch('credentials.request'):
            meta=credentials.save(self.m,'test@example.com','private-password')
        public=webserver.public_monitor(dict(self.m,**meta))
        self.assertTrue(public['has_credentials'])
        self.assertNotIn('private-password',json.dumps(meta))
        self.assertNotIn('credential_version',json.dumps(public))
        with self.assertRaises(engine.MonitorError):credentials.connection_site(dict(self.m,url='https://other.example/'))
    def test_missing_credentials_does_not_reuse_an_unverified_browser(self):
        with patch('credentials.load',side_effect=engine.SessionExpired('fill credentials')),patch('adapters.browser_evaluate') as browser:
            with self.assertRaises(engine.SessionExpired):app.check_openreview(self.m)
        browser.assert_not_called()

if __name__=='__main__':unittest.main()
