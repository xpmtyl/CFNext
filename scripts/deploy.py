#!/usr/bin/env python3
"""把 CFNext 明文版部署到 Cloudflare Worker。

直接用 Cloudflare REST API，不依赖 npm / wrangler（wrangler 在 CI 里装不上时这条路更稳）。

必需环境变量：
  CLOUDFLARE_API_TOKEN   或 CF_API_TOKEN
  CLOUDFLARE_ACCOUNT_ID 或 CF_ACCOUNT_ID
可选：
  U       面板 / 订阅路径（UUID）。留空则不写该 binding，沿用 KV 里的配置。
  KV_ID   KV 命名空间 ID，默认沿用 cfe 的命名空间。

⚠️ 关键点：ES module 必须用 Content-Type: application/javascript+module，
   否则 Cloudflare 会报 "Cannot use import statement outside a module"。
"""
import json, os, sys, uuid, urllib.request, urllib.error

TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN') or os.environ.get('CF_API_TOKEN')
AID = os.environ.get('CLOUDFLARE_ACCOUNT_ID') or os.environ.get('CF_ACCOUNT_ID')
if not TOKEN or not AID:
    sys.exit('缺少 CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID')

SCRIPT = os.environ.get('WORKER_NAME', 'cfe')
KV_ID = os.environ.get('KV_ID', '43c7b97bffcc4e50b33a9f5904783426')
U_VAL = os.environ.get('U', '').strip()

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = os.path.join(here, 'CFNext 明文版.js')
if not os.path.exists(src):
    sys.exit('找不到源文件: %s' % src)

js = open(src, 'rb').read()
print('source : %s (%d bytes)' % (src, len(js)))
print('worker : %s | account: %s' % (SCRIPT, AID))

bindings = [{'type': 'kv_namespace', 'name': 'K', 'namespace_id': KV_ID}]
if U_VAL:
    bindings.append({'type': 'plain_text', 'name': 'U', 'text': U_VAL})
    print('binding: K=KV, U=%s' % U_VAL)
else:
    print('binding: K=KV (U 未设置，沿用 KV 配置)')

meta = {
    'main_module': 'worker.js',
    'bindings': bindings,
    'compatibility_date': '2024-09-01',
}

boundary = '----cfnext' + uuid.uuid4().hex


def field(name, value, ctype=None, filename=None):
    head = 'Content-Disposition: form-data; name="%s"' % name
    if filename:
        head += '; filename="%s"' % filename
    part = b'--' + boundary.encode() + b'\r\n' + head.encode()
    if ctype:
        part += b'\r\nContent-Type: ' + ctype.encode()
    return part + b'\r\n\r\n' + value + b'\r\n'


payload = b''
payload += field('metadata', json.dumps(meta).encode(), 'application/json')
payload += field('worker.js', js, 'application/javascript+module', 'worker.js')
payload += b'--' + boundary.encode() + b'--\r\n'

url = ('https://api.cloudflare.com/client/v4/accounts/%s/workers/scripts/%s'
       % (AID, SCRIPT))
req = urllib.request.Request(url, data=payload, method='PUT', headers={
    'Authorization': 'Bearer ' + TOKEN,
    'Content-Type': 'multipart/form-data; boundary=' + boundary,
})
try:
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read().decode())
except urllib.error.HTTPError as e:
    sys.exit('部署失败 HTTP %s\n%s' % (e.code, e.read().decode()[:1200]))

if not d.get('success'):
    sys.exit('部署失败: %s' % json.dumps(d.get('errors'), ensure_ascii=False))

res = d.get('result') or {}
print('部署成功: id=%s modified=%s' % (res.get('id'), res.get('modified_on')))
