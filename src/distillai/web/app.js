"use strict";
const workspace = document.querySelector("#workspace"), notice = document.querySelector("#notice");
let csrf = "", epoch = 0;
const titles = {knowledge: "知识与关系", episodes: "交流片段", history: "处理历史", config: "配置"};
const labels = {knowledge: "知识点", relations: "关系", hypotheses: "理解假设", expansions: "外扩结果", episodes: "交流片段"};
const statuses = {queued: "已登记", running: "处理中", validating: "校验与提交中", recovering: "停止与恢复中", succeeded: "已提交", failed: "失败", cancelled: "已取消", recovery_conflict: "恢复冲突"};
const drafts = new Map();
function el(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
function button(text, action, className) { const node = el("button", text, className); node.type = "button"; node.addEventListener("click", action); return node; }
function message(text, error = false) { notice.textContent = text; notice.className = error ? "error" : ""; }
function route() { return Object.fromEntries(new URLSearchParams(location.hash.slice(1))); }
function go(values) { location.hash = new URLSearchParams(values).toString(); }
function current(token) { return epoch === token; }
async function api(path, method = "GET", data) {
  const response = await fetch(path, {method, credentials: "same-origin", cache: "no-store", headers: {"Content-Type": "application/json", ...(method === "GET" ? {} : {"X-DistillAI-CSRF": csrf})}, ...(data === undefined ? {} : {body: JSON.stringify(data)})});
  const body = await response.json();
  if (!response.ok) { const error = new Error(response.status === 409 ? "记录已被其他操作修改。输入已保留；请查看当前版本后重新决定修改。" : response.status === 401 ? "本次浏览器会话已失效，请运行 start.ps1 -Action Web 重新打开。" : "请求失败：" + (body.error?.code || response.status)); error.status = response.status; error.fields = body.error?.fields; throw error; }
  return body;
}
function field(parent, title, value, {area = false, type = "text", name = "", wide = false} = {}) {
  const label = el("label", title, wide ? "wide" : "");
  const input = document.createElement(area ? "textarea" : "input"); if (!area) input.type = type; input.name = name; input.value = value ?? "";
  if (area) input.className = "body"; label.append(input); parent.append(label); return input;
}
function select(parent, title, options, value) {
  const label = el("label", title), input = document.createElement("select");
  for (const [key, text] of options) { const option = el("option", text); option.value = key; input.append(option); }
  input.value = value; label.append(input); parent.append(label); return input;
}
function jsonView(parent, title, value, open = false) { const details = el("details"); details.open = open; details.append(el("summary", title), el("pre", typeof value === "string" ? value : JSON.stringify(value, null, 2))); parent.append(details); }
function badge(status) { return el("span", statuses[status] || status, "status " + status); }
function sourceRefs(value, found = new Map()) {
  if (Array.isArray(value)) value.forEach(item => sourceRefs(item, found));
  else if (value && typeof value === "object") { if ((value.connector && Number.isInteger(value.line_start) && Number.isInteger(value.line_end)) || (value.source_kind && value.id && value.version)) found.set(JSON.stringify(value), value); else Object.values(value).forEach(item => sourceRefs(item, found)); }
  return [...found.values()];
}
async function showSource(ref) {
  const dialog = document.querySelector("#source-dialog"), body = document.querySelector("#source-body"); body.replaceChildren(el("p", "正在读取该版本来源…")); dialog.showModal();
  try { const result = await api("/v1/sources?" + new URLSearchParams({ref: JSON.stringify(ref)})); body.replaceChildren(el("p", JSON.stringify(ref), "meta"));
    if (result.record?.url) { const link = el("a", result.record.url); link.href = result.record.url; link.target = "_blank"; link.rel = "noreferrer noopener"; body.append(link); }
    body.append(el("pre", result.text));
  } catch (error) { body.replaceChildren(el("p", error.message, "error")); }
}
function sources(parent, value) {
  const refs = sourceRefs(value); if (!refs.length) return;
  parent.append(el("h3", "依据与来源")); const list = el("div", undefined, "source-list");
  for (const ref of refs) list.append(button(ref.connector ? `${ref.connector} / ${ref.session_key} / 行 ${ref.line_start}–${ref.line_end}` : `${ref.source_kind} / ${ref.id.slice(0, 12)} / ${ref.version.slice(0, 10)}`, () => showSource(ref)));
  parent.append(list);
}
function retry(parent, error, action) { const box = el("div", undefined, "message error"); box.append(el("p", error.message), button("重试", action)); parent.replaceChildren(box); }

async function renderConfig(token) {
  const data = await api("/v1/config"); if (!current(token)) return;
  const form = el("form", undefined, "config-layout"), meta = el("p", `已保存配置 v${data.version} · 修改后显式保存`, "meta"); form.append(meta);
  let version = data.version, editSerial = 0;
  const changed = new Map(), controls = new Map();
  const specs = [
    ["模型服务", [["llm.base_url", "API 地址", "text"], ["llm.model", "模型名", "text"], ["llm.api_key", `模型密钥（${data.api_key_configured ? "已配置" : "未配置"}；留空保留）`, "password"], ["llm.parameters", "模型参数 JSON（只发送你填写的参数）", "json"]]],
    ["搜索与正文读取 · Tavily", [["search.api_key", `Tavily 密钥（${data.search_key_configured ? "已配置" : data.search_environment_configured ? "使用 TAVILY_API_KEY" : "未配置，使用免费免 key 模式"}；留空保留）`, "password"]]],
    ["处理节奏", [["runtime.max_model_calls", "每任务最大模型请求数", "number"], ["runtime.poll_interval_seconds", "材料扫描间隔（秒）", "number"], ["episode.switch_buffer_turns", "切换缓冲轮数", "number"], ["context.refresh_update_count", "上下文更新间隔（有效材料次数）", "number"], ["expansion.interval_seconds", "外扩间隔（秒）", "number"], ["expansion.batch_size", "每批最多知识点数", "number"]]],
    ["允许发布变更的工作目录", [["workspace.paths", "绝对目录路径，每行一项", "paths"]]]
  ];
  for (const [title, items] of specs) {
    const group = el("fieldset"), grid = el("div", undefined, "fields"); group.append(el("legend", title), grid); form.append(group);
    for (const [key, title, type] of items) {
      const [owner, name] = key.split("."), value = data.values[owner][name];
      const input = field(grid, title, type === "json" ? JSON.stringify(value, null, 2) : type === "paths" ? value.join("\n") : value,
        {area: ["json", "paths"].includes(type), type: type === "password" ? "password" : "text", name: key, wide: ["paths", "json"].includes(type)});
      if (type === "number") { input.inputMode = "decimal"; }
      if (type === "password") input.autocomplete = "new-password";
      const control = {input, type, clear: null}; controls.set(key, control);
      input.addEventListener("input", () => { changed.set(key, ++editSerial); });
      if (type === "password") { const label = el("label", undefined, "check"); const check = document.createElement("input"); check.type = "checkbox"; label.append(check, document.createTextNode("清除私有配置中的此密钥")); grid.append(label); control.clear = check; check.addEventListener("change", () => { changed.set(key, ++editSerial); }); }
    }
  }
  form.append(el("p", "新任务使用新配置；运行中的任务保留登记时版本。收紧工作目录权限会触发相关任务停止与恢复。", "hint"));
  if (data.search_environment_configured) form.append(el("p", "已检测到后台启动进程的 TAVILY_API_KEY。清除私有配置后仍使用该环境凭证；变更环境凭证需重启后台。", "hint"));
  const actions = el("div", undefined, "actions"), save = el("button", "保存配置", "primary"), feedback = el("span", "", "save-state"); save.type = "submit"; actions.append(save, feedback); form.append(actions);
  jsonView(form, "正在执行任务使用的配置版本", data.active_task_versions);
  form.addEventListener("submit", async event => {
    event.preventDefault(); const values = {}, submitted = new Map(changed);
    try {
      for (const [key] of submitted) {
        const {input, type, clear} = controls.get(key); let value = input.value;
        if (type === "json") value = JSON.parse(value); else if (type === "paths") value = value.split(/\r?\n/).map(s => s.trim()).filter(Boolean); else if (type === "number") { if (!value.trim()) throw new Error("数值不能为空。"); value = Number(value); if (!Number.isFinite(value)) throw new Error("请输入有限数值。"); }
        if (clear?.checked) value = null;
        const [owner, name] = key.split("."); (values[owner] ||= {})[name] = value;
      }
      if (!submitted.size) { feedback.textContent = "没有修改。"; return; }
      save.disabled = true; feedback.textContent = "正在保存…"; feedback.className = "save-state";
      const result = await api("/v1/config", "PUT", {expected_version: version, values}); if (!current(token)) return;
      version = result.version; meta.textContent = `已保存配置 v${version} · 新任务使用此版本`;
      for (const [key, configured] of [["llm.api_key", result.api_key_configured], ["search.api_key", result.search_key_configured]]) controls.get(key).input.parentElement.firstChild.textContent = `${key === "llm.api_key" ? "模型" : "Tavily"}密钥（${configured ? "已配置" : key === "search.api_key" ? result.search_environment_configured ? "使用 TAVILY_API_KEY" : "未配置，使用免费免 key 模式" : "未配置"}；留空保留）`;
      for (const [key, serial] of submitted) if (changed.get(key) === serial) { changed.delete(key); const control = controls.get(key); if (control.type === "password") control.input.value = ""; if (control.clear) control.clear.checked = false; }
      feedback.textContent = `已保存 v${version}${changed.size ? "；提交期间的新输入尚未保存。" : "。"}`;
    } catch (error) { if (!current(token)) return; feedback.className = "save-state error"; feedback.textContent = error.message + (error.fields ? " · " + Object.entries(error.fields).map(([key, message]) => `${key}: ${message}`).join("；") : ""); const first = error.fields && controls.get(Object.keys(error.fields)[0]); first?.input.focus(); }
    finally { save.disabled = false; }
  });
  workspace.replaceChildren(form);
}

async function renderCollection(token, state) {
  const kind = state.view === "episodes" ? "episodes" : state.kind || "knowledge";
  if (!(kind in labels)) throw new Error("未知记录类型。");
  const shell = el("div"), toolbar = el("form", undefined, "toolbar");
  if (state.view !== "episodes") { const choice = select(toolbar, "记录类型", ["knowledge", "relations", "hypotheses", "expansions"].map(key => [key, labels[key]]), kind); choice.addEventListener("change", () => go({view: "knowledge", kind: choice.value})); }
  const filter = field(toolbar, kind === "episodes" ? "会话 ID" : "准确名称", state.filter || "");
  const submit = el("button", "筛选"); submit.type = "submit"; toolbar.append(submit); toolbar.addEventListener("submit", event => {event.preventDefault(); go({view: state.view, kind, filter: filter.value});});
  const split = el("div", undefined, "split"), list = el("section", undefined, "list"), detail = el("section", undefined, "detail"); list.setAttribute("aria-label", "记录列表"); detail.setAttribute("aria-label", "记录详情"); split.append(list, detail); shell.append(toolbar, split); workspace.replaceChildren(shell);
  const params = new URLSearchParams({limit: "20"}); if (state.filter) params.set(kind === "episodes" ? "session_key" : "name", state.filter);
  const count = el("p", "正在读取…", "list-count"); list.append(count);
  async function page(cursor) {
    try { const query = new URLSearchParams(params); if (cursor) query.set("cursor", cursor); const result = await api(`/v1/${kind}?${query}`); if (!current(token)) return;
      count.textContent = `${labels[kind]} / 共 ${result.total} 条`; list.querySelector(".more")?.remove();
      if (!result.items.length && !cursor) list.append(el("p", "这里还没有记录。", "empty"));
      for (const item of result.items) { const entry = button("", () => go({...state, kind, id: item.id, version: ""}), "record"); entry.append(el("strong", item.name || item.topic || item.goal || item.claim || item.question || item.id.slice(0, 12)), el("small", `${item.state || labels[kind]} · ${item.id.slice(0, 10)}`)); entry.setAttribute("aria-current", String(item.id === state.id)); list.append(entry); }
      if (result.next_cursor) list.append(button("加载更多", () => page(result.next_cursor), "more"));
    } catch (error) { if (current(token)) retry(list, error, () => page(cursor)); }
  }
  page();
  if (!state.id) { detail.append(el("p", "选择一条记录，查看正文、依据与版本。", "empty")); return; }
  await renderDetail(detail, kind, state, token);
}
async function renderDetail(parent, kind, state, token) {
  const path = kind === "knowledge" || kind === "relations" ? `/v1/records/${kind === "knowledge" ? "knowledge" : "relation"}/${state.id}` : `/v1/${kind}/${state.id}`;
  parent.append(el("p", "正在读取该版本…"));
  const result = await api(path + (state.version ? "?" + new URLSearchParams({version: state.version}) : "")); if (!current(token)) return;
  const record = result.record; parent.replaceChildren(el("h2", record.name || record.topic || record.goal || record.claim || record.question || labels[kind]));
  parent.append(el("p", `ID ${record.id}\n版本 ${result.version}${state.version ? " · 历史版本，只读" : " · 加载时保存版本"}`, "meta"));
  if (result.reanalysis?.some(item => item.status === "waiting")) parent.append(el("p", "依据已修订，等待重新分析。旧判断及其版本保留供回查；暂不用于新的引导素材。", "message"));
  else if (result.reanalysis?.length) parent.append(el("p", "当前依据已完成重新分析。相关引导素材经上下文重新准备后恢复使用。", "message"));
  if (!state.version && result.reanalysis?.some(item => item.status === "waiting")) {
    const requestId = crypto.randomUUID(), output = el("span", "", "save-state");
    const request = button("按最新依据重新分析", async () => {
      request.disabled = true;
      try {const task = await api("/v1/reanalysis-requests", "POST", {client_request_id:requestId,record_id:record.id,reason:"用户在本地工作台要求按最新依据重新分析"}); if (!current(token)) return;
        output.replaceChildren(document.createTextNode("已登记新的知识分析，随后接续认知分析；当前仍保持等待。"), button("跟踪本次分析", () => go({view:"history",task_id:task.task_id}), "link"));
      } catch (error) {if (current(token)) output.textContent = error.message;} finally {request.disabled = false;}
    }); parent.append(request, output);
  }
  if (result.reanalysis?.length) jsonView(parent, "依据修订与重分析状态", result.reanalysis);
  const versionForm = el("form", undefined, "version-form"), versionInput = document.createElement("input"); versionInput.placeholder = "输入完整历史版本 SHA-256"; versionInput.setAttribute("aria-label", "历史版本 SHA-256"); versionInput.value = state.version || "";
  const open = el("button", "读取版本"); open.type = "submit"; versionForm.append(versionInput, open); versionForm.addEventListener("submit", event => {event.preventDefault(); go({...state, version: versionInput.value.trim()});}); parent.append(versionForm);
  parent.append(button("查看相关处理历史", () => go({view: "history", [kind === "episodes" ? "episode_id" : "record_id"]: record.id}), "link"));
  if (kind === "knowledge" && !state.version) { try { const neighbors = await api(`/v1/knowledge/${record.id}/neighbors`); if (!current(token)) return; jsonView(parent, "一跳关系与名称子图", neighbors); } catch (error) { if (current(token)) parent.append(el("p", error.message, "hint")); } }
  if ((kind === "knowledge" || kind === "relations") && !state.version) renderEditor(parent, record, result.version, kind, token);
  else if (kind === "episodes" && !state.version) renderEpisodeCorrection(parent, record, result.version, token);
  else if (kind === "hypotheses") parent.append(el("p", "本页提供版本与来源回查，认知纠错入口继续接续。", "hint"));
  if ((kind === "knowledge" || kind === "relations") && !state.version) renderCognitionCorrection(parent, record, result.version, kind, token);
  renderRelated(parent, kind, record.id, token);
  sources(parent, record); jsonView(parent, "完整记录 · 含判断、假设、核查与历史", record, !["knowledge", "relations"].includes(kind));
}
function renderRelated(parent, kind, identifier, token) {
  const section = el("section"), list = el("div"), query = new URLSearchParams({[kind === "episodes" ? "episode_id" : "record_id"]: identifier, limit: "20"});
  const load = button("查看外扩、子图与选材记录", () => page()); section.append(load, list); parent.append(section);
  async function page(cursor) {
    load.disabled = true;
    try {const params = new URLSearchParams(query); if (cursor) params.set("cursor", cursor);
      const result = await api("/v1/related?" + params); if (!current(token)) return;
      if (!cursor) list.replaceChildren(el("p", `关联版本 / 共 ${result.total} 条`, "meta")); list.querySelector(".more")?.remove();
      if (!result.items.length) list.append(el("p", "尚无可确认的关联记录。", "hint"));
      for (const item of result.items) {
        const record = item.record, details = el("details"), title = {knowledge:"知识点", relation:"关系", expansion:"外扩", context:"子图与候选", selection:"本轮选材"}[item.record_kind];
        details.append(el("summary", `${title} · ${record.name || record.question || record.session_key || item.id.slice(0,12)}`), el("p", `ID ${item.id}\n版本 ${item.version}`, "meta"));
        if (["knowledge", "relation", "expansion"].includes(item.record_kind)) details.append(button("打开该历史版本", () => go({view:"knowledge", kind:{knowledge:"knowledge",relation:"relations",expansion:"expansions"}[item.record_kind], id:item.id, version:item.version}), "link"));
        if (item.record_kind === "context") {jsonView(details, "当时子图", record.subgraph, true); jsonView(details, "当时 MCP 背景", record.mcp_context); jsonView(details, "当时注入候选", record.injection_candidates);}
        else if (item.record_kind === "selection") {details.append(el("p", record.output_phase ? `已记录输出阶段：${record.output_phase}；不等于平台确认或助手采用。` : "这是选材准备记录，尚无 Hook 实际输出证据。", "hint")); jsonView(details, "当时选中文字与来源版本", record.selected, true);}
        else jsonView(details, "当时完整内容", record);
        if (record.task_id) details.append(button("查看关联任务", () => go({view:"history",task_id:record.task_id}), "link"));
        sources(details, record); list.append(details);
      }
      if (result.next_cursor) list.append(button("加载更多关联版本", () => page(result.next_cursor), "more"));
    } catch (error) {if (current(token)) list.append(el("p", error.message, "error"));} finally {load.disabled = false;}
  }
}
function renderCognitionCorrection(parent, record, version, kind, token) {
  const details = el("details"), form = el("form"), key = "cognition/" + record.id, draft = drafts.get(key);
  details.append(el("summary", "纠正关于我的判断"), el("p", "写下具体表现、当时获得的帮助以及纠错原因。提交后后台结合旧证据重新判断；原判断和来源版本可继续回查。", "hint"), form); parent.append(details);
  const performance = field(form, "实际表现或需要纠正的事实", draft?.performance || "", {area: true});
  const help = field(form, "当时得到的帮助（没有或不清楚也请注明）", draft?.help || "", {area: true});
  const reason = field(form, "纠错原因", draft?.reason || "", {area: true});
  for (const input of [performance, help, reason]) input.required = true;
  let serial = 0; const expectedVersion = draft?.version || version;
  const remember = () => {serial++; drafts.set(key, {performance: performance.value, help: help.value, reason: reason.value, version: expectedVersion});};
  for (const input of [performance, help, reason]) input.addEventListener("input", remember);
  const actions = el("div", undefined, "actions"), save = el("button", "提交认知纠错", "primary"), feedback = el("span", "", "save-state"); save.type = "submit"; actions.append(save, feedback); form.append(actions);
  form.addEventListener("submit", async event => {
    event.preventDefault(); const submitted = serial; save.disabled = true; feedback.textContent = "正在登记纠错…";
    try {const result = await api("/v1/cognition-corrections", "POST", {record_kind: kind === "knowledge" ? "knowledge" : "relation", record_id: record.id, expected_version: expectedVersion, performance: performance.value, help: help.value, reason: reason.value}); if (!current(token)) return;
      watchTask(result.task_id, feedback, token, () => {if (submitted === serial) drafts.delete(key); feedback.append(button("读取已保存判断", render, "link"));});
    } catch (error) {if (current(token)) {feedback.className = "save-state error"; feedback.textContent = error.message;}} finally {save.disabled = false;}
  });
}
function renderEpisodeCorrection(parent, record, version, token) {
  const key = "correction/" + record.id, draft = drafts.get(key), form = el("form");
  const ranges = refs => refs.map(ref => `${ref.line_start}-${ref.line_end}`).join(", ");
  const parse = value => value.split(",").map(part => {const match = /^\s*(\d+)(?:\s*-\s*(\d+))?\s*$/.exec(part); if (!match) throw new Error("来源行请用 1-4, 7-8 的形式填写。"); return {connector: "codex", session_key: record.session_key, line_start: Number(match[1]), line_end: Number(match[2] || match[1])};});
  parent.append(el("p", "来源归属纠错", "section-label"), el("p", "调整同一会话内两个已有片段的来源行。完整保留所有原来源，同一轮用户和助手文本放在一起。", "hint"), form);
  const own = field(form, "本片段应归属的来源行", draft?.own ?? ranges(record.source_refs));
  const targetId = field(form, "另一个片段 ID", draft?.targetId || "");
  const other = field(form, "另一个片段应归属的来源行", draft?.other || "");
  const reason = field(form, "纠错原因", draft?.reason || "", {area: true}); reason.required = true;
  let target = draft?.target || null, serial = 0; const expectedVersion = draft?.version || version;
  const remember = () => {serial++; drafts.set(key, {own: own.value, targetId: targetId.value, other: other.value, reason: reason.value, target, version: expectedVersion});};
  for (const input of [own, other, reason]) input.addEventListener("input", remember);
  targetId.addEventListener("input", () => {target = null; remember();});
  const info = el("p", target ? `已载入 ${target.record.topic} · ${target.version}` : "先载入另一个片段，核对它的来源与版本。", "meta");
  const actions = el("div", undefined, "actions"), feedback = el("span", "", "save-state");
  const load = button("载入另一个片段", async () => {
    const requested = targetId.value.trim(), before = serial; load.disabled = true;
    try {if (!/^[0-9a-f]{32}$/.test(requested) || requested === record.id) throw new Error("请填写另一个片段的完整 ID。");
      const result = await api(`/v1/episodes/${requested}`); if (!current(token) || before !== serial) return;
      if (result.record.session_key !== record.session_key) throw new Error("两个片段必须属于同一会话。");
      target = result; other.value = ranges(result.record.source_refs); info.textContent = `已载入 ${result.record.topic} · 版本 ${result.version}`; remember();
    } catch (error) {if (current(token)) feedback.textContent = error.message;} finally {load.disabled = false;}
  });
  const save = el("button", "提交归属纠错", "primary"); save.type = "submit"; actions.append(load, save, feedback); form.append(info, actions);
  form.addEventListener("submit", async event => {
    event.preventDefault(); const submitted = serial;
    try {if (!target || target.record.id !== targetId.value.trim()) throw new Error("请先载入并核对另一个片段。");
      const data = {session_key: record.session_key, episode_refs: [{id: record.id, version: expectedVersion}, {id: target.record.id, version: target.version}], assignments: [{episode_id: record.id, source_refs: parse(own.value)}, {episode_id: target.record.id, source_refs: parse(other.value)}], reason: reason.value};
      save.disabled = true; feedback.textContent = "正在登记纠错…";
      let result; try {result = await api("/v1/episode-corrections", "POST", data);} catch (error) {if (error.status === 422) error.message = "归属无效：两个片段须完整保留所有原来源行、互不重叠，且不能拆开同一轮用户和助手文本。输入已保留。"; throw error;} if (!current(token)) return;
      watchTask(result.task_id, feedback, token, () => {if (submitted === serial) drafts.delete(key); feedback.append(button("读取已保存记录", render, "link"));});
    } catch (error) {if (current(token)) {feedback.className = "save-state error"; feedback.textContent = error.message;}} finally {save.disabled = false;}
  });
}
function renderEditor(parent, record, version, kind, token) {
  const form = el("form"), key = kind + "/" + record.id, draft = drafts.get(key), inputs = {};
  parent.append(el("p", "正文编辑", "section-label"), form);
  for (const [name, title, value, area] of [["name", "名称", record.name, false], ["aliases", "别名，每行一项", (record.aliases || []).join("\n"), true], ["body", kind === "knowledge" ? "正文摘要" : "关系陈述", record.content[kind === "knowledge" ? "summary" : "statement"], true], ...(kind === "relations" ? [["source_knowledge_id", "起点知识 ID", record.source_knowledge_id, false], ["target_knowledge_id", "终点知识 ID", record.target_knowledge_id, false], ["relation_type", "关系类型", record.relation_type, false], ["direction_semantics", "方向语义", record.direction_semantics, false]] : [])]) inputs[name] = field(form, title, draft?.values[name] ?? value, {area, name});
  const reason = field(form, "修改原因", draft?.reason || "", {area: true, name: "reason"}); reason.required = true;
  let editSerial = 0; const expectedVersion = draft?.version || version;
  const remember = () => { editSerial++; drafts.set(key, {version: expectedVersion, values: Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value])), reason: reason.value}); };
  form.addEventListener("input", remember);
  const actions = el("div", undefined, "actions"), save = el("button", "提交修改", "primary"), feedback = el("span", "", "save-state"); save.type = "submit"; actions.append(save, feedback); form.append(actions);
  form.append(el("p", "ID、来源和理解判断只读。提交后由知识维护任务处理；成功提交前不显示为已保存。", "hint"));
  if (draft && expectedVersion !== version) {feedback.textContent = "已保留此前草稿；其基线版本与当前记录不同。"; form.append(button("清除草稿并重新读取", () => {drafts.delete(key); render();}, "link"));}
  form.addEventListener("submit", async event => {
    event.preventDefault(); const changes = {}, submittedSerial = editSerial;
    for (const [key, input] of Object.entries(inputs)) { const value = key === "aliases" ? input.value.split(/\r?\n/).map(s => s.trim()).filter(Boolean) : input.value; const original = key === "body" ? record.content[kind === "knowledge" ? "summary" : "statement"] : record[key] ?? (key === "aliases" ? [] : ""); if (JSON.stringify(value) !== JSON.stringify(original)) { if (key === "body") changes.content = {[kind === "knowledge" ? "summary" : "statement"]: value}; else changes[key] = value; } }
    if (!Object.keys(changes).length) { feedback.textContent = "正文没有修改。"; return; }
    save.disabled = true; feedback.className = "save-state"; feedback.textContent = "正在登记修改…";
    try { const result = await api("/v1/knowledge-edits", "POST", {record_kind: kind === "knowledge" ? "knowledge" : "relation", record_id: record.id, expected_version: expectedVersion, changes, reason: reason.value}); if (!current(token)) return;
      feedback.textContent = `已登记 ${result.task_id}，尚未保存。`; watchTask(result.task_id, feedback, token, () => {if (submittedSerial === editSerial) drafts.delete(key); feedback.append(button("读取已保存记录", render, "link"));});
    } catch (error) { if (current(token)) {feedback.className = "save-state error"; feedback.textContent = error.message;} }
    finally { save.disabled = false; }
  });
}
async function watchTask(id, target, token, onSuccess) {
  if (!current(token)) return;
  try { const task = await api(`/v1/tasks/${id}`); if (!current(token)) return;
    target.replaceChildren(document.createTextNode(`${statuses[task.status] || task.status} · `), button("查看任务", () => go({view: "history", task_id: id}), "link"));
    if (task.status === "succeeded") {target.prepend(document.createTextNode("修改已提交。")); onSuccess();}
    else if (["failed", "cancelled", "recovery_conflict"].includes(task.status)) {target.className = "save-state error"; target.append(document.createTextNode("输入已保留。"));}
    else setTimeout(() => watchTask(id, target, token, onSuccess), 1500);
  } catch (error) { if (current(token)) {target.textContent = error.message; target.append(button("重试查询", () => watchTask(id, target, token, onSuccess), "link"));} }
}

