"""The compatibility list as one page people can search (#304).

compatibility.py adds the shared results up per game for the tool to read
before an install. That sum hides what #304 asked for: a result is a fact
about a game on one card, one driver and one build, not about the game. So
the workflow also hands this script one row per configuration - the same
results, kept apart instead of added up - and it writes a single static
page for GitHub Pages:

    python .github/scripts/compat_page.py              # docs/compatibility.json -> _site/
    python .github/scripts/compat_page.py --out DIR

Run on its own it has only the per-game sums, and the page says so instead
of offering filters it cannot apply. Everything is inline: no CDN, nothing
fetched after the page loads. Every string in the data was typed by
whoever opened an issue, so the page builds its rows with textContent and
the data block cannot close its own script tag.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.gpu import SM_NAMES               # noqa: E402  one table of card families

# The fields of one configuration row, in the order compatibility.py keys them.
KEYS = ("exe", "route", "build", "api", "sm", "gpu", "driver", "tool")
REPO_URL = "https://github.com/Kizzuwatnaa/DLSS5-Autopilot"


def family(sm: str) -> str:
    """'sm_89' -> 'RTX 40', or 'other'. The filter's own short name."""
    try:
        name = SM_NAMES.get(int(str(sm).lower().replace("sm_", "")), "")
    except ValueError:
        name = ""
    return name.split(" (")[0].split(" /")[0] if name.startswith("RTX") else "other"


