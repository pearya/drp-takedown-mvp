const state = {
  bootstrap: null,
  batches: [],
  cases: [],
  customers: [],
  templates: [],
  channels: [],
  namesiloSettings: null,
  selectedBatchId: null,
  selectedCaseId: null,
  selectedCustomerId: null,
  selectedTemplate: null,
  selectedNamesiloCustomerId: null,
};

const $ = (id) => document.getElementById(id);

const elements = {
  statsBar: $("statsBar"),
  globalStatus: $("globalStatus"),
  batchForm: $("batchForm"),
  batchCustomerSelect: $("batchCustomerSelect"),
  batchList: $("batchList"),
  batchSummary: $("batchSummary"),
  batchCaseList: $("batchCaseList"),
  batchHint: $("batchHint"),
  verifyBatchBtn: $("verifyBatchBtn"),
  caseList: $("caseList"),
  caseSummary: $("caseSummary"),
  verificationPanel: $("verificationPanel"),
  providerList: $("providerList"),
  actionList: $("actionList"),
  runList: $("runList"),
  caseHint: $("caseHint"),
  resolveBtn: $("resolveBtn"),
  planBtn: $("planBtn"),
  executeBtn: $("executeBtn"),
  verifyCaseBtn: $("verifyCaseBtn"),
  customerList: $("customerList"),
  customerForm: $("customerForm"),
  namesiloCustomerForm: $("namesiloCustomerForm"),
  namesiloCustomerSelect: $("namesiloCustomerSelect"),
  namesiloSettingsForm: $("namesiloSettingsForm"),
  namesiloVariableMap: $("namesiloVariableMap"),
  namesiloTemplateHint: $("namesiloTemplateHint"),
  templateList: $("templateList"),
  templateForm: $("templateForm"),
  openclawGuide: $("openclawGuide"),
  automationGuide: $("automationGuide"),
  channelTable: $("channelTable"),
};

async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `请求失败: ${response.status}`);
  }
  return response.json();
}

async function apiJson(url, method = "GET", payload = null) {
  return api(url, {
    method,
    headers: payload ? { "Content-Type": "application/json" } : undefined,
    body: payload ? JSON.stringify(payload) : undefined,
  });
}

function setStatus(text) {
  elements.globalStatus.textContent = text;
}

function formatDate(value) {
  if (!value) return "未记录";
  try {
    return new Date(value).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return value;
  }
}

function toStorageUrl(path) {
  if (!path || typeof path !== "string") return "";
  const normalized = path.replace(/\\/g, "/");
  const idx = normalized.toLowerCase().indexOf("/storage/");
  if (idx >= 0) return normalized.slice(idx);
  return "";
}

function escapeHtml(text) {
  if (text === null || text === undefined) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function pill(status, type = "") {
  const map = {
    SUCCESS: "success",
    PARTIAL_SUCCESS: "warn",
    WAITING_HUMAN: "warn",
    FAILED: "danger",
    NO_ROUTE_DEFINED: "danger",
    LIVE: "danger",
    DOWN_CONFIRMED: "success",
    ACCESS_BLOCKED: "success",
    CHECK_TIMEOUT: "warn",
    CHECK_ERROR: "danger",
    ENRICHED: "info",
    PLANNED: "info",
    RUNNING: "warn",
    NEW: "info",
  };
  const cls = type || map[status] || "info";
  return `<span class="pill ${cls}">${escapeHtml(status)}</span>`;
}

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((node) => {
    node.classList.toggle("active", node.dataset.tab === name);
  });
  document.querySelectorAll(".tab-panel").forEach((node) => {
    node.classList.toggle("active", node.id === `tab-${name}`);
  });
}

