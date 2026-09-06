#!/usr/bin/env python3
"""
CSF1 Viewer v0.1
Host GUI / CLI to open JCkernel raw (.img/.bin) or QEMU (.qcow2) disks
read-only, detect CSF1 at LBA 4096, and browse as a tree.

Inspect CLI prints one token (no extra English on that line):
  NO_SUPERBLOCK | WRONG_MAGIC | WRONG_VERSION | MOUNT_OK
"""

from __future__ import annotations

import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

APP_NAME = "CSF1 Viewer"
APP_VER = "v0.1"

# allow running from this folder
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from csf1_core import CSF1Volume  # noqa: E402
from qcow2io import open_disk  # noqa: E402

STATE = {
    "vol": None,
    "path": "",
    "order": "az",
    "status": "No disk mounted.",
    "ok": False,
}


def inspect_path(path: str) -> str:
    """Open PATH rb-only and classify the LBA 4096 superblock.

    Does not import / export / remove. Does not scan the first 64 MiB.
    """
    path = os.path.abspath(path.strip().strip('"'))
    dev = open_disk(path, writable=False)
    try:
        vol = CSF1Volume(dev)
        return vol.inspect()
    finally:
        try:
            dev.close()
        except Exception:
            pass


def inspect_cli(path: str) -> int:
    token = inspect_path(path)
    print(token)
    return 0 if token == "MOUNT_OK" else 1


def mount_path(path: str) -> dict:
    path = os.path.abspath(path.strip().strip('"'))
    if not os.path.isfile(path):
        return {"ok": False, "message": f"File not found: {path}"}
    try:
        if STATE["vol"] and STATE["vol"].dev:
            STATE["vol"].dev.close()
    except Exception:
        pass
    try:
        dev = open_disk(path, writable=False)
        vol = CSF1Volume(dev)
        ok = vol.detect_and_mount()
        STATE["vol"] = vol
        STATE["path"] = path
        STATE["ok"] = ok
        STATE["status"] = vol.message
        return {
            "ok": ok,
            "message": vol.message,
            "path": path,
            "kind": "qcow2" if path.lower().endswith(".qcow2") else "raw",
            "sb": _sb_dict(vol) if ok else None,
        }
    except Exception as e:
        STATE["ok"] = False
        STATE["status"] = str(e)
        return {"ok": False, "message": str(e)}


def _sb_dict(vol: CSF1Volume):
    s = vol.sb
    return {
        "disk_name": s.disk_name,
        "version": s.version,
        "created_at": s.created_at,
        "layout_id": s.layout_id,
        "total_size_mb": s.total_size_mb,
        "file_count": s.file_count,
        "folder_count": s.folder_count,
        "max_files": s.max_files,
        "max_folders": s.max_folders,
        "origin_lba": s.origin_lba,
        "data_start_sector": s.data_start_sector,
    }


def tree_payload(order: str = None):
    vol = STATE["vol"]
    if not vol or not STATE["ok"]:
        return {"ok": False, "rows": [], "message": STATE["status"]}
    order = order or STATE["order"]
    STATE["order"] = order
    rows = []
    for path, e in vol.tree_rows(order):
        rows.append({
            "path": path,
            "name": e.name,
            "kind": e.kind,
            "size": e.size,
            "owner": e.owner,
            "created": e.created_at,
            "modified": e.modified_at,
            "deleted": e.deleted_at,
            "index": e.index,
        })
    return {"ok": True, "rows": rows, "order": order, "sb": _sb_dict(vol), "message": STATE["status"]}


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>CSF1 Viewer v0.1</title>
<style>
:root {
  --bg:#0e1114; --panel:#171c21; --ink:#e8edf2; --muted:#8b98a5;
  --line:#2a333c; --ok:#3dba7a; --bad:#e05a5a; --accent:#c45c4a;
  --hi:#243028;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);
  font:14px/1.4 "Segoe UI",system-ui,sans-serif}
header{padding:14px 20px;border-bottom:1px solid var(--line);
  display:flex;align-items:center;gap:16px}
