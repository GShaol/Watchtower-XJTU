"""Public module catalog. Never imports or migrates another application's data."""
import copy
import urllib.parse
import engine
import store

JOURNALS=[('tifs','TIFS','tifs-ieee'),('tdsc','TDSC','tdsc-cs'),('ton','ToN','tnet-ieee'),('tmc','TMC','tmc-cs'),('jsac','JSAC','jsac-ieee')]

def templates():
    def entry(key,title,kind,url,minutes=30,category='paper'):
        return dict(id='community_'+key,title=title,kind=kind,url=url,interval_minutes=minutes,category=category,enabled=False,setup_required=True,notifications=True,fields=[],browser='Watchtower Community',refresh=True,notification_mode='changes')
    rows=[entry('scholar','Google Scholar','google_scholar','https://scholar.google.com/citations?user=',1440,'scholar'),entry('mail','交大学生邮箱','coremail','https://stu.xjtu.edu.cn/coremail/index.jsp?cus=1',15,'work'),entry('oa','交大 OA','xjtu_oa','https://oa.xjtu.edu.cn/',1440,'work'),entry('openreview','OpenReview','openreview','https://openreview.net/notifications')]
    rows += [dict(entry(key,'IEEE '+code,'scholarone','https://mc.manuscriptcentral.com/'+slug),journal_code=code) for key,code,slug in JOURNALS]
    for row in rows:
        if row['kind'] in ('google_scholar','xjtu_oa'):
            row.update(schedule={'type':'daily','time':'09:00'},notification_mode='daily_digest')
    return rows

def initialize():
    import os
    if not os.path.exists(store.CONFIG):store.save_monitors(templates())

def validate_module(m):
    preset=next((p for p in templates() if p['id']==m['id']),None)
    if not preset or preset['kind']!=m['kind']:raise engine.MonitorError('请选择分享版的九个模块之一')
    u=urllib.parse.urlparse(m.get('url',''))
    if u.scheme!='https' or u.username or u.password or u.port not in (None,443):raise engine.MonitorError('请使用官方网站的 HTTPS 地址')
    if m['kind']=='scholarone':
        import credentials
        bound=credentials.site(m['url'])
        if bound!=preset['url']:raise engine.MonitorError('请使用此期刊预置的 ScholarOne 入口；EDAS 暂不支持')
    elif m['kind']=='google_scholar':
        if u.hostname!='scholar.google.com' or u.path!='/citations':raise engine.MonitorError('请使用 Google Scholar 个人主页链接')
    elif m['url']!=preset['url']:raise engine.MonitorError('此模块只支持预置的官方入口')