function renderStats() {
  if (!state.bootstrap) return;
  const cards = [
    ["批次数", state.bootstrap.stats.total_batches],
    ["案件数", state.bootstrap.stats.total_cases],
    ["渠道数", state.bootstrap.channel_count],
    ["疑似下线", state.bootstrap.stats.positive_verifications],
  ];
  elements.statsBar.innerHTML = cards
    .map(([label, value]) => `<div class="stat-card"><span>${label}</span><strong>${value}</strong></div>`)
    .join("");
}

function renderCustomerSelects() {
  const options = state.customers
    .map(
      (customer) =>
        `<option value="${customer.customer_id}">${escapeHtml(customer.brand_name_cn)} / ${escapeHtml(customer.brand_name_en)}</option>`
    )
    .join("");
  elements.batchCustomerSelect.innerHTML = options;
  elements.namesiloCustomerSelect.innerHTML = options;
}

function renderBatchList() {
  if (!state.batches.length) {
    elements.batchList.innerHTML = '<div class="empty-state">暂无批次，请先录入 URL。</div>';
    return;
  }
  elements.batchList.innerHTML = state.batches
    .map((batch) => {
      const active = batch.id === state.selectedBatchId ? "active" : "";
      return `
        <button class="list-item ${active}" data-batch-id="${batch.id}">
          <div>${pill(batch.status)}<strong>批次 #${batch.id}</strong></div>
          <div class="muted">客户: ${escapeHtml(batch.customer_id)} · URL: ${batch.total_urls} · 案件: ${batch.case_count}</div>
          <div class="muted">疑似下线: ${batch.takedown_positive_cases} · 创建: ${formatDate(batch.created_at)}</div>
        </button>
      `;
    })
    .join("");
  elements.batchList.querySelectorAll("[data-batch-id]").forEach((node) => {
    node.addEventListener("click", () => loadBatchDetail(Number(node.dataset.batchId)));
  });
}

function renderBatchDetail(bundle) {
  const batch = bundle.batch;
  elements.batchHint.textContent = `当前批次 #${batch.id}`;
  const positiveCount = bundle.cases.filter((item) =>
    ["DOWN_CONFIRMED", "ACCESS_BLOCKED"].includes(item.verification?.verdict)
  ).length;
  elements.batchSummary.innerHTML = `
    <div class="kv"><strong>客户</strong><span>${escapeHtml(batch.customer_id)}</span></div>
    <div class="kv"><strong>状态</strong><span>${pill(batch.status)}</span></div>
    <div class="kv"><strong>URL 总数</strong><span>${batch.total_urls}</span></div>
    <div class="kv"><strong>案件总数</strong><span>${bundle.cases.length}</span></div>
    <div class="kv"><strong>疑似下线</strong><span>${positiveCount}</span></div>
    <div class="kv"><strong>说明</strong><span>${escapeHtml(batch.notes || "无")}</span></div>
  `;
  elements.batchCaseList.innerHTML = bundle.cases
    .map(
      (item) => `
      <button class="list-item" data-case-id="${item.id}">
        <div>${pill(item.status)}${item.verification ? pill(item.verification.verdict) : ""}<strong>${escapeHtml(item.target_domain)}</strong></div>
        <div class="muted mono">${escapeHtml(item.target_url)}</div>
        <div class="muted">动作 ${item.action_count} · 执行 ${item.run_count} · 批次 ${item.batch_id || "-"}</div>
      </button>
    `
    )
    .join("");
  elements.batchCaseList.querySelectorAll("[data-case-id]").forEach((node) => {
    node.addEventListener("click", () => {
      activateTab("cases");
      loadCaseDetail(Number(node.dataset.caseId));
    });
  });
}

