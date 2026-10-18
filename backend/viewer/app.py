#!/usr/bin/env python3
"""Local upload UI: drop a clip, it runs viewer/build.py (convert -> predict -> viewer page).

  python viewer/app.py [--port 8000]      then open http://localhost:8000
Clips go to outputs/uploads/, viewer pages to outputs/viewer/<name>/. Stdlib only.
"""
import argparse, html, json, mimetypes, re, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "outputs/uploads"
CLIPS = ROOT / "outputs/viewer"
PY = ROOT / "convert/.venv/bin/python"
jobs = {}  # name -> "running" | "done" | "failed"

PAGE = """<!doctype html><meta charset=utf-8><title>Skate clips</title>
<style>body{font:15px sans-serif;background:#111;color:#ddd;max-width:760px;margin:40px auto}
#drop{border:2px dashed #555;border-radius:10px;padding:40px;text-align:center;cursor:pointer}
#drop.over{border-color:#3cb4ff;background:#1a2530}a{color:#3cb4ff}
pre{background:#000;padding:10px;max-height:240px;overflow:auto;font-size:12px}
li{margin:6px 0}.s{color:#888;font-size:12px}</style>
<h2>Upload a skating clip</h2>
<div id=drop>Drop a video here or click to choose<input id=f type=file accept="video/*" hidden></div>
<p id=msg></p><pre id=log hidden></pre>
<h3>Processed clips</h3><ul>%s</ul>
<script>
const drop=document.getElementById('drop'),f=document.getElementById('f'),msg=document.getElementById('msg'),log=document.getElementById('log');
drop.onclick=()=>f.click();f.onchange=()=>f.files[0]&&up(f.files[0]);
drop.ondragover=e=>{e.preventDefault();drop.classList.add('over')};drop.ondragleave=()=>drop.classList.remove('over');
drop.ondrop=e=>{e.preventDefault();drop.classList.remove('over');e.dataTransfer.files[0]&&up(e.dataTransfer.files[0])};
async function up(file){
  msg.textContent='Uploading '+file.name+'…';
  const r=await fetch('/upload',{method:'POST',headers:{'X-Filename':encodeURIComponent(file.name)},body:file});
  if(!r.ok){msg.textContent='Upload failed: '+await r.text();return}
  const {name}=await r.json();msg.textContent='Processing '+name+' (skeleton + model)…';log.hidden=false;
  const t=setInterval(async()=>{const s=await (await fetch('/status/'+name)).json();log.textContent=s.log;log.scrollTop=1e9;
    if(s.state==='done'){clearInterval(t);location.href='/clips/'+name+'/index.html'}
    if(s.state==='failed'){clearInterval(t);msg.textContent='Processing failed — see log.'}},1000);
}
</script>"""


def safe_name(fn):
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(fn).stem).strip("_")[:40] or "clip"
    return f"{stem}_{time.strftime('%m%d-%H%M%S')}"


def process(name, video):
    out = CLIPS / name
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "build.log", "w") as log:
        r = subprocess.run([PY, ROOT / "viewer/build.py", video, "-o", out], cwd=ROOT,
                           stdout=log, stderr=subprocess.STDOUT)
    jobs[name] = "done" if r.returncode == 0 and (out / "index.html").exists() else "failed"


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path = unquote(self.path.split("?")[0])
        if path == "/":
            items = []
            for d in sorted(CLIPS.glob("*/index.html"), key=lambda p: -p.stat().st_mtime):
                n = d.parent.name
                items.append(f'<li><a href="/clips/{html.escape(n)}/index.html">{html.escape(n)}</a> '
                             f'<span class=s>{time.strftime("%b %d %H:%M", time.localtime(d.stat().st_mtime))}</span></li>')
            return self._send(200, PAGE % ("".join(items) or "<li class=s>none yet</li>"))
        if path.startswith("/status/"):
            n = path[len("/status/"):]
            logf = CLIPS / n / "build.log"
            tail = logf.read_text(errors="replace")[-4000:] if logf.exists() else ""
            return self._send(200, json.dumps({"state": jobs.get(n, "unknown"), "log": tail}), "application/json")
        if path.startswith("/clips/"):
            f = (CLIPS / path[len("/clips/"):]).resolve()
            if CLIPS.resolve() not in f.parents or not f.is_file():
                return self._send(404, "not found")
            return self._file(f)
        self._send(404, "not found")

    def _file(self, f):
        size = f.stat().st_size
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        start, end = 0, size - 1
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1)); end = int(m.group(2)) if m.group(2) else end
            else:
                start = size - int(m.group(2))
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(f, "rb") as fh:
            fh.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = fh.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def do_POST(self):
        if self.path != "/upload":
            return self._send(404, "not found")
        fn = unquote(self.headers.get("X-Filename", "clip.mov"))
        if Path(fn).suffix.lower() not in {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}:
            return self._send(400, "unsupported file type")
        n = int(self.headers.get("Content-Length", 0))
        name = safe_name(fn)
        UPLOADS.mkdir(parents=True, exist_ok=True)
        video = UPLOADS / (name + Path(fn).suffix.lower())
        with open(video, "wb") as out:
            left = n
            while left > 0:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                out.write(chunk)
                left -= len(chunk)
        jobs[name] = "running"
        threading.Thread(target=process, args=(name, video), daemon=True).start()
        self._send(200, json.dumps({"name": name}), "application/json")

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    CLIPS.mkdir(parents=True, exist_ok=True)
    print(f"open http://localhost:{a.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
