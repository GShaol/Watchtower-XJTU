from pathlib import Path
import sys
import json
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import integrations as app
import engine

class LatestMailTests(unittest.TestCase):
    def test_only_three_headers_are_saved_without_body_or_read_flags(self):
        rows=[dict(id=str(i),subject='Subject '+str(i),**{'from':'Sender <sender@example.com>'},receivedDate='2026-11-05T12:00:00',body='private body',to='private recipient',flags={'read':False}) for i in range(5)]
        items=app.parse_coremail_latest({'code':'S_OK','var':rows},4)
        self.assertEqual(len(items),3);self.assertEqual(items[0]['published'],'2026-11-05 12:00')
        for text in ['private body','private recipient','flags','read']:self.assertNotIn(text,json.dumps(items))
        self.assertFalse(rows[0]['flags']['read'])
    def test_incomplete_and_expired_lists_never_become_empty_success(self):
        for payload in [{'code':'S_OK','var':[]},{'code':'S_OK','var':[{'id':'1','subject':'x'}]},{'code':'ERROR','var':[]}]:
            with self.assertRaises(engine.MonitorError):app.parse_coremail_latest(payload,4)
        with self.assertRaises(engine.SessionExpired):app.parse_coremail_latest({'code':'FA_INVALID_SESSION'},4)
        self.assertEqual(app.parse_coremail_latest({'code':'S_OK','var':[]},0),[])
    def test_check_uses_only_folder_and_header_list_endpoints(self):
        monitor=dict(id='mail',kind='coremail',url='https://stu.xjtu.edu.cn/coremail/index.jsp',cookie='')
        folders={'code':'S_OK','var':[{'id':1,'stats':{'messageCount':1,'unreadMessageCount':1}}]}
        latest={'code':'S_OK','var':[{'id':'m1','subject':'New mail','from':'Sender','receivedDate':'2026-11-05 12:00:00'}]}
        with patch('session_bridge.submit',return_value={'cookie':'Coremail.sid=private'}),patch.object(app,'request_json',side_effect=[(folders,[]),(latest,[])]) as request:
            result=app.check_coremail(monitor)
        self.assertEqual(request.call_count,2)
        self.assertIn('mbox%3AlistMessages',request.call_args.args[0])
        self.assertEqual(request.call_args.kwargs['body'],{'fid':1,'start':0,'limit':3,'order':'receivedDate','desc':True})
        self.assertEqual(result['items'][0]['title'],'New mail')
        self.assertEqual(result['unread'],1)
        self.assertNotIn('private',json.dumps(result))

if __name__=='__main__':unittest.main()