function renderCaseList() {
  if (!state.cases.length) {
    elements.caseList.innerHTML = '<div class="empty-state">暂无案件。</div>';
    return;
  }
  elements.caseList.innerHTML = state.cases
    .map((item) => {
      const active = item.id === state.selectedCaseId ? "active" : "";
      const verification = item.verification?.verdict ? pill(item.verification.verdict) : "";
      return `
        <button class="list-item ${active}" data-case-id="${item.id}">
          <div>${pill(item.status)}${verification}<strong>${escapeHtml(item.target_domain)}</strong></div>
          <div class="muted mono">${escapeHtml(item.target_url)}</div>
          <div class="muted">客户: ${escapeHtml(item.customer_id)} · 责任商 ${item.provider_count} · 动作 ${item.action_count}</div>
        </button>
      `;
    })
    .join("");
  elements.caseList.querySelectorAll("[data-case-id]").forEach((node) => {
    node.addEventListener("click", () => loadCaseDetail(Number(node.dataset.caseId)));
  });
}

function renderRunArtifacts(detail) {
  const artifacts = detail?.artifacts || {};
  const artifactItems = [
    ["填表截图", artifacts.screenshot],
    ["验证码区域截图", artifacts.captcha_screenshot],
    ["表单截图", artifacts.form_screenshot],
    ["执行轨迹", artifacts.trace],
  ];
  const links = artifactItems
    .map(([label, path]) => {
      const url = toStorageUrl(path);
      if (!url) return "";
      return `<a href="${url}" target="_blank" rel="noopener">${label}</a>`;
    })
    .filter(Boolean);

  const previewUrl = toStorageUrl(artifacts.captcha_screenshot) || toStorageUrl(artifacts.screenshot);
  const preview = previewUrl
    ? `<div class="run-preview"><img src="${previewUrl}" alt="执行截图预览"></div>`
    : "";

  if (!links.length && !preview) return "";
  return `
    <div class="record">
      <strong>执行产物</strong>
      <div class="inline-actions">${links.join("")}</div>
      ${preview}
    </div>
  `;
}

