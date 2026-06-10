"""乾坤 · 组织台 — single owner entry for the whole ft-* organism (:3000).

Owner mandate (2026-06-10): ONE entry on :3000, every organ redesigned, the
太一 battle console integrated, zero passwords, honest placeholders where an
organ has nothing yet.

Stack (first principles, owner-freed): zero build chain — Starlette renders
server-side HTML from local artifacts (files + systemctl reads). No node, no
bundler, no auth. Daedalus owns this by charter (owner/operator tools).

Boundaries: this console READS other organs' artifacts (files) and host state
(systemctl); it imports no organ code. Everything rendered is report-only
evidence — accepted_edges=0, never advice, never a GO. The OWNER_IDENTITY
five-element motif styles atmosphere only.
"""

from __future__ import annotations

import html
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

COSMOS = Path("/home/ft/dev/ft-cosmos")
KAIROS_BUNDLE = (
    COSMOS / "ft-kairos" / "var" / "reports" / "owner_cockpit" / "web" / "owner_web_latest.json"
)

ORGANS: list[dict[str, str]] = [
    {"slug": "kairos", "zh": "太一", "element": "火", "en": "kairos", "role": "A 股战场:研究·证据·执行"},
    {"slug": "logos", "zh": "天道", "element": "木", "en": "logos", "role": "知识与记忆,喂给行动"},
    {"slug": "atlas", "zh": "地载", "element": "土", "en": "atlas", "role": "基础设施·恢复·自动化骨架"},
    {"slug": "hermes", "zh": "灵枢", "element": "金", "en": "hermes", "role": "中立契约脊柱"},
    {"slug": "proteus", "zh": "太虚", "element": "水", "en": "proteus", "role": "数字资产器官"},
    {"slug": "daedalus", "zh": "天工", "element": "器", "en": "daedalus", "role": "Owner 工具(含本台)"},
    {"slug": "cosmos", "zh": "乾坤", "element": "场", "en": "cosmos", "role": "治理·工作台·文档"},
]

CSS = """
:root{
  --ink:#0c0f12; --panel:#13181d; --line:#222a31;
  --fg:#d6d3c8; --dim:#8a8678;
  --fire:#e8853b; --bamboo:#69b07c; --cinnabar:#c4524a; --steel:#7d96a8;
  --wood:#8aa86b; --earth:#b59a6a; --metal:#a8b0b8; --water:#6e93b5;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ink);color:var(--fg);
  font:15px/1.55 "Noto Sans SC","PingFang SC",system-ui,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 20px 80px}
nav{display:flex;gap:4px;flex-wrap:wrap;align-items:baseline;
  border-bottom:1px solid var(--fire);padding:14px 0 10px;margin-bottom:24px}
nav .brand{font-size:18px;letter-spacing:.14em;margin-right:18px;
  color:var(--fire);font-weight:600}
nav a{color:var(--dim);text-decoration:none;padding:3px 10px;border-radius:4px;
  font-size:13px;letter-spacing:.06em}
nav a:hover{color:var(--fg)} nav a.on{color:var(--fire);border:1px solid var(--fire)}
h1{font-size:19px;margin:0 0 4px;letter-spacing:.1em}
h1 .el{font-size:12px;color:var(--dim);margin-left:10px;letter-spacing:.2em}
.lede{color:var(--dim);font-size:12.5px;margin:0 0 18px}
section{background:var(--panel);border:1px solid var(--line);
  border-radius:6px;padding:16px 18px;margin-bottom:18px}
h2{font-size:14px;margin:0 0 10px;color:var(--fire);letter-spacing:.08em;
  display:flex;justify-content:space-between;align-items:baseline}
h2 small{color:var(--dim);font-weight:normal;letter-spacing:0}
table{width:100%;border-collapse:collapse;font-size:13px}
th{color:var(--dim);text-align:left;font-weight:normal;padding:4px 8px;
  border-bottom:1px solid var(--line)}
td{padding:4px 8px;border-bottom:1px solid rgba(34,42,49,.55)}
tr:last-child td{border-bottom:none}
.num{font-family:"JetBrains Mono","SF Mono",ui-monospace,monospace;
  font-variant-numeric:tabular-nums}
.code{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:12px}
.pos{color:var(--bamboo)} .neg{color:var(--cinnabar)} .dim{color:var(--dim)}
.pill{display:inline-block;padding:1px 8px;border-radius:9px;font-size:11.5px;
  border:1px solid var(--line)}
.pill.durable,.pill.ok{color:var(--bamboo);border-color:var(--bamboo)}
.pill.lottery,.pill.warn{color:var(--fire);border-color:var(--fire)}
.pill.pilot{color:var(--steel);border-color:var(--steel)}
.pill.inverted,.pill.dead,.pill.bad{color:var(--cinnabar);border-color:var(--cinnabar)}
.kv{display:flex;gap:26px;flex-wrap:wrap;margin-bottom:8px}
.kv b{font-weight:600}
details{margin-top:8px}summary{cursor:pointer;color:var(--dim);font-size:12.5px}
ul.files{font-size:11.5px;line-height:1.8;margin:6px 0 0;padding-left:18px}
.missing{color:var(--dim);font-style:italic}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}
a.card{display:block;background:var(--panel);border:1px solid var(--line);
  border-radius:6px;padding:14px 16px;color:var(--fg);text-decoration:none}
a.card:hover{border-color:var(--fire)}
.card .t{font-size:15px;letter-spacing:.1em}
.card .t .el{color:var(--dim);font-size:11px;margin-left:8px}
.card .r{color:var(--dim);font-size:12px;margin:4px 0 8px}
.card .v{font-size:12.5px;line-height:1.7}
pre.doc{white-space:pre-wrap;font-size:12px;line-height:1.6;
  font-family:"JetBrains Mono",ui-monospace,monospace;color:var(--fg);
  background:transparent;margin:0;max-height:520px;overflow:auto}
@media(max-width:900px){.grid2{grid-template-columns:1fr}}
footer{color:var(--dim);font-size:11px;text-align:center;margin-top:30px}
"""

