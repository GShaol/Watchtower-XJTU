"""Read-only ScholarOne author monitoring, using the site's own login/navigation UI."""
import json
import re
import time
import adapters
import credentials
import engine

MANUSCRIPT=re.compile(r'\b[A-Z][A-Z0-9&]{1,15}[-_.](?:20\d{2}[-_.])?(?:\d{2}[-_.])?\d{3,8}(?:[._]R\d+)?\b',re.I)
STATUS=re.compile(r'^(?:awaiting\b|under review\b|in (?:peer )?review\b|with (?:the )?editor\b|submitted\b|accept(?:ed)?\b|rejected\b|reject\b|decision\b|revision\b|revis[ei]\b|major revision\b|minor revision\b|returned\b|withdrawn\b|审稿|外审|初审|终审|修回|录用|拒稿)',re.I)

# No password, cookies, hidden session fields or review bodies are read by this collector.
COLLECT=r"""(()=>{
 const docs=[document];
 for(const f of document.querySelectorAll('iframe,frame')){try{if(f.contentDocument)docs.push(f.contentDocument)}catch{}}
 const text=docs.map(d=>(d.body?.innerText||'').slice(0,25000)).join('\n');
 const login=docs.some(d=>!!d.querySelector('#USERID,#PASSWORD'));
 const result={url:location.href,login,challenge:/verify you are human|verification code|two.factor|验证码|二次验证/i.test(text),badPassword:docs.some(d=>Array.from(d.querySelectorAll('#loginError,#notificationDiv .alert-error,#notificationDiv .alert-danger')).some(e=>/password|user\s*id|username|credential/i.test(e.innerText||'')))||/incorrect (?:user|password)|invalid (?:user|password)|user id or password.{0,25}(?:incorrect|invalid)/i.test(text),authenticated:/log out|logout|sign out/i.test(text),author:/author (?:center|dashboard)|submitted manuscripts|manuscripts.*(?:review|decision)/i.test(text),empty:/no manuscripts|no records found|no submissions|暂无稿件/i.test(text),rows:[],links:[]};
 if(login||result.challenge)return JSON.stringify(result);
 result.links=Array.from(document.querySelectorAll('a')).map(a=>(a.innerText||'').replace(/[\uE000-\uF8FF]/g,'').trim()).filter(t=>/^(?:manuscripts with decisions|manuscripts i have co-authored|submitted manuscripts|manuscripts submitted|manuscripts in review)$/i.test(t));
 const id=/\b[A-Z][A-Z0-9&]{1,15}[-_.](?:20\d{2}[-_.])?(?:\d{2}[-_.])?\d{3,8}(?:[._]R\d+)?\b/i;
 for(const d of docs){
  for(const row of d.querySelectorAll('tr')){
   const cells=Array.from(row.children);
   if(cells.length<2||cells.length>15)continue;
   const values=cells.map(c=>(c.innerText||'').slice(0,1500));
   if(!values.some(v=>id.test(v)))continue;
   result.rows.push({cells:values,spans:cells.map(c=>c.colSpan||1),headers:Array.from(row.closest('table')?.querySelectorAll('thead th')||[]).slice(0,15).map(h=>(h.innerText||'').slice(0,100))});
   if(result.rows.length>=100)break;
  }
  if(result.rows.length>=100)break;
 }
 return JSON.stringify(result);
})()"""


def c_is_tracking(cell):
    return cell.upper().startswith('REX-')


def parse(m,data):
    expected=credentials.site(m['url'])
    if not str(data.get('url','')).startswith(expected+'?') and str(data.get('url','')).rstrip('/')!=expected:
        raise engine.MonitorError('页面未停留在指定的 ScholarOne 期刊，未读取其他站点')
    if data.get('challenge'):raise engine.SessionExpired('ScholarOne 需要验证码或二次验证，请在浏览器完成后重新检查')
    if data.get('login'):raise engine.SessionExpired('ScholarOne 尚未完成登录')
    if not data.get('authenticated'):raise engine.MonitorError('尚未确认 ScholarOne 登录状态，已保留原有数据')
    papers={};incomplete=False
    for row in sorted(data.get('rows',[]),key=lambda r:sum(len(c) for c in r.get('cells',[]))):
        cells=[str(c).strip() for c in row.get('cells',[])]
        # ScholarOne puts REX tracking UUIDs and revision notices beside the actual ID.
        # Only a cell beginning with a manuscript number identifies this row.
        id_cells=[(i,MANUSCRIPT.match(c)) for i,c in enumerate(cells)]
        id_cells=[(i,match) for i,match in id_cells if match and not c_is_tracking(cells[i])]
        if len(id_cells)!=1:continue
        id_index,match=id_cells[0];mid=match.group(0)
        status=next((engine.norm_ws(line) for c in cells[:id_index] for line in c.splitlines() if STATUS.match(line.strip()) and len(line.strip())<180),'')
        # The title follows ID even when ACTION/STATUS use merged cells or rowspans.
        title=''
        if id_index+1<len(cells):
            title=next((engine.norm_ws(line) for line in cells[id_index+1].splitlines() if len(line.strip())>15 and not re.match(r'^(?:view|submitting author|contact|\d{1,2}[-/])',line.strip(),re.I)),'')
        # Header-based fallback supports other standard ScholarOne journal layouts.
        if not status:
            status=next((engine.norm_ws(line) for c in cells for line in c.splitlines() if STATUS.match(line.strip()) and len(line.strip())<180),'')
        if not title or not status:incomplete=True;continue
        base=re.sub(r'[._]R\d+$','',mid,flags=re.I)
        revision=int(re.search(r'[._]R(\d+)$',mid,re.I).group(1)) if re.search(r'[._]R(\d+)$',mid,re.I) else 0
        previous=papers.get(base)
        if not previous or revision>previous['_revision']:
            papers[base]=dict(id=mid,title=title[:800],status=status[:180],url=expected,_revision=revision)
    for paper in papers.values():paper.pop('_revision',None)
    if incomplete:raise engine.MonitorError('已登录，但稿件字段尚未完整识别；保留旧状态，请在浏览器打开作者中心后重试')
    if not papers and not (data.get('author') and data.get('empty')):
        raise engine.MonitorError('已登录，但尚未读到完整的作者中心稿件列表，保留旧状态')
    return adapters.snap(m,{p['id']:p['status'] for p in papers.values()},source='scholarone',papers=list(papers.values()),total=len(papers),summary=' · '.join('#'+p['id']+' '+p['status'] for p in papers.values()) or '账号已连接，作者中心暂无稿件')


