"use strict";

const $ = (s) => document.querySelector(s);
const api = (p, opt) => fetch(p, opt).then((r) => r.json());

// ---------- 极简 markdown 渲染（覆盖我们 prompt 的输出格式） ----------
function mdToHtml(md) {
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const lines = esc(md).split("\n");
  let html = "", inList = false;
  const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
  for (let line of lines) {
    line = line.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    if (/^##\s+/.test(line)) { closeList(); html += `<h2>${line.replace(/^##\s+/, "")}</h2>`; }
    else if (/^###\s+/.test(line)) { closeList(); html += `<h3>${line.replace(/^###\s+/, "")}</h3>`; }
    else if (/^[-*]\s+/.test(line)) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${line.replace(/^[-*]\s+/, "")}</li>`; }
    else if (line.trim() === "") { closeList(); }
    else { closeList(); html += `<p>${line}</p>`; }
  }
  closeList();
  return html;
}

// ---------- 迷你走势 sparkline ----------
function drawSpark(canvas, points, up) {
  if (!points || points.length < 2) return;
  const dpr = window.devicePixelRatio || 1;
  const w = 60, h = 28;
  canvas.width = w * dpr; canvas.height = h * dpr;
  canvas.style.width = w + "px"; canvas.style.height = h + "px";
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const min = Math.min(...points), max = Math.max(...points);
  const range = max - min || 1;
  const x = (i) => (i / (points.length - 1)) * (w - 2) + 1;
  const y = (v) => h - 2 - ((v - min) / range) * (h - 4);
  ctx.beginPath();
  points.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
  ctx.strokeStyle = up ? "#2ea043" : "#f85149";
  ctx.lineWidth = 1.5; ctx.stroke();
}

// ---------- 配置 / key 状态 / 角色分工 ----------
let CFG = null;
const ROLE_INFO = {
  bull: { name: "多头", avatar: "🐂" },
  bear: { name: "空头", avatar: "🐻" },
  judge: { name: "组合经理", avatar: "⚖️" },
};

async function loadConfig() {
  CFG = await api("/api/config");
  const badge = (name, on) =>
    `<span class="key-badge ${on ? "on" : "off"}">${name} ${on ? "✓" : "✗ 缺 key"}</span>`;
  $("#keyStatus").innerHTML =
    badge("Gemini", CFG.keys.gemini) + badge("DeepSeek", CFG.keys.deepseek);
  renderRoles();
}

function modelLabel(key) {
  const m = CFG.models[key];
  return m ? `${key}（${m.model}）` : key;
}

function renderRoles() {
  // 顶部参与者 chips，带当前模型
  $("#participants").innerHTML = Object.entries(ROLE_INFO).map(([r, info]) =>
    `<span class="p ${r}">${info.avatar} ${info.name} · ${CFG.roles[r]}</span>`).join("");

  // 设置区：每个角色一个下拉，选 config.models 里的模型 key
  const opts = (sel) => Object.keys(CFG.models).map((k) =>
    `<option value="${k}" ${k === sel ? "selected" : ""}>${modelLabel(k)}</option>`).join("");
  $("#roleConfig").innerHTML = `
    <p class="rc-tip">选谁扮演哪个角色（改完即时生效，无需重启）：</p>
    ${Object.entries(ROLE_INFO).map(([r, info]) => `
      <label class="rc-row">
        <span>${info.avatar} ${info.name}</span>
        <select data-role="${r}">${opts(CFG.roles[r])}</select>
      </label>`).join("")}`;
  $("#roleConfig").querySelectorAll("select").forEach((s) =>
    s.addEventListener("change", saveRoles));
}

async function saveRoles() {
  const roles = {};
  $("#roleConfig").querySelectorAll("select").forEach((s) => (roles[s.dataset.role] = s.value));
  const r = await api("/api/roles", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ roles }),
  });
  CFG.roles = r.roles;
  renderRoles();
}

$("#roleBtn").addEventListener("click", () => $("#roleConfig").classList.toggle("hidden"));

$("#collapseBtn").addEventListener("click", () => {
  document.body.classList.toggle("pf-collapsed");
  // 记住折叠状态
  localStorage.setItem("pfCollapsed", document.body.classList.contains("pf-collapsed") ? "1" : "");
});
if (localStorage.getItem("pfCollapsed")) document.body.classList.add("pf-collapsed");

// ---------- 持仓看板 ----------
let HOLDINGS = [];
async function loadPortfolio() {
  const data = await api("/api/portfolio");
  HOLDINGS = data.holdings;
  renderMktBar(data.summary);
  renderSummary(data.summary);
  renderHoldings(data.holdings);
  renderTickerSelect(data.holdings);
}

function cls(v) { return v > 0 ? "up" : v < 0 ? "down" : ""; }
function sign(v) { return (v > 0 ? "+" : "") + v; }

const _SESSION_DOT = { "盘中": "open", "盘前": "ext", "盘后": "ext", "休市": "closed" };
function renderMktBar(s) {
  const sess = s.session || "未知";
  const dot = _SESSION_DOT[sess] || "closed";
  const live = sess === "盘中";
  const fresh = s.quoteTime ? `行情时间 ${s.quoteTime}${live ? "" : "（收盘价）"}` : "";
  const now = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  $("#mktBar").innerHTML = `
    <span class="dot ${dot}"></span>
    <b>美股 ${sess}</b>
    <span class="mb-sep">·</span><span class="mb-fresh">${fresh}</span>
    <span class="mb-upd">本地刷新 ${now}</span>`;
}

function renderSummary(s) {
  $("#pfCollapsed").innerHTML = `
    <div class="cp-label">今日盈亏</div>
    <div class="cp-val ${cls(s.dayPnl)}">${sign(s.dayPnl)}</div>
    <div class="cp-sub">总盈亏 <span class="${cls(s.pnl)}">${sign(s.pnl)} (${sign(s.pnlPct)}%)</span></div>`;
  $("#summary").innerHTML = `
    <div class="sum-card wide">
      <div class="label">总市值</div>
      <div class="val">$${s.marketValue.toLocaleString()}</div>
    </div>
    <div class="sum-card">
      <div class="label">今日盈亏</div>
      <div class="val ${cls(s.dayPnl)}">${sign(s.dayPnl)}</div>
    </div>
    <div class="sum-card">
      <div class="label">总盈亏</div>
      <div class="val ${cls(s.pnl)}">${sign(s.pnl)} <small>(${sign(s.pnlPct)}%)</small></div>
    </div>`;
}

function renderHoldings(list) {
  const box = $("#holdings");
  if (!list.length) { box.innerHTML = `<p class="hint">还没有持仓，下面添加 ↓</p>`; return; }
  box.innerHTML = "";
  list.forEach((h) => {
    const el = document.createElement("div");
    el.className = "holding";
    if (h.error) {
      el.innerHTML = `<div class="h-main"><div class="tkr">${h.ticker}</div>
        <div class="nm down">行情失败</div></div><div></div>
        <button class="del" data-t="${h.ticker}">✕</button>`;
    } else {
      const ext = h.extended
        ? `<span class="ext">${h.extended.label} $${h.extended.price} <span class="${cls(h.extended.changePct)}">${sign(h.extended.changePct)}%</span></span>`
        : "";
      const state = h.marketStateLabel ? `<span class="mstate">${h.marketStateLabel}</span>` : "";
      el.innerHTML = `
        <div class="h-main">
          <div class="tkr">${h.ticker} <span class="${cls(h.changePct)}">${sign(h.changePct)}%</span> ${state}</div>
          <div class="nm">${h.name}</div>
          <div class="price">$${h.price} · ${h.shares}股 @ ${h.cost}</div>
          ${ext ? `<div class="price ext-line">${ext}</div>` : ""}
        </div>
        <div class="pnl-col">
          <canvas></canvas>
          <div class="big ${cls(h.pnl)}">${sign(h.pnl)}</div>
          <div class="${cls(h.pnlPct)}">${sign(h.pnlPct)}%</div>
        </div>
        <button class="del" data-t="${h.ticker}" title="删除">✕</button>`;
    }
    box.appendChild(el);
    if (!h.error) drawSpark(el.querySelector("canvas"), h.spark, h.pnl >= 0);
  });
  box.querySelectorAll(".del").forEach((b) =>
    b.addEventListener("click", () => delHolding(b.dataset.t)));
}

function renderTickerSelect(list) {
  const sel = $("#tickerSel");
  const cur = sel.value;
  sel.innerHTML = list.map((h) => `<option value="${h.ticker}">${h.ticker}</option>`).join("")
    + `<option value="__custom">其他…</option>`;
  if (cur) sel.value = cur;
}

async function delHolding(t) {
  if (!confirm(`删除 ${t}？`)) return;
  await api("/api/holdings/delete", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker: t }),
  });
  loadPortfolio();
}

$("#addForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  await api("/api/holdings", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ticker: f.ticker.value, shares: f.shares.value, cost: f.cost.value,
    }),
  });
  f.reset();
  loadPortfolio();
});

$("#refreshBtn").addEventListener("click", loadPortfolio);

// ---------- 投资偏好 ----------
async function loadProfile() {
  const p = await api("/api/profile");
  $("#prefText").value = p.preferences || "";
}
$("#savePref").addEventListener("click", async () => {
  await api("/api/profile", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ preferences: $("#prefText").value }),
  });
  const tip = $("#prefTip");
  tip.textContent = "已保存 ✓";
  setTimeout(() => (tip.textContent = ""), 2000);
});

// ---------- 聊天 / 辩论 ----------
const SUGGEST = [
  "我的 {t} 现在该怎么操作？",
  "今天 {t} 可以建仓吗？建议什么价位？",
  "{t} 该止盈还是继续持有？",
];
function renderSuggest() {
  const t = ($("#tickerSel").value && $("#tickerSel").value !== "__custom")
    ? $("#tickerSel").value : (HOLDINGS[0] && HOLDINGS[0].ticker) || "MU";
  $("#suggest").innerHTML = SUGGEST.map((s) =>
    `<span class="chip">${s.replace("{t}", t)}</span>`).join("");
  $("#suggest").querySelectorAll(".chip").forEach((c) =>
    c.addEventListener("click", () => { $("#topicInput").value = c.textContent; }));
}

function addMsg(role, name, avatar, htmlOrText, isMd) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  wrap.innerHTML = `
    <div class="avatar">${avatar}</div>
    <div>
      <div class="who">${name}</div>
      <div class="bubble">${isMd ? mdToHtml(htmlOrText) : htmlOrText}</div>
    </div>`;
  $("#messages").appendChild(wrap);
  $("#messages").scrollTop = $("#messages").scrollHeight;
  return wrap;
}

function addTyping() {
  const wrap = document.createElement("div");
  wrap.className = "msg pending";
  wrap.innerHTML = `<div class="avatar">⏳</div><div><div class="who">思考中</div>
    <div class="bubble"><span class="typing"><span></span><span></span><span></span></span></div></div>`;
  $("#messages").appendChild(wrap);
  $("#messages").scrollTop = $("#messages").scrollHeight;
  return wrap;
}

let running = false;
$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  if (running) return;
  const topic = $("#topicInput").value.trim();
  let ticker = $("#tickerSel").value;
  if (ticker === "__custom" || !ticker) {
    ticker = prompt("输入股票代码（如 GOOGL）：", "");
    if (!ticker) return;
  }
  if (!topic) return;

  // 若当前在历史回看视图，先清空回到对话流
  if ($("#messages").querySelector(".hist-bar, .history-list")) clearMessages();
  $(".welcome") && $(".welcome").remove();
  addMsg("user", "我", "🧑", topic, false);
  $("#topicInput").value = "";
  running = true; $("#sendBtn").disabled = true;

  const typing = addTyping();
  const url = `/api/debate?topic=${encodeURIComponent(topic)}&ticker=${encodeURIComponent(ticker)}`;
  const es = new EventSource(url);
  let first = true;

  es.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    if (d.type === "message") {
      if (first) { typing.remove(); first = false; }
      addMsg(d.role, d.name, d.avatar, d.content, true);
    } else if (d.type === "error") {
      if (first) { typing.remove(); first = false; }
      addMsg("error", "系统", "⚠️", `<div class="error">${d.message}</div>`, false);
    } else if (d.type === "done") {
      es.close(); finish();
    }
  };
  es.onerror = () => { es.close(); if (first) typing.remove(); finish(); };

  function finish() {
    running = false; $("#sendBtn").disabled = false;
    loadPortfolio(); // 辩论后刷新一下行情
  }
});

$("#tickerSel").addEventListener("change", renderSuggest);

// ---------- 历史辩论回看 ----------
const _INTENT_CN = { DECISION: "决策", ANALYSIS: "解读", CHITCHAT: "闲聊" };
function escapeHtml(s) {
  return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function clearMessages() { $("#messages").innerHTML = ""; }

async function showHistory() {
  clearMessages();
  const { sessions } = await api("/api/logs");
  const wrap = document.createElement("div");
  wrap.className = "history-list";
  let html = `<div class="hist-head"><span>📜 历史辩论（点击回放）</span><button class="chip" id="newChatBtn">✏️ 新对话</button></div>`;
  if (!sessions.length) {
    html += `<p class="hint">还没有历史记录，发起一场辩论试试。</p>`;
  } else {
    html += sessions.map((s) => `
      <div class="hist-item" data-f="${s.file}">
        <span class="hi-badge ${s.intent}">${_INTENT_CN[s.intent] || s.intent}</span>
        <span class="hi-topic">${escapeHtml(s.topic || "(空)")}</span>
        <span class="hi-meta">${s.ticker} · ${s.time}</span>
      </div>`).join("");
  }
  wrap.innerHTML = html;
  $("#messages").appendChild(wrap);
  wrap.querySelectorAll(".hist-item").forEach((it) =>
    it.addEventListener("click", () => openSession(it.dataset.f)));
  $("#newChatBtn").addEventListener("click", newChat);
}

async function openSession(file) {
  const s = await api(`/api/log?file=${encodeURIComponent(file)}`);
  clearMessages();
  const turnByRole = {};
  (s.turns || []).forEach((t) => { if (!turnByRole[t.role]) turnByRole[t.role] = t; });

  const bar = document.createElement("div");
  bar.className = "hist-bar";
  bar.innerHTML = `<button class="chip" id="backHist">← 返回历史</button>
    <span class="hb-title">${escapeHtml(s.topic || "")} · ${s.ticker || ""} · ${_INTENT_CN[s.intent] || s.intent} · ${s.time || ""}</span>`;
  $("#messages").appendChild(bar);

  if (s.context) {
    const c = s.context;
    const parts = [["行情数据", c.market], ["新闻", c.news || "(无)"], ["持仓", c.holding], ["投资偏好", c.preferences]];
    const det = document.createElement("details");
    det.className = "ctx-det";
    det.innerHTML = `<summary>🔧 本场注入的数据 / 新闻（调优用）</summary><pre>${escapeHtml(parts.map(([k, v]) => `【${k}】\n${v}`).join("\n\n"))}</pre>`;
    $("#messages").appendChild(det);
  }

  (s.messages || []).forEach((m) => {
    const el = document.createElement("div");
    el.className = `msg ${m.role}`;
    el.innerHTML = `<div class="avatar">${m.avatar}</div><div>
      <div class="who">${m.name}</div>
      <div class="bubble ${m.role === "error" ? "error" : ""}">${m.role === "error" ? escapeHtml(m.content) : mdToHtml(m.content)}</div></div>`;
    $("#messages").appendChild(el);
    const t = turnByRole[m.role];
    if (t) {
      const d = document.createElement("details");
      d.className = "prompt-det";
      d.innerHTML = `<summary>查看 ${t.name} 的提示词（${t.model} · ${t.ms}ms）</summary><pre>【System】\n${escapeHtml(t.system)}\n\n【User】\n${escapeHtml(t.user)}</pre>`;
      $("#messages").appendChild(d);
    }
  });
  $("#backHist").addEventListener("click", showHistory);
  $("#messages").scrollTop = 0;
}

function newChat() {
  $("#messages").innerHTML = `<div class="welcome">
    <p>抛一个议题，🐂多头 与 🐻空头 会辩论，最后 ⚖️组合经理 给你<strong>确定性操作建议</strong>。</p>
    <div class="suggest" id="suggest"></div></div>`;
  renderSuggest();
}

$("#historyBtn").addEventListener("click", showHistory);

// ---------- 定时自动刷新行情 ----------
// 走势图/指标已长缓存，轮询只拉价格(每只票 1 次请求)，10s 也安全。
const POLL_MS = 15000; // 每 15 秒；想更快可改 10000
setInterval(() => {
  if (document.hidden) return; // 标签页在后台时跳过，省流量
  if (running) return;         // 辩论进行中不打断
  loadPortfolio();
}, POLL_MS);

// ---------- 初始化 ----------
(async function init() {
  await Promise.all([loadConfig(), loadPortfolio(), loadProfile()]);
  renderSuggest();
})();
