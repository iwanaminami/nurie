#!/usr/bin/env python3
"""nurie（塗るだけ日程調整）サーバ: Python標準ライブラリ + SQLite のみ。
イベント作成 / 参加者の塗り保存 / 共有URL / 主催者キー を実装。"""
import json, re, secrets, sqlite3, os, csv, io, hmac, time, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("NURIE_DB") or os.environ.get("TONTON_DB") or os.path.join(BASE, "nurie.db")
# 旧 tonton.db からの自動移行（同じフォルダにあれば nurie.db へ改名して引き継ぐ）
try:
    _old_db = os.path.join(os.path.dirname(os.path.abspath(DB)), "tonton.db")
    if os.path.abspath(DB) != os.path.abspath(_old_db) and not os.path.exists(DB) and os.path.exists(_old_db):
        os.replace(_old_db, DB)
except OSError:
    pass

PORT = 8378

def db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS events(
        id TEXT PRIMARY KEY, title TEXT, dates TEXT, admin_key TEXT, created_at TEXT,
        start_min INTEGER DEFAULT 0, end_min INTEGER DEFAULT 1440)""")
    cols = [r[1] for r in con.execute("PRAGMA table_info(events)")]
    if "start_min" not in cols:
        con.execute("ALTER TABLE events ADD COLUMN start_min INTEGER DEFAULT 0")
        con.execute("ALTER TABLE events ADD COLUMN end_min INTEGER DEFAULT 1440")
    if "allowed" not in cols:
        con.execute("ALTER TABLE events ADD COLUMN allowed TEXT")
    if "kind" not in cols:
        con.execute("ALTER TABLE events ADD COLUMN kind TEXT DEFAULT 'time'")
    con.execute("""CREATE TABLE IF NOT EXISTS paints(
        event_id TEXT, name TEXT, marks TEXT, updated_at TEXT,
        PRIMARY KEY(event_id, name))""")
    pcols = [r[1] for r in con.execute("PRAGMA table_info(paints)")]
    if "note" not in pcols:
        con.execute("ALTER TABLE paints ADD COLUMN note TEXT DEFAULT ''")
    return con

def jbody(h):
    n = int(h.headers.get("Content-Length") or 0)
    if n < 0 or n > 200_000: raise ValueError("bad length")
    return json.loads(h.rfile.read(n) or b"{}")


def cleanup_expired():
    con = db()
    con.execute("DELETE FROM paints WHERE event_id IN (SELECT id FROM events WHERE created_at < datetime('now','-30 days'))")
    con.execute("DELETE FROM events WHERE created_at < datetime('now','-30 days')")
    con.commit(); con.close()

CREATE_PAGE = """<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>nurie｜塗るだけ日程調整</title>
<meta name="description" content="ドラッグで塗るだけの日程調整。候補日と空き時間を塗ると、みんなの空きが一目で分かります。登録不要・無料。">
<meta name="theme-color" content="#c8102e">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20viewBox%3D%270%200%2064%2064%27%3E%3Crect%20width%3D%2764%27%20height%3D%2764%27%20rx%3D%2714%27%20fill%3D%27%23c8102e%27%2F%3E%3Ccircle%20cx%3D%2732%27%20cy%3D%2732%27%20r%3D%2714%27%20fill%3D%27none%27%20stroke%3D%27%23fff%27%20stroke-width%3D%277%27%2F%3E%3C%2Fsvg%3E">
<meta property="og:site_name" content="nurie">
<meta property="og:title" content="nurie｜塗るだけ日程調整">
<meta property="og:description" content="ドラッグで塗るだけの日程調整。候補日と空き時間を塗ると、みんなの空きが一目で分かります。登録不要・無料。">
<meta property="og:type" content="website">
<meta property="og:url" content="https://nurie.noweb.page/">
<meta property="og:image" content="https://nurie.noweb.page/ogp.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="https://nurie.noweb.page/ogp.png">
<meta name="twitter:title" content="nurie｜塗るだけ日程調整">
<meta name="twitter:description" content="ドラッグで塗るだけの日程調整。候補日と空き時間を塗ると、みんなの空きが一目で分かります。登録不要・無料。"><link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&family=Noto+Sans+JP:wght@400;500;700&display=swap" rel="stylesheet">
<style>body{font-family:"Google Sans","Noto Sans JP",system-ui,-apple-system,"Hiragino Kaku Gothic ProN",sans-serif;margin:24px auto;padding:0 16px;max-width:860px;color:#1e293b;background:#f6f8fc;-webkit-text-size-adjust:100%}
h1{text-align:center;font-size:20px} h2{font-size:15px;margin:22px 0 6px}
.sub{font-size:12.5px;color:#64748b;text-align:center}
label{display:block;margin:14px 0 4px;font-size:13px;color:#64748b}
input{padding:9px;border:1px solid #cbd5e1;border-radius:9px;font-size:15px;box-sizing:border-box;width:100%;background:#fff;color:inherit}
.calnav{display:flex;gap:8px;align-items:center;justify-content:center;margin:8px 0}
.calnav b{min-width:110px;text-align:center}
.calnav button{border:1px solid #cbd5e1;background:#fff;border-radius:8px;height:32px;padding:0 12px;cursor:pointer;color:inherit;font-size:13px}
table.cal{border-collapse:collapse;margin:0 auto;user-select:none;-webkit-user-select:none;touch-action:none}
table.cal th,table.cal td{width:40px;height:38px;text-align:center;border:1px solid #e3e3e3;font-size:13px;background:#fff}
table.cal td{cursor:pointer}
table.cal td.sel{background:#c8102e;color:#fff;font-weight:bold}
table.cal td.dim{color:#c3cad4;background:#fafbfc}
table.cal td.sun{color:#dc2626} table.cal td.sat{color:#2563eb}
table.cal td.sel.sun,table.cal td.sel.sat{color:#fff}
.gwrap{overflow-x:auto;border:1px solid #ddd;border-radius:10px;background:#fff}
table.grid{border-collapse:collapse;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;table-layout:fixed;width:max-content}
table.grid th,table.grid td{border:1px solid #e3e3e3;text-align:center;font-size:10.5px;padding:0;box-sizing:border-box}
table.grid th.day{width:66px;min-width:66px;position:sticky;left:0;background:#f7f7f7;z-index:2;height:26px}
table.grid th.time{width:22px;min-width:22px;height:22px;position:relative;font-weight:normal}
table.grid th.time .tick{position:absolute;left:0;top:3px;transform:translateX(-50%);white-space:nowrap}
table.grid td.c{width:22px;min-width:22px;height:26px;cursor:cell;touch-action:none;background:#fff}
table.grid td.c.on{background:#f3a7b1}
table.grid td.c.hourL{border-left:2px solid #d9b3ba}
button.go{display:block;margin:20px auto 30px;background:#c8102e;color:#fff;border:none;padding:12px 44px;border-radius:10px;font-size:15px;cursor:pointer}
.err{color:#dc2626;font-size:13px;text-align:center}
@media (prefers-color-scheme:dark){body{background:#101216;color:#e8eaee}
input{background:#1d2129;border-color:#3a4152}
.calnav button{background:#1d2129;border-color:#3a4152}
table.cal th,table.cal td{border-color:#262c38;background:#15181e}
table.cal td.dim{background:#101216;color:#454c58}
table.grid th,table.grid td{border-color:#262c38}
table.grid th.day{background:#1d2129}
table.grid td.c{background:#15181e}
table.grid td.c.on{background:#7c1626}
.gwrap{background:#15181e;border-color:#333a48}}
body[data-theme="dark"]{background:#101216;color:#e8eaee}
body[data-theme="dark"] input{background:#1d2129;border-color:#3a4152}
body[data-theme="dark"] .calnav button{background:#1d2129;border-color:#3a4152}
body[data-theme="dark"] table.cal th{border-color:#262c38;background:#15181e}
body[data-theme="dark"] table.cal td{border-color:#262c38;background:#15181e}
body[data-theme="dark"] table.cal td.dim{background:#101216;color:#454c58}
body[data-theme="dark"] table.grid th{border-color:#262c38}
body[data-theme="dark"] table.grid td{border-color:#262c38}
body[data-theme="dark"] table.grid th.day{background:#1d2129}
body[data-theme="dark"] table.grid td.c{background:#15181e}
body[data-theme="dark"] table.grid td.c.on{background:#7c1626}
body[data-theme="dark"] .gwrap{background:#15181e;border-color:#333a48}
body[data-theme="dark"] select.ctl{background-color:#1d2129;border-color:#3a4152}
body[data-theme="dark"] table.cal td.sel{background:#c8102e;color:#fff}
body[data-theme="dark"]{background:#101216;color:#e8eaee}
body[data-theme="light"] input{background:#fff}
body[data-theme="light"] .calnav button{background:#fff}
body[data-theme="light"] table.cal td.dim{background:#fafbfc;color:#c3cad4}
body[data-theme="light"] table.grid th.day{background:#f7f7f7}
body[data-theme="light"] table.grid td.c{background:#fff}
body[data-theme="light"] table.grid td.c.on{background:#f3a7b1}
body[data-theme="light"] .gwrap{background:#fff}
body[data-theme="light"] select.ctl{background-color:#fff}


body[data-theme="light"]{background:#f6f8fc;color:#1e293b}

body[data-theme="light"] input{border-color:#cbd5e1}
body[data-theme="light"] .calnav button{border-color:#cbd5e1}
body[data-theme="light"] table.cal th,body[data-theme="light"] table.cal td{border-color:#e3e3e3;background:#fff}
body[data-theme="light"] table.cal td.dim{background:#fafbfc}
body[data-theme="light"] table.cal td.sel{background:#c8102e}
body[data-theme="light"] table.grid th,body[data-theme="light"] table.grid td{border-color:#e3e3e3}
body[data-theme="light"] table.grid td.c.hourL{border-left-color:#d9b3ba}
body[data-theme="light"] .gwrap{border-color:#ddd}
body[data-theme="light"] input,body[data-theme="light"] select{color:#1e293b}
body[data-theme="light"] #themeBtn{background:#fff;color:#1e293b}
body[data-theme="dark"] #themeBtn{background:#1d2129;color:#e8eaee;border-color:#3a4152}
/* 横スクロールバーは枠の下側の帯に出し、色をテーマに合わせる */
.gframe{border:1px solid #ddd;border-radius:10px;background:#fff;overflow:hidden;position:relative}
.gfadeR{position:absolute;top:0;right:0;bottom:16px;width:44px;pointer-events:none;background:linear-gradient(to right,rgba(255,255,255,0),rgba(200,120,130,.30));transition:opacity .25s}
.gfadeL{position:absolute;top:0;bottom:16px;width:44px;pointer-events:none;left:66px;background:linear-gradient(to left,rgba(255,255,255,0),rgba(200,120,130,.30));transition:opacity .25s;opacity:0}
@media (prefers-color-scheme:dark){.gfadeR{background:linear-gradient(to right,rgba(16,18,22,0),rgba(200,100,115,.35))}.gfadeL{background:linear-gradient(to left,rgba(16,18,22,0),rgba(200,100,115,.35))}}
body[data-theme="dark"] .gfadeR{background:linear-gradient(to right,rgba(16,18,22,0),rgba(200,100,115,.35))}
body[data-theme="dark"] .gfadeL{background:linear-gradient(to left,rgba(16,18,22,0),rgba(200,100,115,.35))}
body[data-theme="light"] .gfadeR{background:linear-gradient(to right,rgba(255,255,255,0),rgba(200,120,130,.30))}
body[data-theme="light"] .gfadeL{background:linear-gradient(to left,rgba(255,255,255,0),rgba(200,120,130,.30))}
.gwrap{border:none;border-radius:0;background:transparent;padding-bottom:16px;scrollbar-width:thin;scrollbar-color:#dfa7b0 transparent}
.gwrap::-webkit-scrollbar{height:8px}
.gwrap::-webkit-scrollbar-track{background:transparent}
.gwrap::-webkit-scrollbar-thumb{background:#dfa7b0;border-radius:99px}
.gwrap::-webkit-scrollbar-thumb:hover{background:#c8102e}
@media (prefers-color-scheme:dark){.gframe{border-color:#333a48;background:#15181e}.gwrap{scrollbar-color:#7a4a55 transparent}.gwrap::-webkit-scrollbar-thumb{background:#7a4a55}}
body[data-theme="dark"] .gframe{border-color:#333a48;background:#15181e}
body[data-theme="dark"] .gwrap{scrollbar-color:#7a4a55 transparent}
body[data-theme="dark"] .gwrap::-webkit-scrollbar-thumb{background:#7a4a55}
body[data-theme="light"] .gframe{border-color:#ddd;background:#fff}
body[data-theme="light"] .gwrap{scrollbar-color:#dfa7b0 transparent}
body[data-theme="light"] .gwrap::-webkit-scrollbar-thumb{background:#dfa7b0}
#themeBtn{position:fixed;top:10px;right:12px;z-index:60;width:38px;height:38px;border-radius:50%;border:1px solid #cbd5e1;background:#fff;font-size:17px;cursor:pointer;box-shadow:0 2px 8px rgba(30,41,59,.18);padding:0}
</style></head><body>
<script>try{var t=localStorage.getItem('nurie-theme');if(t)document.body.dataset.theme=t;}catch(e){}</script>
<button id="themeBtn" title="ダークモード切替">🌙</button>
<style>.logoD{display:none}@media (prefers-color-scheme:dark){.logoL{display:none!important}.logoD{display:inline!important}}body[data-theme="dark"] .logoL{display:none!important}body[data-theme="dark"] .logoD{display:inline!important}body[data-theme="light"] .logoL{display:inline!important}body[data-theme="light"] .logoD{display:none!important}</style><div style="text-align:center;margin:0 0 10px"><a href="/" style="text-decoration:none;display:inline-block"><img class="logoL" src="/logo.png" alt="nurie" style="height:30px;vertical-align:middle"><img class="logoD" src="/logo-dark.png" alt="nurie" style="height:30px;vertical-align:middle;display:none"></a></div>
<h1>日程調整をつくる</h1>
<style>
.kindSeg{display:flex;background:#eef2f7;border-radius:10px;padding:3px;gap:2px}
.kindSeg button{border:none;background:transparent;padding:8px 18px;border-radius:8px;font-size:14px;cursor:pointer;color:inherit;font-family:inherit}
.kindSeg button.on{background:#c8102e;color:#fff;font-weight:700}
@media (prefers-color-scheme:dark){.kindSeg{background:#232833}}
body[data-theme="dark"] .kindSeg{background:#232833}
body[data-theme="light"] .kindSeg{background:#eef2f7}
</style>
<div style="display:flex;justify-content:center;margin:8px 0 4px"><div class="kindSeg"><button type="button" id="kindTime" class="on">🕐 時間で調整</button><button type="button" id="kindDate">📅 日だけで調整</button></div></div>
<label>タイトル</label><input id="title" placeholder="例：研究室 打ち合わせ">
<h2>① 候補日を塗る</h2>
<div class="calnav"><button id="prevM" type="button">◀</button><b id="calTitle"></b><button id="nextM" type="button">▶</button></div>
<table class="cal" id="cal"></table>
<div id="step2wrap"><h2>② まずデフォルトの時間を全日に適用</h2>
<style>
.ctl{height:36px;box-sizing:border-box;font-size:14px;border-radius:9px}
select.ctl{appearance:none;-webkit-appearance:none;border:1px solid #c3cad6;background-color:#fff;color:inherit;padding:0 30px 0 12px;cursor:pointer;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path d='M1 1l4 4 4-4' stroke='%2364748b' stroke-width='1.6' fill='none' stroke-linecap='round'/></svg>");
  background-repeat:no-repeat;background-position:right 10px center}
button.ctl{border:1px solid #c8102e;background:#c8102e;color:#fff;padding:0 16px;cursor:pointer;font-weight:600}
@media (prefers-color-scheme:dark){select.ctl{background-color:#1d2129;border-color:#3a4152}}
</style>
<div class="gframe"><div class="gwrap"><table class="grid" id="tgrid2"></table></div><div class="gfadeL"></div><div class="gfadeR"></div></div>
<div style="text-align:center;margin:10px 0 2px"><button id="applyDef" type="button" class="ctl">塗った時間を全日に適用</button></div>
</div><div id="step3wrap"><h2>③ 仕上げに時間を塗る</h2>
<div class="gframe"><div class="gwrap"><table class="grid" id="tgrid"></table></div><div class="gfadeL"></div><div class="gfadeR"></div></div>
</div>
<button class="go" id="go">この内容で作成する</button><p class="err" id="err"></p>
<div style="text-align:center;font-size:12px;color:#94a3b8;margin:26px 0 8px"><a href="/privacy" style="color:inherit">プライバシーポリシー</a>｜<a href="/terms" style="color:inherit">利用規約</a>｜<a href="https://forms.gle/SVbQobSbyKk2UpJQ6" target="_blank" rel="noopener" style="color:inherit">お問い合わせ</a>｜<a href="https://github.com/nurie-nuru/nurie" target="_blank" rel="noopener" style="color:inherit">GitHub</a></div>
<script>
const themeBtn=document.getElementById('themeBtn');
function applyTheme(){
  const t=(localStorage.getItem('nurie-theme')||localStorage.getItem('tonton-theme'));
  if(t){ document.body.dataset.theme=t; } else { delete document.body.dataset.theme; }
  const dark=t? (t==='dark') : matchMedia('(prefers-color-scheme: dark)').matches;
  themeBtn.textContent=dark?'☀️':'🌙';
}
themeBtn.addEventListener('click',()=>{
  const darkNow=document.body.dataset.theme? (document.body.dataset.theme==='dark') : matchMedia('(prefers-color-scheme: dark)').matches;
  localStorage.setItem('nurie-theme', darkNow?'light':'dark');
  applyTheme();
});
applyTheme();
const SLOT=30, slots=[]; for(let m=0;m<24*60;m+=SLOT) slots.push(m);
const fmt=m=>String(Math.floor(m/60)).padStart(2,'0')+':'+String(m%60).padStart(2,'0');
const iso=d=>d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
const chosen=new Set();       // 候補日 'YYYY-MM-DD'
const allowed=new Set();      // 選択可能なセル 'YYYY-MM-DD|slot'
let viewD=new Date(); viewD.setDate(1);
// カレンダー
const cal=document.getElementById('cal'), calTitle=document.getElementById('calTitle');
let calPaint=null, calDrag=false;
function renderCal(){
  const y=viewD.getFullYear(), mo=viewD.getMonth();
  calTitle.textContent=y+'年 '+(mo+1)+'月';
  cal.innerHTML='';
  const hr=document.createElement('tr');
  '日月火水木金土'.split('').forEach(w=>{const th=document.createElement('th'); th.textContent=w; hr.appendChild(th);});
  cal.appendChild(hr);
  const first=new Date(y,mo,1), startDay=first.getDay(), dim=new Date(y,mo+1,0).getDate();
  let dnum=1;
  for(let r=0;r<6&&dnum<=dim;r++){
    const tr=document.createElement('tr');
    for(let c=0;c<7;c++){
      const td=document.createElement('td');
      if((r===0&&c<startDay)||dnum>dim){ td.className='dim'; tr.appendChild(td); continue; }
      const d=new Date(y,mo,dnum), key=iso(d);
      td.textContent=dnum;
      if(c===0) td.classList.add('sun'); if(c===6) td.classList.add('sat');
      if(chosen.has(key)) td.classList.add('sel');
      td.dataset.k=key;
      td.addEventListener('pointerdown',e=>{ e.preventDefault(); calDrag=true; dragCtx='cal'; prevPt={x:e.clientX,y:e.clientY};
        calPaint=!chosen.has(key); applyCal(key,td); });
      dnum++; tr.appendChild(td);
    }
    cal.appendChild(tr);
  }
}
function applyCal(key,td){
  if(calPaint){ if(!chosen.has(key)){ if(chosen.size>=31){ document.getElementById('err').textContent='候補日は31日までです'; return; }
      chosen.add(key); slots.forEach((_,si)=>allowed.add(key+'|'+si)); } }
  else { chosen.delete(key); [...allowed].forEach(k=>{ if(k.startsWith(key+'|')) allowed.delete(k); }); }
  td.classList.toggle('sel',chosen.has(key));
  calDirty=true;
}
document.addEventListener('pointerup',()=>{ calDrag=false; calPaint=null; });
document.getElementById('prevM').onclick=()=>{ viewD.setMonth(viewD.getMonth()-1); renderCal(); };
document.getElementById('nextM').onclick=()=>{ viewD.setMonth(viewD.getMonth()+1); renderCal(); };
// 時間グリッド
const tgrid=document.getElementById('tgrid');
let tPaint=null, tDrag=false;
function dayLabel(ds){ const d=new Date(ds+'T00:00:00'); return (d.getMonth()+1)+'/'+d.getDate()+'（'+'日月火水木金土'[d.getDay()]+'）'; }
function renderTimeGrid(){
  tgrid.innerHTML='';
  const days=[...chosen].sort();
  const hr=document.createElement('tr');
  hr.appendChild(document.createElement('th'));
  slots.forEach(m=>{ const th=document.createElement('th'); th.className='time';
    if(m%60===0){ const sp=document.createElement('span'); sp.className='tick'; sp.textContent=fmt(m); th.appendChild(sp); } hr.appendChild(th); });
  tgrid.appendChild(hr);
  days.forEach(ds=>{
    const tr=document.createElement('tr');
    const th=document.createElement('th'); th.className='day'; th.textContent=dayLabel(ds); tr.appendChild(th);
    slots.forEach((_,si)=>{
      const td=document.createElement('td'); td.className='c'+(slots[si]%60===0?' hourL':'');
      const key=ds+'|'+si;
      if(allowed.has(key)) td.classList.add('on');
      td.dataset.k=key;
      td.addEventListener('pointerdown',e=>{ e.preventDefault(); tDrag=true; dragCtx='time'; prevPt={x:e.clientX,y:e.clientY};
        tPaint=!allowed.has(key); applyT(key,td); });
      tr.appendChild(td);
    });
    tgrid.appendChild(tr);
  });
  // 初期表示は8:00を左端に
  const wrap=tgrid.parentElement, ths=tgrid.querySelectorAll('th.time');
  if(ths[16]) wrap.scrollLeft=ths[16].offsetLeft;
  if(typeof gridFadeUpdaters!=='undefined') gridFadeUpdaters.forEach(f=>f());
}
function applyT(key,td){
  if(tPaint) allowed.add(key); else allowed.delete(key);
  td.classList.toggle('on',allowed.has(key));
}
document.addEventListener('pointerup',()=>{ tDrag=false; tPaint=null; });
// デフォルト時間は1日分のストリップを塗って決める（初期値は塗りなし）
const defAllowed=new Set();
const tgrid2=document.getElementById('tgrid2');
let dPaint=null, dDrag2=false;
function renderDefGrid(){
  tgrid2.innerHTML='';
  const hr=document.createElement('tr');
  hr.appendChild(document.createElement('th'));
  slots.forEach(m=>{ const th=document.createElement('th'); th.className='time';
    if(m%60===0){ const sp=document.createElement('span'); sp.className='tick'; sp.textContent=fmt(m); th.appendChild(sp); } hr.appendChild(th); });
  tgrid2.appendChild(hr);
  const tr=document.createElement('tr');
  const th=document.createElement('th'); th.className='day'; th.textContent='時間'; tr.appendChild(th);
  slots.forEach((m,si)=>{
    const td=document.createElement('td'); td.className='c'+(m%60===0?' hourL':'');
    if(defAllowed.has(si)) td.classList.add('on');
    td.dataset.si=si;
    td.addEventListener('pointerdown',e=>{ e.preventDefault(); dDrag2=true; dragCtx='def'; prevPt={x:e.clientX,y:e.clientY};
      dPaint=!defAllowed.has(si); applyDefCell(si,td); });
    tr.appendChild(td);
  });
  tgrid2.appendChild(tr);
  const wrap2=tgrid2.parentElement, ths=tgrid2.querySelectorAll('th.time');
  if(ths[16]) wrap2.scrollLeft=ths[16].offsetLeft;
  if(typeof gridFadeUpdaters!=='undefined') gridFadeUpdaters.forEach(f=>f());
}
function applyDefCell(si,td){
  if(dPaint) defAllowed.add(si); else defAllowed.delete(si);
  td.classList.toggle('on',defAllowed.has(si));
}
document.addEventListener('pointerup',()=>{ dDrag2=false; dPaint=null; });
document.getElementById('applyDef').onclick=()=>{
  const err=document.getElementById('err');
  if(!chosen.size){ err.textContent='先に候補日を塗ってください'; return; }
  if(!defAllowed.size){ err.textContent='時間を1マス以上塗ってください'; return; }
  [...chosen].forEach(ds=>{
    [...allowed].forEach(k=>{ if(k.startsWith(ds+'|')) allowed.delete(k); });
    defAllowed.forEach(si=>allowed.add(ds+'|'+si));
  });
  err.textContent='';
  renderTimeGrid();
};
let kind='time';
const kindTime=document.getElementById('kindTime'), kindDate=document.getElementById('kindDate');
function setKind(k){ kind=k;
  kindTime.classList.toggle('on',k==='time'); kindDate.classList.toggle('on',k==='date');
  document.getElementById('step2wrap').style.display=(k==='time')?'':'none';
  document.getElementById('step3wrap').style.display=(k==='time')?'':'none';
}
kindTime.addEventListener('click',()=>setKind('time'));
kindDate.addEventListener('click',()=>setKind('date'));
// ドラッグ塗りは回答画面と同じ方式：pointermove を rAF で間引き、軌跡を8px刻みで補間してマスを取りこぼさない
let dragCtx=null, prevPt=null, lastPt=null, moveQ=false, calDirty=false;
document.addEventListener('pointermove',e=>{
  if(!dragCtx) return;
  lastPt={x:e.clientX,y:e.clientY};
  if(moveQ) return; moveQ=true;
  requestAnimationFrame(()=>{
    moveQ=false; if(!dragCtx||!lastPt||!prevPt) return;
    const dx=lastPt.x-prevPt.x, dy=lastPt.y-prevPt.y;
    const steps=Math.max(1,Math.ceil(Math.hypot(dx,dy)/8));
    for(let i=1;i<=steps;i++){
      const el=document.elementFromPoint(prevPt.x+dx*i/steps, prevPt.y+dy*i/steps);
      if(!el||!el.closest) continue;
      if(dragCtx==='cal'){ const td=el.closest('td[data-k]'); if(td&&td.closest('table.cal')) applyCal(td.dataset.k,td); }
      else if(dragCtx==='time'){ const td=el.closest('td[data-k]'); if(td&&td.closest('#tgrid')) applyT(td.dataset.k,td); }
      else if(dragCtx==='def'){ const td=el.closest('td[data-si]'); if(td&&td.closest('#tgrid2')) applyDefCell(+td.dataset.si,td); }
    }
    prevPt=lastPt;
  });
});
function endCreateDrag(){ dragCtx=null; prevPt=null; lastPt=null;
  if(calDirty){ calDirty=false; renderTimeGrid(); } }
document.addEventListener('pointerup',endCreateDrag);
document.addEventListener('pointercancel',endCreateDrag);
function attachGridFades(frame){
  const wrap=frame.querySelector('.gwrap'), fL=frame.querySelector('.gfadeL'), fR=frame.querySelector('.gfadeR');
  const upd=()=>{ const max=wrap.scrollWidth-wrap.clientWidth;
    fR.style.opacity=(max>2 && wrap.scrollLeft<max-2)?'1':'0';
    fL.style.opacity=(wrap.scrollLeft>2)?'1':'0'; };
  wrap.addEventListener('scroll',upd,{passive:true});
  return upd;
}
const gridFadeUpdaters=[...document.querySelectorAll('.gframe')].map(attachGridFades);
setKind('time');
renderCal(); renderTimeGrid(); renderDefGrid();
gridFadeUpdaters.forEach(f=>f());
document.getElementById('go').onclick=async()=>{
  const err=document.getElementById('err');
  const title=document.getElementById('title').value.trim()||'（無題）';
  if(!chosen.size){ err.textContent='候補日を1日以上塗ってください'; return; }
  if(kind==='time' && !allowed.size){ err.textContent='選択できる時間を1マス以上残してください'; return; }
  const payload={title,dates:[...chosen],kind};
  if(kind==='time') payload.allowed=[...allowed];
  const r=await fetch('/api/events',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload)});
  if(!r.ok){ let msg='作成に失敗しました';
    if(r.status===429){ const j=await r.json().catch(()=>null); if(j&&j.error) msg=j.error; }
    err.textContent=msg; return; }
  const j=await r.json();
  location.href='/e/'+j.id+'?admin='+j.adminKey;
};
</script></body></html>"""

NOT_FOUND_PAGE = """<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>見つかりません | nurie</title>
<meta name="description" content="ドラッグで塗るだけの日程調整。候補日と空き時間を塗ると、みんなの空きが一目で分かります。登録不要・無料。">
<meta name="theme-color" content="#c8102e">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20viewBox%3D%270%200%2064%2064%27%3E%3Crect%20width%3D%2764%27%20height%3D%2764%27%20rx%3D%2714%27%20fill%3D%27%23c8102e%27%2F%3E%3Ccircle%20cx%3D%2732%27%20cy%3D%2732%27%20r%3D%2714%27%20fill%3D%27none%27%20stroke%3D%27%23fff%27%20stroke-width%3D%277%27%2F%3E%3C%2Fsvg%3E">
<meta property="og:site_name" content="nurie">
<meta property="og:title" content="nurie｜塗るだけ日程調整">
<meta property="og:description" content="ドラッグで塗るだけの日程調整。候補日と空き時間を塗ると、みんなの空きが一目で分かります。登録不要・無料。">
<meta property="og:type" content="website">
<meta property="og:url" content="https://nurie.noweb.page/">
<meta property="og:image" content="https://nurie.noweb.page/ogp.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="https://nurie.noweb.page/ogp.png">
<meta name="twitter:title" content="nurie｜塗るだけ日程調整">
<meta name="twitter:description" content="ドラッグで塗るだけの日程調整。候補日と空き時間を塗ると、みんなの空きが一目で分かります。登録不要・無料。"><link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&family=Noto+Sans+JP:wght@400;500;700&display=swap" rel="stylesheet">
<style>body{font-family:"Google Sans","Noto Sans JP",system-ui,-apple-system,"Hiragino Kaku Gothic ProN",sans-serif;margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;color:#1e293b;background:#f6f8fc;text-align:center}
@media (prefers-color-scheme:dark){body{background:#101216;color:#e8eaee}}
body[data-theme="dark"]{background:#101216;color:#e8eaee}
body[data-theme="light"]{background:#f6f8fc;color:#1e293b}
.box{padding:32px 24px}
.big{font-size:56px}
h1{font-size:20px;margin:10px 0 6px}
p{color:#64748b;font-size:14px;line-height:1.7}
a.btn{display:inline-block;margin-top:16px;background:#c8102e;color:#fff;text-decoration:none;padding:10px 22px;border-radius:10px;font-size:14px}</style></head><body>
<div class="box"><div class="big">🗓️💨</div><style>.logoD{display:none}@media (prefers-color-scheme:dark){.logoL{display:none!important}.logoD{display:inline!important}}body[data-theme="dark"] .logoL{display:none!important}body[data-theme="dark"] .logoD{display:inline!important}body[data-theme="light"] .logoL{display:inline!important}body[data-theme="light"] .logoD{display:none!important}</style><div style="text-align:center;margin:0 0 10px"><a href="/" style="text-decoration:none;display:inline-block"><img class="logoL" src="/logo.png" alt="nurie" style="height:30px;vertical-align:middle"><img class="logoD" src="/logo-dark.png" alt="nurie" style="height:30px;vertical-align:middle;display:none"></a></div>
<h1>調整表が見つかりません</h1>
<p>URLが間違っているか、主催者によって削除された可能性があります。<br>共有されたURLをもう一度確認してください。</p>
<a class="btn" href="/">新しい調整表をつくる</a></div></body></html>"""


def _legal(title, body):
    return LEGAL_TEMPLATE.replace("{title}", title).replace("{body}", body)

LEGAL_TEMPLATE = '<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>{title}｜nurie</title>\n<link rel="apple-touch-icon" href="/apple-touch-icon.png">\n<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20viewBox%3D%270%200%2064%2064%27%3E%3Crect%20width%3D%2764%27%20height%3D%2764%27%20rx%3D%2714%27%20fill%3D%27%23c8102e%27%2F%3E%3Ccircle%20cx%3D%2732%27%20cy%3D%2732%27%20r%3D%2714%27%20fill%3D%27none%27%20stroke%3D%27%23fff%27%20stroke-width%3D%277%27%2F%3E%3C%2Fsvg%3E">\n<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&family=Noto+Sans+JP:wght@400;500;700;900&display=swap" rel="stylesheet">\n<style>body{font-family:"Google Sans","Noto Sans JP",system-ui,sans-serif;margin:24px auto;padding:0 16px;max-width:760px;color:#1e293b;background:#f6f8fc;line-height:1.8}\nh1{text-align:center;font-size:20px} h2{font-size:15.5px;margin-top:26px}\np,li{font-size:14px} .box{background:#fff;border:1px solid #e3e3e3;border-radius:12px;padding:20px 26px 26px}\nfooter{text-align:center;font-size:12.5px;color:#64748b;margin:22px 0} a{color:#a50d26}\n@media (prefers-color-scheme:dark){body{background:#101216;color:#e8eaee} .box{background:#15181e;border-color:#262c38} a{color:#f3a7b1}}\n</style></head><body>\n<style>.logoD{display:none}@media (prefers-color-scheme:dark){.logoL{display:none!important}.logoD{display:inline!important}}body[data-theme="dark"] .logoL{display:none!important}body[data-theme="dark"] .logoD{display:inline!important}body[data-theme="light"] .logoL{display:inline!important}body[data-theme="light"] .logoD{display:none!important}</style><div style="text-align:center;margin:0 0 10px"><a href="/" style="text-decoration:none;display:inline-block"><img class="logoL" src="/logo.png" alt="nurie" style="height:30px;vertical-align:middle"><img class="logoD" src="/logo-dark.png" alt="nurie" style="height:30px;vertical-align:middle;display:none"></a></div>\n<div class="box"><h1>{title}</h1>\n{body}\n</div>\n<footer><a href="/">トップへ戻る</a>｜<a href="/privacy">プライバシーポリシー</a>｜<a href="/terms">利用規約</a>｜<a href="https://forms.gle/SVbQobSbyKk2UpJQ6" target="_blank" rel="noopener">お問い合わせ</a>｜<a href="https://github.com/nurie-nuru/nurie" target="_blank" rel="noopener">GitHub</a></footer>\n</body></html>'

PRIVACY_PAGE = _legal("プライバシーポリシー", '\n<h2>取得する情報</h2>\n<p>本サービスでは、日程調整のために以下の情報を取得・保存します。</p>\n<ul>\n<li>調整表のタイトル、候補日、選択可能な時間帯</li>\n<li>参加者の名前、各時間帯への回答（空き状況）、任意の一言コメント</li>\n<li>調整表の作成日時</li>\n</ul>\n<p>アカウント登録は不要で、メールアドレス等の連絡先は取得しません。参加者の名前とテーマ設定（ダークモード等）の保持のために、お使いのブラウザのローカルストレージを使用します。</p>\n<h2>利用目的</h2>\n<p>取得した情報は、日程調整表の表示・集計のためにのみ使用します。</p>\n<h2>保存期間</h2>\n<p>調整表は作成から30日で自動的に削除されます。主催者は管理用URLからいつでも削除できます。</p>\n<h2>運営者によるアクセスについて</h2>\n<p>本サービスのデータは暗号化されておらず、サービス運営者は保守・運用のために保存されたデータ（タイトル、名前、回答内容）を閲覧できる状態にあります。機密性の高い内容の入力はお控えください。</p>\n<h2>第三者提供</h2>\n<p>法令に基づく場合を除き、取得した情報を第三者に提供しません。</p>\n<h2>アクセス解析・広告</h2>\n<p>本サービスでは、アクセス解析ツールおよび広告配信を利用していません（導入する場合は本ポリシーを改定します）。</p>\n<h2>お問い合わせ</h2>\n<p>本ポリシーに関するお問い合わせは、<a href="https://forms.gle/SVbQobSbyKk2UpJQ6" target="_blank" rel="noopener">お問い合わせフォーム</a>からご連絡ください。</p>\n')
TERMS_PAGE = _legal("利用規約", '\n<h2>サービス内容</h2>\n<p>nurie は、候補日と空き時間を塗る形式で日程調整を行う無料のウェブサービスです。調整表は作成から30日間保存され、期間を過ぎると自動的に削除されます。</p>\n<h2>管理用URLについて</h2>\n<p>調整表を作成すると、削除等ができる管理用URLが発行されます。管理用URLを知る人は主催者とみなされます。URLの管理はご自身の責任で行ってください。</p>\n<h2>禁止事項</h2>\n<ul>\n<li>法令または公序良俗に反する内容の入力</li>\n<li>他の利用者や第三者へのなりすまし、誹謗中傷</li>\n<li>サービスの運営を妨げる行為（過剰な自動アクセス、脆弱性の悪用等）</li>\n<li>スパム目的での大量作成</li>\n</ul>\n<h2>免責</h2>\n<p>本サービスは現状のまま提供されます。データの消失、サービスの中断・終了、その他本サービスの利用により生じた損害について、運営者は、運営者の故意または重大な過失による場合および法令により免責が認められない場合を除き、責任を負いません。本サービスのデータは暗号化されておらず、第三者に閲覧される可能性を完全には排除できないため、機密性の高い内容の入力はお控えください。重要な日程の調整では、確定した日時を別途控えておくことをおすすめします。</p>\n<h2>規約の変更</h2>\n<p>運営者は、必要に応じて本規約を変更できます。変更後の規約は、本ページに掲載した時点で効力を生じます。</p>\n<h2>お問い合わせ</h2>\n<p>本サービスに関するお問い合わせは、<a href="https://forms.gle/SVbQobSbyKk2UpJQ6" target="_blank" rel="noopener">お問い合わせフォーム</a>からご連絡ください。</p>\n')

EVENT_PAGE = open(os.path.join(BASE, "event.html"), encoding="utf-8").read()

def _csv_safe(v):
    """CSV数式インジェクション対策：先頭（空白類を除く）が = + - @ のセルは ' を前置する。"""
    s = str(v)
    t = s.lstrip(" \t\r\n")
    if t and t[0] in "=+-@":
        return "'" + s
    return s


# イベント作成のレート制限（メモリ内保持。サーバ再起動でリセットされる）
_RATE_LOCK = threading.Lock()
_RATE_BY_IP = {}
_RATE_ALL = []

def _rate_limited(ip):
    now = time.time()
    with _RATE_LOCK:
        _RATE_ALL[:] = [t for t in _RATE_ALL if now - t < 86400]
        if len(_RATE_ALL) >= 1000:
            return True
        lst = _RATE_BY_IP.get(ip)
        if lst:
            lst[:] = [t for t in lst if now - t < 86400]
            if len(lst) >= 100:
                return True
            if sum(1 for t in lst if now - t < 3600) >= 20:
                return True
    return False

def _rate_record(ip):
    now = time.time()
    with _RATE_LOCK:
        _RATE_BY_IP.setdefault(ip, []).append(now)
        _RATE_ALL.append(now)


class H(BaseHTTPRequestHandler):
    timeout = 10
    def log_message(self, *a): pass
    def _sec(self):
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self._sec()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def send_html(self, code, html, noindex=False):
        body = html.encode()
        self.send_response(code)
        self._sec()
        if noindex:
            self.send_header("X-Robots-Tag", "noindex")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def send_csv(self, eid, text):
        body = text.encode("utf-8")
        self.send_response(200)
        self._sec()
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="nurie-%s.csv"' % eid)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        p = urlparse(self.path)
        if p.path == "/":
            return self.send_html(200, CREATE_PAGE)
        if p.path == "/privacy": return self.send_html(200, PRIVACY_PAGE, noindex=True)
        if p.path == "/terms": return self.send_html(200, TERMS_PAGE, noindex=True)
        if p.path in ("/ogp.png", "/apple-touch-icon.png", "/logo.png", "/logo-dark.png"):
            fname = p.path.lstrip("/")
            try:
                data = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), fname), "rb").read()
                self.send_response(200); self._sec(); self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
            except OSError: return self.send_html(404, NOT_FOUND_PAGE, noindex=True)
        m = re.fullmatch(r"/e/([A-Za-z0-9_-]{8,32})", p.path)
        if m:
            con = db()
            if not con.execute("SELECT 1 FROM events WHERE id=?", (m.group(1),)).fetchone():
                return self.send_html(404, NOT_FOUND_PAGE, noindex=True)
            return self.send_html(200, EVENT_PAGE, noindex=True)
        m = re.fullmatch(r"/api/events/([A-Za-z0-9_-]{8,32})", p.path)
        if m:
            cleanup_expired()
            con = db()
            ev = con.execute("SELECT title,dates,start_min,end_min,allowed,created_at,kind FROM events WHERE id=?", (m.group(1),)).fetchone()
            if not ev: return self.send_json(404, {"error": "not found"})
            from datetime import datetime, timedelta, timezone
            created = datetime.strptime(ev[5], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            expires_jst = (created + timedelta(days=30)).astimezone(timezone(timedelta(hours=9)))
            expires_str = expires_jst.strftime("%Y/%m/%d")
            rows = con.execute("SELECT name,marks,note FROM paints WHERE event_id=? ORDER BY updated_at", (m.group(1),)).fetchall()
            return self.send_json(200, {"title": ev[0], "kind": ev[6] or "time", "dates": json.loads(ev[1]),
                "startMin": ev[2], "endMin": ev[3],
                "allowed": json.loads(ev[4]) if ev[4] else None,
                "expiresAt": expires_str,
                "participants": [{"name": n, "marks": json.loads(mk), "note": nt or ""} for n, mk, nt in rows]})
        return self.send_html(404, NOT_FOUND_PAGE, noindex=True)

    def do_POST(self):
        p = urlparse(self.path)
        try: body = jbody(self)
        except Exception: return self.send_json(400, {"error": "bad json"})
        if p.path == "/api/events":
            client_ip = self.headers.get("CF-Connecting-IP") or self.client_address[0]
            if _rate_limited(client_ip):
                return self.send_json(429, {"error": "作成回数の上限に達しました。しばらくしてからお試しください"})
            title = str(body.get("title", ""))[:100] or "（無題）"
            dates = body.get("dates") or []
            if not (1 <= len(dates) <= 31) or not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d)) for d in dates):
                return self.send_json(400, {"error": "dates invalid"})
            dates = sorted(set(str(d) for d in dates))
            kind = body.get("kind") if body.get("kind") in ("time", "date") else "time"
            allowed = body.get("allowed")
            allowed_json = None
            if kind == "date":
                smin, emin = 0, 1440
            elif allowed is not None:
                if not isinstance(allowed, list) or not (1 <= len(allowed) <= 31 * 48):
                    return self.send_json(400, {"error": "allowed invalid"})
                clean = []
                for k in allowed:
                    mm = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\|(\d{1,2})", str(k))
                    if not mm or mm.group(1) not in dates or not (0 <= int(mm.group(2)) < 48):
                        return self.send_json(400, {"error": "allowed invalid"})
                    clean.append(str(k))
                allowed = sorted(set(clean))
                mins = [int(k.split("|")[1]) * 30 for k in allowed]
                smin, emin = min(mins), max(mins) + 30
                allowed_json = json.dumps(allowed)
            else:
                smin, emin = body.get("startMin", 0), body.get("endMin", 1440)
                if not (isinstance(smin, int) and isinstance(emin, int) and 0 <= smin < emin <= 1440
                        and smin % 30 == 0 and emin % 30 == 0):
                    return self.send_json(400, {"error": "time range invalid"})
            eid = secrets.token_urlsafe(18)[:24]; key = secrets.token_urlsafe(32)
            con = db()
            cleanup_expired()
            con.execute("INSERT INTO events(id,title,dates,admin_key,created_at,start_min,end_min,allowed,kind) VALUES(?,?,?,?,datetime('now'),?,?,?,?)",
                        (eid, title, json.dumps(dates), key, smin, emin, allowed_json, kind))
            con.commit()
            _rate_record(client_ip)
            return self.send_json(200, {"id": eid, "adminKey": key})
        m = re.fullmatch(r"/api/events/([A-Za-z0-9_-]{8,32})/paint", p.path)
        if m:
            name = str(body.get("name", "")).strip()[:30]
            note = re.sub(r"\s+", " ", str(body.get("note", ""))).strip()[:200]
            marks = body.get("marks")
            if not name or not isinstance(marks, dict) or len(marks) > 2000:
                return self.send_json(400, {"error": "paint invalid"})
            con = db()
            evrow = con.execute("SELECT allowed,dates,kind FROM events WHERE id=?", (m.group(1),)).fetchone()
            if not evrow:
                return self.send_json(404, {"error": "not found"})
            prev0 = str(body.get("prevName", "")).strip()[:30]
            name_exists = con.execute("SELECT 1 FROM paints WHERE event_id=? AND name=?", (m.group(1), name)).fetchone()
            is_rename = bool(prev0 and prev0 != name and con.execute("SELECT 1 FROM paints WHERE event_id=? AND name=?", (m.group(1), prev0)).fetchone())
            if not name_exists and not is_rename:
                cnt = con.execute("SELECT COUNT(*) FROM paints WHERE event_id=?", (m.group(1),)).fetchone()[0]
                if cnt >= 100:
                    return self.send_json(403, {"error": "参加者の上限（100人）に達しています"})
            allowed_set = set(json.loads(evrow[0])) if evrow[0] else None
            date_set = set(json.loads(evrow[1]))
            ev_kind = evrow[2] or "time"
            clean = {}
            for k, v in marks.items():
                if v not in (1, 0.5, -1):
                    continue
                ks = str(k)
                if ev_kind == "date":
                    if ks in date_set:
                        clean[ks] = v
                elif re.fullmatch(r"\d{4}-\d{2}-\d{2}\|\d{1,2}", ks):
                    if allowed_set is not None and ks not in allowed_set:
                        continue
                    clean[ks] = v
            con.execute("INSERT INTO paints(event_id,name,marks,updated_at,note) VALUES(?,?,?,datetime('now'),?) "
                        "ON CONFLICT(event_id,name) DO UPDATE SET marks=excluded.marks, updated_at=excluded.updated_at, note=excluded.note",
                        (m.group(1), name, json.dumps(clean), note))
            prev = str(body.get("prevName", "")).strip()[:30]
            if prev and prev != name:
                con.execute("DELETE FROM paints WHERE event_id=? AND name=?", (m.group(1), prev))
            con.commit()
            return self.send_json(200, {"ok": True})
        m = re.fullmatch(r"/api/events/([A-Za-z0-9_-]{8,40})/verify-admin", p.path)
        if m:
            con = db(); row = con.execute("SELECT admin_key FROM events WHERE id=?", (m.group(1),)).fetchone()
            if not row: return self.send_json(404, {"error": "not found"})
            return self.send_json(200, {"ok": hmac.compare_digest(str(body.get("adminKey", "")), row[0])})
        m = re.fullmatch(r"/api/events/([A-Za-z0-9_-]{8,32})/delete", p.path)
        if m:
            con = db()
            row = con.execute("SELECT admin_key FROM events WHERE id=?", (m.group(1),)).fetchone()
            if not row or not hmac.compare_digest(str(body.get("adminKey", "")), row[0]):
                return self.send_json(403, {"error": "forbidden"})
            con.execute("DELETE FROM events WHERE id=?", (m.group(1),))
            con.execute("DELETE FROM paints WHERE event_id=?", (m.group(1),))
            con.commit()
            return self.send_json(200, {"ok": True})
        m = re.fullmatch(r"/api/events/([A-Za-z0-9_-]{8,32})/participant/self-delete", p.path)
        if m:
            name = str(body.get("name", "")).strip()[:30]
            if not name: return self.send_json(400, {"error": "name required"})
            con = db()
            if not con.execute("SELECT 1 FROM events WHERE id=?", (m.group(1),)).fetchone():
                return self.send_json(404, {"error": "not found"})
            cur = con.execute("DELETE FROM paints WHERE event_id=? AND name=?", (m.group(1), name))
            con.commit()
            if cur.rowcount < 1: return self.send_json(404, {"error": "participant not found"})
            return self.send_json(200, {"ok": True})
        m = re.fullmatch(r"/api/events/([A-Za-z0-9_-]{8,32})/participant/admin-delete", p.path)
        if m:
            name = str(body.get("name", "")).strip()[:30]
            if not name: return self.send_json(400, {"error": "name required"})
            con = db()
            row = con.execute("SELECT admin_key FROM events WHERE id=?", (m.group(1),)).fetchone()
            if not row: return self.send_json(404, {"error": "not found"})
            if not hmac.compare_digest(str(body.get("adminKey", "")), row[0]):
                return self.send_json(403, {"error": "forbidden"})
            cur = con.execute("DELETE FROM paints WHERE event_id=? AND name=?", (m.group(1), name))
            con.commit()
            if cur.rowcount < 1: return self.send_json(404, {"error": "participant not found"})
            return self.send_json(200, {"ok": True})
        m = re.fullmatch(r"/api/events/([A-Za-z0-9_-]{8,32})/export\.csv", p.path)
        if m:
            con = db()
            ev = con.execute("SELECT title,dates,start_min,end_min,allowed,admin_key,kind FROM events WHERE id=?", (m.group(1),)).fetchone()
            if not ev: return self.send_json(404, {"error": "not found"})
            if not hmac.compare_digest(str(body.get("adminKey", "")), ev[5]):
                return self.send_json(403, {"error": "forbidden"})
            prow = con.execute("SELECT name,marks,note FROM paints WHERE event_id=? ORDER BY updated_at", (m.group(1),)).fetchall()
            participants = [(n, json.loads(mk), nt or "") for n, mk, nt in prow]
            dates = json.loads(ev[1])
            if (ev[6] or "time") == "date":
                from datetime import datetime as _dt2
                _wd = "月火水木金土日"
                def _dl(ds):
                    try:
                        _d = _dt2.strptime(ds, "%Y-%m-%d")
                        return _d.strftime("%Y/%m/%d") + "（" + _wd[_d.weekday()] + "）"
                    except ValueError:
                        return ds
                _sym = {1: "○", 0.5: "△"}
                out = io.StringIO()
                w = csv.writer(out, lineterminator="\r\n")
                w.writerow(["タイトル", _csv_safe(ev[0])])
                noted = [(n, nt) for n, _, nt in participants if nt]
                if noted:
                    w.writerow([])
                    w.writerow(["名前", "一言"])
                    for n, nt in noted: w.writerow([_csv_safe(n), _csv_safe(nt)])
                w.writerow([])
                w.writerow(["回答者"] + [_dl(ds) for ds in dates] + ["一言"])
                for n, mk, nt in participants:
                    w.writerow([_csv_safe(n)] + [_sym.get(mk.get(ds), "×") for ds in dates] + [_csv_safe(nt)])
                w.writerow(["○の数"] + [sum(1 for _, mk, _ in participants if mk.get(ds) == 1) for ds in dates] + [""])
                return self.send_csv(m.group(1), "\ufeff" + out.getvalue())
            allowed_set = set(json.loads(ev[4])) if ev[4] else None
            eff = allowed_set
            if eff is None and ((ev[2] or 0) > 0 or (ev[3] or 1440) < 1440):
                eff = set()
                for ds in dates:
                    for mm in range(ev[2] or 0, ev[3] or 1440, 30):
                        eff.add("%s|%d" % (ds, mm // 30))
            from datetime import datetime as _dt
            wdays = "月火水木金土日"
            out = io.StringIO()
            w = csv.writer(out, lineterminator="\r\n")
            w.writerow(["タイトル", _csv_safe(ev[0])])
            noted = [(n, nt) for n, _, nt in participants if nt]
            if noted:
                w.writerow([])
                w.writerow(["名前", "一言"])
                for n, nt in noted: w.writerow([_csv_safe(n), _csv_safe(nt)])
            w.writerow([])
            w.writerow(["日付", "時刻"] + [_csv_safe(n) for n, _, _ in participants] + ["○の数"])
            sym = {1: "○", 0.5: "△"}
            for ds in dates:
                try:
                    _d = _dt.strptime(ds, "%Y-%m-%d")
                    dstr = _d.strftime("%Y/%m/%d") + "（" + wdays[_d.weekday()] + "）"
                except ValueError:
                    dstr = ds
                for si in range(48):
                    key = "%s|%d" % (ds, si)
                    if eff is not None and key not in eff: continue
                    vals = []; cnt = 0
                    for n, mk, _nt in participants:
                        v = mk.get(key)
                        if v == 1: cnt += 1
                        vals.append(sym.get(v, "×"))
                    w.writerow([dstr, "%02d:%02d" % (si * 30 // 60, si * 30 % 60)] + vals + [cnt])
            return self.send_csv(m.group(1), "\ufeff" + out.getvalue())
        return self.send_json(404, {"error": "not found"})

if __name__ == "__main__":
    cleanup_expired()
    db().close()
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