def navigate(m,pattern):
    expression="""(()=>{const re=new RegExp(%s,'i');const a=Array.from(document.querySelectorAll('a,button')).find(a=>re.test((a.innerText||'').replace(/[\\uE000-\\uF8FF]/g,'').trim()));if(!a)return JSON.stringify({clicked:false});setTimeout(()=>a.click(),100);return JSON.stringify({clicked:true})})()""" % json.dumps(pattern)
    return adapters.browser_evaluate(dict(m,refresh=False),expression).get('clicked')


def check(m):
    creds=credentials.load(m)
    target=dict(m,kind='browser',url=credentials.site(m['url']),refresh=True,wake_tab=True)
    data=adapters.browser_evaluate(target,COLLECT)
    target['refresh']=False
    if data.get('challenge'):raise engine.SessionExpired('请先在浏览器完成 ScholarOne 验证，再点击重新检查')
    if not data.get('login') and m.get('credential_version') and m.get('credential_verified')!=m['credential_version']:
        if not navigate(target,r'^(?:log\s*out|sign out)$'):
            raise engine.SessionExpired('浏览器已有其他登录会话，请先退出此期刊账号再连接，以便验证新凭证')
        time.sleep(2);data=adapters.browser_evaluate(target,COLLECT)
        if not data.get('login'):raise engine.MonitorError('正在结束原有登录会话，请稍后重新检查')
    if data.get('login'):
        # All credential text is sent over stdin to the local browser, never process arguments or logs.
        expression="""(()=>{if(location.origin!=='https://mc.manuscriptcentral.com'||location.pathname.replace(/\\/$/,'')!==%s)return JSON.stringify({wrongSite:true});const u=document.querySelector('#USERID'),p=document.querySelector('#PASSWORD'),b=document.querySelector('#logInButton');if(!u||!p||!b)return JSON.stringify({missing:true});u.value=%s;p.value=%s;for(const e of [u,p]){e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}))}setTimeout(()=>b.click(),100);return JSON.stringify({submitted:true})})()""" % (json.dumps('/'+target['url'].rsplit('/',1)[1]),json.dumps(creds['username']),json.dumps(creds['password']))
        result=adapters.browser_evaluate(target,expression,secret=True)
        del expression,creds
        if not result.get('submitted'):raise engine.MonitorError('当前页面不是此期刊的标准登录页，凭证未提交')
        for _ in range(3):
            time.sleep(2)
            data=adapters.browser_evaluate(target,COLLECT)
            if not data.get('login') or data.get('badPassword') or data.get('challenge'):break
        if data.get('challenge'):raise engine.SessionExpired('ScholarOne 需要验证，请在浏览器完成后重新检查')
        if data.get('badPassword'):
            credentials.block(m)
            raise engine.SessionExpired('账号或密码未通过验证；已暂停自动登录，请更新凭证')
        if data.get('login'):raise engine.SessionExpired('登录未完成，请检查账号密码，或在浏览器完成验证后重新检查')
    # Read every advertised author queue, including co-authored papers. Never open tasks.
    if not data.get('author') and navigate(target,r'^(?:author|author center|author dashboard|作者中心)$'):
        time.sleep(2);data=adapters.browser_evaluate(target,COLLECT)
    rows=list(data.get('rows',[]));empty=data.get('empty',False)
    for label in dict.fromkeys(data.get('links',[])):
        if navigate(target,'^'+re.escape(label)+'$'):
            time.sleep(2)
            page=adapters.browser_evaluate(target,COLLECT)
            if page.get('login') or not page.get('authenticated'):
                raise engine.SessionExpired('读取作者列表时登录已失效，保留原有状态')
            rows.extend(page.get('rows',[]));empty=empty or page.get('empty',False)
    data=dict(data,rows=rows,empty=empty)
    result=parse(m,data)
    credentials.mark_verified(m)
    return result