function renderCaseBundle(bundle) {
  const item = bundle.case;
  elements.caseHint.textContent = `当前案件 #${item.id}`;
  elements.caseSummary.innerHTML = `
    <div class="kv"><strong>客户</strong><span>${escapeHtml(item.customer_id)}</span></div>
    <div class="kv"><strong>目标域名</strong><span class="mono">${escapeHtml(item.target_domain)}</span></div>
    <div class="kv"><strong>目标 URL</strong><span class="mono">${escapeHtml(item.target_url)}</span></div>
    <div class="kv"><strong>案件状态</strong><span>${pill(item.status)}</span></div>
    <div class="kv"><strong>所属批次</strong><span>${item.batch_id || "无"}</span></div>
    <div class="kv"><strong>证据文件</strong><span class="mono">${escapeHtml(item.evidence_path)}</span></div>
    <div class="kv"><strong>备注</strong><span>${escapeHtml(item.notes || "无")}</span></div>
  `;

  if (bundle.latest_verification) {
    const v = bundle.latest_verification;
    const verdictText = {
      LIVE: "站点仍可访问，当前未达到下线目标。",
      DOWN_CONFIRMED: "站点返回 404/410/451 或无法连接，可视为疑似下线。",
      ACCESS_BLOCKED: "站点访问受阻，通常可视为阶段性处置成功。",
      CHECK_TIMEOUT: "站点验证超时，建议稍后重试。",
      CHECK_ERROR: "验证流程报错，建议复核。",
    }[v.verdict] || "无说明";
    const history = bundle.verifications
      .map((entry) => `<div class="record">${pill(entry.verdict)}<span class="muted mono">${entry.http_status || "-"}</span> <span class="muted">${formatDate(entry.checked_at)}</span></div>`)
      .join("");
    elements.verificationPanel.innerHTML = `
      <div class="kv"><strong>最新判定</strong><span>${pill(v.verdict)}</span></div>
      <div class="kv"><strong>HTTP 状态</strong><span>${escapeHtml(v.http_status || "无")}</span></div>
      <div class="kv"><strong>检查时间</strong><span>${formatDate(v.checked_at)}</span></div>
      <div class="kv"><strong>说明</strong><span>${verdictText}</span></div>
      <div class="record"><strong>验证历史</strong></div>
      ${history}
    `;
  } else {
    elements.verificationPanel.innerHTML = '<div class="empty-state">尚未验证站点是否仍可访问。</div>';
  }

  elements.providerList.innerHTML = bundle.providers.length
    ? bundle.providers
        .map(
          (provider) => `
            <div class="record">
              <div>${pill(provider.role)}<strong>${escapeHtml(provider.provider_name)}</strong></div>
              <div class="muted mono">${escapeHtml(provider.provider_key)}</div>
              <div class="muted">置信度 ${Math.round(provider.confidence * 100)}% · 来源 ${escapeHtml(provider.source.join(", "))}</div>
            </div>
          `
        )
        .join("")
    : '<div class="empty-state">暂无责任商识别结果。</div>';

  elements.actionList.innerHTML = bundle.actions.length
    ? bundle.actions
        .map((action) => {
          const attachments = (action.payload.attachments || [])
            .map((attachment) => `${attachment.label}${attachment.required ? "(必传)" : ""}`)
            .join("、");
          return `
            <div class="record">
              <div>${pill(action.status)}<strong>${escapeHtml(action.channel_id)}</strong></div>
              <div class="muted">角色 ${escapeHtml(action.provider_role)} · 执行器 ${escapeHtml(action.executor)} · 区域 ${escapeHtml(action.region)} · 语言 ${escapeHtml(action.language)}</div>
              <div class="muted">验证码策略 ${escapeHtml(action.captcha_strategy)} · 实现状态 ${escapeHtml(action.payload.implementation_status || "mock")}</div>
              <div class="muted">入口/目标 ${escapeHtml(action.payload.entry_url || action.payload.send_to || "无")}</div>
              <div class="muted">Email ${escapeHtml(action.payload.reporter_email || "-")} · Real Website ${escapeHtml(action.payload.real_website || "-")} · Phishing Website ${escapeHtml(action.payload.phishing_website || "-")}</div>
              <div class="muted">附件 ${escapeHtml(attachments || "无")}</div>
              <pre>${escapeHtml(action.payload.preview_body || "")}</pre>
            </div>
          `;
        })
        .join("")
    : '<div class="empty-state">暂无渠道动作。</div>';

  elements.runList.innerHTML = bundle.runs.length
    ? bundle.runs
        .map((run) => {
          const artifactsBlock = renderRunArtifacts(run.detail || {});
          return `
            <div class="record">
              <div>${pill(run.result)}<strong>${escapeHtml(run.channel_id)}</strong></div>
              <div class="muted">责任商 ${escapeHtml(run.provider_name)} / ${escapeHtml(run.provider_role)}</div>
              <div class="muted mono">${escapeHtml(run.external_ticket_id || "无外部编号")} · ${formatDate(run.finished_at)}</div>
              ${artifactsBlock}
              <pre>${escapeHtml(JSON.stringify(run.detail, null, 2))}</pre>
            </div>
          `;
        })
        .join("")
    : '<div class="empty-state">暂无执行记录。</div>';
}

function renderCustomerList() {
  if (!state.customers.length) {
    elements.customerList.innerHTML = '<div class="empty-state">暂无客户。</div>';
    return;
  }
  elements.customerList.innerHTML = state.customers
    .map((customer) => {
      const active = customer.customer_id === state.selectedCustomerId ? "active" : "";
      return `
        <button class="list-item ${active}" data-customer-id="${customer.customer_id}">
          <div><strong>${escapeHtml(customer.brand_name_cn)}</strong> / ${escapeHtml(customer.brand_name_en)}</div>
          <div class="muted mono">${escapeHtml(customer.customer_id)}</div>
          <div class="muted">${escapeHtml(customer.contact_email || "未配置联系邮箱")}</div>
          <div class="muted">Real Website: ${escapeHtml(customer.official_website || "-")}</div>
          <div class="muted">Reporter Email: ${escapeHtml(customer.reporter_email || "-")}</div>
        </button>
      `;
    })
    .join("");
  elements.customerList.querySelectorAll("[data-customer-id]").forEach((node) => {
    node.addEventListener("click", () => loadCustomer(node.dataset.customerId));
  });
}