VERDICT_ZH = {
    "DURABLE": ("稳定", "durable"),
    "LOTTERY": ("彩票型", "lottery"),
    "PILOT": ("试点", "pilot"),
    "INVERTED": ("反向", "inverted"),
    "NEEDS_RESPEC": ("需重设", "pilot"),
    "DEAD": ("无选样", "dead"),
}


# ---------------------------------------------------------------- helpers
def _e(value: Any) -> str:
    return html.escape(str(value)) if value is not None else "—"


def _n(value: Any, digits: int = 2) -> str:
    try:
        if value is None:
            return "—"
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _signed(value: Any, digits: int = 2) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return '<span class="dim">—</span>'
    cls = "pos" if v > 0 else ("neg" if v < 0 else "dim")
    return f'<span class="num {cls}">{v:+.{digits}f}</span>'


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_text(path: Path, limit: int = 40_000) -> str | None:
    try:
        return path.read_text(encoding="utf-8")[:limit]
    except OSError:
        return None


def _mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).strftime(
            "%m-%d %H:%MZ"
        )
    except OSError:
        return "缺席"


def _sysctl(args: list[str]) -> str:
    try:
        return subprocess.run(
            ["systemctl", *args], capture_output=True, text=True, timeout=8, check=False
        ).stdout
    except Exception:  # noqa: BLE001
        return ""


