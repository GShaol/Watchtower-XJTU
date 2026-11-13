"""Exercise an isolated packaged backend without UI, accounts or website requests."""
import argparse,json,os,socket,subprocess,tempfile,time,urllib.request,urllib.error
from pathlib import Path

def main():
 parser=argparse.ArgumentParser();parser.add_argument('app',type=Path);args=parser.parse_args()
 resources=args.app.resolve()/'Contents/Resources'
 with tempfile.TemporaryDirectory(prefix='watchtower-community-check-') as folder:
  sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
  env=dict(os.environ,WATCHTOWER_COMMUNITY_HOME=folder,WATCHTOWER_COMMUNITY_RESOURCES=str(resources),WATCHTOWER_COMMUNITY_SESSION_TOKEN='isolated-verification-only')
  process=subprocess.Popen([str(resources/'backend/watchtower-core'),'--port',str(port),'--parent-pid',str(os.getpid())],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));base=f'http://127.0.0.1:{port}'
  def request(path,body=None,headers=None):
   h={'Content-Type':'application/json'};h.update(headers or {})
   r=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers=h)
   with opener.open(r,timeout=5) as response:return json.load(response)
  try:
   for _ in range(60):
    try:request('/api/health');break
    except (OSError,ValueError):time.sleep(.2)
   else:raise RuntimeError('Backend did not start')
   state=request('/api/state');rows=state['monitors']
   assert len(rows)==9 and len({m['id'] for m in rows})==9
   assert all(not m['enabled'] and m['setup_required'] and not m['has_cookie'] and not m['has_credentials'] for m in rows)
   assert not state['recent'] and all(not i.get('last_success') for i in state['items'].values())
   assert request('/api/check',{})['started']==0
   for path in ('/api/email-digest','/api/notion/connect'):
    try:request(path,{})
    except urllib.error.HTTPError as e:assert e.code==404
    else:raise AssertionError('Removed route is still available')
   for path,body,headers in [('/api/internal/sessions',None,{}),('/api/settings',{}, {'Origin':'https://example.com'})]:
    try:request(path,body,headers)
    except urllib.error.HTTPError as e:assert e.code==403
    else:raise AssertionError('Access check failed')
   print('PASS: nine disabled modules; no credentials, baseline or history; removed APIs return 404; loopback/bridge isolation.')
  finally:
   process.terminate()
   try:process.wait(timeout=8)
   except subprocess.TimeoutExpired:process.kill();process.wait()
   assert not process.poll() is None

if __name__=='__main__':main()