function populateCustomerForm(customer = null) {
  const form = elements.customerForm;
  const data = customer || {
    customer_id: "",
    brand_name_cn: "",
    brand_name_en: "",
    legal_entity_cn: "",
    legal_entity_en: "",
    contact_email: "",
    reporter_email: "",
    official_website: "",
    signature_cn: "",
    signature_en: "",
  };
  Object.keys(data).forEach((key) => {
    if (form.elements[key]) {
      form.elements[key].value = data[key] || "";
    }
  });
}

function renderNamesiloPanel() {
  const customer = state.customers.find((item) => item.customer_id === state.selectedNamesiloCustomerId);
  if (!customer) return;
  elements.namesiloCustomerForm.elements.reporter_email.value =
    customer.reporter_email || customer.contact_email || "";
  elements.namesiloCustomerForm.elements.official_website.value = customer.official_website || "";
  elements.namesiloCustomerForm.elements.phishing_website_preview.value = "自动使用案件 URL（target_url）";

  if (state.namesiloSettings) {
    elements.namesiloSettingsForm.elements.entry_url.value = state.namesiloSettings.entry_url || "";
    elements.namesiloSettingsForm.elements.channel_id.value = state.namesiloSettings.channel_id || "";
    elements.namesiloSettingsForm.elements.template_key.value = state.namesiloSettings.template_key || "";
    elements.namesiloSettingsForm.elements.default_reporter_email.value =
      state.namesiloSettings.default_reporter_email || "";
    elements.namesiloSettingsForm.elements.notes.value = state.namesiloSettings.notes || "";
  }

  elements.namesiloVariableMap.innerHTML = `
    <pre>字段映射:
email -> customer.reporter_email || customer.contact_email || namesilo.default_reporter_email
Real Website -> customer.official_website
Phishing Website -> case.target_url
截图 -> action.payload.attachments[type=phishing_screenshot]
话术 -> en/${state.namesiloSettings?.template_key || "namesilo_phishing_report"}.md（建议仅替换 {{brand_name}}）</pre>
  `;

  const template = state.templates.find(
    (item) => item.locale === "en" && item.template_key === (state.namesiloSettings?.template_key || "namesilo_phishing_report")
  );
  if (template) {
    const brand = customer.brand_name_en || customer.brand_name_cn || customer.customer_id;
    const preview = template.content.replaceAll("{{brand_name}}", brand);
    elements.namesiloTemplateHint.textContent = `话术预览（品牌变量已替换）: ${preview.slice(0, 220)}...`;
  } else {
    elements.namesiloTemplateHint.textContent = "未找到 NameSilo 对应英文模板，请在话术配置中新增或维护。";
  }
}

function renderTemplateList() {
  elements.templateList.innerHTML = state.templates
    .map((item) => {
      const active =
        state.selectedTemplate &&
        item.locale === state.selectedTemplate.locale &&
        item.template_key === state.selectedTemplate.template_key
          ? "active"
          : "";
      return `
        <button class="list-item ${active}" data-locale="${item.locale}" data-template-key="${item.template_key}">
          <div><strong>${escapeHtml(item.template_key)}</strong></div>
          <div class="muted mono">${escapeHtml(item.locale)}</div>
        </button>
      `;
    })
    .join("");
  elements.templateList.querySelectorAll("[data-template-key]").forEach((node) => {
    node.addEventListener("click", () => loadTemplate(node.dataset.locale, node.dataset.templateKey));
  });
}

function populateTemplateForm(item) {
  elements.templateForm.elements.locale.value = item.locale;
  elements.templateForm.elements.template_key.value = item.template_key;
  elements.templateForm.elements.content.value = item.content;
}