header h1{margin:0;font-size:18px;letter-spacing:.04em}
header .ver{color:var(--muted);font-size:12px}
.drop{
  margin:16px 20px 8px;border:1.5px dashed var(--line);border-radius:10px;
  padding:22px;text-align:center;background:var(--panel);color:var(--muted)
}
.drop.over{border-color:var(--ok);background:var(--hi);color:var(--ink)}
.row{display:flex;gap:8px;flex-wrap:wrap;margin:0 20px 12px;align-items:center}
input[type=text]{flex:1;min-width:240px;background:#0b0e11;color:var(--ink);
  border:1px solid var(--line);border-radius:6px;padding:8px 10px}
button{background:#222a31;color:var(--ink);border:1px solid var(--line);
  border-radius:6px;padding:8px 12px;cursor:pointer}
button.primary{background:var(--accent);border-color:#a3483a;color:#fff}
button:hover{filter:brightness(1.08)}
.banner{margin:0 20px 12px;padding:10px 12px;border-radius:8px;display:none}
.banner.ok{display:block;background:#16351f;color:#b7f0cc;border:1px solid #2e6b44}
.banner.bad{display:block;background:#3a1616;color:#f3b4b4;border:1px solid #7a3030}
.meta{margin:0 20px 8px;color:var(--muted);font-size:12px}
.split{display:grid;grid-template-columns:1.3fr .7fr;gap:12px;margin:0 20px 20px;
  height:calc(100vh - 280px);min-height:280px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:auto}
table{width:100%;border-collapse:collapse}
th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;font-size:13px}
th{position:sticky;top:0;background:#1d242b;color:var(--muted);font-weight:600}
tr:hover{background:#1c2329;cursor:pointer}
tr.sel{background:#2a3a30}
.preview{padding:12px;white-space:pre-wrap;word-break:break-word;
  font-family:ui-monospace,Consolas,monospace;font-size:12px;color:#d5dde4}
.hint{padding:12px;color:var(--muted)}
</style>
</head>
<body>
<header>
  <h1>CSF1 Viewer</h1>
  <span class="ver">v0.1 — JCkernel host bypass</span>
</header>
<div id="drop" class="drop">
  Drop a virtual disk here (.qcow2 / .img / .bin) or browse below.<br>
  Detects CSF1 at LBA 4096 and shows the tree (read-only inspect).
</div>
<div class="row">
  <input id="path" type="text" placeholder="Path to disk image…"/>
  <input id="filepick" type="file" style="display:none"/>
  <button onclick="document.getElementById('filepick').click()">Browse</button>
  <button class="primary" onclick="mount()">Mount / Detect CSF1</button>
  <button onclick="setOrder('az')">Tree A→Z (low→high)</button>
  <button onclick="setOrder('za')">Tree Z→A (high→low)</button>
</div>
<div id="banner" class="banner"></div>
<div id="meta" class="meta"></div>
<div class="row">
  <input id="dest" type="text" value="/Base/Files" style="max-width:220px"/>
  <input id="importpick" type="file"/>
  <button class="primary" onclick="importFile()">Import into CSF1</button>
  <button onclick="removeSel()">Remove selected</button>
  <button onclick="exportSel()">Export selected</button>
</div>
<div class="split">
  <div class="card">
    <table>
      <thead><tr><th>Path</th><th>Kind</th><th>Size</th><th>Owner</th><th>Modified</th></tr></thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
  <div class="card">
    <div id="preview" class="hint">Select a file to preview text / hex.</div>
  </div>
</div>
<script>
let selected = null;
const drop = document.getElementById('drop');
drop.addEventListener('dragover', e => {e.preventDefault(); drop.classList.add('over');});
drop.addEventListener('dragleave', () => drop.classList.remove('over'));
drop.addEventListener('drop', e => {
  e.preventDefault(); drop.classList.remove('over');
  const f = e.dataTransfer.files[0];
  if (!f) return;
  document.getElementById('path').value = f.path || f.name;
  if (f.path) mount();
  else banner(false, 'Browser hid the real path. Paste the full disk path and click Mount. On Linux/Windows launchers, drag-drop onto the window still works via the path box.');
});
document.getElementById('filepick').addEventListener('change', ev => {
  const f = ev.target.files[0];
  if (!f) return;
  document.getElementById('path').value = f.path || f.name;
});
function banner(ok, msg) {
  const b = document.getElementById('banner');
  b.className = 'banner ' + (ok ? 'ok' : 'bad');
  b.textContent = msg;
}
async function api(url, body) {
  const opt = body ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {};
  const r = await fetch(url, opt);
  return r.json();
}
async function mount() {
  const path = document.getElementById('path').value.trim();
  const j = await api('/api/mount', {path});
  banner(j.ok, j.message);
  if (j.ok && j.sb) {
    document.getElementById('meta').textContent =
      `Disk: ${j.sb.disk_name}  |  CSF1 v${j.sb.version}  |  ${j.sb.total_size_mb} MB  |  layout ${j.sb.layout_id}  |  LBA ${j.sb.origin_lba}`;
  }
  await refresh();
}
async function setOrder(o) { await refresh(o); }
async function refresh(order) {
  const j = await api('/api/tree' + (order ? ('?order='+order) : ''));
  const tb = document.getElementById('tbody');
  tb.innerHTML = '';
  if (!j.ok) return;
  for (const row of j.rows) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${esc(row.path)}</td><td>${row.kind}</td><td>${row.size}</td><td>${esc(row.owner)}</td><td>${esc(row.modified)}</td>`;
    tr.onclick = () => { selected = row; [...tb.children].forEach(x=>x.classList.remove('sel')); tr.classList.add('sel'); preview(row); };
    tb.appendChild(tr);
  }
}
async function preview(row) {
  if (row.kind !== 'file') { document.getElementById('preview').textContent = '(folder)'; return; }
  const j = await api('/api/preview?index='+row.index);
  document.getElementById('preview').textContent = j.text || j.message || '';
}
async function importFile() {
  const f = document.getElementById('importpick').files[0];
  const dest = document.getElementById('dest').value || '/Base/Files';
  if (!f) { banner(false, 'Choose a host file to import.'); return; }
  // send name + base64
  const buf = await f.arrayBuffer();
  const b64 = btoa(String.fromCharCode(...new Uint8Array(buf).slice(0, 262144)));
  const j = await api('/api/import_bytes', {name: f.name, dest, data_b64: b64});
  banner(j.ok, j.message);
  await refresh();
}
async function removeSel() {
  if (!selected || selected.kind !== 'file') { banner(false, 'Select a file to remove.'); return; }
  if (!confirm('Remove '+selected.path+' from CSF1?')) return;
  const j = await api('/api/remove', {index: selected.index});
  banner(j.ok, j.message);
  selected = null;
  await refresh();
}
async function exportSel() {
  if (!selected || selected.kind !== 'file') { banner(false, 'Select a file to export.'); return; }
  window.location = '/api/export?index='+selected.index+'&name='+encodeURIComponent(selected.name);
}
function esc(s){return String(s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (APP_NAME, fmt % args))

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if u.path == "/api/tree":
            qs = parse_qs(u.query)
            order = (qs.get("order") or [None])[0]
            self._json(tree_payload(order))
            return
        if u.path == "/api/preview":
            qs = parse_qs(u.query)
            idx = int((qs.get("index") or ["-1"])[0])
            vol = STATE["vol"]
            if not vol:
                self._json({"ok": False, "message": "not mounted"})
                return
            for e in vol.files:
                if e.index == idx:
                    text = e.content.decode("utf-8", "replace")
                    if any(c == "\x00" for c in text[:200]):
                        text = e.content[:512].hex(" ")
                    self._json({"ok": True, "text": text[:8000]})
                    return
            self._json({"ok": False, "message": "not found"})
            return
        if u.path == "/api/export":
            qs = parse_qs(u.query)
            idx = int((qs.get("index") or ["-1"])[0])
            name = unquote((qs.get("name") or ["file.bin"])[0])
            vol = STATE["vol"]
            if not vol or not getattr(vol.dev, "writable", False):
                self._json({"ok": False, "message": "volume opened read-only"})
                return
            blob = b""
            if vol:
                for e in vol.files:
                    if e.index == idx:
                        blob = e.content
                        break
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)
            return
        self.send_error(404)

    def do_POST(self):
        u = urlparse(self.path)
        body = self._read_json()
        if u.path == "/api/mount":
            self._json(mount_path(body.get("path") or ""))
            return
        if u.path == "/api/remove":
            vol = STATE["vol"]
            if not vol or not STATE["ok"]:
                self._json({"ok": False, "message": "not mounted"})
                return
            if not getattr(vol.dev, "writable", False):
                self._json({"ok": False, "message": "volume opened read-only"})
                return
            try:
                vol.remove_file(int(body.get("index")))
                self._json({"ok": True, "message": "File removed from CSF1."})
            except Exception as e:
                self._json({"ok": False, "message": str(e)})
            return
        if u.path == "/api/import_bytes":
            vol = STATE["vol"]
            if not vol or not STATE["ok"]:
                self._json({"ok": False, "message": "Mount a CSF1 disk first."})
                return
            if not getattr(vol.dev, "writable", False):
                self._json({"ok": False, "message": "volume opened read-only"})
                return
            import base64
            import tempfile
            name = os.path.basename(body.get("name") or "imported.bin")
            dest = body.get("dest") or "/Base/Files"
            raw = base64.b64decode(body.get("data_b64") or "")
            tmp = os.path.join(tempfile.gettempdir(), name)
            with open(tmp, "wb") as f:
                f.write(raw)
            try:
                e = vol.add_file(tmp, dest)
                self._json({"ok": True, "message": f"Imported {e.name} into {e.path} (slot {e.index})."})
            except Exception as ex:
                self._json({"ok": False, "message": str(ex)})
            return
        self.send_error(404)


def run_server(port: int = 8765):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"{APP_NAME} {APP_VER}")
    print(f"Open {url}")
    print("Drop or type a path to uefi-disk.img / *.qcow2 then Mount.")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


def try_tk():
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception:
        return False

    root = tk.Tk()
    root.title(f"{APP_NAME} {APP_VER}")
    root.geometry("980x620")
    root.configure(bg="#0e1114")

    path_var = tk.StringVar()
    dest_var = tk.StringVar(value="/Base/Files")
    order_var = tk.StringVar(value="az")
    status_var = tk.StringVar(value="Drop or browse a .qcow2 / .img disk.")

    def do_mount(p=None):
        p = p or path_var.get()
        r = mount_path(p)
        status_var.set(r["message"])
        if r["ok"]:
            messagebox.showinfo(APP_NAME, "Success.\n\n" + r["message"] + "\n\nCSF1 is visible in the tree.")
        else:
            messagebox.showerror(APP_NAME, r["message"])
        refresh()

    def refresh():
        for i in tree.get_children():
            tree.delete(i)
        payload = tree_payload(order_var.get())
        if not payload["ok"]:
            return
        for row in payload["rows"]:
            tree.insert("", "end", iid=f"{row['kind']}-{row['index']}",
                        values=(row["path"], row["kind"], row["size"], row["owner"], row["modified"]))

    def browse():
        p = filedialog.askopenfilename(
            title="Select JCkernel virtual disk",
            filetypes=[
                ("Disk images", "*.qcow2 *.img *.bin *.raw"),
                ("QCOW2", "*.qcow2"),
                ("Raw", "*.img *.bin *.raw"),
                ("All", "*.*"),
            ],
        )
        if p:
            path_var.set(p)
            do_mount(p)

    def do_import():
        if not STATE["ok"]:
            messagebox.showerror(APP_NAME, "Mount a CSF1 disk first.")
            return
        if not STATE["vol"] or not getattr(STATE["vol"].dev, "writable", False):
            messagebox.showerror(APP_NAME, "volume opened read-only")
            return
        p = filedialog.askopenfilename(title="Import any file into CSF1")
        if not p:
            return
        try:
            e = STATE["vol"].add_file(p, dest_var.get())
            messagebox.showinfo(APP_NAME, f"Imported {e.name} into {e.path}")
            refresh()
        except Exception as ex:
            messagebox.showerror(APP_NAME, str(ex))

    def do_remove():
        if not STATE["vol"] or not getattr(STATE["vol"].dev, "writable", False):
            messagebox.showerror(APP_NAME, "volume opened read-only")
            return
        sel = tree.selection()
        if not sel:
            return
        kind, idx = sel[0].split("-", 1)
        if kind != "file":
            messagebox.showinfo(APP_NAME, "Select a file, not a folder.")
            return
        if not messagebox.askyesno(APP_NAME, "Remove this file from CSF1?"):
            return
        try:
            STATE["vol"].remove_file(int(idx))
            refresh()
        except Exception as ex:
            messagebox.showerror(APP_NAME, str(ex))

    def do_export():
        if not STATE["vol"] or not getattr(STATE["vol"].dev, "writable", False):
            messagebox.showerror(APP_NAME, "volume opened read-only")
            return
        sel = tree.selection()
        if not sel:
            return
        kind, idx = sel[0].split("-", 1)
        if kind != "file":
            return
        out = filedialog.asksaveasfilename(title="Export CSF1 file")
        if not out:
            return
        STATE["vol"].export_file(int(idx), out)

    frm = tk.Frame(root, bg="#0e1114")
    frm.pack(fill="x", padx=10, pady=8)
    tk.Entry(frm, textvariable=path_var, width=70, bg="#171c21", fg="#e8edf2",
             insertbackground="#e8edf2").pack(side="left", fill="x", expand=True)
    tk.Button(frm, text="Browse", command=browse).pack(side="left", padx=4)
    tk.Button(frm, text="Mount / Detect", command=lambda: do_mount(), bg="#c45c4a", fg="white").pack(side="left")

    frm2 = tk.Frame(root, bg="#0e1114")
    frm2.pack(fill="x", padx=10)
    tk.Button(frm2, text="A→Z low→high", command=lambda: (order_var.set("az"), refresh())).pack(side="left")
    tk.Button(frm2, text="Z→A high→low", command=lambda: (order_var.set("za"), refresh())).pack(side="left", padx=4)
    tk.Label(frm2, text="Import path:", bg="#0e1114", fg="#8b98a5").pack(side="left", padx=(16, 4))
    tk.Entry(frm2, textvariable=dest_var, width=20, bg="#171c21", fg="#e8edf2").pack(side="left")
    tk.Button(frm2, text="Import file", command=do_import).pack(side="left", padx=4)
    tk.Button(frm2, text="Remove", command=do_remove).pack(side="left")
    tk.Button(frm2, text="Export", command=do_export).pack(side="left", padx=4)

    tk.Label(root, textvariable=status_var, bg="#0e1114", fg="#b7f0cc", anchor="w").pack(fill="x", padx=12)

    cols = ("path", "kind", "size", "owner", "modified")
    tree = ttk.Treeview(root, columns=cols, show="headings")
    for c, w in zip(cols, (420, 70, 80, 90, 160)):
        tree.heading(c, text=c)
        tree.column(c, width=w)
    tree.pack(fill="both", expand=True, padx=10, pady=8)

    def drop_file(event):
        p = event.data.strip("{}") if hasattr(event, "data") else ""
        if p:
            path_var.set(p)
            do_mount(p)

    try:
        root.drop_target_register("DND_Files")
        root.dnd_bind("<<Drop>>", drop_file)
    except Exception:
        pass

    root.mainloop()
    return True


def main():
    if "--inspect" in sys.argv:
        idx = sys.argv.index("--inspect")
        if idx + 1 >= len(sys.argv) or str(sys.argv[idx + 1]).startswith("-"):
            sys.stderr.write("usage: csf1_viewer.py --inspect PATH\n")
            sys.exit(2)
        path = sys.argv[idx + 1]
        try:
            sys.exit(inspect_cli(path))
        except Exception as e:
            sys.stderr.write(str(e) + "\n")
            sys.exit(2)
    if "--web" in sys.argv:
        run_server()
        return
    if "--tk" in sys.argv or os.environ.get("CSF1_VIEWER_UI") == "tk":
        if not try_tk():
            print("tkinter not available, starting web UI")
            run_server()
        return
    # prefer desktop UI when present
    if try_tk():
        return
    run_server()


if __name__ == "__main__":
    main()
