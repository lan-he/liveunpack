#!/usr/bin/env python3
"""Extract embedded MP4 bytes without decoding or transcoding. Standard library only."""
import argparse
import hashlib
import io
import json
import sys
from pathlib import Path
import re
import struct
import threading
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

__version__ = "0.1.0"
ROOT = Path(__file__).resolve().parent
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_ZIP_ENTRY_BYTES = 256 * 1024 * 1024

def extract(data):
    # Validate an ISO BMFF box chain, including extended-size mdat boxes.
    for match in re.finditer(b'ftyp', data):
        start = match.start() - 4
        if start < 2 or data[:2] != b'\xff\xd8':
            continue
        pos = start
        types = set()
        end = start
        while pos + 8 <= len(data):
            size, kind = struct.unpack_from('>I4s', data, pos)
            header = 8
            if not all(32 <= c <= 126 for c in kind):
                break
            if size == 1:
                if pos + 16 > len(data):
                    break
                size = struct.unpack_from('>Q', data, pos + 8)[0]
                header = 16
            elif size == 0:
                size = len(data) - pos
            if size < header or pos + size > len(data):
                break
            if pos == start and (kind != b'ftyp' or size < 16 or size > 1024):
                break
            types.add(kind)
            pos += size
            end = pos
        if {b'ftyp', b'moov', b'mdat'} <= types:
            # Vivo's XMP length includes vendor trailer bytes. Preserve the full
            # declared video resource so the export is byte-for-byte original.
            for tag in re.findall(rb'<(?:\w+:)?Item\b[^>]*>', data[:start]):
                attrs = dict(re.findall(rb'(?:\w+:)?(\w+)="([^"]*)"', tag))
                if attrs.get(b'Mime') == b'video/mp4':
                    length = attrs.get(b'Length', b'')
                    if length.isdigit() and start + int(length) == len(data):
                        end = len(data)
            return data[start:end]
    raise ValueError('未找到完整的内嵌 MP4；可能是普通照片、文件不完整或格式暂不支持')

def save(data, name, output):
    video = extract(data)
    stem = Path(name.replace('\\', '/')).stem
    stem = re.sub(r'[^\w .()\-\u4e00-\u9fff]', '_', stem)[:160] or 'live'
    output.mkdir(parents=True, exist_ok=True)
    index = 0
    while True:
        target = output / (stem + (f'_{index}' if index else '') + '.mp4')
        try:
            with target.open('xb') as f:
                f.write(video)
            return {'name': name, 'status': '成功', 'output': str(target), 'bytes': len(video), 'sha256': hashlib.sha256(video).hexdigest()}
        except FileExistsError:
            index += 1

def process(data, name, output):
    if len(data) > MAX_FILE_BYTES:
        raise ValueError('单个输入文件不能超过 512 MiB；大批量请直接选择照片文件夹')
    results = []
    def one(blob, filename):
        try:
            results.append(save(blob, filename, output))
        except Exception as e:
            results.append({'name': filename, 'status': '跳过/失败', 'error': str(e)})
    if name.lower().endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if not info.is_dir() and not info.filename.startswith('__MACOSX/') and info.filename.lower().endswith(('.jpg', '.jpeg')):
                    try:
                        if info.file_size > MAX_ZIP_ENTRY_BYTES:
                            raise ValueError('ZIP 中单张照片不能超过 256 MiB')
                        one(z.read(info), info.filename)
                    except Exception as e:
                        results.append({'name': info.filename, 'status': '失败', 'error': str(e)})
        if not results:
            results.append({'name': name, 'status': '跳过', 'error': 'ZIP 中没有 JPG 照片'})
    else:
        one(data, name)
    return results