function renderAutomationCenter() {
  const guide = state.bootstrap?.automation_guide;
  if (guide) {
    elements.openclawGuide.innerHTML = `
<pre>{
  "customer_id": "tencent",
  "urls": [
    "https://phish-a.example.com",
    "https://phish-b.example.com"
  ],
  "notes": "腾讯仿冒站点批次",
  "auto_execute": true,
  "auto_verify": true
}</pre>
<div class="record"><strong>接口:</strong> <code>${guide.openclaw_endpoint}</code></div>
<div class="record"><strong>说明:</strong> OpenClaw 只需提交 customer_id + urls 即可自动编排执行。</div>
    `;
    elements.automationGuide.innerHTML = `
      <div class="record"><strong>批量调用步骤</strong><pre>${guide.steps.join("\n")}</pre></div>
      <div class="record"><strong>真实自动化蓝图</strong><pre>${guide.real_automation_blueprint.join("\n")}</pre></div>
      <div class="record"><strong>关键结论</strong><span class="muted">“提交成功”不等于“下线成功”，需结合验证结果判定。</span></div>
    `;
  }

  elements.channelTable.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>渠道</th>
          <th>责任角色</th>
          <th>执行器</th>
          <th>区域</th>
          <th>验证码</th>
          <th>实现状态</th>
          <th>入口</th>
        </tr>
      </thead>
      <tbody>
        ${state.channels
          .map(
            (channel) => `
              <tr>
                <td>${escapeHtml(channel.channel_id)}</td>
                <td>${escapeHtml(channel.provider_role)}</td>
                <td>${escapeHtml(channel.executor)}</td>
                <td>${escapeHtml(channel.region)}</td>
                <td>${escapeHtml(channel.captcha_strategy)}</td>
                <td>${escapeHtml(channel.implementation_status)}</td>
                <td class="mono">${escapeHtml(channel.entry_url || channel.send_to || "-")}</td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
  `;
}

async function refreshBootstrap() {
  state.bootstrap = await api("/api/bootstrap");
  renderStats();
}

async function refreshBatches() {
  state.batches = await api("/api/batches");
  renderBatchList();
}

async function refreshCases() {
  state.cases = await api("/api/cases");
  renderCaseList();
}

async function refreshCustomers() {
  state.customers = await api("/api/admin/customers");
  renderCustomerSelects();
  renderCustomerList();
  if (!state.selectedNamesiloCustomerId && state.customers.length) {
    state.selectedNamesiloCustomerId = state.customers[0].customer_id;
  }
  if (elements.namesiloCustomerSelect.value !== state.selectedNamesiloCustomerId) {
    elements.namesiloCustomerSelect.value = state.selectedNamesiloCustomerId || "";
  }
  renderNamesiloPanel();
}

async function refreshTemplates() {
  state.templates = await api("/api/admin/templates");
  renderTemplateList();
  renderNamesiloPanel();
}

async function refreshChannels() {
  state.channels = await api("/api/admin/channels");
  renderAutomationCenter();
}

async function refreshNamesiloSettings() {
  state.namesiloSettings = await api("/api/admin/namesilo-settings");
  renderNamesiloPanel();
}

async function loadBatchDetail(batchId) {
  state.selectedBatchId = batchId;
  renderBatchList();
  const bundle = await api(`/api/batches/${batchId}`);
  renderBatchDetail(bundle);
}

async function loadCaseDetail(caseId) {
  state.selectedCaseId = caseId;
  renderCaseList();
  const bundle = await api(`/api/cases/${caseId}`);
  renderCaseBundle(bundle);
}

async function loadCustomer(customerId) {
  state.selectedCustomerId = customerId;
  renderCustomerList();
  const customer = state.customers.find((item) => item.customer_id === customerId);
  if (customer) populateCustomerForm(customer);
}

async function loadTemplate(locale, templateKey) {
  state.selectedTemplate = { locale, template_key: templateKey };
  renderTemplateList();
  const item = await api(`/api/admin/templates/${locale}/${templateKey}`);
  populateTemplateForm(item);
}

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => activateTab(button.dataset.tab));
});

