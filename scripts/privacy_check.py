"""Offline heuristic release gate. Prints paths/rule names, never matched secrets."""
import argparse
import io
import re
import sys
import zipfile
from pathlib import Path

RULES={
 'provider-token':re.compile(rb'(?:ntn_|ghp_|github_pat_)[A-Za-z0-9_]{20,}'),
 'bearer-token':re.compile(rb'Bearer [A-Za-z0-9_.-]{45,}'),
 'session-value':re.compile(rb'(?:JSESSIONID|Coremail\.sid|openreview\.accessToken)=[A-Za-z0-9_.-]{16,}'),
 'private-key':re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
 'local-user-path':re.compile(rb'/Users/[A-Za-z0-9_.-]+/'),
 'profile-query':re.compile(rb'[?&]user=(?!EXAMPLE_USER|DEMO_USER)[A-Za-z0-9_-]{8,}'),
}
FORBIDDEN_DIRS={'data','logs','.upgrade-backups','WebKit','WebsiteData'}

def inspect(name,data,findings):
 if data.startswith(b'PK\x03\x04') and zipfile.is_zipfile(io.BytesIO(data)):
  with zipfile.ZipFile(io.BytesIO(data)) as archive:
   for entry in archive.infolist():
    if not entry.is_dir():inspect(name+'!'+entry.filename,archive.read(entry),findings)
  return
 for label,rule in RULES.items():
  if rule.search(data):findings.add((name,label))
 # Vendored Python bytecode/native libraries contain upstream copyright contacts
 # and arbitrary machine-code bytes. Check email patterns in project text only;
 # credential and user-path rules above still apply to every byte of every file.
 project_text='/backend/_internal/' not in name and not name.startswith('__MACOSX/')
 if project_text and re.search(rb'[A-Za-z0-9_.+-]+@(?!example\.(?:com|org)|invalid\b)[A-Za-z0-9.-]+\.(?:com|org|net|edu|cn|io|co|uk|de|gov|me)\b',data,re.I):findings.add((name,'non-example-email'))

def scan(root):
 findings=set();count=0
 paths=[root] if root.is_file() else root.rglob('*')
 for p in paths:
  if not p.is_file() or p.is_symlink():continue
  rel=p.name if root.is_file() else str(p.relative_to(root))
  if any(part in ('.git','.venv','__pycache__') for part in p.relative_to(root).parts if not root.is_file()):continue
  count+=1
  if FORBIDDEN_DIRS.intersection(Path(rel).parts):findings.add((rel,'runtime-directory'))
  if p.suffix=='.zip':
   with zipfile.ZipFile(p) as z:
    for item in z.infolist():
     if item.is_dir():continue
     name=rel+'!'+item.filename
     if FORBIDDEN_DIRS.intersection(Path(item.filename).parts):findings.add((name,'runtime-directory'))
     inspect(name,z.read(item),findings)
  else:inspect(rel,p.read_bytes(),findings)
 return count,sorted(findings)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('path',nargs='?',default='.')
 args=parser.parse_args();count,findings=scan(Path(args.path).resolve())
 for name,rule in findings:print('FAIL',rule,name)
 print(f'Checked {count} files; {len(findings)} finding(s). Heuristic scan only; manual review is also required.')
 sys.exit(bool(findings))