def data(payload: dict, rows: list[dict]) -> dict:
    """What the page reads: every game, and its configurations when there are any."""
    by_exe: dict[str, list] = {}
    for r in rows:
        if not isinstance(r, dict) or not r.get("exe"):
            continue
        gpu = str(r.get("gpu") or "")
        for word in ("NVIDIA ", "GeForce "):
            gpu = gpu.replace(word, "")
        by_exe.setdefault(str(r["exe"]), []).append([
            str(r.get("route") or ""), str(r.get("build") or ""),
            str(r.get("api") or ""), family(str(r.get("sm") or "")), gpu.strip(),
            str(r.get("driver") or ""), str(r.get("tool") or ""),
            int(r.get("worked") or 0), int(r.get("failed") or 0),
            str(r.get("last") or "")])
    games = []
    for exe, g in (payload.get("games") or {}).items():
        if not isinstance(g, dict):
            continue
        games.append({"exe": exe, "name": str(g.get("name") or exe),
                      "routes": g.get("routes") or {},
                      "measured": g.get("measured") or {},
                      "configs": sorted(by_exe.get(exe, []), key=lambda c: c[9], reverse=True)})
    return {"generated": str(payload.get("generated") or ""),
            "reports": int(payload.get("reports") or 0),
            "detailed": bool(rows), "games": games}


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DLSS 5 Autopilot - compatibility</title>
<meta name="description" content="Shared DLSS 5 Autopilot results: which route worked in which game, on which card and driver.">
<style>
:root{--bg:#0a0b0d;--surf:#14161a;--surf2:#1b1e23;--line:#23272d;--text:#ece9e2;--muted:#8c929b;--dim:#5a6069;--amber:#e6ac50;--ok:#86d493;--bad:#ec6f5f}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 "Cascadia Mono",Consolas,ui-monospace,monospace}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:18px;margin:0 0 4px;color:var(--amber);font-weight:600}
a{color:var(--amber)}
.sub{color:var(--muted);margin:0 0 20px}
.bar{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px}
input,select{background:var(--surf);color:var(--text);border:1px solid var(--line);border-radius:4px;padding:8px 10px;font:inherit;min-width:0}
input:focus,select:focus{outline:1px solid var(--amber);border-color:var(--amber)}
#q{flex:1 1 260px}
select{flex:0 1 auto}
.count{color:var(--dim);margin:0 0 12px}
.game{border:1px solid var(--line);background:var(--surf);border-radius:4px;margin-bottom:8px}
.game>button{all:unset;display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline;width:100%;padding:10px 12px;cursor:pointer;box-sizing:border-box}
.game>button:hover .name,.game>button:focus-visible .name{color:var(--amber)}
.game>button:focus-visible{outline:1px solid var(--amber)}
.name{font-weight:600;flex:1 1 220px}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{background:var(--surf2);border:1px solid var(--line);border-radius:3px;padding:0 6px;color:var(--muted);white-space:nowrap}
.chip b{font-weight:600}
.all{color:var(--ok)}.none{color:var(--bad)}.some{color:var(--amber)}
.detail{display:none;border-top:1px solid var(--line);padding:8px 12px 12px}
.open .detail{display:block}
.cost{color:var(--muted);margin:4px 0 8px}
.wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;min-width:640px}
th,td{text-align:left;padding:4px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--dim);font-weight:400}
.note{color:var(--muted);border-left:2px solid var(--amber);padding:4px 10px;margin:0 0 16px}
footer{color:var(--dim);margin-top:24px}
</style>
</head>
<body>
<main>
<h1>DLSS 5 Autopilot - compatibility</h1>
<p class="sub" id="sub"></p>
<p class="note" id="note" hidden></p>
<div class="bar">
<input id="q" type="search" placeholder="search a game" aria-label="search a game" autocomplete="off">
<select id="route" aria-label="route"><option value="">every route</option></select>
<select id="fam" aria-label="card family"><option value="">every card</option></select>
<select id="drv" aria-label="driver"><option value="">every driver</option></select>
<select id="res" aria-label="result"><option value="">any result</option><option value="w">worked</option><option value="f">did not work</option></select>
</div>
<p class="count" id="count"></p>
<div id="list"></div>
<footer>A result gets here when somebody presses <b>share the result</b> in the tool and posts the issue it opens.
Results the tool could not see and nobody confirmed are left out. <a href="__REPO__">DLSS 5 Autopilot</a></footer>
</main>
<script type="application/json" id="data">__DATA__</script>
<script>
(function(){
var D=JSON.parse(document.getElementById("data").textContent);
var $=function(id){return document.getElementById(id)};
function el(tag,cls,txt){var e=document.createElement(tag);if(cls)e.className=cls;if(txt!=null)e.textContent=txt;return e}
function tone(w,t){return w===t?"all":(w===0?"none":"some")}
function dkey(v){return v.split(".").map(function(n){return ("0000"+n).slice(-4)}).join(".")}
$("sub").textContent=D.reports+" shared results across "+D.games.length+" games"+(D.generated?", rebuilt "+D.generated.slice(0,10):"")+". A result belongs to one card, driver and build - the same game can work on one and fail on another.";
var routes={},fams={},drvs={};
D.games.forEach(function(g){Object.keys(g.routes).forEach(function(r){routes[r]=1});g.configs.forEach(function(c){if(c[3])fams[c[3]]=1;if(c[5])drvs[c[5]]=1})});
function fill(sel,vals){vals.forEach(function(v){var o=el("option",null,v);o.value=v;sel.appendChild(o)})}
fill($("route"),Object.keys(routes).sort());
fill($("fam"),Object.keys(fams).sort());
fill($("drv"),Object.keys(drvs).sort(function(a,b){return dkey(b)<dkey(a)?-1:1}));
if(!D.detailed){$("fam").disabled=$("drv").disabled=true;$("note").hidden=false;$("note").textContent="This copy has only the totals per game and route; card and driver filters appear once the list is rebuilt with every configuration."}
var open={};
function rowsOf(g,f){
  if(!D.detailed){var out=[];Object.keys(g.routes).forEach(function(r){var c=g.routes[r];if(f.route&&r!==f.route)return;out.push(["",r,c.worked,c.failed])});return out}
  return g.configs.filter(function(c){return(!f.route||c[0]===f.route)&&(!f.fam||c[3]===f.fam)&&(!f.drv||c[5]===f.drv)});
}
function sums(g,f){
  var by={};
  if(!D.detailed){rowsOf(g,f).forEach(function(r){by[r[1]]=[r[2],r[3]]});return by}
  rowsOf(g,f).forEach(function(c){var s=by[c[0]]||(by[c[0]]=[0,0]);s[0]+=c[7];s[1]+=c[8]});return by;
}
function render(){
  var f={q:$("q").value.trim().toLowerCase(),route:$("route").value,fam:$("fam").value,drv:$("drv").value,res:$("res").value};
  var list=$("list");list.textContent="";var shown=0;
  var gs=D.games.map(function(g){var by=sums(g,f),w=0,t=0;Object.keys(by).forEach(function(r){w+=by[r][0];t+=by[r][0]+by[r][1]});return{g:g,by:by,w:w,t:t}})
   .filter(function(x){if(!x.t)return false;if(f.q&&x.g.name.toLowerCase().indexOf(f.q)<0&&x.g.exe.indexOf(f.q)<0)return false;if(f.res==="w"&&!x.w)return false;if(f.res==="f"&&x.w===x.t)return false;return true})
   .sort(function(a,b){return b.t-a.t||a.g.name.localeCompare(b.g.name)});
  gs.forEach(function(x){
    var g=x.g,box=el("div","game"+(open[g.exe]?" open":"")),head=el("button");
    head.setAttribute("aria-expanded",open[g.exe]?"true":"false");
    head.appendChild(el("span","name",g.name));
    head.appendChild(el("span",tone(x.w,x.t),"worked in "+x.w+" of "+x.t));
    var chips=el("span","chips");
    Object.keys(x.by).sort().forEach(function(r){var s=x.by[r],c=el("span","chip");c.appendChild(document.createTextNode(r+" "));c.appendChild(el("b",tone(s[0],s[0]+s[1]),s[0]+"/"+(s[0]+s[1])));chips.appendChild(c)});
    head.appendChild(chips);
    head.onclick=function(){open[g.exe]=!open[g.exe];box.classList.toggle("open");head.setAttribute("aria-expanded",open[g.exe]?"true":"false")};
    box.appendChild(head);
    var det=el("div","detail");
    Object.keys(g.measured).sort().forEach(function(r){var m=g.measured[r];det.appendChild(el("p","cost",r+": "+m.res+"% work area"+(m.fps?", "+m.fps+" fps":"")+(m.ms?", "+m.ms+(r==="feeder"?" ms a frame for the model and feed together":" ms of model a frame"):"")+" - the middle of "+m.n+" measured result"+(m.n>1?"s":"")))});
    if(D.detailed){
      var wrap=el("div","wrap"),t=el("table"),hr=el("tr");
      ["route","build","api","card","driver","tool","result","last seen"].forEach(function(h){hr.appendChild(el("th",null,h))});
      t.appendChild(hr);
      rowsOf(g,f).forEach(function(c){var tr=el("tr");[c[0],c[1]||"-",c[2]||"-",c[4]||c[3]||"-",c[5]||"-",c[6]||"-"].forEach(function(v){tr.appendChild(el("td",null,v))});var n=c[7]+c[8];tr.appendChild(el("td",tone(c[7],n),n>1?"worked "+c[7]+" of "+n:(c[7]?"worked":"did not work")));tr.appendChild(el("td",null,c[9]||"-"));t.appendChild(tr)});
      wrap.appendChild(t);det.appendChild(wrap);
    }else if(!det.firstChild){det.appendChild(el("p","cost","No configuration detail in this copy."))}
    box.appendChild(det);list.appendChild(box);shown++;
  });
  $("count").textContent=shown?shown+" game"+(shown>1?"s":""):"Nothing matches. Clear a filter, or be the first: install it with the tool and share the result.";
}
["q","route","fam","drv","res"].forEach(function(id){$(id).addEventListener("input",render)});
render();
})();
</script>
</body>
</html>
"""


def render(payload: dict, rows: list[dict] | None = None) -> str:
    blob = json.dumps(data(payload, rows or []), separators=(",", ":"), sort_keys=True)
    # A game name is somebody's text: "</script>" inside it must not end the block.
    blob = blob.replace("</", "<\\/").replace("<!--", "<\\!--")
    return PAGE.replace("__REPO__", html.escape(REPO_URL)).replace("__DATA__", blob)


def write(payload: dict, rows: list[dict] | None, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    page = out_dir / "index.html"
    page.write_text(render(payload, rows), encoding="utf8")
    # The machine-readable sum beside it, for anyone who wants the numbers.
    (out_dir / "compatibility.json").write_text(
        json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf8")
    return page


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", default=str(ROOT / "docs" / "compatibility.json"))
    ap.add_argument("--out", default=str(ROOT / "_site"))
    a = ap.parse_args()
    payload = json.loads(Path(a.json).read_text(encoding="utf8"))
    print(write(payload, [], Path(a.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