elements.batchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setStatus("正在批量创建案件并执行处置...");
  try {
    const formData = new FormData(elements.batchForm);
    formData.set("auto_execute", elements.batchForm.elements.auto_execute.checked ? "true" : "false");
    formData.set("auto_verify", elements.batchForm.elements.auto_verify.checked ? "true" : "false");
    const bundle = await api("/api/batches", { method: "POST", body: formData });
    state.selectedBatchId = bundle.batch.id;
    await refreshBootstrap();
    await refreshBatches();
    await refreshCases();
    await loadBatchDetail(bundle.batch.id);
    if (bundle.cases.length) {
      state.selectedCaseId = bundle.cases[0].id;
      await loadCaseDetail(bundle.cases[0].id);
    }
    activateTab("batch");
    setStatus(`批次 #${bundle.batch.id} 已创建，共 ${bundle.cases.length} 个案件。`);
    elements.batchForm.reset();
    renderCustomerSelects();
  } catch (error) {
    setStatus(error.message);
  }
});

elements.verifyBatchBtn.addEventListener("click", async () => {
  if (!state.selectedBatchId) {
    setStatus("请先选择批次。");
    return;
  }
  setStatus("正在重新验证整批站点...");
  try {
    await api(`/api/batches/${state.selectedBatchId}/verify`, { method: "POST" });
    await refreshBootstrap();
    await refreshBatches();
    await loadBatchDetail(state.selectedBatchId);
    if (state.selectedCaseId) await loadCaseDetail(state.selectedCaseId);
    setStatus("整批验证完成。");
  } catch (error) {
    setStatus(error.message);
  }
});

elements.resolveBtn.addEventListener("click", async () => {
  if (!state.selectedCaseId) return setStatus("请先选择案件。");
  try {
    setStatus("正在识别责任商...");
    await api(`/api/cases/${state.selectedCaseId}/resolve`, { method: "POST" });
    await refreshCases();
    await loadCaseDetail(state.selectedCaseId);
    setStatus("责任商识别完成。");
  } catch (error) {
    setStatus(error.message);
  }
});

elements.planBtn.addEventListener("click", async () => {
  if (!state.selectedCaseId) return setStatus("请先选择案件。");
  try {
    setStatus("正在生成处置计划...");
    await api(`/api/cases/${state.selectedCaseId}/plan`, { method: "POST" });
    await refreshCases();
    await loadCaseDetail(state.selectedCaseId);
    setStatus("处置计划已生成。");
  } catch (error) {
    setStatus(error.message);
  }
});

elements.executeBtn.addEventListener("click", async () => {
  if (!state.selectedCaseId) return setStatus("请先选择案件。");
  try {
    setStatus("正在执行处置...");
    await api(`/api/cases/${state.selectedCaseId}/execute`, { method: "POST" });
    await refreshBootstrap();
    await refreshCases();
    await loadCaseDetail(state.selectedCaseId);
    setStatus("处置执行完成。");
  } catch (error) {
    setStatus(error.message);
  }
});

elements.verifyCaseBtn.addEventListener("click", async () => {
  if (!state.selectedCaseId) return setStatus("请先选择案件。");
  try {
    setStatus("正在验证站点是否仍可访问...");
    await api(`/api/cases/${state.selectedCaseId}/verify`, { method: "POST" });
    await refreshBootstrap();
    await refreshCases();
    await loadCaseDetail(state.selectedCaseId);
    setStatus("站点验证完成。");
  } catch (error) {
    setStatus(error.message);
  }
});

