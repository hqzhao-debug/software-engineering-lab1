"use strict";

const $ = (selector, scope = document) => scope.querySelector(selector);
const app = { context: null, view: "market", page: 1, side: "buyer", filters: {}, products: new Map(), generation: 0 };
const modal = $("#modal");
const labels = { DRAFT: "私人草稿", REVIEW: "待审核", REJECTED: "已驳回", ON_SALE: "在售", PENDING: "待确认", CONFIRMED: "待面交", OFF_SHELF: "已下架", VIOLATION: "违规下架", SOLD: "已成交", CANCELLED: "已取消", COMPLETED: "已完成", WITHDRAWN: "已撤回", APPROVED: "审核通过", NORMAL: "正常", BANNED: "已封禁", SUCCESS: "成功", FAILURE: "失败", REPLAY: "重复请求" };
const operations = { save_draft: "保存草稿", delete_draft: "删除草稿", submit_product: "提交审核", withdraw_product: "撤回审核", off_shelf: "商品下架", reserve: "创建预约", confirm: "确认预约", reject: "拒绝预约", cancel: "取消预约", complete: "完成交易", review: "审核商品", mark_violation: "违规处理", ban_account: "封禁账号", unban_account: "解除封禁", moderation_cancel: "管理联动取消", ban_product: "封禁联动下架", login: "账号登录", logout: "退出登录", register: "账号注册", verify_email: "邮箱验证", create_admin: "创建管理员", bootstrap_admin: "初始化管理员", upload_image: "上传图片", read: "查询记录" };
const iconPaths = {
  market: '<path d="m3 9 2-5h14l2 5v3a3 3 0 0 1-5 2 3 3 0 0 1-4 0 3 3 0 0 1-4 0 3 3 0 0 1-5-2V9Z"/><path d="M5 15v6h14v-6M9 21v-5h6v5"/>',
  box: '<path d="m3 7 9-4 9 4-9 4-9-4Zm0 0v10l9 4 9-4V7M12 11v10M7 5l10 4"/>',
  trade: '<path d="M4 7h15l-4-4M20 17H5l4 4M19 7v5M5 17v-5"/>',
  check: '<path d="M9 12l2 2 5-5"/><path d="m12 3 8 4v5c0 5-8 9-8 9S4 17 4 12V7l8-4Z"/>',
  users: '<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6M18 15a5 5 0 0 1 3 5"/>',
  chart: '<path d="M4 3v18h17M8 17v-5M13 17V7M18 17V4"/>',
  log: '<path d="M7 3h10l3 3v15H4V3h3ZM8 8h7M8 12h8M8 16h5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  book: '<path d="M3 4h7a3 3 0 0 1 3 3v15a4 4 0 0 0-4-3H3V4Zm18 0h-5a3 3 0 0 0-3 3M21 4v15h-4a4 4 0 0 0-4 3M6 8h4M6 12h4M16 8h2M16 12h2"/>',
  digital: '<rect x="4" y="3" width="16" height="12" rx="2"/><path d="M8 21h8M12 15v6M8 7h8"/>',
  home: '<path d="M6 6h12v8a6 6 0 0 1-12 0V6ZM18 7h2a3 3 0 0 1 0 6h-2M8 3h8M3 21h18"/>',
  sport: '<circle cx="12" cy="12" r="9"/><path d="m9 8 6 0 2 5-5 4-5-4 2-5ZM9 8 7 4M15 8l2-4M17 13l4 1M12 17v4M7 13l-4 1"/>',
  music: '<path d="M9 18V6l11-3v12M9 10l11-3"/><ellipse cx="6" cy="18" rx="3" ry="2"/><ellipse cx="17" cy="15" rx="3" ry="2"/>',
  pen: '<path d="m4 16 12-12 4 4L8 20l-5 1 1-5ZM13 7l4 4M4 16l4 4"/>',
};
function icon(name, size = 20) { return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${iconPaths[name] || iconPaths.box}</svg>`; }
function esc(value) { return String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]); }
function badge(value) { return `<span class="badge ${/^[A-Z_]+$/.test(value) ? value : ""}">${esc(labels[value] || value)}</span>`; }
function date(value) { return value ? new Date(value * 1000).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }) : "—"; }
function price(value) { return `<span class="price"><small>¥</small>${esc(value || "待填写")}</span>`; }
function empty(title, text = "", action = "") { return `<div class="empty">${icon("box", 44)}<h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`; }
function heading(title, subtitle, extra = "") { return `<div class="page-heading"><div><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div><div class="heading-extra">${extra}</div></div>`; }
function button(text, action, style = "secondary", attrs = "") { return `<button class="button ${style}" data-action="${action}" ${attrs}>${text}</button>`; }
function option(value, label, selected = "") { return `<option value="${esc(value)}"${String(value) === String(selected) ? " selected" : ""}>${esc(label)}</option>`; }
function stateOptions(values, selected = "") { return option("", "全部状态", selected) + values.map((value) => option(value, labels[value], selected)).join(""); }
function toast(message, error = false) {
  const node = $("#toast"); node.textContent = message; node.className = error ? "error" : ""; node.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { node.hidden = true; }, error ? 6500 : 3500);
}
async function api(action, body = {}) {
  const response = await fetch(`/api/${action}`, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRF-Token": app.context?.csrf || "" }, body: JSON.stringify(body) });
  const result = await response.json();
  if (!response.ok || !result.ok) { const error = new Error(result.error?.message || "操作未完成，请稍后重试"); error.code = result.error?.code; throw error; }
  return result.data;
}
async function context() {
  const response = await fetch("/api/context", { credentials: "same-origin", cache: "no-store" });
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error(result.error?.message || "无法连接校园循物");
  app.context = result.data; renderChrome();
}
function renderChrome() {
  const account = app.context.account; const admin = account?.role === "ADMIN";
  const links = [["market", "market", "发现好物"]];
  if (account && !admin) links.push(["mine", "box", "我的商品"], ["reservations", "trade", "我的预约"]);
  if (admin) links.push(["review", "check", "商品审核"], ["manage", "box", "商品管理"], ["accounts", "users", "账号管理"], ["reservations", "trade", "交易记录"]);
  if (account) links.push(["divider"], ["statistics", "chart", admin ? "平台统计" : "我的统计"], ["logs", "log", "操作历史"]);
  $("#navigation").innerHTML = links.map(([view, glyph, title]) => view === "divider" ? '<div class="nav-divider"></div>' : `<button class="nav-item ${app.view === view ? "active" : ""}" data-view="${view}">${icon(glyph)}${title}</button>`).join("");
  $("#mode-tag").textContent = app.context.demo ? "本地演示" : "校园交易";
  $("#account-menu").innerHTML = account ? `<span class="avatar">${esc(account.username.slice(0, 1).toUpperCase())}</span><span class="account-name">${esc(account.username)}</span><span class="muted">${admin ? "管理员" : "同学"}</span><button class="text-button" data-action="logout">退出</button>` : '<button class="text-button" data-action="login">登录</button><button class="button primary small" data-action="register">注册账号</button>';
  const bar = $("#demo-bar"); bar.hidden = !app.context.demo;
  if (app.context.demo) bar.innerHTML = '<span><strong>试用一下</strong> · 选择角色，即可操作演示商品与交易</span><div class="demo-actions"><button data-profile="buyer">买家体验</button><button data-profile="seller">卖家体验</button><button data-profile="admin">管理员体验</button></div>';
}
function filterValues(form) {
  const result = Object.fromEntries(new FormData(form).entries());
  for (const field of ["min_price", "max_price", "start", "end"]) if (result[field] === "") delete result[field];
  for (const field of ["start", "end"]) if (result[field]) result[field] = new Date(result[field]).getTime() / 1000;
  return result;
}
function productFilters(management = false) {
  const f = app.filters; const states = ["DRAFT", "REVIEW", "ON_SALE", "PENDING", "CONFIRMED", "SOLD", "OFF_SHELF", "REJECTED", "VIOLATION"];
  return `<form class="filters" id="filter-form"><div class="filter-row"><div class="field grow"><label for="keyword">寻找好物</label><input id="keyword" name="keyword" placeholder="搜索商品名称或描述" value="${esc(f.keyword || "")}"></div><div class="field money-field"><label for="min-price">最低价格</label><input id="min-price" name="min_price" inputmode="decimal" placeholder="¥ 不限" value="${esc(f.min_price || "")}"></div><div class="field money-field"><label for="max-price">最高价格</label><input id="max-price" name="max_price" inputmode="decimal" placeholder="¥ 不限" value="${esc(f.max_price || "")}"></div><div class="field compact"><label for="sort">排序方式</label><select id="sort" name="sort">${option("newest", "最近发布", f.sort || "newest")}${option("price_asc", "价格从低到高", f.sort)}${option("price_desc", "价格从高到低", f.sort)}</select></div>${management ? `<div class="field compact"><label for="state">商品状态</label><select id="state" name="state">${stateOptions(states, f.state)}</select></div>` : ""}<button type="submit" class="button primary">${icon("search", 17)}搜索</button></div><input type="hidden" name="category" value="${esc(f.category || "")}"><div class="category-tabs">${["", ...app.context.categories].map((category) => `<button type="button" data-category="${esc(category)}" class="${(f.category || "") === category ? "active" : ""}">${esc(category || "全部好物")}</button>`).join("")}</div></form>`;
}
function illustration(content, extraClass = "") {
  const index = Math.max(0, app.context.categories.indexOf(content.category));
  const names = ["book", "digital", "home", "sport", "music", "pen", "box"];
  return `<div class="product-art art-tone-${index % 6} ${extraClass}">${content.images?.length ? `<img src="/api/image/${encodeURIComponent(content.images[0])}" alt="${esc(content.title)}" loading="lazy">` : icon(names[index] || "box", 76)}<span class="category-label">${esc(content.category || "未分类")}</span><span class="condition-badge">${esc(content.condition || "待补充")}</span></div>`;
}
function pagination(data) {
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));
  return `<div class="pagination"><button class="button secondary small" data-page="${data.page - 1}"${data.page <= 1 ? " disabled" : ""}>上一页</button><span>第 ${data.page} / ${pages} 页</span><button class="button secondary small" data-page="${data.page + 1}"${data.page >= pages ? " disabled" : ""}>下一页</button></div>`;
}
function productCard(product) {
  const c = product.content;
  return `<article class="product-card">${illustration(c)}<div class="product-card-body"><h3 title="${esc(c.title)}">${esc(c.title)}</h3>${price(c.price)}<p class="product-description">${esc(c.description || "等待你发现这件好物的更多可能")}</p><div class="product-card-meta"><span class="seller"><span class="seller-dot">${esc(product.seller_username.slice(0, 1))}</span>${esc(product.seller_username)}</span><button class="card-action" data-action="product" data-id="${esc(product.id)}">查看详情</button></div></div></article>`;
}
function rowAction(label, action, id, danger = false) { return `<button class="inline-link${danger ? " danger" : ""}" data-action="${action}" data-id="${esc(id)}">${label}</button>`; }
function productActions(product, admin = false) {
  let result = rowAction("详情", "product", product.id);
  if (admin) {
    if (product.state === "REVIEW") result += rowAction("审核", "review-product", product.id);
    else if (product.state !== "DRAFT") result += rowAction("违规处理", "violation", product.id, true);
  } else {
    if (["DRAFT", "ON_SALE", "OFF_SHELF", "REJECTED", "VIOLATION"].includes(product.state)) result += rowAction("编辑", "edit", product.id);
    if (["DRAFT", "OFF_SHELF"].includes(product.state)) result += rowAction("提交审核", "submit", product.id);
    if (product.state === "REVIEW") result += rowAction("撤回", "withdraw", product.id);
    if (product.state === "ON_SALE") result += rowAction("下架", "off-shelf", product.id);
    if (product.state === "DRAFT" && !product.current_submission_id) result += rowAction("删除", "delete-draft", product.id, true);
  }
  return result;
}
async function renderProducts(ticket) {
  const admin = ["review", "manage"].includes(app.view); const mine = app.view === "mine";
  const query = { ...app.filters, scope: admin ? "admin" : mine ? "mine" : "public", page: app.page };
  if (app.view === "review") query.state = "REVIEW";
  const result = await api("products", query); if (ticket !== app.generation) return;
  app.products = new Map(result.items.map((product) => [product.id, product]));
  const meta = { market: ["发现校园里的好物", "让闲置流动起来，发现身边的小美好。"], mine: ["我的商品", "从私人草稿到完成交易，在这里管理每一件闲置。"], review: ["商品审核", "查看已提交资料，审核通过后商品将自动上架。"], manage: ["商品管理", "管理已提交商品与违规处理，保留完整业务历史。"] }[app.view];
  const publish = !admin ? button(`${icon("plus", 18)}发布闲置`, "publish", "primary") : "";
  let html = heading(meta[0], meta[1], publish);
  if (app.view === "market") html += '<section class="hero"><div><span class="hero-eyebrow">GOOD THINGS DESERVE A SECOND LIFE</span><h2>让闲置物品，继续发光。</h2><p>一本读过的书，一件用心挑选的物品。<br>在校园里，为它找到下一位主人。</p></div><div class="hero-art" aria-hidden="true"><i class="art-circle"></i><i class="art-book"></i><i class="art-cup"></i><i class="art-leaf"></i><span class="art-spark">✧</span></div></section>';
  html += productFilters(mine || app.view === "manage");
  html += `<div class="results-line"><span><strong>${app.view === "market" ? "校园好物" : "商品列表"}</strong>共 ${result.total} 件</span><span>${app.view === "market" ? "单件物品 · 校内面交" : "点击详情查看资料与审核历史"}</span></div>`;
  if (!result.items.length) html += empty(app.view === "review" ? "暂时没有待审核商品" : "还没有找到符合条件的商品", "试试其他筛选条件，或发布一件自己的闲置。", publish);
  else if (app.view === "market") html += `<div class="product-grid">${result.items.map(productCard).join("")}</div>`;
  else html += `<div class="table-panel"><table class="data-table"><thead><tr><th>商品</th><th>价格</th><th>状态</th><th>${admin ? "卖家" : "更新 / 发布"}</th><th>操作</th></tr></thead><tbody>${result.items.map((product) => `<tr><td class="title-cell">${esc(product.content.title)}<span class="subline">${esc(product.content.category || "待分类")} · ${esc(product.content.condition || "待补充")}</span></td><td>¥ ${esc(product.content.price || "待填写")}</td><td>${badge(product.state)}</td><td>${admin ? esc(product.seller_username) : date(product.updated_at || product.published_at)}</td><td><div class="row-actions">${productActions(product, admin)}</div></td></tr>`).join("")}</tbody></table></div>`;
  html += pagination(result); $("#main").innerHTML = html; bindFilter();
}
function bindFilter() {
  const form = $("#filter-form"); if (!form) return;
  form.addEventListener("submit", (event) => { event.preventDefault(); app.filters = filterValues(form); app.page = 1; renderView(); });
}
async function renderReservations(ticket) {
  const admin = app.context.account.role === "ADMIN";
  const result = await api("reservations", { side: admin ? "all" : app.side, state: app.filters.state || "", page: app.page }); if (ticket !== app.generation) return;
  let html = heading(admin ? "交易记录" : "我的预约", "查看面交约定、当前状态与双方的处理结果。", admin ? "" : `<div class="segmented"><button data-side="buyer" class="${app.side === "buyer" ? "active" : ""}">我预约的</button><button data-side="seller" class="${app.side === "seller" ? "active" : ""}">收到的预约</button></div>`);
  html += `<form class="filters" id="filter-form"><div class="filter-row"><div class="field compact"><label for="trade-state">预约状态</label><select id="trade-state" name="state">${stateOptions(["PENDING", "CONFIRMED", "COMPLETED", "CANCELLED", "REJECTED"], app.filters.state)}</select></div><button type="submit" class="button primary">筛选</button><span class="muted">共 ${result.total} 条记录</span></div></form>`;
  html += result.items.length ? `<div class="table-panel"><table class="data-table"><thead><tr><th>预约商品</th><th>约定价格</th><th>交易双方</th><th>状态</th><th>预约时间</th><th>操作</th></tr></thead><tbody>${result.items.map((r) => `<tr><td class="title-cell">${esc(r.snapshot.title)}<span class="subline">${esc(r.snapshot.category)}</span></td><td>¥ ${esc(r.snapshot.price)}</td><td>${esc(r.buyer_username)} <span class="muted">与</span> ${esc(r.seller_username)}</td><td>${badge(r.state)}</td><td>${date(r.created_at)}</td><td>${rowAction("查看预约", "reservation", r.id)}</td></tr>`).join("")}</tbody></table></div>` : empty("这里还没有预约记录", admin ? "交易产生后，可以在这里查看。" : app.side === "buyer" ? "去发现好物，预约一件喜欢的闲置。" : "商品通过审核后，就可以收到同学的预约。");
  $("#main").innerHTML = html + pagination(result); bindFilter();
}
async function renderAccounts(ticket) {
  const accounts = await api("accounts"); if (ticket !== app.generation) return;
  $("#main").innerHTML = heading("账号管理", "管理用户状态；封禁将取消相关有效预约并下架其商品。", button(`${icon("plus", 17)}创建管理员`, "create-admin", "primary")) + `<div class="table-panel"><table class="data-table"><thead><tr><th>用户名</th><th>校园邮箱</th><th>学号 / 工号</th><th>角色</th><th>状态</th><th>操作</th></tr></thead><tbody>${accounts.map((account) => `<tr><td>${esc(account.username)}</td><td>${esc(account.email)}<span class="subline">${account.verified ? "邮箱已验证" : "邮箱待验证"}</span></td><td>${esc(account.campus_id)}</td><td>${account.role === "ADMIN" ? "管理员" : "普通用户"}</td><td>${badge(account.status)}</td><td>${account.role === "USER" ? rowAction(account.status === "BANNED" ? "解除封禁" : "封禁", account.status === "BANNED" ? "unban" : "ban", account.id, account.status !== "BANNED") : '<span class="muted">—</span>'}</td></tr>`).join("")}</tbody></table></div>`;
}
async function renderStatistics(ticket) {
  const data = await api("statistics", app.filters); if (ticket !== app.generation) return;
  const admin = app.context.account.role === "ADMIN"; const onSale = data.categories.reduce((sum, item) => sum + item.on_sale, 0);
  let html = heading(admin ? "平台成交统计" : "我的分类统计", "成交以已完成预约为准，金额取预约时确认的商品标价。");
  html += `<form class="filters" id="filter-form"><div class="filter-row"><div class="field"><label for="start">完成时间起点</label><input type="datetime-local" id="start" name="start" value="${esc(localTimeInput(app.filters.start))}"></div><div class="field"><label for="end">完成时间终点</label><input type="datetime-local" id="end" name="end" value="${esc(localTimeInput(app.filters.end))}"></div><button class="button primary" type="submit">查看统计</button><button class="button secondary" type="button" data-action="reset-filters">全部时间</button></div></form>`;
  html += `<div class="stat-grid"><article class="stat-card"><span>已完成交易</span><strong>${data.completed}</strong><small>件单件商品</small></article><article class="stat-card"><span>成交标价合计</span><strong>¥ ${esc(data.amount)}</strong><small>按历史预约价格汇总</small></article><article class="stat-card"><span>${admin ? "商品分类" : "当前在售"}</span><strong>${admin ? data.categories.length : onSale}</strong><small>${admin ? "覆盖校园常见闲置" : "不含正在预约的商品"}</small></article></div>`;
  html += `<h2 class="section-caption">分类明细</h2><div class="table-panel"><table class="data-table"><thead><tr><th>商品分类</th>${admin ? "" : "<th>当前在售</th>"}<th>已完成交易</th><th>成交标价合计</th></tr></thead><tbody>${data.categories.map((item) => `<tr><td>${esc(item.category)}</td>${admin ? "" : `<td>${item.on_sale} 件</td>`}<td>${item.completed} 件</td><td>¥ ${esc(item.amount)}</td></tr>`).join("")}</tbody></table></div><div class="notice">${esc(data.notice)}</div>`;
  $("#main").innerHTML = html; bindFilter();
}
function localTimeInput(seconds) { if (!seconds) return ""; const d = new Date(seconds * 1000); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); }
async function renderLogs(ticket) {
  const data = await api("logs", { ...app.filters, page: app.page }); if (ticket !== app.generation) return;
  const f = app.filters; const admin = app.context.account.role === "ADMIN";
  let html = heading("操作历史", "保存每一次关键操作与处理结果，关联记录按访问权限展示。");
  html += `<form class="filters" id="filter-form"><div class="filter-row"><div class="field compact"><label for="operation">操作类型</label><select id="operation" name="operation">${option("", "全部操作", f.operation)}${Object.entries(operations).map(([value, label]) => option(value, label, f.operation)).join("")}</select></div><div class="field compact"><label for="result">操作结果</label><select id="result" name="result">${stateOptions(["SUCCESS", "FAILURE", "REPLAY"], f.result)}</select></div><div class="field grow"><label for="object-id">关联记录编号</label><input id="object-id" name="object_id" placeholder="可从商品或预约详情复制" value="${esc(f.object_id || "")}"></div>${admin ? `<div class="field compact"><label for="actor-id">操作者编号</label><input id="actor-id" name="actor_id" placeholder="全部操作者" value="${esc(f.actor_id || "")}"></div>` : ""}<div class="field"><label for="start">开始时间</label><input type="datetime-local" id="start" name="start" value="${esc(localTimeInput(f.start))}"></div><div class="field"><label for="end">结束时间</label><input type="datetime-local" id="end" name="end" value="${esc(localTimeInput(f.end))}"></div><button type="submit" class="button primary">查询</button></div></form>`;
  html += data.items.length ? `<div class="table-panel"><table class="data-table"><thead><tr><th>时间</th><th>操作</th><th>状态变化</th><th>结果</th><th>原因 / 记录</th></tr></thead><tbody>${data.items.map((item) => `<tr><td>${date(item.created_at)}</td><td>${esc(operations[item.operation] || item.operation)}<span class="subline">${item.actor_role === "ADMIN" ? "管理员" : "普通用户"}</span></td><td>${esc(labels[item.before_state] || item.before_state || "—")} / ${esc(labels[item.after_state] || item.after_state || "—")}</td><td>${badge(item.result)}</td><td class="log-detail">${esc(item.reason || "操作已记录")}<span class="subline">${esc(item.object_id ? item.object_id.slice(0, 10) : "")}</span></td></tr>`).join("")}</tbody></table></div>` : empty("没有找到相关操作", "试试其他查询条件。");
  $("#main").innerHTML = html + pagination(data); bindFilter();
}
async function renderView() {
  const ticket = ++app.generation; renderChrome(); $("#main").innerHTML = '<div class="loading">正在读取最新记录…</div>';
  try {
    if (["market", "mine", "review", "manage"].includes(app.view)) await renderProducts(ticket);
    else if (app.view === "reservations") await renderReservations(ticket);
    else if (app.view === "accounts") await renderAccounts(ticket);
    else if (app.view === "statistics") await renderStatistics(ticket);
    else if (app.view === "logs") await renderLogs(ticket);
  } catch (error) {
    if (ticket !== app.generation) return;
    $("#main").innerHTML = `<div class="alert-page">${icon("box", 38)}<h2>暂时无法读取页面</h2><p>${esc(error.message)}</p>${button("重新加载", "refresh", "primary")} ${button("返回发现好物", "market")}</div>`;
    if (["AUTH", "SESSION_EXPIRED", "ACCOUNT_RESTRICTED"].includes(error.code)) { await context(); }
  }
}
function openModal(title, content, wide = false) {
  $("#modal-body").innerHTML = `<div class="modal-head"><h2 id="modal-title">${esc(title)}</h2><button type="button" class="modal-close" data-action="close-modal" aria-label="关闭窗口">×</button></div><div class="modal-content">${content}</div>`;
  modal.style.width = wide ? "min(760px,calc(100vw - 30px))" : "";
  if (!modal.open) modal.showModal(); modal.scrollTop = 0;
}
function closeModal() { modal.close(); }
function formFooter(label = "保存", extra = "") { return `<div class="form-error" role="alert"></div><div class="modal-footer">${extra}<button type="button" class="button secondary" data-action="close-modal">取消</button><button class="button primary" type="submit">${label}</button></div>`; }
function bindModalForm(handler) {
  const form = $("#modal form");
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); const submit = $('button[type="submit"]', form); const errorNode = $(".form-error", form); if (errorNode) errorNode.textContent = "";
    submit.disabled = true;
    try { await handler(form); } catch (error) { if (errorNode) errorNode.textContent = error.message; else toast(error.message, true); } finally { submit.disabled = false; }
  });
}
function auth(mode = "login") {
  const register = mode === "register"; const verify = mode === "verify"; const create = mode === "create-admin";
  let fields = "";
  if (verify) fields = '<div class="field"><label for="verification-token">邮箱验证码</label><input id="verification-token" name="verification_token" autocomplete="one-time-code" required placeholder="粘贴邮件中的验证码"></div>';
  else if (register || create) fields = `<div class="form-grid"><div class="field full"><label for="username">用户名</label><input id="username" name="username" autocomplete="username" required placeholder="取一个大家认识的名字"></div><div class="field full"><label for="email">校园邮箱</label><input type="email" id="email" name="email" required placeholder="name@${esc(app.context.email_domain)}"></div><div class="field"><label for="campus-id">学号 / 工号</label><input id="campus-id" name="campus_id" required></div><div class="field"><label for="password">密码</label><input type="password" id="password" name="password" autocomplete="new-password" required></div></div>`;
  else fields = '<div class="form-grid"><div class="field full"><label for="identifier">用户名或校园邮箱</label><input id="identifier" name="identifier" autocomplete="username" required placeholder="请输入用户名或校园邮箱"></div><div class="field full"><label for="password">密码</label><input type="password" id="password" name="password" autocomplete="current-password" required placeholder="请输入密码"></div></div>';
  openModal(create ? "创建管理员账号" : verify ? "验证校园邮箱" : "欢迎来到校园循物", `<form>${!create && !verify ? `<div class="auth-tabs"><button type="button" data-action="login" class="${register ? "" : "active"}">登录账号</button><button type="button" data-action="register" class="${register ? "active" : ""}">注册账号</button></div>` : ""}${fields}${formFooter(verify ? "完成验证" : register || create ? "创建账号" : "登录")}</form>${!verify && !create ? '<button class="helper-link" data-action="verify">已有验证码？完成邮箱验证</button>' : ""}`);
  bindModalForm(async (form) => {
    const values = Object.fromEntries(new FormData(form).entries()); const result = await api(create ? "create-admin" : verify ? "verify" : register ? "register" : "login", values);
    if (register || create) {
      openModal("账号创建成功", `<div class="notice">已为 ${esc(result.account.username)} 创建账号，请验证校园邮箱后再登录。</div>${app.context.demo && !create ? button("完成演示邮箱验证", "demo-verify", "primary", `data-id="${esc(result.account.id)}"`) : button("输入邮箱验证码", "verify", "primary")}<p class="form-note">${app.context.demo ? "当前为本地演示环境，邮箱验证用于体验注册流程。" : "请查看校园邮箱中的验证邮件。"}</p>`);
    } else { closeModal(); await context(); app.view = "market"; app.page = 1; app.filters = {}; await renderView(); toast(verify ? "邮箱验证成功，现在可以登录" : "欢迎回来"); }
  });
}
function reasonDialog(title, description, action, requiredReason = true, submitLabel = "确认") {
  openModal(title, `<form><p class="muted">${esc(description)}</p><div class="field"><label for="reason">${requiredReason ? "请填写原因" : "补充说明（选填）"}</label><textarea id="reason" name="reason" ${requiredReason ? "required" : ""} placeholder="说明具体情况，方便对方了解"></textarea></div>${formFooter(submitLabel)}</form>`);
  bindModalForm(async (form) => { await action(new FormData(form).get("reason").trim()); closeModal(); await renderView(); toast("处理成功，记录已更新"); });
}
async function showProduct(id, reviewing = false) {
  const product = await api("product", { product_id: id }); app.products.set(id, product);
  const c = product.content; const account = app.context.account; const owner = account?.id === product.seller_id; const admin = account?.role === "ADMIN";
  let content = `<div class="detail-top">${illustration(c)}<div class="detail-main"><h3 class="detail-title">${esc(c.title)}</h3>${price(c.price)}<div class="detail-meta">${badge(product.state)} · ${esc(product.seller_username)}</div></div></div><p class="detail-description">${esc(c.description || "卖家暂未补充描述。")}</p>${c.images?.length > 1 ? `<div class="image-list">${c.images.map((image) => `<img src="/api/image/${encodeURIComponent(image)}" alt="商品图片" loading="lazy">`).join("")}</div>` : ""}<dl class="details-list"><div><dt>商品分类</dt><dd>${esc(c.category || "待补充")} / ${esc(c.condition || "待补充")}</dd></div><div><dt>交易方式</dt><dd>校园当面交付，付款在线下完成</dd></div><div><dt>商品编号</dt><dd>${esc(id)}</dd></div></dl>`;
  if (admin && product.state === "REVIEW") content += `<div class="notice">审核当前正式提交的商品资料，审批结果和原因会向卖家显示。</div><div class="detail-actions">${button("审核通过", "approve", "primary", `data-id="${esc(id)}"`)}${button("驳回修改", "reject-review", "danger", `data-id="${esc(id)}"`)}</div>`;
  else if (product.state === "ON_SALE" && account?.role === "USER" && !owner) content += `<form id="reserve-form"><div class="notice">确认预约「${esc(c.title)}」，标价 ¥${esc(c.price)}。</div><div class="field"><label for="message">面交留言</label><textarea id="message" name="message" required placeholder="例如：周三下午 3 点，图书馆门口方便面交吗？"></textarea></div>${formFooter("确认预约")}</form>`;
  else if (!account && product.state === "ON_SALE") content += `<div class="notice">登录后可填写面交约定并预约商品。</div>${button("登录并预约", "login", "primary")}`;
  if (owner || admin) content += `<div class="detail-actions">${owner ? productActions(product) : ""}${button("查看审核历史", "history", "secondary small", `data-id="${esc(id)}"`)}</div>`;
  if (reviewing && product.state !== "REVIEW") content += '<div class="notice warning">这件商品的审核状态已更新。</div>';
  openModal(admin && product.state === "REVIEW" ? "审核商品" : "商品详情", content);
  if ($("#reserve-form")) {
    const key = crypto.randomUUID(); bindModalForm(async (form) => { const result = await api("reserve", { product_id: id, content_version: product.content_version, message: new FormData(form).get("message"), request_key: key }); closeModal(); app.view = "reservations"; app.side = "buyer"; app.page = 1; app.filters = {}; await renderView(); toast("预约已提交，等待卖家确认"); await showReservation(result.id); });
  }
}
async function editor(id = null) {
  if (!app.context.account) return auth("login");
  if (app.context.account.role !== "USER") return toast("管理员不能发布商品，请切换到卖家体验", true);
  const product = id ? await api("product", { product_id: id }) : null;
  const c = product?.content || { title: "", category: "", condition: "", price: "", description: "", images: [] }; let images = [...c.images]; const uploadedFiles = new Map();
  openModal(product ? "编辑商品草稿" : "发布一件闲置", `<form><div class="form-grid"><div class="field full"><label for="title">商品标题</label><input id="title" name="title" maxlength="50" required value="${esc(c.title)}" placeholder="给你的闲置起一个清楚的名字"></div><div class="field"><label for="category">商品分类</label><select id="category" name="category">${option("", "请选择分类", c.category)}${app.context.categories.map((value) => option(value, value, c.category)).join("")}</select></div><div class="field"><label for="condition">成色</label><select id="condition" name="condition">${option("", "请选择成色", c.condition)}${app.context.conditions.map((value) => option(value, value, c.condition)).join("")}</select></div><div class="field full"><label for="price">标价（元）</label><input id="price" name="price" inputmode="decimal" value="${esc(c.price)}" placeholder="例如 35.00"></div><div class="field full"><label for="description">商品描述</label><textarea id="description" name="description" maxlength="500" placeholder="介绍使用情况、功能和需要说明的小瑕疵">${esc(c.description)}</textarea><p class="form-note">最多 500 字；图片和描述可选。</p></div><div class="field full"><label for="images">商品图片</label><input type="file" id="images" accept="image/jpeg,image/png" multiple><p class="form-note">JPG / PNG，最多 5 张，每张不超过 5 MB。</p><div class="image-list" id="existing-images"></div></div></div><div class="notice">先保存为私人草稿；提交并审核通过后，才会出现在公开市场。</div>${formFooter("保存草稿")}</form>`, true);
  const renderImages = () => { $("#existing-images").innerHTML = images.map((image) => `<div class="image-chip"><img src="/api/image/${encodeURIComponent(image)}" alt="已保存的商品图片"><button type="button" data-remove-image="${esc(image)}" aria-label="移除这张图片">×</button></div>`).join(""); };
  renderImages(); $("#existing-images").addEventListener("click", (event) => { const control = event.target.closest("[data-remove-image]"); if (control) { images = images.filter((image) => image !== control.dataset.removeImage); renderImages(); } });
  bindModalForm(async (form) => {
    const files = [...$("#images", form).files]; if (images.length + files.filter((file) => !uploadedFiles.has(file)).length > 5) throw new Error("图片最多 5 张，请减少后再保存");
    for (const file of files) {
      if (uploadedFiles.has(file)) continue;
      if (file.size > 5 * 1024 * 1024) throw new Error("单张图片不能超过 5 MB");
      const contentBase64 = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(",")[1]); reader.onerror = () => reject(new Error("图片读取失败")); reader.readAsDataURL(file); });
      const uploaded = await api("upload-image", { name: file.name, content_base64: contentBase64 }); images.push(uploaded.id); uploadedFiles.set(file, uploaded.id);
    }
    const values = Object.fromEntries(new FormData(form).entries()); const payload = { content: { ...values, images } };
    if (product) { payload.product_id = product.id; payload.expected_version = product.row_version; }
    const saved = await api("save-draft", payload); closeModal(); app.view = "mine"; app.filters = {}; app.page = 1; await renderView(); toast("草稿已保存，可以继续提交审核"); await showProduct(saved.id);
  });
}
async function showHistory(id) {
  const history = await api("history", { product_id: id });
  const versions = new Map(history.versions.map((version) => [version.id, version]));
  const content = history.submissions.length ? `<div class="timeline">${[...history.submissions].reverse().map((submission) => { const version = versions.get(submission.version_id); return `<article class="timeline-item"><strong>${esc(version?.content?.title || "已提交商品")} · ${badge(submission.status)}</strong><p>${esc(submission.reason || "等待审核处理")}</p><small>提交于 ${date(submission.created_at)}${submission.reviewed_at ? ` · 处理于 ${date(submission.reviewed_at)}` : ""}</small><p>提交标价 ¥${esc(version?.content?.price || "—")} · ${esc(version?.content?.condition || "")}</p></article>`; }).join("")}</div>` : empty("尚未提交审核", "当前内容仍是私人草稿。");
  openModal("审核历史", content);
}
async function showReservation(id) {
  const r = await api("reservation", { reservation_id: id }); const account = app.context.account; const seller = account.id === r.seller_id; const buyer = account.id === r.buyer_id;
  let content = `<div class="detail-top">${illustration(r.snapshot)}<div class="detail-main"><h3 class="detail-title">${esc(r.snapshot.title)}</h3>${price(r.snapshot.price)}<div class="detail-meta">${badge(r.state)}</div></div></div><dl class="details-list"><div><dt>买家</dt><dd>${esc(r.buyer_username)}</dd></div><div><dt>卖家</dt><dd>${esc(r.seller_username)}</dd></div><div><dt>面交留言</dt><dd>${esc(r.message || r.snapshot.buyer_message)}</dd></div>${r.counterparty_email ? `<div><dt>对方邮箱</dt><dd>${esc(r.counterparty_email)}</dd></div>` : ""}<div><dt>预约时间</dt><dd>${date(r.created_at)}</dd></div>${r.confirmed_at ? `<div><dt>确认时间</dt><dd>${date(r.confirmed_at)}</dd></div>` : ""}${r.completed_at ? `<div><dt>完成时间</dt><dd>${date(r.completed_at)}</dd></div>` : ""}${r.close_reason ? `<div><dt>结束原因</dt><dd>${esc(r.close_reason)}</dd></div>` : ""}<div><dt>预约编号</dt><dd>${esc(id)}</dd></div></dl><div class="detail-actions">`;
  if (seller && r.state === "PENDING") content += button("确认预约", "confirm", "primary", `data-id="${esc(id)}"`) + button("拒绝预约", "reject", "danger", `data-id="${esc(id)}"`);
  if (seller && r.state === "CONFIRMED") content += button("标记交易完成", "complete", "primary", `data-id="${esc(id)}"`);
  if ((buyer && ["PENDING", "CONFIRMED"].includes(r.state)) || (seller && r.state === "CONFIRMED")) content += button("取消预约", "cancel", "secondary", `data-id="${esc(id)}" data-state="${r.state}"`);
  content += "</div>";
  if (r.state === "CONFIRMED") content += '<div class="notice">请通过邮箱协商校内面交；交付完成后，由卖家标记完成。</div>';
  if (["REJECTED", "CANCELLED"].includes(r.state)) content += '<div class="notice">预约已结束，对方邮箱不再显示。历史商品资料仍保留。</div>';
  openModal("预约详情", content);
}
async function performAction(action, node) {
  const id = node.dataset.id;
  if (action === "close-modal") return closeModal();
  if (["login", "register", "verify", "create-admin"].includes(action)) return auth(action);
  if (action === "demo-verify") { await api("demo-verify", { account_id: id }); closeModal(); toast("演示邮箱验证成功，可以登录此账号"); return auth("login"); }
  if (action === "logout") { await api("logout"); closeModal(); await context(); app.view = "market"; app.filters = {}; app.page = 1; return renderView(); }
  if (action === "publish") return editor();
  if (action === "edit") return editor(id);
  if (action === "product") return showProduct(id);
  if (action === "review-product") return showProduct(id, true);
  if (action === "history") return showHistory(id);
  if (action === "reservation") return showReservation(id);
  if (action === "refresh") { await context(); return renderView(); }
  if (action === "market") { app.view = "market"; app.page = 1; app.filters = {}; return renderView(); }
  if (action === "reset-filters") { app.filters = {}; app.page = 1; return renderView(); }
  if (["submit", "withdraw", "off-shelf", "delete-draft"].includes(action)) {
    const product = app.products.get(id) || await api("product", { product_id: id });
    const names = { submit: "提交审核", withdraw: "撤回审核", "off-shelf": "下架商品", "delete-draft": "删除草稿" };
    openModal(names[action], `<form><p>确认${names[action]}「${esc(product.content.title)}」？</p><p class="muted">${action === "submit" ? "提交后内容将进入审核，审核通过后自动在售。" : action === "delete-draft" ? "仅从未提交的私人草稿可以删除。" : "操作将立即更新当前商品状态。"}</p>${formFooter(`确认${names[action]}`)}</form>`);
    const key = crypto.randomUUID(); bindModalForm(async () => { const payload = { product_id: id, expected_version: product.row_version }; if (action === "submit") payload.request_key = key; await api(action, payload); closeModal(); await renderView(); toast(`${names[action]}成功`); }); return;
  }
  if (["approve", "reject-review"].includes(action)) {
    const product = app.products.get(id) || await api("product", { product_id: id });
    return reasonDialog(action === "approve" ? "审核通过" : "驳回修改", `请说明对「${product.content.title}」的审核结论。`, (reason) => api("review", { submission_id: product.current_submission_id, approve: action === "approve", reason }), true, "提交审核结论");
  }
  if (action === "violation") return reasonDialog("违规处理", "处理将终止该商品的有效预约；已成交商品仅保留违规记录。", (reason) => api("violation", { product_id: id, reason }), true, "确认违规处理");
  if (["ban", "unban"].includes(action)) return reasonDialog(action === "ban" ? "封禁账号" : "解除封禁", action === "ban" ? "封禁会撤销会话、取消有效预约并下架该用户的未成交商品。" : "解封不会自动上架商品，也不会恢复已结束的预约。", (reason) => api(action, { account_id: id, reason }));
  if (["reject", "cancel"].includes(action)) {
    const key = crypto.randomUUID();
    return reasonDialog(action === "reject" ? "拒绝预约" : "取消预约", "本次处理将结束预约，相关结果会向交易双方显示。", (reason) => api(action, { reservation_id: id, request_key: key, reason }), action === "cancel" && node.dataset.state === "CONFIRMED", "确认处理");
  }
  if (["confirm", "complete"].includes(action)) {
    openModal(action === "confirm" ? "确认接受预约" : "确认交易完成", `<form><p>${action === "confirm" ? "接受预约后，请通过邮箱与买家协商校内面交。" : "确认已与买家完成线下交付？完成后商品不可再出售，交易不可撤销。"}</p>${formFooter(action === "confirm" ? "接受预约" : "标记完成")}</form>`);
    const key = crypto.randomUUID(); bindModalForm(async () => { await api(action, { reservation_id: id, request_key: key }); closeModal(); await renderView(); toast(action === "confirm" ? "已确认，等待线下面交" : "交易已完成，统计已更新"); await showReservation(id); });
  }
}
document.addEventListener("click", async (event) => {
  const node = event.target.closest("button"); if (!node || node.disabled) return;
  if (node.dataset.view) { app.view = node.dataset.view; app.page = 1; app.filters = {}; await renderView(); return; }
  if (node.dataset.page) { app.page = Number(node.dataset.page); await renderView(); return; }
  if (node.dataset.side) { app.side = node.dataset.side; app.page = 1; app.filters = {}; await renderView(); return; }
  if (Object.hasOwn(node.dataset, "category")) { const form = $("#filter-form"); app.filters = filterValues(form); app.filters.category = node.dataset.category; app.page = 1; await renderView(); return; }
  if (node.dataset.profile) {
    node.disabled = true;
    try { await api("demo-login", { profile: node.dataset.profile }); closeModal(); await context(); app.view = node.dataset.profile === "admin" ? "review" : node.dataset.profile === "seller" ? "mine" : "market"; app.page = 1; app.filters = {}; app.side = node.dataset.profile === "seller" ? "seller" : "buyer"; await renderView(); toast("已切换演示角色"); } catch (error) { toast(error.message, true); } finally { node.disabled = false; } return;
  }
  if (node.dataset.action) {
    node.disabled = true;
    try { await performAction(node.dataset.action, node); } catch (error) { toast(error.message, true); } finally { node.disabled = false; }
  }
});
modal.addEventListener("click", (event) => { if (event.target === modal) { const rectangle = modal.getBoundingClientRect(); if (event.clientX < rectangle.left || event.clientX > rectangle.right || event.clientY < rectangle.top || event.clientY > rectangle.bottom) closeModal(); } });
async function boot() {
  try { await context(); await renderView(); }
  catch (error) { $("#main").innerHTML = `<div class="alert-page"><h1>暂时无法连接</h1><p>${esc(error.message)}</p><p>请确认启动窗口仍然打开，然后刷新本页。</p></div>`; }
}
boot();
