#!/usr/bin/env python3
"""Claude Code 对话日志查看器 — 直观展示对话记录的 Web 页面。

两种查看模式：
- 按文件：选择 JSONL 文件查看
- 按天：跨文件按日期聚合查看

Usage:
    python3 scripts/conversation_viewer.py
    # 打开 http://localhost:8888
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

CST = timezone(timedelta(hours=8))

JSONL_DIR = Path.home() / ".claude/projects/-home-iamlibai-workspace-claude-project-xiaomei-brain"

PAGE_SIZE = 20

# ── 全局缓存 ──
_day_index_cache: dict | None = None  # {date_str: count}
_cache_mtime: float = 0  # 最新 JSONL 文件 mtime，用于失效检测


def get_cst_date(ts_str: str) -> str:
    """UTC timestamp → CST date string YYYY-MM-DD."""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.astimezone(CST).strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return ts_str[:10] if len(ts_str) >= 10 else ts_str


def utc_to_cst(ts_str: str) -> str:
    """UTC timestamp → CST datetime string."""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.astimezone(CST).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, AttributeError):
        return ts_str


# ── JSONL 文件列表 ──────────────────────────────────────────

def find_jsonl_files(directory: Path) -> list[dict]:
    files = []
    for p in sorted(directory.glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True):
        stat = p.stat()
        size_mb = stat.st_size / (1024 * 1024)
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=CST).strftime("%Y-%m-%d %H:%M")
        files.append({
            "file": p.name,
            "label": p.stem[:20],
            "size_mb": round(size_mb, 1),
            "mtime": mtime,
            "info": f"{size_mb:.0f}MB · {mtime}",
        })
    return files


# ── 按天索引 ────────────────────────────────────────────────

def build_day_index(force: bool = False) -> dict:
    """扫描所有 JSONL 文件，返回 {date_str: turn_count}。

    结果缓存在 _day_index_cache 中，仅在文件有更新时重新扫描。
    """
    global _day_index_cache, _cache_mtime
    if not force and _day_index_cache is not None:
        # 检查是否有更新的文件
        latest = max((p.stat().st_mtime for p in JSONL_DIR.glob("*.jsonl")), default=0)
        if latest <= _cache_mtime:
            return _day_index_cache

    counts = defaultdict(int)
    for jsonl_path in sorted(JSONL_DIR.glob("*.jsonl")):
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "user" or obj.get("isMeta"):
                    continue
                content = obj.get("message", {}).get("content", "")
                if isinstance(content, list) or not isinstance(content, str):
                    continue
                content = content.strip()
                if not content or content.startswith("<command-name>") or content.startswith("<local-command"):
                    continue
                date_str = get_cst_date(obj.get("timestamp", ""))
                counts[date_str] += 1

    _day_index_cache = dict(sorted(counts.items(), reverse=True))
    _cache_mtime = max((p.stat().st_mtime for p in JSONL_DIR.glob("*.jsonl")), default=time.time())
    return _day_index_cache


# ── 对话提取 ────────────────────────────────────────────────

def _is_valid_user_message(obj: dict) -> bool:
    """检查是否为有效的用户消息。"""
    if obj.get("type") != "user" or obj.get("isMeta"):
        return False
    content = obj.get("message", {}).get("content", "")
    if isinstance(content, list):
        return False
    content = str(content).strip()
    if not content or content.startswith("<command-name>") or content.startswith("<local-command"):
        return False
    return True


def _parse_assistant_blocks(content: list) -> list[dict]:
    """解析 assistant 消息的 content 列表为展示用的 blocks。"""
    blocks = []
    for block in (content or []):
        if not isinstance(block, dict):
            continue
        bt = block.get("type", "")
        if bt == "thinking":
            text = block.get("thinking", block.get("text", ""))
            if text and text.strip():
                blocks.append({"type": "thinking", "content": text.strip()[:500]})
        elif bt == "tool_use":
            blocks.append({
                "type": "tool",
                "name": block.get("name", "?"),
                "input": json.dumps(block.get("input", {}), ensure_ascii=False)[:200],
            })
        elif bt == "text":
            text = block.get("text", "")
            if text.strip():
                blocks.append({"type": "text", "content": text.strip()})
    return blocks


def extract_turns(jsonl_path: Path, page: int = 0, page_size: int = PAGE_SIZE) -> dict:
    """从单个 JSONL 文件提取分页对话轮次。"""
    all_turns = []
    current_user = None
    current_blocks = []

    def commit():
        nonlocal current_blocks
        if current_user is None:
            current_blocks = []
            return
        user_text = current_user["content"].strip()
        has_text = any(b["type"] == "text" and b["content"].strip() for b in current_blocks)
        if user_text or has_text:
            all_turns.append({"time": current_user["time"], "user": user_text or None, "blocks": list(current_blocks)})
        current_blocks = []

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            t = obj.get("type", "")
            msg = obj.get("message", {})
            content = msg.get("content", "")

            if _is_valid_user_message(obj):
                commit()
                current_user = {"time": utc_to_cst(obj["timestamp"]), "content": str(content).strip()}
            elif t == "assistant":
                if not isinstance(content, list):
                    continue
                current_blocks.extend(_parse_assistant_blocks(content))

        commit()

    total = len(all_turns)
    total_pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 1
    start = page * page_size
    return {
        "turns": all_turns[start:start + page_size],
        "page": page, "page_size": page_size,
        "total_turns": total, "total_pages": total_pages,
    }


def extract_turns_by_date(date_str: str, page: int = 0, page_size: int = PAGE_SIZE) -> dict:
    """跨所有 JSONL 文件提取指定日期的对话轮次（分页）。"""
    all_turns = []
    current_user = None
    current_blocks = []

    def commit():
        nonlocal current_blocks
        if current_user is None:
            current_blocks = []
            return
        user_text = current_user["content"].strip()
        has_text = any(b["type"] == "text" and b["content"].strip() for b in current_blocks)
        if user_text or has_text:
            all_turns.append({"time": current_user["time"], "user": user_text or None, "blocks": list(current_blocks)})
        current_blocks = []

    for jsonl_path in sorted(JSONL_DIR.glob("*.jsonl")):
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts = obj.get("timestamp", "")
                if get_cst_date(ts) != date_str:
                    # 即使日期不匹配，也可能有跨天的 assistant 回复需要关联到当前用户
                    # 简化处理：只关注日期匹配的消息
                    t = obj.get("type", "")
                    if t == "assistant" and current_user is not None:
                        msg = obj.get("message", {})
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            current_blocks.extend(_parse_assistant_blocks(content))
                    continue

                t = obj.get("type", "")
                msg = obj.get("message", {})
                content = msg.get("content", "")

                if _is_valid_user_message(obj):
                    commit()
                    current_user = {"time": utc_to_cst(ts), "content": str(content).strip()}
                elif t == "assistant":
                    if not isinstance(content, list):
                        continue
                    current_blocks.extend(_parse_assistant_blocks(content))

    commit()

    total = len(all_turns)
    total_pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 1
    start = page * page_size
    return {
        "turns": all_turns[start:start + page_size],
        "page": page, "page_size": page_size,
        "total_turns": total, "total_pages": total_pages,
    }


# ── HTTP Handler ────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claude Code 对话日志</title>
<style>
:root {
    --bg: #1a1a2e; --surface: #16213e; --surface2: #0f3460;
    --text: #e4e4e7; --text2: #a1a1aa; --accent: #e94560;
    --user-bg: #1a3a4a; --asst-bg: #16213e; --border: #2a2a4a;
    --code-bg: #0d1117; --thinking: #8b5cf6; --tool: #f59e0b;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", sans-serif; background: var(--bg); color: var(--text); height: 100vh; display: flex; }
/* ── Sidebar ── */
.sidebar { width: 260px; min-width: 260px; background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; }
.sidebar-header { padding: 16px 16px 10px; border-bottom: 1px solid var(--border); }
.sidebar-header h2 { font-size: 18px; font-weight: 700; background: linear-gradient(135deg, var(--accent), #f59342); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.sidebar-header p { font-size: 11px; color: var(--text2); margin-top: 4px; }
/* ── Mode tabs ── */
.mode-tabs { display: flex; padding: 8px 8px 0; gap: 4px; }
.mode-tab { flex: 1; padding: 6px 0; text-align: center; border-radius: 6px 6px 0 0; cursor: pointer; font-size: 12px; color: var(--text2); border: 1px solid transparent; border-bottom: none; transition: all .15s; }
.mode-tab:hover { color: var(--text); }
.mode-tab.active { color: var(--text); background: var(--bg); border-color: var(--border); font-weight: 600; }
/* ── List ── */
.item-list { flex: 1; overflow-y: auto; padding: 4px 8px 8px; }
.item-row { display: flex; align-items: center; padding: 10px 12px; border-radius: 8px; cursor: pointer; transition: all .15s; margin-bottom: 2px; gap: 10px; }
.item-row:hover { background: var(--surface2); }
.item-row.active { background: var(--surface2); border-left: 3px solid var(--accent); padding-left: 9px; }
.item-icon { width: 32px; height: 32px; border-radius: 50%; background: var(--surface2); display: flex; align-items: center; justify-content: center; font-size: 14px; flex-shrink: 0; }
.item-info { flex: 1; min-width: 0; }
.item-name { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.item-meta { font-size: 11px; color: var(--text2); margin-top: 2px; }
/* ── Main ── */
.main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.topbar { padding: 12px 24px; border-bottom: 1px solid var(--border); background: var(--surface); display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.topbar h3 { font-size: 16px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.topbar-right { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
.btn { padding: 6px 14px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface2); color: var(--text); cursor: pointer; font-size: 13px; transition: all .15s; }
.btn:hover { border-color: var(--accent); }
.btn:disabled { opacity: .4; cursor: default; }
.page-jump { width: 50px; padding: 6px 4px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface2); color: var(--text); font-size: 13px; text-align: center; }
.conversation { flex: 1; overflow-y: auto; padding: 24px; display: flex; flex-direction: column; gap: 24px; }
/* ── Turn ── */
.turn { display: flex; flex-direction: column; gap: 10px; }
.turn-header { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text2); padding: 0 4px; }
.turn-header .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }
.turn-header .file-tag { font-size: 10px; color: var(--text2); background: var(--surface2); padding: 1px 6px; border-radius: 4px; }
/* ── Bubbles ── */
.bubble { padding: 14px 18px; border-radius: 12px; line-height: 1.7; font-size: 14px; max-width: 100%; overflow-x: auto; }
.user-bubble { background: var(--user-bg); border-left: 3px solid #3b82f6; font-weight: 500; }
.asst-bubble { background: var(--asst-bg); border-left: 3px solid var(--accent); }
.thinking-block { background: var(--code-bg); border-left: 3px solid var(--thinking); padding: 10px 14px; margin: 6px 0; border-radius: 8px; font-size: 13px; color: #a78bfa; font-style: italic; }
.tool-block { background: var(--code-bg); border-left: 3px solid var(--tool); padding: 8px 14px; margin: 6px 0; border-radius: 8px; font-size: 13px; }
.tool-block .tool-name { color: var(--tool); font-weight: 600; }
.code-block { background: var(--code-bg); padding: 12px 16px; border-radius: 8px; margin: 8px 0; overflow-x: auto; font-family: "JetBrains Mono", "Fira Code", monospace; font-size: 13px; white-space: pre-wrap; word-break: break-word; }
/* ── States ── */
.loading { display: flex; align-items: center; justify-content: center; height: 200px; color: var(--text2); font-size: 14px; }
.spinner { width: 24px; height: 24px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin .6s linear infinite; margin-right: 10px; }
@keyframes spin { to { transform: rotate(360deg); } }
.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--text2); gap: 12px; }
.empty-state .icon { font-size: 48px; }
/* ── Markdown ── */
.bubble h1, .bubble h2 { font-size: 1.2em; margin: 10px 0 6px; }
.bubble h3, .bubble h4 { font-size: 1.05em; margin: 8px 0 4px; }
.bubble ul, .bubble ol { padding-left: 20px; margin: 6px 0; }
.bubble li { margin: 3px 0; }
.bubble p { margin: 6px 0; }
.bubble strong { color: #fbbf24; }
.bubble em { color: #94a3b8; }
.bubble blockquote { border-left: 3px solid #4b5563; padding: 4px 12px; margin: 8px 0; color: #9ca3af; }
.bubble .inline-code { background: var(--code-bg); padding: 2px 6px; border-radius: 4px; font-family: monospace; font-size: .9em; }
@media (max-width: 700px) { .sidebar { display: none; } }
</style>
</head>
<body>

<div class="sidebar">
    <div class="sidebar-header">
        <h2>Claude Code 对话日志</h2>
        <p id="list-summary">加载中...</p>
    </div>
    <div class="mode-tabs">
        <div class="mode-tab active" id="tab-file" onclick="switchMode('file')">按文件</div>
        <div class="mode-tab" id="tab-day" onclick="switchMode('day')">按天</div>
    </div>
    <div class="item-list" id="item-list"></div>
</div>

<div class="main">
    <div class="topbar">
        <h3 id="current-title">选择一个会话</h3>
        <div class="topbar-right">
            <span id="page-info" style="font-size:12px;color:var(--text2)"></span>
            <input type="number" class="page-jump" id="page-jump" min="1" value="1" onkeydown="if(event.key==='Enter')jumpPage()">
            <button class="btn" id="btn-prev" onclick="prevPage()" disabled>上一页</button>
            <button class="btn" id="btn-next" onclick="nextPage()" disabled>下一页</button>
        </div>
    </div>
    <div class="conversation" id="conversation">
        <div class="empty-state"><div class="icon">💬</div><div>从左侧选择查看对话记录</div></div>
    </div>
</div>

<script>
const state = {
    mode: 'file',
    files: [],
    days: [],
    currentKey: null,
    currentPage: 0,
    totalPages: 0,
};

async function init() {
    // 并行加载文件和日期索引
    const [fr, dr] = await Promise.all([
        fetch('/api/sessions'),
        fetch('/api/days')
    ]);
    state.files = await fr.json();
    state.days = await dr.json();
    switchMode('file');
}

function switchMode(mode) {
    state.mode = mode;
    state.currentKey = null;
    state.currentPage = 0;
    document.getElementById('tab-file').classList.toggle('active', mode === 'file');
    document.getElementById('tab-day').classList.toggle('active', mode === 'day');

    if (mode === 'file') {
        document.getElementById('list-summary').textContent = `${state.files.length} 个会话`;
        renderFileList();
        if (state.files.length > 0) selectFile(0);
    } else {
        document.getElementById('list-summary').textContent = `${state.days.length} 天`;
        renderDayList();
        if (state.days.length > 0) selectDay(0);
    }
}

function renderFileList() {
    const el = document.getElementById('item-list');
    el.innerHTML = state.files.map((f, i) => `
        <div class="item-row ${state.currentKey === f.file ? 'active' : ''}" onclick="selectFile(${i})">
            <div class="item-icon">📁</div>
            <div class="item-info">
                <div class="item-name">${esc(f.label)}</div>
                <div class="item-meta">${f.info}</div>
            </div>
        </div>
    `).join('');
}

function renderDayList() {
    const el = document.getElementById('item-list');
    el.innerHTML = state.days.map((d, i) => `
        <div class="item-row ${state.currentKey === d.date ? 'active' : ''}" onclick="selectDay(${i})">
            <div class="item-icon">📅</div>
            <div class="item-info">
                <div class="item-name">${d.date}</div>
                <div class="item-meta">${d.count} 轮对话</div>
            </div>
        </div>
    `).join('');
}

function selectFile(idx) {
    state.currentKey = state.files[idx].file;
    state.currentPage = 0;
    document.getElementById('current-title').textContent = '会话: ' + state.files[idx].label;
    updateActiveRow();
    loadPage(0);
}

function selectDay(idx) {
    state.currentKey = state.days[idx].date;
    state.currentPage = 0;
    document.getElementById('current-title').textContent = '日期: ' + state.days[idx].date;
    updateActiveRow();
    loadPage(0);
}

function updateActiveRow() {
    document.querySelectorAll('.item-row').forEach(el => el.classList.remove('active'));
    const items = document.querySelectorAll('.item-row');
    const idx = state.mode === 'file'
        ? state.files.findIndex(f => f.file === state.currentKey)
        : state.days.findIndex(d => d.date === state.currentKey);
    if (idx >= 0 && items[idx]) items[idx].classList.add('active');
}

async function loadPage(page) {
    const conv = document.getElementById('conversation');
    conv.innerHTML = '<div class="loading"><div class="spinner"></div>加载中...</div>';
    document.getElementById('btn-prev').disabled = true;
    document.getElementById('btn-next').disabled = true;

    let url;
    if (state.mode === 'file') {
        url = `/api/conversations?file=${encodeURIComponent(state.currentKey)}&page=${page}`;
    } else {
        url = `/api/conversations-by-day?date=${encodeURIComponent(state.currentKey)}&page=${page}`;
    }

    const res = await fetch(url);
    const data = await res.json();

    state.currentPage = data.page;
    state.totalPages = data.total_pages;

    document.getElementById('page-info').textContent =
        `第 ${data.page + 1}/${Math.max(1, data.total_pages)} 页 · ${data.total_turns} 轮`;
    document.getElementById('page-jump').value = data.page + 1;
    document.getElementById('page-jump').max = Math.max(1, data.total_pages);

    if (data.turns.length === 0) {
        conv.innerHTML = '<div class="empty-state"><div class="icon">📭</div><div>暂无对话记录</div></div>';
        return;
    }

    conv.innerHTML = data.turns.map(renderTurn).join('');
    conv.scrollTop = 0;

    document.getElementById('btn-prev').disabled = page <= 0;
    document.getElementById('btn-next').disabled = page >= data.total_pages - 1;
}

function jumpPage() {
    const p = parseInt(document.getElementById('page-jump').value) - 1;
    if (p >= 0 && p < state.totalPages) loadPage(p);
    else document.getElementById('page-jump').value = state.currentPage + 1;
}

function prevPage() { if (state.currentPage > 0) loadPage(state.currentPage - 1); }
function nextPage() { if (state.currentPage < state.totalPages - 1) loadPage(state.currentPage + 1); }

function renderTurn(turn) {
    let html = `<div class="turn"><div class="turn-header"><div class="dot"></div>${esc(turn.time)}`;
    if (turn.file) html += ` <span class="file-tag">${esc(turn.file)}</span>`;
    html += `</div>`;
    if (turn.user) html += `<div class="bubble user-bubble"><strong>用户</strong><br>${md2html(turn.user)}</div>`;
    for (const block of (turn.blocks || [])) {
        if (block.type === 'thinking') html += `<div class="thinking-block">💭 ${esc(block.content)}</div>`;
        else if (block.type === 'tool') html += `<div class="tool-block">🔧 <span class="tool-name">${esc(block.name)}</span></div>`;
        else if (block.type === 'text') html += `<div class="bubble asst-bubble">${md2html(block.content)}</div>`;
    }
    html += '</div>';
    return html;
}

function md2html(text) {
    let html = esc(text);
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<div class="code-block">$2</div>');
    html = html.replace(/`([^`]+)`/g, '<span class="inline-code">$1</span>');
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
    html = html.replace(/((?:<li>[^<]*<\/li>)+)/g, '<ul>$1</ul>');
    html = html.replace(/\n\n/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');
    return '<p>' + html + '</p>';
}

function esc(s) { if (!s) return ''; return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

init();
</script>
</body>
</html>"""


class ViewerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/":
            self._serve_html()
        elif path == "/api/sessions":
            self._serve_json(find_jsonl_files(JSONL_DIR))
        elif path == "/api/days":
            index = build_day_index()
            days = [{"date": d, "count": c} for d, c in sorted(index.items(), reverse=True)]
            self._serve_json(days)
        elif path == "/api/conversations":
            file_name = qs.get("file", [None])[0]
            page = int(qs.get("page", [0])[0])
            if not file_name:
                self._serve_json({"error": "missing file param"}, 400)
                return
            file_path = JSONL_DIR / file_name
            if not file_path.exists():
                self._serve_json({"error": "file not found"}, 404)
                return
            self._serve_json(extract_turns(file_path, page=page))
        elif path == "/api/conversations-by-day":
            date_str = qs.get("date", [None])[0]
            page = int(qs.get("page", [0])[0])
            if not date_str:
                self._serve_json({"error": "missing date param"}, 400)
                return
            self._serve_json(extract_turns_by_date(date_str, page=page))
        else:
            self.send_error(404)

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML.encode("utf-8"))

    def _serve_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def main():
    port = int(os.environ.get("PORT", "8888"))
    server = HTTPServer(("0.0.0.0", port), ViewerHandler)
    print(f"对话日志查看器已启动: http://localhost:{port}")
    print(f"JSONL 目录: {JSONL_DIR}")
    print("按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