elements.customerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    setStatus("正在保存客户配置...");
    const formData = new FormData(elements.customerForm);
    const saved = await api("/api/admin/customers", { method: "POST", body: formData });
    await refreshBootstrap();
    await refreshCustomers();
    await loadCustomer(saved.customer_id);
    state.selectedNamesiloCustomerId = saved.customer_id;
    elements.namesiloCustomerSelect.value = saved.customer_id;
    renderNamesiloPanel();
    setStatus(`客户 ${saved.customer_id} 已保存。`);
  } catch (error) {
    setStatus(error.message);
  }
});

elements.namesiloCustomerSelect.addEventListener("change", () => {
  state.selectedNamesiloCustomerId = elements.namesiloCustomerSelect.value;
  renderNamesiloPanel();
});

elements.namesiloCustomerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const customerId = elements.namesiloCustomerSelect.value;
  if (!customerId) {
    setStatus("请先选择客户。");
    return;
  }
  try {
    setStatus("正在保存 NameSilo 客户参数...");
    await apiJson(`/api/admin/customers/${customerId}/namesilo-config`, "PUT", {
      reporter_email: elements.namesiloCustomerForm.elements.reporter_email.value.trim(),
      official_website: elements.namesiloCustomerForm.elements.official_website.value.trim(),
    });
    await refreshCustomers();
    setStatus(`NameSilo 客户参数已保存: ${customerId}`);
  } catch (error) {
    setStatus(error.message);
  }
});

elements.namesiloSettingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    setStatus("正在保存 NameSilo 渠道配置...");
    await apiJson("/api/admin/namesilo-settings", "PUT", {
      entry_url: elements.namesiloSettingsForm.elements.entry_url.value.trim(),
      channel_id: elements.namesiloSettingsForm.elements.channel_id.value.trim(),
      template_key: elements.namesiloSettingsForm.elements.template_key.value.trim(),
      default_reporter_email: elements.namesiloSettingsForm.elements.default_reporter_email.value.trim(),
      notes: elements.namesiloSettingsForm.elements.notes.value.trim(),
    });
    await refreshBootstrap();
    await refreshNamesiloSettings();
    await refreshChannels();
    setStatus("NameSilo 渠道配置已保存。");
  } catch (error) {
    setStatus(error.message);
  }
});

elements.templateForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const locale = elements.templateForm.elements.locale.value;
    const templateKey = elements.templateForm.elements.template_key.value;
    const content = elements.templateForm.elements.content.value;
    setStatus("正在保存模板...");
    await apiJson(`/api/admin/templates/${locale}/${templateKey}`, "PUT", { content });
    await refreshTemplates();
    await loadTemplate(locale, templateKey);
    setStatus(`模板 ${locale}/${templateKey} 已保存。`);
  } catch (error) {
    setStatus(error.message);
  }
});

async function bootstrap() {
  try {
    await refreshBootstrap();
    await refreshCustomers();
    await refreshTemplates();
    await refreshNamesiloSettings();
    await refreshChannels();
    await refreshBatches();
    await refreshCases();

    if (state.templates.length) {
      const firstTemplate = state.templates[0];
      state.selectedTemplate = {
        locale: firstTemplate.locale,
        template_key: firstTemplate.template_key,
      };
      populateTemplateForm(firstTemplate);
      renderTemplateList();
    }

    if (state.customers.length) {
      state.selectedCustomerId = state.customers[0].customer_id;
      state.selectedNamesiloCustomerId = state.customers[0].customer_id;
      elements.namesiloCustomerSelect.value = state.selectedNamesiloCustomerId;
      populateCustomerForm(state.customers[0]);
      renderCustomerList();
      renderNamesiloPanel();
    }

    if (state.batches.length) {
      await loadBatchDetail(state.batches[0].id);
    }
    if (state.cases.length) {
      await loadCaseDetail(state.cases[0].id);
    }

    if (window.location.pathname.toLowerCase() === "/namesilo") {
      activateTab("namesilo");
    }

    setStatus("系统已就绪，可开始批量处置。");
  } catch (error) {
    setStatus(error.message);
  }
}

bootstrap();