async function renderHistory(token, state) {
  const shell = el("div"), filters = el("form", undefined, "toolbar");
  const module = select(filters, "模块", [["", "全部模块"], ...["M03", "M04", "M05", "M06", "M07"].map(v => [v, v])], state.module || "");
  const status = select(filters, "状态", [["", "全部状态"], ...Object.entries(statuses)], state.status || "");
  const session = field(filters, "会话 ID", state.session_key || ""), taskId = field(filters, "任务 ID", state.task_id || "");
  const submit = el("button", "筛选"); submit.type = "submit"; filters.append(submit); filters.addEventListener("submit", event => {event.preventDefault(); go({view: "history", module: module.value, status: status.value, session_key: session.value, task_id: taskId.value});});
  const split = el("div", undefined, "split"), list = el("section", undefined, "list"), detail = el("section", undefined, "detail"); split.append(list, detail); shell.append(filters, split); workspace.replaceChildren(shell);
  const params = new URLSearchParams({limit: "20"}); for (const name of ["module", "status", "session_key", "task_id", "episode_id", "record_id"]) if (state[name]) params.set(name, state[name]);
  if (state.record_id || state.episode_id) list.append(el("p", `关联对象 ${state.record_id || state.episode_id}`, "meta"));
  async function page(cursor) { try {const query = new URLSearchParams(params); if (cursor) query.set("cursor", cursor); const data = await api("/v1/history?" + query); if (!current(token)) return; list.querySelector(".more")?.remove();
      if (!cursor) list.append(el("p", `任务 / 共 ${data.total} 条`, "list-count")); if (!data.items.length) list.append(el("p", "没有符合条件的任务。", "empty"));
      for (const task of data.items) {const entry = button("", () => taskDetail(detail, task, token), "record"); entry.append(el("strong", `${task.kind} / ${task.trigger}`), badge(task.status), el("small", `${task.id.slice(0, 12)} · ${task.model_calls} 次请求`)); list.append(entry);}
      if (data.next_cursor) list.append(button("加载更多", () => page(data.next_cursor), "more")); if (state.task_id && data.items.length === 1) taskDetail(detail, data.items[0], token);
    } catch (error) {if (current(token)) retry(list, error, () => page(cursor));} }
  detail.append(el("p", "选择任务，回查当时输入、输出、配置和 Prompt。", "empty")); await page();
}
let taskDetailSerial = 0;
function taskDetail(parent, task, token) {
  const serial = ++taskDetailSerial; parent.replaceChildren(el("h2", task.kind + " / " + task.trigger), badge(task.status), el("p", `任务 ${task.id}\n模型请求 ${task.model_calls} / ${task.config.values.runtime.max_model_calls}\n配置 v${task.config.version}`, "meta"));
  jsonView(parent, "当时脱敏配置", task.config); jsonView(parent, "提交、恢复与错误", {commit_id: task.commit_id, error: task.error, cancel_reason: task.cancel_reason, dependencies: task.dependencies});
  const stoppedPeriodic = task.status === "cancelled" && task.kind === "expansion" && task.trigger === "periodic_coverage" && task.cancel_reason === "runtime_stopping";
  if ((task.status === "failed" || stoppedPeriodic) && task.model_calls < task.config.values.runtime.max_model_calls) parent.append(button("重试原任务（保留已用次数）", async () => {try {const result = await api(`/v1/tasks/${task.id}/retry`, "POST", {}); if (current(token) && serial === taskDetailSerial) taskDetail(parent, result, token);} catch (error) {if (current(token) && serial === taskDetailSerial) message(error.message, true);}}));
  for (const [field, title] of [["input_version", "登记时输入"], ["execution_input_version", "执行时冻结输入"], ["prompt_version", "当时 Prompt"], ["result_version", "已保存输出"], ["model_output_version", "模型最终答复"]]) if (task[field]) {
    const holder = el("div"); holder.append(button(title + " / " + task[field].slice(0, 10), async () => {try {const result = await api(`/v1/tasks/${task.id}/artifacts?` + new URLSearchParams({field})); if (!current(token) || serial !== taskDetailSerial) return; jsonView(holder, result.version, result.text, true);} catch (error) {if (current(token) && serial === taskDetailSerial) holder.append(el("p", error.message, "error"));}}, "link")); parent.append(holder);
  }
  for (const [attempt, info] of Object.entries(task.generation_attempts || {})) if (info.request_version) parent.append(button(`生成请求 ${attempt.slice(0, 10)} / ${info.state}`, async () => {try {const result = await api(`/v1/tasks/${task.id}/artifacts?` + new URLSearchParams({attempt})); if (current(token) && serial === taskDetailSerial) jsonView(parent, "当时生成请求 / " + result.version, result.text, true);} catch (error) {if (current(token) && serial === taskDetailSerial) message(error.message, true);}}, "link"));
  for (const call of task.web_calls || []) jsonView(parent, "实际网络工具 / " + call.tool, call);
  sources(parent, task.inputs); jsonView(parent, "任务元数据", task);
}
async function render() {
  const token = ++epoch, state = route(); state.view ||= "knowledge";
  if (!(state.view in titles)) {message("未知页面。", true); return;}
  document.querySelector("#heading").textContent = titles[state.view]; document.title = titles[state.view] + " · DistillAI";
  for (const link of document.querySelectorAll("nav a")) {if (link.dataset.view === state.view) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");}
  message(""); workspace.replaceChildren(el("p", "正在读取…", "empty"));
  try {if (state.view === "config") await renderConfig(token); else if (state.view === "history") await renderHistory(token, state); else await renderCollection(token, state);}
  catch (error) {if (current(token)) retry(workspace, error, render);}
}
document.querySelector("#close-source").addEventListener("click", () => document.querySelector("#source-dialog").close());
document.querySelector(".skip").addEventListener("click", event => {event.preventDefault(); document.querySelector("#main").focus();});
window.addEventListener("hashchange", () => {if (csrf) render();});
api("/v1/web/session").then(session => {csrf = session.csrf_token; render();}).catch(error => retry(workspace, error, () => location.reload()));