def _page(slug: str, title_zh: str, element: str, lede: str, body: str) -> str:
    nav = "".join(
        f'<a href="/{o["slug"]}" class="{"on" if o["slug"] == slug else ""}">'
        f'{o["zh"]} {o["en"]}</a>'
        for o in ORGANS
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="120">
<title>{title_zh} · 乾坤台</title><style>{CSS}</style></head>
<body><main>
<nav><span class="brand">乾坤台</span><a href="/" class="{"on" if slug == "home" else ""}">总览</a>{nav}</nav>
<h1>{title_zh}<span class="el">{element}</span></h1>
<p class="lede">{lede}</p>
{body}
<footer>report-only · accepted_edges=0 · 木生火,证据喂行动 · 这里的一切是证据展示,不是建议,不是 GO</footer>
</main></body></html>"""


# ---------------------------------------------------------------- 太一 (kairos)
def _k_sec_package(pkg: dict[str, Any] | None) -> str:
    if not pkg:
        return '<section><h2>今日包</h2><p class="missing">暂无产物(诚实缺席,不伪造)。</p></section>'
    rows = "".join(
        f"<tr><td class='num dim'>{_e(c.get('rank') or i + 1)}</td>"
        f"<td class='code'>{_e(c.get('stock_code'))}</td>"
        f"<td>{_e(c.get('stock_name'))}</td>"
        f"<td>{_e(c.get('industry_name'))}</td>"
        f"<td class='code dim'>{_e(c.get('best_tactic_id'))}</td>"
        f"<td class='num'>{_n(c.get('score'), 1)}</td>"
        f"<td>{('<span class=\"pill bad\">' + str(len(c.get('wounds') or [])) + '</span>') if c.get('wounds') else '<span class=dim>—</span>'}</td></tr>"
        for i, c in enumerate((pkg.get("candidates") or [])[:25])
    )
    return f"""<section>
<h2>今日包 → {_e(pkg.get('target_trade_date'))} <small>as-of {_e(pkg.get('as_of_date'))} · 生成 {_e(pkg.get('generated_at_utc'))}</small></h2>
<div class="kv"><span>候选 <b class="num">{_e(pkg.get('candidate_count'))}</b></span>
<span>watchlist <b class="num">{len(pkg.get('watchlist') or [])}</b></span>
<span>读序行 <b class="num">{len(pkg.get('read_order_rows') or [])}</b></span>
<span>accepted_edges <b class="num">{_e(pkg.get('accepted_edges'))}</b></span></div>
<table><thead><tr><th>#</th><th>代码</th><th>名称</th><th>行业</th><th>战法</th><th>分</th><th>伤口</th></tr></thead>
<tbody>{rows}</tbody></table>
</section>"""


def _k_sec_recall(rc: dict[str, Any] | None) -> str:
    if not rc:
        return '<section><h2>今日复盘</h2><p class="missing">暂无产物。</p></section>'
    hits = rc.get("matched_candidate_launch_codes") or []
    hits_html = (
        f"<div class='code' style='margin-top:6px'>命中:{_e(' · '.join(hits))}</div>"
        if hits
        else ""
    )
    return f"""<section>
<h2>今日复盘({_e(rc.get('target_trade_date'))}) <small>{_e(rc.get('status'))}</small></h2>
<div class="kv">
<span>全市场 launch(≥5%) <b class="num">{_e(rc.get('whole_market_launch_count'))}</b></span>
<span>候选 <b class="num">{_e(rc.get('candidate_count'))}</b> 中命中 <b class="num">{_e(rc.get('candidate_launch_count'))}</b></span>
<span>recall <b class="num">{_n(rc.get('launch_recall_pct'))}%</b></span>
<span>precision <b class="num">{_n(rc.get('candidate_launch_precision_pct'), 1)}%</b></span>
<span class="dim">d3/d5:{_e(rc.get('d3_d5_status') or '随 panel 成熟')}</span></div>
{hits_html}
</section>"""


def _k_sec_families(fv: dict[str, Any] | None) -> str:
    if not fv:
        return '<section><h2>家族裁决账本</h2><p class="missing">暂无产物。</p></section>'
    counts = " · ".join(
        f"{VERDICT_ZH.get(k, (k, ''))[0]} {v}"
        for k, v in (fv.get("verdict_counts") or {}).items()
    )
    rows = ""
    for r in fv.get("rows") or []:
        zh, cls = VERDICT_ZH.get(str(r.get("verdict")), (str(r.get("verdict")), "pilot"))
        rows += (
            f"<tr><td><span class='pill {cls}'>{zh}</span></td>"
            f"<td class='code'>{_e(r.get('family'))}</td>"
            f"<td>{_signed(r.get('launch_excess_pct'))}</td>"
            f"<td>{_signed(r.get('mean_excess_pct'), 3)}</td>"
            f"<td class='num dim'>{_e(r.get('n'))}</td>"
            f"<td class='num dim'>{_e(r.get('date_clusters'))}</td></tr>"
        )
    return f"""<section>
<h2>家族裁决账本 <small>下游唯一可读面;{_e(fv.get('source_config_count'))} configs / {_e(fv.get('source_confirmed_count'))} confirmed = 候选池,不是信号</small></h2>
<p class="lede">{counts} · 彩票型 = launch 概率强但纸面均值为负,永远不是收益声明</p>
<table><thead><tr><th>裁决</th><th>家族</th><th>launch 超额%</th><th>均值超额%</th><th>n</th><th>日簇</th></tr></thead>
<tbody>{rows}</tbody></table>
</section>"""


ENV_ZH = {"hot": "热", "warm": "温", "cold": "冷"}
PHASE_ZH = {
    "climax": "高潮",
    "fermenting": "发酵",
    "ebbing": "退潮",
    "remnant": "残留",
    "quiet": "静默",
}


def _k_sec_steering(st: dict[str, Any] | None) -> str:
    if not st:
        return '<section><h2>自适应转向 · 读序</h2><p class="missing">暂无产物。</p></section>'
    as_of = st.get("as_of") or {}
    env = str(as_of.get("env_regime_today") or "")
    phases = st.get("industry_phase_today") or []
    phase_line = (
        " · ".join(
            f"{_e(p.get('industry_name') or p.get('industry_code_l2'))}"
            f" {PHASE_ZH.get(str(p.get('lifecycle_state')), _e(p.get('lifecycle_state')))}"
            for p in phases
        )
        or "全部行业静默"
    )
    rows = ""
    for r in st.get("steering_table") or []:
        role = str(r.get("family_role"))
        rank = r.get("read_priority_rank")
        pos = " ".join(
            PHASE_ZH.get(p, p) for p in (r.get("positive_phases") or [])
        )
        rows += (
            f"<tr><td class='num'>{_e(rank) if rank else '避险'}</td>"
            f"<td class='code'>{_e(r.get('family'))}</td>"
            f"<td>{_signed(r.get('prior_env_mean_excess_pct'), 3)}</td>"
            f"<td>{_signed(r.get('scaled_cum_forward_payoff_pct'), 2)}</td>"
            f"<td>{_signed(r.get('steering_score_pct'), 2)}</td>"
            f"<td class='dim'>{_e(pos) or '—'}</td>"
            f"<td class='num dim'>{_e(r.get('forward_settled_days'))}</td></tr>"
        ) if role else rows
    routing = ""
    for r in st.get("industry_routing") or []:
        routing += (
            f"<tr><td class='code'>{_e(r.get('family'))}</td>"
            f"<td>{_e(r.get('industry_name') or r.get('industry_code_l2'))}</td>"
            f"<td>{PHASE_ZH.get(str(r.get('lifecycle_state')), '')}</td>"
            f"<td>{_signed(r.get('steering_score_pct'), 2)}</td></tr>"
        )
    routing_block = (
        f"<h3>今日路由 <small>正相位行业 × 家族</small></h3>"
        f"<table><thead><tr><th>家族</th><th>行业</th><th>相位</th><th>分</th></tr></thead>"
        f"<tbody>{routing}</tbody></table>"
        if routing
        else '<p class="dim">今日无正相位行业路由 — 没有高潮/残留相位的行业,接力族先验为负。</p>'
    )
    fp = st.get("forward_payoff") or {}
    return f"""<section>
<h2>自适应转向 · 读序 <small>环境×轮动相位 = 注意力路由,非门槛 · {_e(st.get('generated_at_utc'))}</small></h2>
<p class="lede">今日环境 <strong>{ENV_ZH.get(env, env)}</strong>({_e(as_of.get('env_date'))}) · 行业相位:{phase_line}</p>
<table><thead><tr><th>序</th><th>家族</th><th>先验@今环境%</th><th>前向累计%</th><th>转向分</th><th>正相位</th><th>结算日</th></tr></thead>
<tbody>{rows}</tbody></table>
{routing_block}
<p class="dim">先验权重 {_e(fp.get('prior_pseudo_days'))} 个伪结算日 · 每日收益按 n/{_e(fp.get('payoff_n_ref'))} 可靠度缩放 · 每一次权重变动 = 账本一行({_e(fp.get('entries_total'))} 行)</p>
</section>"""


def _k_sec_holdout(holdout: dict[str, Any] | None) -> str:
    eras = (holdout or {}).get("eras") or []
    if not eras:
        return '<section><h2>真持出战绩</h2><p class="missing">暂无产物。</p></section>'
    blocks = ""
    for era in eras:
        rows = "".join(
            f"<tr><td class='code'>{_e(name)}</td>"
            f"<td class='num'>{_n(c.get('launch_rate_pct'))}</td>"
            f"<td class='num'>{_n(c.get('lift_x'))}×</td>"
            f"<td>{_signed(c.get('d3_excess'), 3)}</td>"
            f"<td class='num dim'>{_e(c.get('n'))}</td></tr>"
            for name, c in (era.get("cells") or {}).items()
        )
        blocks += f"""<div><h2 style="color:var(--steel)">{_e(era.get('era'))} <small>基线 launch {_n(era.get('baseline_launch_rate_pct'))}%</small></h2>
<table><thead><tr><th>cell</th><th>launch%</th><th>lift</th><th>d3 纸面超额%</th><th>n</th></tr></thead>
<tbody>{rows}</tbody></table></div>"""
    return f"""<section>
<h2>真持出战绩 <small>launch 家族 = 八年全政权结构性质;纸面均值为负 = 彩票解剖</small></h2>
<div class="grid2">{blocks}</div>
</section>"""


def _k_sec_forward(fl: dict[str, Any] | None) -> str:
    fl = fl or {}
    ex5 = fl.get("ex5_rule")
    freeze = fl.get("candidate_freeze")
    ex5_html = (
        f"<div class='code'>EX5 {_e(ex5.get('rule_id'))}</div>"
        f"<div class='kv'><span>冻结 <b class='num'>{_e(ex5.get('frozen_days'))}</b> 天</span>"
        f"<span>已结算 <b class='num'>{_e(ex5.get('settled_days'))}</b> 天 / <b class='num'>{_e(ex5.get('settled_entries'))}</b> 笔</span>"
        f"<span>累计净均值 <b class='num'>{_e(ex5.get('cumulative_net_mean_ret_pct') if ex5.get('cumulative_net_mean_ret_pct') is not None else '待成熟')}</b>%</span></div>"
        if ex5
        else '<p class="missing">EX5 账本暂缺。</p>'
    )
    freeze_html = (
        f"<div class='dim'>候选冻结:{_e(freeze.get('status'))} · as-of {_e(freeze.get('as_of_date'))}</div>"
        if freeze
        else ""
    )
    return f"""<section>
<h2>前向账本 <small>预注册规则,promotion 只看这里;in-sample 无权威</small></h2>
{ex5_html}{freeze_html}
</section>"""


def _k_sec_organism(bundle: dict[str, Any]) -> str:
    org = bundle.get("organism") or {}
    au1 = org.get("au1") or {}
    levels = " · ".join(f"{k}:{v}" for k, v in (au1.get("levels") or {}).items())
    au1_cls = "ok" if au1.get("status") == "OK" else "bad"
    queue = org.get("dp_queue") or {}
    flow = org.get("order_flow_canonical") or {}
    landed = (org.get("order_flow_backfill") or {}).get("packages_landed")
    chain = org.get("evening_chain") or {}
    files = "".join(
        f"<li class='code' style='opacity:{1 if a.get('exists') else .45}'>{_e(a.get('mtime_utc') or '缺席')} — {_e(a.get('path'))}</li>"
        for a in bundle.get("artifact_index") or []
    )
    return f"""<section>
<h2>机体状态 <small>回填 · 免疫 · 晚链 · 窗口 {_e(org.get('window_registry_version'))}</small></h2>
<div class="kv">
<span>免疫 AU1 <span class="pill {au1_cls}">{_e(au1.get('status') or '未知')}</span></span>
<span>资金流 canonical <b class="num">{_e(flow.get('d'))}</b> 天({_e(flow.get('lo'))} → {_e(flow.get('hi'))})</span>
<span>包裹已落 <b class="num">{_e(landed)}</b></span>
<span>队列 pending <b class="num">{_e(queue.get('pending'))}</b> / failed <b class="num">{_e(queue.get('failed'))}</b></span>
<span class="dim">晚链上次退出码 {_e(chain.get('ExecMainStatus'))}</span></div>
<p class="lede">{levels}</p>
<details><summary>产物目录(关键 artifact · UTC 更新时间)</summary><ul class="files">{files}</ul></details>
</section>"""


ARCHIVE_DIR = COSMOS / "ft-kairos" / "var" / "reports" / "research_substrate" / "owner_daily_archive"


def _k_sec_days(days: list[dict[str, Any]] | None) -> str:
    if not days:
        return ""
    rows = ""
    for d in days:
        r = d.get("recall") or {}
        if r.get("status") == "D1_LAUNCH_RECALL":
            recall_html = (
                f"全市场 <span class='num'>{_e(r.get('market_launch_count'))}</span> · "
                f"命中 <span class='num'>{_e(r.get('candidate_launch_count'))}</span> · "
                f"prec <span class='num'>{_n(r.get('precision_pct'), 1)}%</span>"
            )
        else:
            recall_html = "<span class='dim'>待成熟</span>"
        rows += (
            f"<tr><td><a class='code' style='color:var(--fire)' "
            f"href='/kairos/day/{_e(d.get('archive_date'))}'>{_e(d.get('target_trade_date'))}</a></td>"
            f"<td class='num dim'>{_e(d.get('as_of_date'))}</td>"
            f"<td class='num'>{_e(d.get('candidate_count'))}</td>"
            f"<td class='num dim'>{_e(d.get('watchlist_count'))}</td>"
            f"<td>{recall_html}</td></tr>"
        )
    return f"""<section>
<h2>历史档案 <small>点日期看完整包 + 当日复盘 · 回头找东西在这里</small></h2>
<table><thead><tr><th>目标交易日</th><th>as-of</th><th>候选</th><th>watch</th><th>d1 复盘</th></tr></thead>
<tbody>{rows}</tbody></table>
</section>"""


async def page_kairos_day(request: Any) -> HTMLResponse:
    date = str(request.path_params.get("date") or "")
    safe = date.replace("-", "")
    if not (len(date) == 10 and safe.isdigit()):
        return HTMLResponse(_page("kairos", "太一 · 档案", "丙火", "无效日期", ""), status_code=404)
    day_dir = ARCHIVE_DIR / date
    pkg = _load_json(day_dir / "owner_daily_package.json")
    if not pkg:
        body = '<section><p class="missing">该日无归档包。</p></section>'
        return HTMLResponse(_page("kairos", f"太一 · {date}", "丙火", "档案缺席", body))
    cands = pkg.get("owner_stock_candidate_list") or []
    rows = ""
    for i, c in enumerate(cands):
        wounds = c.get("evidence_wounds") or []
        wound_txt = (
            "<br>".join(_e(w if isinstance(w, str) else json.dumps(w, ensure_ascii=False)[:90]) for w in wounds[:3])
            if wounds
            else "<span class='dim'>—</span>"
        )
        rows += (
            f"<tr><td class='num dim'>{_e(c.get('rank') or i + 1)}</td>"
            f"<td class='code'>{_e(str(c.get('stock_code') or '').split('.')[0])}</td>"
            f"<td>{_e(c.get('stock_name'))}</td>"
            f"<td>{_e(c.get('industry_name'))}</td>"
            f"<td class='code dim'>{_e(c.get('best_tactic_id'))}</td>"
            f"<td class='num'>{_n(c.get('score'), 1)}</td>"
            f"<td style='font-size:11px'>{wound_txt}</td></tr>"
        )
    watch = pkg.get("stock_watchlist") or []
    watch_rows = "".join(
        f"<tr><td class='code'>{_e(str(w.get('stock_code') or '').split('.')[0])}</td>"
        f"<td>{_e(w.get('stock_name'))}</td><td>{_e(w.get('industry_name'))}</td>"
        f"<td class='code dim'>{_e(w.get('best_tactic_id') or w.get('reason'))}</td></tr>"
        for w in watch
    )
    # recall for THIS day from the bundle history
    bundle = _load_json(KAIROS_BUNDLE) or {}
    day_rec = next(
        (d.get("recall") for d in bundle.get("days") or [] if d.get("archive_date") == date),
        None,
    ) or {}
    if day_rec.get("status") == "D1_LAUNCH_RECALL":
        hits = day_rec.get("hit_codes") or []
        recall_html = f"""<div class="kv">
<span>全市场 launch(≥5%) <b class="num">{_e(day_rec.get('market_launch_count'))}</b></span>
<span>候选命中 <b class="num">{_e(day_rec.get('candidate_launch_count'))}</b></span>
<span>precision <b class="num">{_n(day_rec.get('precision_pct'), 1)}%</b></span>
<span>recall <b class="num">{_n(day_rec.get('recall_pct'))}%</b></span></div>
<div class="code">{('命中:' + _e(' · '.join(hits))) if hits else ''}</div>"""
    else:
        recall_html = '<p class="missing">当日结果待成熟。</p>'
    nav_days = [d.get("archive_date") for d in bundle.get("days") or []]
    try:
        idx = nav_days.index(date)
        prev_d = nav_days[idx + 1] if idx + 1 < len(nav_days) else None
        next_d = nav_days[idx - 1] if idx > 0 else None
    except ValueError:
        prev_d = next_d = None
    nav = "<div class='kv'>"
    if prev_d:
        nav += f"<a class='code' style='color:var(--steel)' href='/kairos/day/{prev_d}'>← {prev_d}</a>"
    nav += "<a class='code' style='color:var(--dim)' href='/kairos'>返回作战台</a>"
    if next_d:
        nav += f"<a class='code' style='color:var(--steel)' href='/kairos/day/{next_d}'>{next_d} →</a>"
    nav += "</div>"
    body = f"""{nav}
<section><h2>当日复盘(d1 launch)</h2>{recall_html}</section>
<section><h2>候选全表 <small>{len(cands)} 名 · accepted_edges {_e(pkg.get('accepted_edges'))}</small></h2>
<table><thead><tr><th>#</th><th>代码</th><th>名称</th><th>行业</th><th>战法</th><th>分</th><th>伤口</th></tr></thead>
<tbody>{rows}</tbody></table></section>
<section><h2>Watchlist <small>{len(watch)} 名</small></h2>
<table><thead><tr><th>代码</th><th>名称</th><th>行业</th><th>来由</th></tr></thead>
<tbody>{watch_rows}</tbody></table></section>"""
    return HTMLResponse(
        _page(
            "kairos",
            f"太一 · {_e(pkg.get('target_trade_date'))} 档案",
            f"as-of {_e(pkg.get('as_of_date'))}",
            f"生成 {_e(pkg.get('generated_at_utc'))} · 归档目录 {_e(str(day_dir))}",
            body,
        )
    )


NARRATIVE_PATH = (
    COSMOS / "ft-kairos" / "var" / "reports" / "research_substrate" / "eod_narrative_review_latest.md"
)


def _k_sec_narrative() -> str:
    text = _read_text(NARRATIVE_PATH, 8000)
    if not text:
        return ""
    return f"""<section>
<h2>日记 <small>它自己写的复盘 · 每句数字可溯源 · {_mtime(NARRATIVE_PATH)}</small></h2>
<pre class="doc">{_e(text)}</pre>
</section>"""


async def page_kairos(_req: Any) -> HTMLResponse:
    bundle = _load_json(KAIROS_BUNDLE)
    if not bundle:
        body = '<section><p class="missing">bundle 缺席 — kairos owner_web_projection 未产出。</p></section>'
        stamp = ""
    else:
        body = (
            _k_sec_package(bundle.get("today_package"))
            + _k_sec_narrative()
            + _k_sec_recall(bundle.get("recall"))
            + _k_sec_days(bundle.get("days"))
            + _k_sec_families(bundle.get("family_verdicts"))
            + _k_sec_steering(bundle.get("adaptive_steering"))
            + _k_sec_holdout(bundle.get("holdout"))
            + _k_sec_forward(bundle.get("forward_ledger"))
            + _k_sec_organism(bundle)
        )
        stamp = f"bundle 刷新 {_e(bundle.get('generated_at_utc'))} · "
    return HTMLResponse(
        _page("kairos", "太一 · 作战台", "丙火 · A 股战场", f"{stamp}研究·证据·执行的全部产出", body)
    )


# ---------------------------------------------------------------- 地载 (atlas)
def _atlas_units() -> str:
    raw = _sysctl(["list-timers", "--no-pager", "--no-legend"])
    rows = ""
    for line in raw.splitlines():
        if "kairos" not in line and "cosmos" not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        nxt = " ".join(parts[0:3])
        unit = next((p for p in parts if p.endswith(".timer")), "?")
        rows += f"<tr><td class='code'>{_e(unit)}</td><td class='num dim'>{_e(nxt)}</td></tr>"
    failed = _sysctl(["--failed", "--no-legend", "--plain"])
    failed_units = [
        line.split()[0] for line in failed.splitlines() if "kairos" in line or "cosmos" in line
    ]
    failed_html = (
        f"<p class='neg'>失败单元:{_e(', '.join(failed_units))}</p>"
        if failed_units
        else "<p class='pos'>无失败单元</p>"
    )
    return f"""<section>
<h2>自动化骨架 <small>systemd timers(下次触发)</small></h2>
{failed_html}
<table><thead><tr><th>timer</th><th>next</th></tr></thead><tbody>{rows}</tbody></table>
</section>"""


def _atlas_backups() -> str:
    spots = [
        ("research 二副本快照", COSMOS / "ft-kairos" / "var" / "backups"),
        ("atlas ops systemd 单元数", COSMOS / "ft-atlas" / "ops" / "systemd"),
    ]
    rows = ""
    for label, p in spots:
        if p.is_dir():
            count = sum(1 for _ in p.iterdir())
            rows += f"<tr><td>{_e(label)}</td><td class='num'>{count} 项</td><td class='num dim'>{_mtime(p)}</td></tr>"
        else:
            rows += f"<tr><td>{_e(label)}</td><td class='missing' colspan='2'>缺席</td></tr>"
    return f"""<section>
<h2>承载与备份 <small>pgBackRest + NAS 链路详情见 atlas runbook</small></h2>
<table><thead><tr><th>面</th><th>规模</th><th>mtime</th></tr></thead><tbody>{rows}</tbody></table>
</section>"""


async def page_atlas(_req: Any) -> HTMLResponse:
    body = _atlas_units() + _atlas_backups()
    return HTMLResponse(
        _page("atlas", "地载 · 基础设施", "土 · 承载", "systemd 骨架 · 备份 · 恢复", body)
    )


# ---------------------------------------------------------------- 乾坤治理 (cosmos)
async def page_cosmos(_req: Any) -> HTMLResponse:
    now_md = _read_text(COSMOS / "docs" / "control" / "NOW.md") or "(缺席)"
    backlog_md = _read_text(COSMOS / "docs" / "control" / "BACKLOG.md", 60_000) or "(缺席)"
    goals = sorted((COSMOS / "docs" / "control" / "goals").glob("*.md"))
    goals_html = "".join(
        f"<li class='code'>{_mtime(g)} — {_e(g.name)}</li>" for g in goals
    )
    body = f"""<section><h2>NOW <small>{_mtime(COSMOS / 'docs/control/NOW.md')}</small></h2>
<pre class="doc">{_e(now_md)}</pre></section>
<section><h2>BACKLOG <small>{_mtime(COSMOS / 'docs/control/BACKLOG.md')} · 活动控制面 = NOW + BACKLOG</small></h2>
<pre class="doc">{_e(backlog_md)}</pre></section>
<section><h2>Goals</h2><ul class="files">{goals_html}</ul></section>"""
    return HTMLResponse(
        _page("cosmos", "乾坤 · 治理", "场 · 容器", "控制面真值:NOW + BACKLOG + goals", body)
    )


# ---------------------------------------------------------------- 天道 (logos)
async def page_logos(_req: Any) -> HTMLResponse:
    index_md = _read_text(
        COSMOS / "ft-kairos" / "docs" / "research" / "SHORT_CYCLE_RESEARCH_INDEX.md",
        60_000,
    )
    body = (
        f'<section><h2>短周期研究索引 <small>{_mtime(COSMOS / "ft-kairos/docs/research/SHORT_CYCLE_RESEARCH_INDEX.md")} · 知识喂行动</small></h2>'
        f'<pre class="doc">{_e(index_md or "(缺席)")}</pre></section>'
        '<section><h2>记忆器官 <small>ft-logos</small></h2>'
        '<p class="missing">Logos 知识库的 web 投影是占位:检索/卡片面尚未接入本台(kb-search 走 MCP)。'
        "落实计划:研究索引已渲染于上;下一步把 logos 知识卡按主题列出。</p></section>"
    )
    return HTMLResponse(
        _page("logos", "天道 · 知识", "木 · 生火", "知识与记忆 — 喂给太一的行动", body)
    )


# ---------------------------------------------------------------- 灵枢 (hermes)
async def page_hermes(_req: Any) -> HTMLResponse:
    src = COSMOS / "ft-hermes" / "src"
    contracts = sorted(src.rglob("*.py")) if src.is_dir() else []
    listing = "".join(
        f"<li class='code'>{_e(p.relative_to(COSMOS / 'ft-hermes'))}</li>"
        for p in contracts[:60]
    )
    body = f"""<section><h2>契约脊柱 <small>contracts-only,中立,不挂业务语义</small></h2>
<div class="kv"><span>契约源文件 <b class="num">{len(contracts)}</b></span></div>
<details open><summary>契约文件清单</summary><ul class="files">{listing}</ul></details>
</section>
<section><h2>占位:契约渲染</h2>
<p class="missing">数据包请求/确认等 schema 的人读渲染未接;落实计划:从 fthermes.contracts 生成只读 schema 卡片。</p></section>"""
    return HTMLResponse(
        _page("hermes", "灵枢 · 契约", "金 · 中立", "组织间的神经传导 — 只传契约,不带业务", body)
    )


# ---------------------------------------------------------------- 太虚 (proteus)
async def page_proteus(_req: Any) -> HTMLResponse:
    body = """<section><h2>器官状态</h2>
<p class="missing">太虚(数字资产器官)尚无运行产物 — 这是诚实占位,不是装饰。
器官章程:数字资产业务;依赖只允许灵枢;当业务启动时,本页渲染其产出包与账本。</p></section>"""
    return HTMLResponse(
        _page("proteus", "太虚 · 数字资产", "水 · 流动", "流动与不确定性的器官(未启动)", body)
    )


# ---------------------------------------------------------------- 天工 (daedalus)
async def page_daedalus(_req: Any) -> HTMLResponse:
    wechat_readme = (COSMOS / "ft-daedalus" / "README.md")
    body = f"""<section><h2>工具清单</h2>
<table><thead><tr><th>工具</th><th>状态</th><th>说明</th></tr></thead><tbody>
<tr><td>乾坤台(本 console)</td><td><span class="pill ok">LIVE</span></td><td class="dim">:3000 零构建零密码,全器官单入口</td></tr>
<tr><td>WeChat operator surface</td><td><span class="pill pilot">存量</span></td><td class="dim">tmux live session 的微信操作面(daedalus_wechat)</td></tr>
<tr><td>Owner 复盘采集(OC1 后半)</td><td><span class="pill pilot">占位</span></td><td class="dim">owner 侧捕捉 UX 待 owner 驱动;intake 链已在晚链</td></tr>
</tbody></table>
<p class="lede">README {_mtime(wechat_readme)}</p>
</section>"""
    return HTMLResponse(
        _page("daedalus", "天工 · 工具", "器 · 造物", "Owner/operator 工具(本台所属器官)", body)
    )


# ---------------------------------------------------------------- 总览 (home)
def _vital_kairos() -> str:
    b = _load_json(KAIROS_BUNDLE) or {}
    pkg = b.get("today_package") or {}
    rc = b.get("recall") or {}
    fv = (b.get("family_verdicts") or {}).get("verdict_counts") or {}
    org = b.get("organism") or {}
    au1 = (org.get("au1") or {}).get("status")
    flow = org.get("order_flow_canonical") or {}
    return (
        f"今日包 → <b class='num'>{_e(pkg.get('target_trade_date'))}</b>(候选 {_e(pkg.get('candidate_count'))})<br>"
        f"复盘 {_e(rc.get('target_trade_date'))}:全市场 launch {_e(rc.get('whole_market_launch_count'))},"
        f"命中 {_e(rc.get('candidate_launch_count'))}<br>"
        f"家族:稳定 {fv.get('DURABLE', 0)} · 彩票 {fv.get('LOTTERY', 0)} · 试点 {fv.get('PILOT', 0)}<br>"
        f"免疫 AU1 <span class='pill {'ok' if au1 == 'OK' else 'bad'}'>{_e(au1 or '未知')}</span> · "
        f"资金流 {_e(flow.get('d'))} 天"
    )


def _vital_atlas() -> str:
    failed = _sysctl(["--failed", "--no-legend", "--plain"])
    n_failed = len([line for line in failed.splitlines() if line.strip()])
    timers = _sysctl(["list-timers", "--no-pager", "--no-legend"])
    n_timers = len([line for line in timers.splitlines() if "kairos" in line])
    cls = "ok" if n_failed == 0 else "bad"
    return (
        f"失败单元 <span class='pill {cls}'>{n_failed}</span> · "
        f"kairos timers <b class='num'>{n_timers}</b><br>晚链 17:35 起五档重试 · 21:05 迟到告警"
    )


def _vital_cosmos() -> str:
    backlog = COSMOS / "docs" / "control" / "BACKLOG.md"
    text = _read_text(backlog, 200_000) or ""
    active = text.count("| ACTIVE |")
    done = text.count("| DONE |")
    queued = text.count("| QUEUED |")
    return f"BACKLOG:ACTIVE <b class='num'>{active}</b> · QUEUED <b class='num'>{queued}</b> · DONE <b class='num'>{done}</b><br>更新 {_mtime(backlog)}"


async def page_home(_req: Any) -> HTMLResponse:
    vitals = {
        "kairos": _vital_kairos(),
        "atlas": _vital_atlas(),
        "cosmos": _vital_cosmos(),
        "logos": "研究索引随产出滚动 · 知识卡占位",
        "hermes": "契约脊柱 · schema 渲染占位",
        "proteus": "未启动(诚实占位)",
        "daedalus": "乾坤台 LIVE · WeChat 面存量 · OC1 采集占位",
    }
    cards = "".join(
        f"""<a class="card" href="/{o['slug']}">
<div class="t">{o['zh']} <span class="el">{o['en']} · {o['element']}</span></div>
<div class="r">{o['role']}</div>
<div class="v">{vitals.get(o['slug'], '')}</div></a>"""
        for o in ORGANS
    )
    body = f'<div class="cards">{cards}</div>'
    return HTMLResponse(
        _page("home", "乾坤 · 组织总览", "一个生命体,活在 A 股里", "七器官 · 单入口 · 零密码 · 证据即视图", body)
    )


async def api_bundle(_req: Any) -> JSONResponse:
    return JSONResponse(_load_json(KAIROS_BUNDLE) or {"error": "bundle_missing"})


async def legacy_research(_req: Any) -> RedirectResponse:
    return RedirectResponse("/kairos", status_code=307)


app = Starlette(
    routes=[
        Route("/", page_home),
        Route("/kairos", page_kairos),
        Route("/kairos/day/{date}", page_kairos_day),
        Route("/atlas", page_atlas),
        Route("/cosmos", page_cosmos),
        Route("/logos", page_logos),
        Route("/hermes", page_hermes),
        Route("/proteus", page_proteus),
        Route("/daedalus", page_daedalus),
        Route("/research", legacy_research),
        Route("/api/bundle", api_bundle),
    ]
)


def main() -> int:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=3000, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