HTML = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LiveUnpack · 拾帧</title>
<style>body{background:#f3f5fa;color:#18233c;font:16px system-ui;max-width:850px;margin:65px auto;padding:24px}main{background:white;padding:36px;border-radius:24px}h1{margin-top:0}button,.pick{background:#315bdf;color:white;padding:13px 20px;border:0;border-radius:10px;cursor:pointer;display:inline-block;margin:8px 8px 8px 0}input[type=file]{display:none}#drop{padding:32px;border:2px dashed #bac6e4;border-radius:14px;margin:20px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f7fb;padding:20px;border-radius:12px}small{color:#61708c}input[type=text]{width:95%;padding:12px;border:1px solid #bdc8df;border-radius:8px}.brand{letter-spacing:2px;color:#315bdf;display:block;margin-bottom:20px}h1{font-size:36px;letter-spacing:-1px}main{box-shadow:0 16px 60px #1d34500d}button:disabled{opacity:.5;cursor:wait}button:focus-visible,.pick:focus-within{outline:3px solid #91b5ff;outline-offset:3px}@media(max-width:600px){body{margin:15px auto;padding:12px}main{padding:22px}h1{font-size:28px}#drop{padding:20px}} </style>
<main><small class="brand">LIVEUNPACK / 拾帧 · v0.1.0</small><h1>把动态瞬间，原样带走。</h1><p>直接提取内嵌视频，不转码。批量提取动态照片中的原始 MP4。照片、ZIP、文件夹，全部在本机处理。</p><label for="out">视频保存位置</label><input id="out" type="text"><div id="drop">拖入 JPG / ZIP 文件，或使用下方按钮选择<br><label class="pick">选择照片 / ZIP<input id="files" type="file" multiple accept=".jpg,.jpeg,.zip"></label><label class="pick">选择整个文件夹<input id="folder" type="file" webkitdirectory multiple></label></div><p id="count" role="status">尚未选择文件</p><button id="go">开始导出</button><small>自动扫描子文件夹；重名自动编号；原照片保持不变。</small><pre id="log" aria-live="polite">等待开始…</pre><small>兼容性：vivo X500 系列已测试 · OPPO 理论支持，尚未验证</small></main>
<script>
let selected=[];const $=id=>document.getElementById(id);fetch('/config').then(r=>r.json()).then(c=>$('out').value=c.output);
function choose(files){selected=Array.from(files).filter(f=>/\\.(jpe?g|zip)$/i.test(f.name));$('count').textContent='已选择 '+selected.length+' 个文件'}
$('files').onchange=e=>choose(e.target.files);$('folder').onchange=e=>choose(e.target.files);$('drop').ondragover=e=>e.preventDefault();$('drop').ondrop=e=>{e.preventDefault();choose(e.dataTransfer.files)};
$('go').onclick=async()=>{if(!selected.length){$('log').textContent='请先选择照片或 ZIP';return}if(!$('out').value.trim()){return} $('go').disabled=true;const batch=selected.slice();$('files').disabled=$('folder').disabled=$('out').disabled=true;$('log').textContent='';let ok=0,bad=0;try{for(let i=0;i<batch.length;i++){let f=batch[i];$('count').textContent='正在处理 '+(i+1)+' / '+batch.length;try{let r=await fetch('/extract?name='+encodeURIComponent(f.name)+'&output='+encodeURIComponent($('out').value),{method:'POST',body:f});let rows=await r.json();for(let row of rows){if(row.status==='成功')ok++;else bad++;$('log').textContent+=row.status+' · '+row.name+'\\n'+(row.output||row.error)+'\\n'}}catch(e){bad++;$('log').textContent+='失败 · '+f.name+' · '+e.message+'\\n'}}$('count').textContent='处理完成：成功 '+ok+'，跳过/失败 '+bad}finally{$('go').disabled=false;$('files').disabled=$('folder').disabled=$('out').disabled=false}};
</script>'''

def serve(output, open_browser=True):
    import secrets
    token = secrets.token_urlsafe(24)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def reply(self, body, content='application/json; charset=utf-8', status=200):
            body = body.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            if self.path == '/?key=' + token:
                self.send_response(302)
                self.send_header('Set-Cookie', 'session='+token+'; HttpOnly; SameSite=Strict; Path=/')
                self.send_header('Location', '/')
                self.end_headers()
                return
            if not self.authorized():
                return self.reply('{}', status=403)
            if self.path == '/config':
                return self.reply(json.dumps({'output': str(output)}))
            self.reply(HTML, 'text/html; charset=utf-8')
        def authorized(self):
            return ('session='+token) in self.headers.get('Cookie','').split('; ')
        def do_POST(self):
            from urllib.parse import urlsplit, parse_qs
            if not self.authorized() or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                return self.reply('{}', status=403)
            try:
                url = urlsplit(self.path)
                if url.path != '/extract':
                    raise ValueError('未知操作')
                args = parse_qs(url.query)
                destination = Path(args['output'][0]).expanduser().resolve()
                size = int(self.headers['Content-Length'])
                if not 0 < size <= MAX_FILE_BYTES:
                    raise ValueError('请选择非空文件；单个输入最大 512 MiB')
                self.connection.settimeout(120)
                data = self.rfile.read(size)
                if len(data) != size:
                    raise ValueError('文件传输不完整，请重试')
                rows = process(data, args['name'][0], destination)
                self.reply(json.dumps(rows, ensure_ascii=False))
            except Exception as e:
                self.reply(json.dumps([{'name':'请求','status':'失败','error':str(e)}], ensure_ascii=False))
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    url = f'http://127.0.0.1:{server.server_port}/?key={token}'
    print('浏览器界面已启动。关闭此终端窗口即可退出。\n'+url, flush=True)
    if open_browser:
        threading.Timer(.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

def main(argv=None):
    parser = argparse.ArgumentParser(description="LiveUnpack · 拾帧：批量无转码提取动态照片中的 MP4")
    parser.add_argument('inputs', nargs='*', type=Path, help='JPG、ZIP 或文件夹；不填则启动浏览器界面')
    parser.add_argument('-o', '--output', type=Path, default=Path.cwd()/'导出视频', help='输出目录')
    parser.add_argument('--version', action='version', version='LiveUnpack '+__version__)
    parser.add_argument('--no-browser', action='store_true', help='启动服务但不自动打开浏览器')
    parser.add_argument('--report', type=Path, help='保存 JSON 处理报告（命令行模式）')
    args = parser.parse_args(argv)
    if not args.inputs:
        serve(args.output, not args.no_browser)
        return 0
    results = []
    seen = set()
    for path in args.inputs:
        paths = sorted(path.rglob('*')) if path.is_dir() else [path]
        for file in paths:
            if file.is_dir() or (file.exists() and file.suffix.lower() not in ('.jpg','.jpeg','.zip')):
                continue
            if file.resolve() in seen:
                continue
            seen.add(file.resolve())
            try:
                if file.stat().st_size > MAX_FILE_BYTES:
                    raise ValueError('单个输入最大 512 MiB；大批量请直接选择照片文件夹')
                rows = process(file.read_bytes(), file.name, args.output)
            except Exception as e:
                rows = [{'name':str(file),'status':'失败','error':str(e)}]
            for row in rows:
                print(json.dumps(row, ensure_ascii=False))
            results.extend(rows)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    if not results:
        print('没有找到 JPG / JPEG / ZIP 文件。', file=sys.stderr)
        return 1
    return 0 if all(r['status'] == '成功' for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
