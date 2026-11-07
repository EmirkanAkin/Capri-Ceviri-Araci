/* Capri arayüzü — Python köprüsü: window.pywebview.api (app_modern.CapriBridge) */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const icon = (name) => `<svg class="i"><use href="#i-${name}"/></svg>`;
const fmt = (n) => Number(n || 0).toLocaleString("tr-TR");
/* İçerik değişmediyse DOM'a dokunulmaz: düğmeler titremez, tıklamalar kaybolmaz, görseller yeniden çözülmez. */
function setHtml(el, html) { if (el.__html !== html) { el.innerHTML = html; el.__html = html; } }
function setText(el, text) { if (el.textContent !== text) el.textContent = text; }
function setBg(el, uri) { if (el.__uri !== uri) { el.style.backgroundImage = uri ? `url("${uri}")` : ""; el.__uri = uri; } }
/* Aynı karede art arda gelen olaylar tek çizime iner. */
const queued = new Set();
function later(fn) {
  if (queued.has(fn)) return;
  queued.add(fn);
  requestAnimationFrame(() => { queued.delete(fn); fn(); });
}
function fmtDur(sec) {
  const t = Math.max(0, Math.round(sec));
  if (t < 60) return `${t} sn`;
  if (t < 3600) return t % 60 ? `${Math.floor(t / 60)} dk ${t % 60} sn` : `${t / 60} dk`;
  const m = Math.floor((t % 3600) / 60);
  return `${Math.floor(t / 3600)} sa${m ? ` ${m} dk` : ""}`;
}
const keyOf = (path) => String(path || "").toLowerCase();

const ENGINE_FILTERS = [["all", "Tümü"], ["renpy", "Ren'Py"], ["unity", "Unity"], ["unreal", "Unreal"], ["rpgmaker", "RPG Maker"]];
const STATUS = {
  new: ["Yeni proje", ""], analyzed: ["Çeviriye hazır", ""], translating: ["Çevriliyor", "warn"],
  translated: ["Çevrildi", "lime"], error: ["Çeviri başarısız", "error"], restored: ["Orijinal dosyalar", ""],
  paused: ["Durduruldu", "warn"],
};
const PROVIDERS = [
  { id: "gemini", short: "G", title: "Google Gemini", tag: "Bulut · en hızlı", desc: "Binlerce satırı dakikalar içinde, doğal ve akıcı çevirir. “Otomatik” modda anahtarının erişebildiği tüm modeller hız sırasıyla denenir; biri kotaya takılırsa sıradakine geçilir. Birden fazla anahtar paralel kullanılır.",
    fields: [["gemini_keys", "API anahtarları (her satıra bir tane)", "textarea", "full"], ["gemini_model", "Model", "gemini-select", "full"]], test: "gemini_keys" },
  { id: "openai", short: "AI", title: "OpenAI", tag: "Bulut · GPT", desc: "GPT modelleriyle bağlamsal, akıcı çeviri.",
    fields: [["openai_key", "API anahtarı", "password", ""], ["openai_model", "Model", "text", ""]], test: "openai_key" },
  { id: "anthropic", short: "C", title: "Anthropic Claude", tag: "Bulut · edebi ton", desc: "Diyalog akıcılığı ve karakter tonunu korumada güçlü.",
    fields: [["anthropic_key", "API anahtarı", "password", ""], ["anthropic_model", "Model", "text", ""]], test: "anthropic_key" },
  { id: "deepl", short: "D", title: "DeepL", tag: "Bulut · makine çevirisi", desc: "Dilbilgisine sadık profesyonel çeviri (Free anahtarlar “:fx” ile biter). Oyun etiketleri otomatik korunur.",
    fields: [["deepl_key", "API anahtarı", "password", "full"]], test: "deepl_key" },
  { id: "ollama", short: "O", title: "Ollama", tag: "Yerel LLM · sansürsüz", desc: "Bilgisayarında çalışan açık kaynak modeller (Qwen 2.5, Llama 3…). İnternet ve kota gerekmez; Ollama uygulaması açık olmalı.",
    fields: [["ollama_host", "Sunucu adresi", "text", ""], ["ollama_model", "Model", "text", ""]], test: "ollama_host" },
  { id: "opus", short: "OP", title: "OPUS-MT", tag: "Çevrimdışı · EN→TR", desc: "Helsinki-NLP İngilizce → Türkçe modeli. Hafif ve hızlı, ekran kartında internetsiz çalışır.", fields: [], test: "opus" },
  { id: "nllb", short: "N", title: "NLLB-200", tag: "Çevrimdışı · çok dilli", desc: "Meta'nın 200 dilli modeli; ekran kartında internetsiz çalışır. Türkçe dışındaki hedef dillere de çevirebilir (Almanca, İspanyolca, Rusça, Japonca…).", fields: [], test: "nllb" },
];
const SAMPLES = [
  ["Diyalog", "Welcome to our tavern, hero! What brings you here tonight?"],
  ["Görev", "Find the ancient crystal hidden deep within the dragon's lair."],
  ["Romantik", "I've been waiting for you all night... come closer."],
  ["Menü", "Save Game / Load Game / Settings / Return to Title"],
  ["Etiketli", "{i}Hey [mc]{/i}, did you see {color=#f00}that{/color}?"],
];
const DEMO = [
  ["Welcome to our tavern, hero!", "Meyhanemize hoş geldin, kahraman!", 0],
  ["Press {0} to open the map.", "Haritayı açmak için {0} tuşuna bas.", 2],
  ["{i}Are you sure, [mc]?{/i}", "{i}Emin misin, [mc]?{/i}", 0],
  ["Quest complete! You earned \\C[3]50 gold\\C[0].", "Görev tamamlandı! \\C[3]50 altın\\C[0] kazandın.", 3],
  ["New Game · Continue · Settings", "Yeni Oyun · Devam Et · Ayarlar", 1],
  ["I never thought I'd see you again.", "Seni bir daha göreceğimi hiç düşünmemiştim.", 5, "Elena"],
];
const GLOSSARY_KINDS = [["general", "Genel"], ["rpgmaker", "RPG Maker"]];

const S = {
  api: null, state: null, settings: {}, projects: [], providers: {}, models: {}, gpu: null, stats: null,
  busy: false, busyLabel: "", progress: null, status: null, analysis: null, lastLog: "",
  slides: [], slide: 0, filter: "all", search: "", heroHover: false,
  log: [], notifs: [], unread: 0, drawerTab: "notifs",
  provSel: null, editor: null, glossary: { kind: "general", rows: [], filter: "" },
};

/* ── Köprü ─────────────────────────────────────────────────────────── */
async function call(name, ...args) {
  if (!S.api) return null;
  try {
    return await S.api[name](...args);
  } catch (err) {
    toast({ title: "Beklenmeyen hata", text: `${name}: ${err && err.message ? err.message : err}`, tone: "error" });
    return null;
  }
}

const HANDLERS = {
  log: (lines) => appendLog(lines),
  status: (d) => { S.status = d; later(renderHero); },
  toast: (d) => toast({ title: d.text, tone: d.tone }),
  notify: (n) => addNotif(n),
  progress: (d) => { S.progress = d; S.progressAt = Date.now(); renderProgress(); later(renderEngineCard); },
  notice: (d) => { S.notice = { text: d.text, at: Date.now() }; renderProgress(); },
  stage: (d) => { S.stageAt = Date.now(); S.stage = d; S.progress = null; (S.stagesSeen = S.stagesSeen || new Set()).add(d.key); later(renderHero); },
  task_error: (d) => {
    if (d.label === "Analiz") { S.analysisError = d; later(renderAnalysis); return; }
    S.taskError = d; later(renderHero);
  },
  analyzing: (d) => {
    S.analyzing = d.active ? d.path : null;
    if (d.active) S.analysisError = null;
    later(renderHero); later(renderAnalysis);
  },
  estimate: (d) => { if (S.analysis) { S.analysis.estimate = d; later(renderAnalysis); later(renderHero); } },
  busy: (d) => {
    const prevLabel = S.busyLabel;
    S.busy = d.busy; S.busyLabel = d.label || ""; S.cancelling = false; S.stage = null; S.progress = null;
    if (d.busy) { S.taskStart = Date.now(); S.taskError = null; S.stagesSeen = new Set(); S.notice = null; S.shownPct = 0; }
    renderHero(); renderEngineCard(); renderProgress(); renderModels(); renderAnalysis();
    if (!d.busy && $("#page-editor").classList.contains("active")) loadEditor(true);
    if (!d.busy && /BepInEx/.test(prevLabel) && activeProject()) call("analyze", true);
  },
  analysis: (d) => { S.analysis = d; S.analysisError = null; renderAnalysis(); renderHero(); },
  project: (p) => upsertProject(p),
  gpu: (g) => { S.gpu = g; renderEngineCard(); renderGpu(); },
  stats: (st) => { S.stats = st; renderStats(); },
  models: (m) => { S.models = m; renderModels(); renderProviders(); },
  backups: (list) => renderBackups(list),
  confirm: (d) => openConfirm(d),
  scan: (d) => { S.scan = d; later(renderScan); },
  update: (info) => { S.update = info; $("#updateDot").classList.toggle("hidden", !info.available); renderUpdate(); },
  update_progress: (p) => { S.updateProgress = p; renderUpdate(); },
  done: () => {},
  gpu_opt: (g) => { S.gpuOpt = g; S.gpuBusy = false; renderGpu(); renderEngineCard(); },
  ocr: (o) => { S.ocr = o; renderOcr(); renderEngineCard(); },
  dropped: (paths) => handleDropped(paths),
};
window.OT = { receive(events) { for (const { e, d } of events) if (HANDLERS[e]) HANDLERS[e](d); } };

/* ── Açılış ────────────────────────────────────────────────────────── */
async function boot(api) {
  if (S.api) return;
  S.api = api;
  const st = await call("get_state");
  if (!st) return;
  Object.assign(S, { state: st, settings: st.settings, projects: st.projects || [], providers: st.providers,
    models: st.models, gpu: st.gpu, busy: st.busy, gpuOpt: st.gpu_opt, ocr: st.ocr, scan: st.scan });
  S.provSel = S.settings.model;
  renderSelects();
  buildSlides();
  renderHero();
  renderEngineCard();
  renderAnalysis();
  renderStats();
  renderLibraries();
  renderScan();
  renderProviders();
  renderModels();
  renderSamples();
  renderTranslator();
  renderGpu();
  renderOcr();
  renderDrawer();
  appendLog([`Capri ${st.version} hazır.`]);
}

/* ── Gezinme ───────────────────────────────────────────────────────── */
function showPage(id) {
  $$(".page").forEach((p) => p.classList.toggle("active", p.id === `page-${id}`));
  $$(".nav").forEach((n) => n.classList.toggle("active", n.dataset.page === id));
  $("#scroll").scrollTop = 0;
  renderProgress();
  if (id === "backups") loadBackups();
  if (id === "models") call("model_status").then((m) => { if (m) { S.models = m; renderModels(); } });
  if (id === "translator") setTimeout(() => $("#txInput").focus(), 50);
  if (id === "ocr") call("ocr_status").then((o) => { if (o) { S.ocr = o; renderOcr(); } });
  if (id === "editor") loadEditor(true);
  if (id === "glossary") loadGlossary();
  if (id === "json") $("#jsonModel").textContent = `Motor: ${S.state.model_labels[S.settings.model]}`;
}

/* ── Vitrin ────────────────────────────────────────────────────────── */
const activeProject = () => S.projects.find((p) => p.active) || null;

function buildSlides() {
  const current = S.slides[S.slide];
  const active = activeProject();
  const list = active ? [active] : [];
  for (const p of S.projects) if (!p.active && list.length < 5) list.push(p);
  S.slides = list.length ? list : [null];
  const keep = current ? S.slides.findIndex((p) => p && keyOf(p.path) === keyOf(current.path)) : -1;
  S.slide = keep >= 0 ? keep : 0;
}

function artFallback(p, withName = true) {
  const initial = `<div class="initial">${esc((p.title || "?").trim()[0] || "?")}</div>`;
  return withName ? `${initial}<div class="name">${esc(p.title)}</div><div class="eng">${esc(p.engine_label)}</div>` : initial;
}

function setArt(el, uri, p) {
  setBg(el, uri);
  el.classList.toggle("art-fallback", !uri);
  setHtml(el, uri ? "" : artFallback(p));
}

function renderHero() {
  if (!S.state) return;
  const p = S.slides[S.slide];
  const bg = $("#heroBg");
  setBg(bg, p && p.hero ? p.hero : "");
  bg.classList.toggle("fallback", !(p && p.hero));
  $("#heroDemo").classList.toggle("hidden", !!p);
  $("#heroSteps").classList.toggle("hidden", !!p);
  $("#heroPoster").classList.toggle("hidden", !p);
  const actions = $("#heroActions");
  const meta = $("#heroMeta");

  if (!p) {
    setHero("Hoş geldin", "");
    setText($("#heroTitle"), "Oyununu Türkçeye çevir.");
    setHtml(meta, ["Ren'Py", "Unity", "Unreal", "RPG Maker", "JSON"].map((t) => `<span class="meta-chip">${t}</span>`).join(""));
    setText($("#heroDesc"), "Oyun klasörünü seç; motoru otomatik algılayıp yedekleyelim ve seçtiğin yapay zekayla tek tıkla çevirelim.");
    setHtml(actions, `<button class="cta" data-action="pick">${icon("plus")}Oyun ekle</button>
                         <button class="ghost" data-page="guide">${icon("book")}Nasıl çalışır?</button>`);
    showHeroError(null);
    startDemo();
  } else {
    stopDemo();
    setArt($("#heroPoster"), p.poster, p);
    setText($("#heroTitle"), p.title);
    const isActive = !!p.active;
    const chips = [p.engine_label];
    const stats = (isActive && S.analysis && S.analysis.stats) || {};
    const lines = p.unique || stats.unique;
    if (lines) chips.push(`${stats.exact === false ? "~" : ""}${fmt(lines)} satır`);
    else if (isActive && S.analysis && S.analysis.meta) chips.push(S.analysis.meta);
    const model = isActive ? S.settings.model : p.model;
    if (model) chips.push(S.state.model_labels[model].replace(/ \(.*\)/, ""));
    chips.push(`${(isActive ? S.settings.source : "en").toUpperCase()} → ${(isActive ? S.settings.target : (p.target || "tr")).toUpperCase()}`);
    setHtml(meta, chips.map((c) => `<span class="meta-chip">${esc(c)}</span>`).join(""));
    const view = isActive ? heroActive(p) : {
      tag: (STATUS[p.status] || ["Proje"])[0], tone: "",
      desc: p.last_action_at ? `Son işlem: ${p.last_action} · ${relTime(p.last_action_at)}.`
        : p.status === "paused" ? "Önceki çeviri yarıda kaldı; açıp kaldığı yerden devam edebilirsin." : "Bu oyunda henüz çeviri yapılmadı.",
      actions: `<button class="cta" data-action="open" data-path="${esc(p.path)}">Projeyi aç ${icon("right")}</button>`,
    };
    setHero(view.tag, view.tone);
    setText($("#heroDesc"), view.desc);
    setHtml(actions, view.actions);
    showHeroError(view.error || null);
  }
  const running = !!(p && p.active && (S.busy || S.analyzing));
  $("#heroProgress").classList.toggle("hidden", !running);

  const multi = S.slides.length > 1 && !running;
  $("#heroNav").classList.toggle("hidden", !multi);
  if (multi) {
    setHtml($("#heroDots"), S.slides.map((_, i) => `<button class="${i === S.slide ? "on" : ""}" data-slide="${i}"></button>`).join(""));
    setText($("#heroCount"), `${S.slide + 1} / ${S.slides.length}`);
  }
  renderProgress();
}

function setHero(tag, tone) {
  const el = $("#heroTag");
  setText(el, tag);
  el.className = `eyebrow ${tone}`;
}

function showHeroError(err) {
  const box = $("#heroError");
  box.classList.toggle("hidden", !err);
  if (!err) return;
  setHtml(box, `<div class="he-title">${icon("alert")}${esc(err.title)}</div><p>${esc(err.hint)}</p>
    ${err.detail ? `<details><summary>Teknik ayrıntılar</summary><code class="selectable">${esc(err.detail)}</code></details>` : ""}`);
}

/* Etkin proje için tek doğruluk kaynağı: etiket, açıklama ve düğmeler aynı durumdan türetilir. */
function heroActive(p) {
  const r = p.last_result || {};
  const editor = `<button class="ghost" data-page="editor">${icon("edit")}Editör</button>`;
  const restore = `<button class="ghost" data-action="restore">${icon("undo")}Orijinale dön</button>`;
  const folder = `<button class="ghost" data-action="open-game">${icon("folder")}Oyun klasörü</button>`;
  const play = `<button class="ghost" data-action="play-game">${icon("play")}Oyna</button>`;
  const reanalyze = `<button class="ghost" data-action="analyze">${icon("scan")}Yeniden analiz</button>`;
  const bx = S.analysis && S.analysis.bepinex;
  const bepinex = !bx || !bx.needed ? ""
    : !bx.installed ? `<button class="ghost" data-action="bepinex-install">${icon("download")}BepInEx kur</button>`
    : bx.managed ? `<button class="ghost" data-action="bepinex-uninstall">${icon("trash")}BepInEx'i kaldır</button>` : "";
  const stop = S.cancelling ? `<button class="stop-btn" disabled><span class="spinner"></span>Durduruluyor…</button>`
    : `<button class="stop-btn" data-action="cancel">${icon("stop")}Durdur</button>`;

  if (S.busy && S.busyLabel === "Çeviri") {
    return { tag: "Çeviri devam ediyor", tone: "run",
      desc: S.cancelling ? "Geçerli parti bitince duracak. Yapılan çeviriler kaydediliyor." : ((S.stage && S.stage.label) || "Çeviri başlatılıyor") + "…",
      actions: `<button class="cta is-running" disabled><span class="spinner dark"></span>Çeviri devam ediyor<span class="cta-pct" id="ctaPct"></span></button>${stop}` };
  }
  if (S.busy) {
    return { tag: `${S.busyLabel || "İşlem"} sürüyor`, tone: "run", desc: (S.status && S.status.text) || "Lütfen bekle…",
      actions: `<button class="cta is-running" disabled><span class="spinner dark"></span>${esc(S.busyLabel || "İşlem")} sürüyor</button>${stop}` };
  }
  if (S.analyzing) {
    return { tag: "Analiz ediliyor", tone: "run",
      desc: "Oyunun metinleri taranıyor. Büyük oyunlarda biraz sürebilir; bu sırada başka bir projeye geçebilirsin.",
      actions: `<button class="cta is-running" disabled><span class="spinner dark"></span>Analiz ediliyor</button>${editor}` };
  }
  const err = S.taskError || (p.status === "error" ? p.last_error : null);
  if (err) {
    const go = err.action && err.action.page ? `<button class="ghost" data-page="${esc(err.action.page)}">${esc(err.action.label)}</button>`
      : err.action && err.action.update ? `<button class="ghost" data-action="update-open">${icon("download")}${esc(err.action.label)}</button>` : "";
    return { tag: p.status === "error" ? "Çeviri başarısız" : "İşlem yapılamadı", tone: "err", desc: "Çeviri durdu; şu an çalışan bir işlem yok.", error: err,
      actions: `<button class="cta" data-action="translate">${icon("undo")}Tekrar dene</button>${go}
        <button class="ghost" data-action="show-log">${icon("terminal")}Teknik günlük</button>${reanalyze}` };
  }
  if (p.status === "translated") {
    const parts = [r.written !== undefined ? `${fmt(r.written)} satır oyuna yazıldı` : "Çeviri oyuna yazıldı"];
    if (r.took) parts.push(fmtDur(r.took));
    if (p.last_action_at) parts.push(relTime(p.last_action_at));
    if (r.failed) parts.push(`${fmt(r.failed)} satır incelenmeli`);
    return { tag: "Çeviri tamamlandı", tone: "ok", desc: `${parts.join(" · ")}.`,
      actions: `<button class="cta is-done" disabled>${icon("check")}Çeviri tamamlandı</button>
        ${play}<button class="ghost" data-action="translate">${icon("undo")}Baştan çevir</button>${editor}${folder}${bepinex}${restore}` };
  }
  if (p.status === "paused") {
    const pct = p.paused_total ? Math.round((p.paused_done / p.paused_total) * 100) : 0;
    return { tag: "Durduruldu", tone: "warn",
      desc: `${pct ? `%${pct} tamamlanmıştı. ` : ""}Yapılan çeviriler kayıtlı; devam ettiğinde kaldığı yerden sürer, tekrar ücret ödemezsin.`,
      actions: `<button class="cta" data-action="translate">${icon("play")}Kaldığı yerden devam et</button>${bepinex}${reanalyze}${editor}${restore}` };
  }
  const est = S.analysis && S.analysis.estimate;
  const desc = est && est.pending && est.text ? `Çeviriye hazır: ${fmt(est.pending)} satır, ${est.text}. İstediğin an durdurabilirsin.`
    : est && est.lines && !est.pending ? "Tüm satırlar önbellekte hazır; çeviri birkaç saniyede biter, API harcanmaz."
    : "Tek tıkla çevir; istediğin an durdur, düzelt ya da orijinal dosyalarına dön.";
  return { tag: p.status === "restored" ? "Orijinal dosyalar" : "Çeviriye hazır", tone: "", desc,
    actions: `<button class="cta" data-action="translate">${icon("play")}Çeviriyi başlat</button>${bepinex}${reanalyze}${editor}${play}${restore}` };
}

const STEPS = [["backup", "Yedek"], ["prepare", "Hazırlık"], ["translate", "Çeviri"], ["write", "Yazma"]];

function progressFacts() {
  const pr = S.progress;
  const elapsed = (Date.now() - (S.taskStart || Date.now())) / 1000;
  const facts = [];
  const est = S.analysis && S.analysis.estimate;
  const firstWait = (Date.now() - (S.stageAt || S.taskStart || Date.now())) / 1000;
  if (pr && pr.done > 0 && pr.eta_s !== null && pr.eta_s !== undefined) {
    const left = Math.max(0, pr.eta_s - (Date.now() - S.progressAt) / 1000);
    facts.push(["Kalan süre", left < 2 ? "az kaldı" : `~${fmtDur(left)}`]);
  } else if (S.stage && S.stage.key === "translate") {
    // İlk sonuç gelmeden: tahmin geri sayılır; aşılırsa bunu dürüstçe söyler
    const left = est && est.seconds ? est.seconds - firstWait : null;
    facts.push(["Kalan süre", left === null ? "hesaplanıyor…" : left > 5 ? `~${fmtDur(left)} (tahmin)` : "ilk sonuç bekleniyor"]);
  }
  if (pr && pr.rate) facts.push(["Hız", pr.rate]);
  if (S.busy) facts.push(["Geçen", fmtDur(elapsed)]);
  return facts;
}

/* Çubuk yalnızca ileri gider: parti arasında gerçek hıza göre ilerler, bir sonraki partiyi geçmez. */
function shownPercent() {
  const pr = S.progress;
  if (!S.busy || !S.stage || S.stage.key !== "translate" || !pr || !pr.total) return pr ? pr.pct : null;
  const elapsed = (Date.now() - (S.progressAt || Date.now())) / 1000;
  const est = S.analysis && S.analysis.estimate;
  const rate = pr.done > 0 && pr.eta_s ? (pr.total - pr.done) / Math.max(pr.eta_s, 1)
    : est && est.seconds ? (est.pending || pr.total) / est.seconds : 0;
  const ahead = Math.min(rate * elapsed, Math.max(pr.total * 0.08, 30) * 0.9);
  const pct = Math.min(99, ((pr.done + ahead) / pr.total) * 100);
  S.shownPct = Math.max(S.shownPct || 0, pct, pr.pct);
  return S.shownPct;
}

function renderProgress() {
  const pr = S.progress;
  const pct = shownPercent();
  for (const bar of [$("#heroBar"), $("#taskBar")]) {
    bar.classList.toggle("indeterminate", pct === null);
    bar.firstElementChild.style.width = pct === null ? "" : `${pct}%`;
  }
  const translating = S.busy && S.busyLabel === "Çeviri";
  const label = S.analyzing && !S.busy ? "Analiz ediliyor" : (S.stage && S.stage.label) || (S.busy ? `${S.busyLabel || "İşlem"} sürüyor` : "");
  setText($("#progPct"), pr && pr.done > 0 ? `%${Math.floor(pr.pct)}` : `${label}…`);
  setText($("#progMeta"), pr ? `${fmt(pr.done)} / ${fmt(pr.total)} ${pr.unit || ""}`.trim() : "");
  const current = translating && S.stage ? STEPS.findIndex(([k]) => k === S.stage.key) : -1;
  const seen = S.stagesSeen || new Set();
  const isDone = (k, i) => i !== current && (i < current || seen.has(k));
  setHtml($("#progSteps"), translating ? STEPS.map(([k, name], i) => `<span class="ps ${isDone(k, i) ? "done" : i === current ? "now" : ""}">
    <b>${isDone(k, i) ? icon("check") : i + 1}</b>${name}</span>`).join("") : "");
  const facts = progressFacts();
  setHtml($("#progFacts"), facts.map(([k, v]) => `<span><em>${k}</em>${esc(v)}</span>`).join("")
    + (S.notice && Date.now() - S.notice.at < 20000 ? `<span class="hint warn">${esc(S.notice.text)}</span>`
      : translating && S.stage && S.stage.key === "translate" && !(pr && pr.done) ? `<span class="hint">İlk sonuçlar bekleniyor; gelince süre netleşir.</span>` : ""));
  const ctaPct = $("#ctaPct");
  if (ctaPct) setText(ctaPct, pr ? `%${Math.floor(pr.pct)}` : "");
  const slide = S.slides[S.slide];
  const heroShowsIt = $("#page-studio").classList.contains("active") && slide && slide.active;
  $("#taskbar").classList.toggle("hidden", !S.busy || heroShowsIt);
  setText($("#taskLabel"), (S.stage && S.stage.label) || S.busyLabel || "İşlem");
  const left = facts.find(([k]) => k === "Kalan süre");
  setText($("#taskMeta"), pr ? `%${Math.floor(pr.pct)} · ${fmt(pr.done)}/${fmt(pr.total)}${left ? ` · kalan ${left[1]}` : ""}` : "hazırlanıyor…");
}
/* İlerleme olayları arasında kalan/geçen süre saniye saniye akar. */
setInterval(() => { if (S.busy && document.visibilityState === "visible") renderProgress(); }, 1000);

function moveSlide(step) {
  if (S.slides.length < 2) return;
  S.slide = (S.slide + step + S.slides.length) % S.slides.length;
  renderHero();
}
setInterval(() => {
  if (!S.busy && !S.heroHover && !activeProject() && document.visibilityState === "visible" && $("#page-studio").classList.contains("active")) moveSlide(1);
}, 9000);

/* Hoş geldin: canlı çeviri animasyonu */
let demoTimer = null;
function highlightTags(text) {
  return esc(text).replace(/(\{[^}]*\}|\[[^\]]*\]|\\C\[\d+\])/g, '<span class="tag">$1</span>');
}
function startDemo() {
  if (demoTimer) return;
  let item = 0;
  const next = (ms) => { demoTimer = setTimeout(() => { item += 1; run(); }, ms); };
  const run = () => {
    const [src, tr, engine, speaker] = DEMO[item % DEMO.length];
    $$("#demoEngines span").forEach((el, i) => el.classList.toggle("on", i === engine));
    const ocr = !!speaker;
    $("#demoCard").classList.toggle("hidden", ocr);
    $("#demoOcr").classList.toggle("hidden", !ocr);
    if (ocr) return runOcrDemo(src, tr, speaker, () => next(3200));
    $("#demoSrc").innerHTML = highlightTags(src);
    let n = 0;
    const type = () => {
      if (!demoTimer) return;
      n += 1;
      $("#demoTr").innerHTML = highlightTags(tr.slice(0, n)) + '<span class="caret"></span>';
      if (n < tr.length) demoTimer = setTimeout(type, 34);
      else next(2600);
    };
    demoTimer = setTimeout(type, 500);
  };
  demoTimer = setTimeout(run, 0);
}
/* Ekran çevirisi sahnesi: kısayol → alan seçimi → tarama → çeviri balonu */
function runOcrDemo(src, tr, speaker, done) {
  const box = $("#demoOcr");
  box.className = "demo-ocr";
  $("#docrName").textContent = speaker;
  $("#docrSrc").textContent = src;
  $("#docrTr").textContent = "";
  $("#docrMs").textContent = "";
  const stages = [["keys", 300], ["select", 1100], ["scan", 1500], ["pop", 900]];
  let i = 0;
  const step = () => {
    if (!demoTimer) return;
    if (i < stages.length) {
      box.classList.add(stages[i][0]);
      demoTimer = setTimeout(step, stages[i++][1]);
      return;
    }
    $("#docrMs").textContent = "0,4 sn";
    let n = 0;
    const type = () => {
      if (!demoTimer) return;
      n += 2;
      $("#docrTr").innerHTML = esc(tr.slice(0, n)) + '<span class="caret"></span>';
      if (n < tr.length) demoTimer = setTimeout(type, 28);
      else done();
    };
    type();
  };
  demoTimer = setTimeout(step, 200);
}
function stopDemo() { clearTimeout(demoTimer); demoTimer = null; }

/* ── Kenar çubuğu motor kartı ──────────────────────────────────────── */
function providerStatus(id) {
  const pv = S.providers || {};
  if (id === "gemini") return pv.gemini_keys && pv.gemini_keys.length ? [`Hazır · ${pv.gemini_keys.length} anahtar`, "ok"] : ["Anahtar gerekli", "warn"];
  if (["openai", "anthropic", "deepl"].includes(id)) return pv[`${id}_key`] ? ["Hazır", "ok"] : ["Anahtar gerekli", "warn"];
  if (id === "ollama") return ["Yerel sunucu", ""];
  const m = S.models && S.models[id];
  return m && m.is_ready ? ["Kurulu", "ok"] : ["Kurulu değil", "warn"];
}

function renderEngineCard() {
  if (!S.state) return;
  const title = S.state.model_labels[S.settings.model] || S.settings.model;
  $("#engineTitle").textContent = title;
  $("#engineTitle").title = title;
  if (S.busy) setHtml($("#engineState"), `<span class="pill warn">${S.progress ? `%${Math.floor(S.progress.pct)}` : esc(S.busyLabel)}</span>`);
  else {
    const [text, tone] = providerStatus(S.settings.model);
    setHtml($("#engineState"), `<span class="pill ${tone}">${esc(text)}</span>`);
  }
  const gpu = S.gpu ? `${S.gpu.name}${S.gpu.detail ? " · " + S.gpu.detail : ""}` : "—";
  $("#engineGpu").textContent = gpu;
  $("#engineGpu").title = gpu;
  const o = S.ocr || {};
  setHtml($("#engineOcr"), !o.available ? '<span class="pill warn">Kullanılamıyor</span>'
    : o.pin_active ? '<span class="pill lime">Canlı</span>' : `<span class="pill ok">${esc(S.settings.ocr_hotkey || "Hazır")}</span>`);
  $("#ocrDot").classList.toggle("hidden", !o.pin_active);
  $("#libraryDot").classList.toggle("hidden", !((S.scan && S.scan.found && S.scan.found.length) || S.projects.some((p) => p.status === "translating")));
}

/* ── Ayarlar ───────────────────────────────────────────────────────── */
function renderSelects() {
  const st = S.state;
  $("#sourceSelect").innerHTML = st.source_languages.map((l) => `<option value="${esc(l.code)}">${esc(l.label)}</option>`).join("");
  $("#targetSelect").innerHTML = st.target_languages.map((l) => `<option value="${esc(l.code)}">${esc(l.label)}</option>`).join("");
  const group = (label, ids) => `<optgroup label="${label}">${ids.map((m) => `<option value="${m}">${esc(st.model_labels[m])}</option>`).join("")}</optgroup>`;
  $("#modelSelect").innerHTML = group("Bulut", ["gemini", "openai", "anthropic", "deepl"]) + group("Yerel", ["ollama", "opus", "nllb"]);
  syncSettingsUi();
}

function syncSettingsUi() {
  $("#sourceSelect").value = S.settings.source;
  $("#targetSelect").value = S.settings.target;
  $("#modelSelect").value = S.settings.model;
  $("#backupToggle").checked = !!S.settings.backup;
  $("#nsfwToggle").checked = !!S.settings.nsfw;
  $("#qualityToggle").checked = !!S.settings.quality_pass;
  const p = PROVIDERS.find((x) => x.id === S.settings.model);
  const [st] = providerStatus(S.settings.model);
  $("#modelHint").textContent = p ? `${p.tag} · ${st}` : "";
}

async function updateSettings(patch) {
  Object.assign(S.settings, patch);
  syncSettingsUi(); renderEngineCard(); renderHero(); renderProviders(); renderOcr();
  const saved = await call("update_settings", patch);
  if (saved) S.settings = saved;
}

function renderAnalysis() {
  const box = $("#analysisPanel");
  const active = activeProject();
  const a = S.analysis;
  const tile = (ic, label, value, sub, tone = "") => `<div class="an-tile ${tone}"><div class="an-label">${icon(ic)}${label}</div>
    <div class="an-value">${value}</div><div class="an-sub">${sub}</div></div>`;
  if (!active) {
    setHtml(box, `<p class="an-empty">Bir oyun eklediğinde burada kaç satır çevrileceğini, ne kadar süreceğini ve dikkat etmen gereken bir şey olup olmadığını görürsün.</p>`);
    return;
  }
  if (S.analyzing) {
    setHtml(box, `<div class="an-state"><span class="spinner"></span><div><b>Oyun analiz ediliyor</b><p>Metinler, fontlar ve dosya yapısı kontrol ediliyor. Sonucu bir sonraki açılışta anında gelir.</p></div></div>`);
    return;
  }
  if (S.analysisError) {
    const e = S.analysisError;
    setHtml(box, `<div class="an-state warn">${icon("alert")}<div><b>Analiz tamamlanamadı: ${esc(e.title)}</b><p>${esc(e.hint)}</p>
      ${e.detail ? `<details><summary>Teknik ayrıntılar</summary><code class="selectable">${esc(e.detail)}</code></details>` : ""}
      <div class="row-actions"><button class="btn" data-action="analyze">${icon("scan")}Tekrar dene</button></div></div></div>`);
    return;
  }
  if (!a) {
    setHtml(box, `<p class="an-empty">Analiz bekleniyor…</p>`);
    return;
  }
  const st = a.stats || {};
  const est = a.estimate || {};
  const approx = st.exact === false ? "yaklaşık " : "";
  const done = active.status === "translated";
  let tiles = "";
  tiles += tile("gamepad", "Oyun motoru", esc(a.engine_detail || active.engine_label), esc(active.title));
  if (st.unique) {
    tiles += done
      ? tile("check", "Çevrilecek metin", "Kalmadı", `${approx}${fmt(st.unique)} satırın tamamı işlendi`, "ok")
      : tile("lines", "Çevrilecek metin", `${est.exact === false ? "~" : ""}${fmt(est.pending ?? st.unique)} satır`,
          `Toplam ${approx}${fmt(st.unique)} satır · ${approx}${fmt(st.words)} kelime`);
    tiles += tile("archive", "Hazır çeviri", `${fmt(est.cached)} satır`,
      est.cached ? "Önbellekte; tekrar ücret ödemezsin" : "Bu motorla henüz çevrilmiş satır yok");
    tiles += done ? tile("zap", "Süre", active.last_result && active.last_result.took ? fmtDur(active.last_result.took) : "Tamamlandı", "Son çevirinin süresi")
      : tile("zap", "Tahmini süre", est.pending ? esc(est.text || "—") : "Birkaç saniye",
        !est.pending ? "Tüm satırlar önbellekte"
          : `${esc(est.model || "")}${est.workers > 1 ? ` · ${est.workers} anahtar` : ""}<br>${est.basis === "learned" ? "Önceki çevirilerindeki hızına göre" : "Ortalama hıza göre; çeviri başlayınca netleşir"}`
            + (est.cost ? `<br>Maliyet: ${esc(est.cost.text)} (fiyatlar değişebilir)` : ""));
  } else {
    tiles += tile("lines", "Çevrilecek metin", "Bulunamadı", "Dosyalarda okunabilir metin yok", "warn");
  }
  if (a.font) tiles += tile("type", "Türkçe harfler", esc(a.font.text), a.font.ok ? "Oyunun fontu destekliyor" : "Oyun içinde kontrol et", a.font.ok ? "" : "warn");
  const advice = (a.advice || []).map((x) => `<div class="an-advice ${esc(x.tone)}">${icon(x.tone === "warn" ? "alert" : "sparkle")}<span>${esc(x.text)}</span></div>`).join("");
  const tech = (a.notes || []).length ? `<details class="an-tech"><summary>Teknik ayrıntılar</summary>
    <ul class="notes">${a.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></details>` : "";
  setHtml(box, `<div class="an-grid">${tiles}</div>${advice}${tech}`);
}

function renderStats() {
  const st = S.stats || { translated: 0, lines: 0, written: 0 };
  const tiles = [
    ["gamepad", fmt(S.projects.length), "Proje"],
    ["check", fmt(st.translated), "Çevrilen oyun"],
    ["lines", fmt(st.lines), "Önbellekteki çeviri"],
    ["sparkle", fmt(st.written), "Oyuna yazılan satır"],
  ];
  setHtml($("#stats"), tiles.map(([ic, v, l]) => `<div class="stat"><div class="stat-icon">${icon(ic)}</div>
    <div><div class="stat-value num">${v}</div><div class="stat-label">${l}</div></div></div>`).join(""));
}

/* ── Kütüphane ─────────────────────────────────────────────────────── */
function upsertProject(p) {
  const i = S.projects.findIndex((x) => keyOf(x.path) === keyOf(p.path));
  if (p.active) S.projects.forEach((x) => { x.active = false; });
  if (i >= 0) S.projects[i] = { ...S.projects[i], ...p };
  else S.projects.unshift(p);
  buildSlides(); later(renderHero); later(renderLibraries); later(renderEngineCard); later(renderStats);
}

function filtered() {
  const q = S.search.trim().toLocaleLowerCase("tr-TR");
  return S.projects.filter((p) => (S.filter === "all" || p.engine === S.filter) &&
    (!q || p.title.toLocaleLowerCase("tr-TR").includes(q) || keyOf(p.path).includes(q)));
}

function filtersHtml() {
  return `<div class="filters">${ENGINE_FILTERS.map(([id, name]) => {
    const count = id === "all" ? S.projects.length : S.projects.filter((p) => p.engine === id).length;
    return `<button class="filter ${S.filter === id ? "on" : ""}" data-filter="${id}">${name}<span>${count}</span></button>`;
  }).join("")}</div>`;
}

function cardHtml(p) {
  const art = p.poster ? `<div class="card-art" style="background-image:url('${p.poster}')"></div>`
    : `<div class="card-art art-fallback">${artFallback(p, false)}</div>`;
  const [label, tone] = STATUS[p.status] || [p.engine_label, ""];
  const badge = ["translated", "translating", "error", "paused"].includes(p.status) ? `<span class="card-badge ${tone}">${label}</span>` : "";
  const meta = [p.engine_label, p.unique ? `${fmt(p.unique)} satır` : ""].filter(Boolean).join(" · ");
  return `<div class="card ${p.active ? "active" : ""}" data-action="open" data-path="${esc(p.path)}" title="${esc(p.path)}">
    ${art}${badge}
    <button class="card-remove" data-action="remove" data-path="${esc(p.path)}" title="Kütüphaneden kaldır">${icon("x")}</button>
    <div class="card-info"><div class="card-title">${esc(p.title)}</div><div class="card-meta">${esc(meta)}</div></div></div>`;
}

const ADD_CARD = `<button class="card add" data-action="pick"><span class="plus">${icon("plus")}</span>Oyun ekle</button>`;
const ENGINE_INTRO = `<div class="engines-intro">${[
  ["Ren'Py", "Görsel romanlar: .rpy/.rpyc/.rpa, otomatik Türkçe font yaması."],
  ["Unity", "resources.assets metinleri; IL2CPP oyunlarda BepInEx köprüsü."],
  ["Unreal Engine", "UE4/UE5 .locres tabloları, ~mods yapısı."],
  ["RPG Maker", "MV / MZ veri dosyaları, kontrol kodları korunur."],
].map(([t, d]) => `<div class="engine-tile"><span class="pill lime">Destekleniyor</span><div class="t">${t}</div><div class="d">${d}</div></div>`).join("")}</div>`;

function renderLibraries() {
  const items = filtered();
  const empty = S.search ? `<div class="empty">“${esc(S.search)}” için sonuç yok.</div>` : "";
  if (!S.projects.length) {
    setHtml($("#homeLibrary"), ENGINE_INTRO + `<button class="empty-cta" data-action="pick"><span class="plus">${icon("plus")}</span>
      <span><b>Kütüphanen henüz boş</b><span>İlk oyununu ekle; motor otomatik algılanır, kapak görseli Steam'den gelir.</span></span>
      <span class="btn lime">Oyun ekle</span></button>`);
    setHtml($("#fullLibrary"), `<div class="empty">Henüz proje yok. “Oyun ekle” ile ilk oyununu seç.</div>`);
    return;
  }
  setHtml($("#homeLibrary"), filtersHtml() + (items.length ? `<div class="grid">${items.slice(0, 11).map(cardHtml).join("")}${ADD_CARD}</div>` : empty));
  setHtml($("#fullLibrary"), filtersHtml() + (items.length ? `<div class="grid">${items.map(cardHtml).join("")}${ADD_CARD}</div>` : empty));
}

async function selectProject(p) {
  if (!p) return;
  if (S.analysis && keyOf(S.analysis.path) !== keyOf(p.path)) S.analysis = null;   // aynı oyunun sonucu önce gelmiş olabilir
  S.status = null;
  S.taskError = null;
  S.analysisError = null;
  upsertProject(p);
  S.slide = 0;
  renderHero(); renderAnalysis();
  showPage("studio");
}
/* Disk yavaşsa tıklanan kart hemen tepki verir; hızlıysa hiç titremez. */
const openProject = async (path) => {
  const timer = setTimeout(() => $$(`.card[data-path="${CSS.escape(path)}"]`).forEach((c) => c.classList.add("is-loading")), 150);
  const project = await call("open_project", path);
  clearTimeout(timer);
  $$(".card.is-loading").forEach((c) => c.classList.remove("is-loading"));
  await selectProject(project);
};
const pickFolder = async () => selectProject(await call("pick_folder"));
/* Düğme anında tepki verir; arka plandan gelen olaylar durumu doğrular. */
async function startTranslate() {
  Object.assign(S, { busy: true, busyLabel: "Çeviri", taskStart: Date.now(), taskError: null, stage: null, progress: null });
  renderHero(); renderEngineCard();
  if ((await call("translate")) !== true) { S.busy = false; S.busyLabel = ""; renderHero(); renderEngineCard(); }
}

/* ── Otomatik oyun tarama ──────────────────────────────────────────── */
function renderScan() {
  const sc = S.scan || { found: [], folders: [] };
  const found = sc.found || [];
  const rows = found.slice(0, 30).map((g) => `<div class="list-row">
      <div class="list-icon">${icon("gamepad")}</div>
      <div class="grow"><div class="title">${esc(g.title)} <span class="pill">${esc(g.engine_label)}</span>${g.lines ? ` <span class="pill">~${fmt(g.lines)} satır</span>` : ""}</div>
        <div class="sub selectable">${esc(g.path)}</div></div>
      <button class="btn" data-action="scan-dismiss" data-path="${esc(g.path)}" title="Bu öneriyi gizle">${icon("x")}</button>
      <button class="btn lime" data-action="scan-add" data-path="${esc(g.path)}">${icon("plus")}Ekle</button></div>`).join("");
  const chips = (sc.folders || []).map((f) => `<button class="chip" data-action="scan-remove-folder" data-path="${esc(f)}" title="Taramadan çıkar">${esc(f)} ${icon("x")}</button>`).join("");
  setHtml($("#scanPanel"), `<div class="panel scan-panel">
    <div class="panel-head"><div><div class="panel-title">Bilgisayarındaki oyunlar</div>
      <p class="panel-desc">${sc.running ? "Taranıyor: Steam, Epic, GOG ve oyun klasörlerin…"
        : found.length ? `${fmt(found.length)} çevrilebilir oyun bulundu.` : "Steam, Epic, GOG ve Games/Oyunlar klasörleri taranır; yalnızca okunur, hiçbir dosya değişmez."}</p></div>
      <div class="row-actions" style="margin:0">
        ${found.length > 1 ? `<button class="btn" data-action="scan-add-all">${icon("plus")}Tümünü ekle</button>` : ""}
        <button class="btn" data-action="scan-folder">${icon("folder")}Klasör ekle</button>
        <button class="btn" data-action="scan-now" ${sc.running ? "disabled" : ""}>${sc.running ? '<span class="spinner"></span>' : icon("scan")}Şimdi tara</button>
      </div></div>
    ${rows ? `<div class="list">${rows}</div>` : ""}
    ${found.length > 30 ? `<p class="panel-desc">…ve ${fmt(found.length - 30)} oyun daha.</p>` : ""}
    ${chips ? `<div class="chips">${chips}</div>` : ""}
    <label class="tx-auto"><span class="switch"><input type="checkbox" id="scanAuto" ${sc.on_start ? "checked" : ""}><i></i></span>Açılışta otomatik tara</label>
  </div>`);
  const auto = $("#scanAuto");
  auto.onchange = () => { S.scan.on_start = auto.checked; updateSettings({ scan_on_start: auto.checked }); };
  $("#libraryDot").classList.toggle("hidden", !found.length && !S.projects.some((p) => p.status === "translating"));
}

/* ── Çeviri editörü ────────────────────────────────────────────────── */
async function loadEditor(reset) {
  const box = $("#editorBody");
  const active = activeProject();
  $("#editorTitle").textContent = active ? active.title : "Çevirileri düzenle";
  $("#qualityBtn").classList.toggle("hidden", !active);
  if (!active) { box.innerHTML = `<div class="empty">Editörü kullanmak için önce kütüphaneden bir proje aç.</div>`; return; }
  const sources = (await call("editor_sources")) || [];
  const reviewTotal = sources.reduce((a, s) => a + s.review, 0);
  $("#reviewCount").textContent = reviewTotal;
  $("#reviewCount").classList.toggle("hidden", !reviewTotal);
  if (!sources.length) { box.innerHTML = `<div class="empty">Bu proje için henüz çeviri yok. Stüdyo'dan çeviriyi başlat.</div>`; return; }
  const ed = S.editor && S.editor.path === active.path ? S.editor : { path: active.path, model: null, query: "", onlyReview: false, dirty: {} };
  if (!ed.model || !sources.some((s) => s.model === ed.model)) ed.model = (sources.find((s) => s.model === S.settings.model) || sources[0]).model;
  ed.sources = sources;
  S.editor = ed;
  if (reset) { ed.items = []; ed.offset = 0; }
  const res = await call("editor_load", ed.model, ed.query, ed.onlyReview, ed.offset, 80);
  if (!res) return;
  ed.total = res.total;
  ed.items = reset ? res.items : ed.items.concat(res.items);
  renderEditor();
}

function renderEditor() {
  const ed = S.editor;
  const dirtyCount = Object.keys(ed.dirty).length;
  const rows = ed.items.map((it, i) => {
    const value = it.src in ed.dirty ? ed.dirty[it.src] : it.tr;
    return `<div class="trow ${it.flag ? "flag" : ""} ${it.src in ed.dirty ? "dirty" : ""}">
      <div class="cell-src selectable">${highlightTags(it.src)}</div>
      <div class="cell-tr"><textarea rows="1" data-edit="${i}" spellcheck="false">${esc(value)}</textarea></div>
      <div class="cell-act">${it.flag ? `<span title="İncelenmeli" style="color:var(--warn)">${icon("alert")}</span>` : ""}</div></div>`;
  }).join("");
  $("#editorBody").innerHTML = `
    <div class="toolbar">
      <select class="input" id="edModel">${ed.sources.map((s) => `<option value="${s.model}" ${s.model === ed.model ? "selected" : ""}>${esc(s.label)} · ${fmt(s.count)} satır</option>`).join("")}</select>
      <input class="input grow" id="edSearch" placeholder="Kaynak veya çeviride ara" value="${esc(ed.query)}" spellcheck="false">
      <button class="filter ${ed.onlyReview ? "on" : ""}" id="edReview">Sadece incelenecekler</button>
      <span class="status-msg">${fmt(ed.total)} satır</span>
    </div>
    <div class="row-actions">
      <button class="btn lime" id="edSave" ${dirtyCount ? "" : "disabled"}>${icon("check")}Kaydet${dirtyCount ? ` (${dirtyCount})` : ""}</button>
      <button class="btn" id="edApply" ${S.busy ? "disabled" : ""}>${icon("play")}Oyuna uygula</button>
    </div>
    <div class="table"><div class="trow head"><div>Kaynak</div><div>Çeviri</div><div></div></div>${rows || `<div class="empty" style="margin:16px;border:0">Eşleşen satır yok.</div>`}</div>
    ${ed.items.length < ed.total ? `<div class="more"><button class="btn" id="edMore">Daha fazla yükle (${fmt(ed.total - ed.items.length)} kaldı)</button></div>` : ""}`;
  $$("#editorBody textarea").forEach(autoGrow);
}

function autoGrow(el) { el.style.height = "auto"; el.style.height = `${el.scrollHeight}px`; }

/* ── Sözlük ────────────────────────────────────────────────────────── */
async function loadGlossary() {
  const g = S.glossary;
  const active = activeProject();
  if (g.kind === "project" && !active) g.kind = "general";
  const kinds = active ? [["project", `Bu oyun · ${active.title}`], ...GLOSSARY_KINDS] : GLOSSARY_KINDS;
  $("#glossaryTabs").innerHTML = kinds.map(([id, label]) => `<button class="filter ${g.kind === id ? "on" : ""}" data-gkind="${id}">${esc(label)}</button>`).join("");
  const panel = $("#glossaryProject");
  if (g.kind === "project") {
    const data = (await call("project_glossary_load")) || { rows: [], address: "sen", notes: "" };
    g.rows = data.rows;
    g.address = data.address;
    const scannable = ["renpy", "rpgmaker"].includes(data.engine);
    panel.classList.remove("hidden");
    panel.innerHTML = `
      <div class="panel-head"><div><div class="panel-title">Oyuna özel bağlam</div>
        <p class="panel-desc">Bu bilgiler Gemini, OpenAI ve Claude'a talimat olarak gönderilir; terimler tüm motorlarda tam eşleşmede kullanılır.</p></div>
        <button class="btn" id="gScan" ${scannable ? "" : "disabled title='Bu motor için desteklenmiyor'"}>${icon("scan")}Karakterleri tara</button></div>
      <div class="form-grid">
        <div><div class="field-label">Hitap</div>
          <div class="seg" id="gAddress"><button data-addr="sen" class="${data.address !== "siz" ? "on" : ""}">Sen (samimi)</button><button data-addr="siz" class="${data.address === "siz" ? "on" : ""}">Siz (resmi)</button></div></div>
        <div class="full"><div class="field-label">Oyun hakkında notlar</div>
          <textarea class="input" id="gNotes" rows="3" placeholder="Ör. Ortaçağ fantastik dünya. Elena kraliçe, Marcus onun ağabeyi. Küfürler yumuşatılmasın.">${esc(data.notes)}</textarea></div>
        ${data.engine === "unreal" ? `<div class="full"><div class="field-label">AES anahtarı <span style="color:var(--muted);font-weight:400">· yalnızca paketleri şifreli Unreal oyunları için</span></div>
          <input class="input" style="font-family:var(--mono)" id="gAes" value="${esc(data.aes_key || "")}" placeholder="0x… (64 hane onaltılık veya base64)" spellcheck="false"></div>` : ""}
      </div>`;
  } else {
    panel.classList.add("hidden");
    g.rows = (await call("glossary_load", g.kind)) || [];
  }
  renderGlossary();
}

function renderGlossary() {
  const g = S.glossary;
  const q = g.filter.toLocaleLowerCase("tr-TR");
  const rows = g.rows.map((r, i) => [r, i]).filter(([r]) => !q || r.join(" ").toLocaleLowerCase("tr-TR").includes(q));
  $("#glossaryTable").innerHTML = `<div class="trow head"><div>Kaynak terim</div><div>Karşılığı</div><div></div></div>` +
    rows.map(([r, i]) => `<div class="trow"><div class="cell-src"><input data-g="${i}" data-c="0" value="${esc(r[0])}" spellcheck="false"></div>
      <div class="cell-tr"><input data-g="${i}" data-c="1" value="${esc(r[1])}" spellcheck="false"></div>
      <div class="cell-act"><button data-gdel="${i}" title="Sil">${icon("trash")}</button></div></div>`).join("");
}

/* ── Yedekler ──────────────────────────────────────────────────────── */
async function loadBackups() {
  renderBackups(activeProject() ? await call("list_backups") : null);
}

function renderBackups(list) {
  const active = activeProject();
  $("#backupsSub").textContent = active
    ? `${active.title} için alınan yedekler. Geri yükleme, dosyaları orijinal hâline döndürür.`
    : "Etkin projenin çeviri öncesi alınan yedekleri burada listelenir.";
  const box = $("#backupList");
  if (!active) { box.innerHTML = `<div class="empty">Yedekleri görmek için önce kütüphaneden bir proje aç.</div>`; return; }
  if (!list || !list.length) { box.innerHTML = `<div class="empty">Bu proje için henüz yedek yok. Çeviri başlatıldığında otomatik alınır.</div>`; return; }
  const oldest = list.length - 1 - [...list].reverse().findIndex((b) => !b.archive);
  box.innerHTML = list.map((b, i) => b.archive ? `
    <div class="list-row">
      <div class="list-icon">${icon("shield")}</div>
      <div class="grow"><div class="title">Şifreli arşiv · ${esc(b.archive)} <span class="pill">Açıldı</span></div>
        <div class="sub">${esc(b.date)} · ${fmt(b.files)} dosya çıkarıldı · orijinal arşiv ${(b.size / 1048576).toFixed(1)} MB</div></div>
      <button class="btn" data-action="open-path" data-path="${esc(b.path)}">${icon("folder")}Göster</button>
      <button class="btn" data-action="restore-archive" ${S.busy ? "disabled" : ""}>${icon("undo")}Arşivi geri koy</button>
    </div>` : `
    <div class="list-row">
      <div class="list-icon">${icon("archive")}</div>
      <div class="grow"><div class="title">${esc(b.date)}${i === oldest ? ' <span class="pill lime">En eski · orijinal</span>' : ""}</div>
        <div class="sub">${esc(b.engine)} · ${fmt(b.files)} dosya · ${(b.size / 1048576).toFixed(2)} MB</div></div>
      <button class="btn" data-action="open-path" data-path="${esc(b.path)}">${icon("folder")}Göster</button>
      <button class="btn lime" data-action="restore" data-path="${esc(b.path)}" ${S.busy ? "disabled" : ""}>${icon("undo")}Geri yükle</button>
    </div>`).join("");
}

/* ── Sağlayıcılar ──────────────────────────────────────────────────── */
function providerValue(field) {
  const v = S.providers[field];
  return Array.isArray(v) ? v.join("\n") : (v || "");
}

function renderProviders() {
  if (!S.state) return;
  $("#providerGrid").innerHTML = PROVIDERS.map((p) => {
    const [st, tone] = providerStatus(p.id);
    return `<button class="prov ${S.provSel === p.id ? "sel" : ""}" data-prov="${p.id}">
      ${S.settings.model === p.id ? '<span class="prov-star">Varsayılan</span>' : ""}
      <div class="prov-icon">${p.short}</div><div class="prov-name">${esc(p.title)}</div>
      <div class="prov-tag">${esc(p.tag)}</div><span class="pill ${tone}">${esc(st)}</span></button>`;
  }).join("");
  const p = PROVIDERS.find((x) => x.id === S.provSel) || PROVIDERS[0];
  const isDefault = S.settings.model === p.id;
  const fields = p.fields.map(([name, label, type, span]) => `<div class="${span}"><div class="field-label">${label}</div>
    ${type === "textarea" ? `<textarea class="input code" data-field="${name}" spellcheck="false">${esc(providerValue(name))}</textarea>`
      : type === "gemini-select" ? geminiSelect(name)
      : `<input class="input" data-field="${name}" type="${type}" value="${esc(providerValue(name))}" spellcheck="false">`}</div>`).join("");
  let extra = "";
  if (!p.fields.length) {
    const m = S.models[p.id] || {};
    extra = `<div class="row-actions"><span class="pill ${m.is_ready ? "ok" : "warn"}">${m.is_ready ? `Kurulu · ${fmt(m.size_mb)} MB` : "Model dosyaları eksik"}</span>
      <button class="btn sm" data-page="models">${icon("cpu")}Yerel modeller</button></div>`;
  }
  $("#providerDetail").innerHTML = `
    <div class="panel-head"><div><div class="panel-title">${esc(p.title)}</div><p class="panel-desc">${esc(p.desc)}</p></div></div>
    ${fields ? `<div class="form-grid">${fields}</div>` : ""}${extra}
    <div class="row-actions">
      ${p.fields.length ? `<button class="btn" data-action="save-provider">${icon("check")}Kaydet</button>` : ""}
      <button class="btn" data-action="test-provider">${icon("zap")}${p.fields.length ? "Bağlantıyı test et" : "Durumu kontrol et"}</button>
      <button class="btn ${isDefault ? "" : "lime"}" data-action="default-provider" ${isDefault ? "disabled" : ""}>${icon("check")}${isDefault ? "Varsayılan motor" : "Varsayılan yap"}</button>
      <span class="status-msg" id="provStatus"></span>
    </div>`;
}

function geminiSelect(name) {
  const current = providerValue(name) || "auto";
  const models = S.geminiModels || [];
  const list = models.includes(current) || current === "auto" ? models : [current, ...models];
  if (!S.geminiModels && !S.geminiLoading) {
    S.geminiLoading = true;
    call("gemini_models").then((m) => { S.geminiModels = m || []; S.geminiLoading = false; if (S.provSel === "gemini") renderProviders(); });
  }
  return `<select class="input" data-field="${name}">
    <option value="auto" ${current === "auto" ? "selected" : ""}>Otomatik — tüm modelleri hız sırasıyla dene (önerilen)</option>
    ${list.map((m) => `<option value="${esc(m)}" ${m === current ? "selected" : ""}>Önce ${esc(m)}, sonra diğerleri</option>`).join("")}
  </select><div class="field-hint">${models.length ? `${models.length} uygun model bulundu. Seçilen model önce denenir; çalışmazsa diğerlerine geçilir.` : "Modeller yükleniyor…"}</div>`;
}

function collectProviders() {
  const data = {};
  $$("#providerDetail [data-field]").forEach((el) => { data[el.dataset.field] = el.value; });
  return data;
}

async function saveProviders(active) {
  const data = collectProviders();
  if (active) data.active = active;
  const res = await call("save_providers", data);
  if (!res) return;
  for (const [k, v] of Object.entries(data)) {
    if (k === "gemini_keys") S.providers[k] = v.split("\n").map((x) => x.trim()).filter(Boolean);
    else if (k !== "active") S.providers[k] = v;
  }
  S.settings = res.settings;
  syncSettingsUi(); renderProviders(); renderEngineCard(); renderHero();
  toast({ title: active ? `${S.state.model_labels[active]} varsayılan motor yapıldı` : "Sağlayıcı ayarları kaydedildi", tone: "ok" });
}

async function testProvider() {
  const p = PROVIDERS.find((x) => x.id === S.provSel) || PROVIDERS[0];
  const field = $(`#providerDetail [data-field="${p.test}"]`);
  const value = field ? field.value.split("\n")[0].trim() : "";
  const status = $("#provStatus");
  status.className = "status-msg";
  status.textContent = "Kontrol ediliyor…";
  const res = await call("test_provider", p.id, value);
  if (!res) return;
  status.className = `status-msg ${res.ok ? "ok" : "error"}`;
  status.textContent = res.msg;
}

/* ── Yerel modeller ────────────────────────────────────────────────── */
function renderModels() {
  const info = {
    opus: ["OPUS-MT · İngilizce → Türkçe", "Helsinki-NLP opus-mt-tc-big-en-tr. ~450 MB, hızlı ve hafif."],
    nllb: ["NLLB-200 · 600M · çok dilli", "facebook/nllb-200-distilled-600M. 200 dil; Türkçe dışı hedeflere de çevirir."],
  };
  const rt = S.models.runtime || { ready: true };
  $("#runtimePanel").classList.toggle("hidden", !!rt.ready);
  if (!rt.ready) $("#runtimePanel").innerHTML = `
    <div class="panel-head"><div><div class="panel-title">Yerel model ortamı kurulu değil</div>
      <p class="panel-desc">OPUS-MT ve NLLB, PyTorch + Transformers ile çalışır. Capri ekran kartına uygun resmi PyTorch sürümünü
        seçip indirir ve kendi klasörüne kurar (NVIDIA kartta ≈2,9 GB, kartsız ≈260 MB). Bulut motorları ve ekran çevirisi bu ortam olmadan da çalışır.</p></div>
      <span class="pill warn">Eksik: ${esc((rt.missing || []).slice(0, 3).join(", "))}${(rt.missing || []).length > 3 ? "…" : ""}</span></div>
    <div class="row-actions"><button class="btn lime" data-action="install-runtime" ${S.busy ? "disabled" : ""}>${icon("download")}Ortamı kur</button>
      <span class="status-msg">Model indirirken de otomatik önerilir.</span></div>`;
  const links = { opus: "https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-en-tr", nllb: "https://huggingface.co/facebook/nllb-200-distilled-600M" };
  $("#modelPanels").innerHTML = ["opus", "nllb"].map((k) => {
    const m = S.models[k] || {};
    const pct = m.expected_mb ? Math.min(100, (m.size_mb / m.expected_mb) * 100) : 0;
    return `<div class="panel">
      <div class="panel-head"><div><div class="panel-title">${info[k][0]}</div><p class="panel-desc">${info[k][1]}</p></div>
        <div class="chips" style="margin:0">${m.compact ? '<span class="pill lime">fp16 · küçültülmüş</span>' : ""}<span class="pill ${m.is_ready ? "ok" : "warn"}">${m.is_ready ? "Hazır" : "Eksik"}</span></div></div>
      <div class="model-meter"><div class="bar"><i style="width:${pct}%"></i></div>
        <div class="line"><span>${fmt(m.present_count)}/${fmt(m.total_files)} dosya</span><span class="num">${fmt(m.size_mb)} / ${fmt(m.expected_mb)} MB</span></div></div>
      <div class="path selectable">${esc(m.dir || "")}</div>
      <div class="row-actions">
        <button class="btn ${m.is_ready ? "" : "lime"}" data-action="download-model" data-id="${k}" ${S.busy ? "disabled" : ""}>${icon("download")}${m.is_ready ? "Doğrula" : "İndir"}</button>
        ${m.is_ready && !m.compact ? `<button class="btn" data-action="compact-model" data-id="${k}" ${S.busy ? "disabled" : ""}>${icon("zap")}Küçült (fp16)</button>` : ""}
        <button class="btn" data-action="open-path" data-path="${esc(m.dir || "")}">${icon("folder")}Klasörü aç</button>
        <button class="btn" data-action="open-url" data-path="${links[k]}">${icon("globe")}Model sayfası</button>
      </div></div>`;
  }).join("");
}

/* ── Metin çevirici ────────────────────────────────────────────────── */
const TX_HISTORY_KEY = "omnitrans.tx.history";
let txTimer = null, txSeq = 0;

function renderSamples() {
  $("#samples").innerHTML = SAMPLES.map(([label], i) => `<button class="chip" data-sample="${i}">${esc(label)}</button>`).join("");
}

function txHistory() {
  try { return JSON.parse(localStorage.getItem(TX_HISTORY_KEY) || "[]"); } catch { return []; }
}

function renderTranslator() {
  const st = S.state;
  const opt = (list, val) => list.map((l) => `<option value="${esc(l.code)}" ${l.code === val ? "selected" : ""}>${esc(l.label)}</option>`).join("");
  $("#txSource").innerHTML = opt(st.source_languages, S.settings.source);
  $("#txTarget").innerHTML = opt(st.target_languages, S.settings.target);
  $("#txModel").innerHTML = Object.entries(st.model_labels).map(([id, label]) => `<option value="${id}" ${id === S.settings.model ? "selected" : ""}>${esc(label)}</option>`).join("");
  renderTxHistory();
}

function renderTxHistory() {
  const items = txHistory();
  $("#txHistory").innerHTML = items.length ? items.map((h, i) => `<button class="tx-item" data-tx-history="${i}">
      <span>${esc(h.src)}</span><span>${esc(h.tr)}</span><small>${esc(h.model)}</small></button>`).join("")
    : `<div class="empty" style="margin-top:0;padding:22px">Henüz çeviri yok.</div>`;
}

async function runTranslate(force) {
  const text = $("#txInput").value;
  $("#txCount").textContent = `${fmt(text.length)} karakter`;
  if (!text.trim()) { $("#txOutput").innerHTML = '<span class="tx-placeholder">Çeviri burada görünecek.</span>'; $("#txMeta").textContent = ""; return; }
  const seq = ++txSeq;
  $("#txMeta").className = "status-msg num";
  $("#txMeta").textContent = "Çevriliyor…";
  $("#txGo").disabled = true;
  const res = await call("translate_text", text, $("#txSource").value, $("#txTarget").value, $("#txModel").value);
  $("#txGo").disabled = false;
  if (!res || seq !== txSeq) return;
  $("#txOutput").textContent = res.text;
  $("#txMeta").className = `status-msg num ${res.ok ? "" : "error"}`;
  $("#txMeta").textContent = res.ok ? `${res.model} · ${fmt(res.latency)} ms` : "Çeviri başarısız";
  if (res.ok && (force || text.length > 2)) {
    const items = txHistory().filter((h) => h.src !== text);
    items.unshift({ src: text, tr: res.text, model: res.model });
    try { localStorage.setItem(TX_HISTORY_KEY, JSON.stringify(items.slice(0, 20))); } catch { /* depolama kapalı olabilir */ }
    renderTxHistory();
  }
}

/* ── GPU hızlandırma ───────────────────────────────────────────────── */
function renderGpu() {
  const g = S.gpuOpt;
  const cuda = S.gpu && S.gpu.cuda;
  const chip = !cuda ? `<span class="pill warn">${S.gpu && S.gpu.runtime === false ? "Yerel ortam gerekli" : "CUDA yok"}</span>`
    : S.gpuBusy ? '<span class="pill warn">Hazırlanıyor…</span>'
    : g && g.ok ? '<span class="pill ok">Hazır · optimize edildi</span>' : '<span class="pill">Optimize edilmedi</span>';
  const metric = (v, l) => `<div class="gpu-metric"><b>${v}</b><span>${l}</span></div>`;
  const metrics = g && g.ok ? `<div class="gpu-metrics">
      ${metric(`${g.vram_free} / ${g.vram_total} GB`, "Boş / toplam VRAM")}
      ${metric(`${g.tflops} TFLOPS`, "FP16 matris hızı")}
      ${metric(`${fmt(g.init_ms)} ms`, "CUDA başlatma (bir kez)")}
      ${metric(g.preload ? `${esc(g.preload.replace(" (çevrimdışı)", ""))}` : "—", g.preload ? `VRAM'de hazır · ${fmt(g.preload_ms)} ms` : "Ön yüklenen model")}
    </div>` : "";
  $("#gpuPanel").innerHTML = `
    <div class="panel-head"><div><div class="panel-title">GPU hızlandırma (CUDA)</div>
      <p class="panel-desc">${esc(S.gpu ? `${S.gpu.name}${S.gpu.detail ? " · " + S.gpu.detail : ""}` : "")}</p></div>${chip}</div>
    ${metrics}
    <div class="why"><b>Bu ayar neden var?</b> Ekran kartı ilk kez kullanıldığında sürücü bağlamı ve cuBLAS çekirdekleri hazırlanır;
      bu, ilk çeviride 1-3 saniyelik bir donma yaratır. Optimizasyon bunu önceden yapar, RTX kartlarda <b>TF32</b> hızlandırmayı açar,
      kullanılmayan VRAM'i boşaltarak “bellek yetmedi” hatalarını azaltır ve seçili yerel modeli (OPUS/NLLB) VRAM'e yükler.
      Böylece OPUS/NLLB çevirileri, canlı önizleme ve ekran çevirisi ilk tıklamadan itibaren anında yanıt verir.
      Gemini gibi bulut motorları GPU kullanmaz; bu ayar yalnızca yerel modelleri hızlandırır.</div>
    <div class="row-actions">
      <button class="btn lime" data-action="gpu-optimize" ${!cuda || S.gpuBusy ? "disabled" : ""}>${icon("zap")}Şimdi optimize et</button>
      <label class="tx-auto"><span class="switch"><input type="checkbox" id="gpuAuto" ${S.settings.gpu_auto ? "checked" : ""}><i></i></span>Yerel motor seçiliyse açılışta hazırla</label>
    </div>`;
}

/* ── Ekran çevirisi ────────────────────────────────────────────────── */
const prettyKey = (k) => String(k || "").split("+").map((x) => x.trim()).join(" + ");

function renderOcr() {
  if (!S.state) return;
  const o = S.ocr || {};
  $("#hkOnce").value = prettyKey(S.settings.ocr_hotkey);
  $("#hkPin").value = prettyKey(S.settings.pin_hotkey);
  $("#hkOnceView").textContent = prettyKey(S.settings.ocr_hotkey);
  $("#hkPinView").textContent = prettyKey(S.settings.pin_hotkey);
  const sel = S.settings.ocr_model || "";
  const mainLabel = S.state.model_labels[S.settings.model];
  $("#ocrModel").innerHTML = `<option value="" ${!sel ? "selected" : ""}>Ana motorla aynı (${esc(mainLabel)})</option>` +
    Object.entries(S.state.model_labels).map(([id, label]) => `<option value="${id}" ${id === sel ? "selected" : ""}>${esc(label)}</option>`).join("");
  $("#ocrInterval").value = S.settings.ocr_interval || 350;
  $("#ocrIntervalVal").textContent = `${S.settings.ocr_interval || 350} ms`;
  $$("#ocrPlace button").forEach((b) => b.classList.toggle("on", b.dataset.place === (S.settings.ocr_place || "below")));
  $("#ocrState").className = `pill ${o.available ? "ok" : "warn"}`;
  $("#ocrState").textContent = o.available ? (o.pin_active ? "Canlı çeviri açık" : "Hazır") : "Kullanılamıyor";
  const hk = o.hotkeys || {};
  const hkPill = (name) => hk[name] === undefined ? '<span class="pill">Bekleniyor</span>'
    : hk[name] ? '<span class="pill ok">Kayıtlı</span>' : '<span class="pill warn">Başka uygulamada kullanılıyor</span>';
  $("#ocrRows").innerHTML = `
    <div class="engine-row"><span>OCR motoru</span><span>${o.available ? `Windows OCR · ${esc(o.languages)}` : esc(o.error || "—")}</span></div>
    <div class="engine-row"><span>${esc(prettyKey(S.settings.ocr_hotkey))}</span><span>${hkPill("ocr")}</span></div>
    <div class="engine-row"><span>${esc(prettyKey(S.settings.pin_hotkey))}</span><span>${hkPill("pin")}</span></div>`;
  const pinBtn = $("#ocrPinBtn");
  pinBtn.dataset.action = o.pin_active ? "ocr-unpin" : "ocr-pin";
  pinBtn.innerHTML = o.pin_active ? `${icon("x")}Sabitlemeyi kaldır` : `${icon("pin")}Alan seç`;
}

function comboFromEvent(e) {
  const key = e.key.length === 1 ? e.key.toUpperCase() : e.key;
  if (["Control", "Shift", "Alt", "Meta"].includes(key)) return null;
  const valid = /^[A-Z0-9]$/.test(key) || /^F([1-9]|1[0-9]|2[0-4])$/.test(key);
  if (!valid) return null;
  const mods = [e.ctrlKey && "Ctrl", e.altKey && "Alt", e.shiftKey && "Shift"].filter(Boolean);
  if (!mods.length && !key.startsWith("F")) return null;
  return [...mods, key].join("+");
}

/* ── Bildirim merkezi ──────────────────────────────────────────────── */
const NOTIF_ICON = { ok: "check", warn: "alert", error: "alert", info: "bell" };
const drawerOpen = () => $("#drawer").classList.contains("open");

function relTime(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 45) return "az önce";
  if (s < 3600) return `${Math.round(s / 60)} dk önce`;
  if (s < 86400) return `${Math.round(s / 3600)} sa önce`;
  return new Date(ts * 1000).toLocaleDateString("tr-TR", { day: "numeric", month: "short" });
}

function addNotif(n) {
  n.unread = !(drawerOpen() && S.drawerTab === "notifs");
  S.notifs.unshift(n);
  if (S.notifs.length > 200) S.notifs.length = 200;
  if (n.unread) { S.unread += 1; renderBell(); toast(n); }
  else renderDrawer();
}

function renderBell() {
  const badge = $("#bellBadge");
  badge.classList.toggle("hidden", !S.unread);
  badge.textContent = S.unread > 99 ? "99+" : S.unread;
}

function renderDrawer() {
  const tools = $("#drawerTools"), body = $("#drawerBody");
  $$("#drawerTabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === S.drawerTab));
  if (S.drawerTab === "notifs") {
    tools.innerHTML = `<span>${S.notifs.length ? `${S.notifs.length} bildirim` : ""}</span>${S.notifs.length ? '<button data-action="clear-notifs">Temizle</button>' : ""}`;
    body.innerHTML = S.notifs.length ? S.notifs.map((n) => `
      <div class="notif ${n.tone} ${n.unread ? "unread" : ""}">
        <div class="notif-icon">${icon(n.icon && n.icon !== "bell" ? n.icon : NOTIF_ICON[n.tone] || "bell")}</div>
        <div class="notif-main">
          <div class="notif-title"><span>${esc(n.title)}</span><time>${relTime(n.time)}</time></div>
          ${n.text ? `<div class="notif-text">${esc(n.text)}</div>` : ""}
          ${n.action ? `<div class="notif-action"><button class="btn sm" data-notif-action='${esc(JSON.stringify(n.action))}'>${esc(n.action.label)}</button></div>` : ""}
        </div></div>`).join("")
      : `<div class="notif-empty">${icon("bell")}<div>Henüz bildirim yok.</div><div style="font-size:12.5px;margin-top:4px">Analiz, çeviri ve yedek işlemleri burada özetlenir.</div></div>`;
    if (drawerOpen()) { S.notifs.forEach((n) => { n.unread = false; }); S.unread = 0; renderBell(); }
  } else {
    tools.innerHTML = `<span>Ayrıntılı işlem kaydı</span><span><button data-action="copy-log">Kopyala</button><button data-action="clear-log">Temizle</button></span>`;
    body.innerHTML = `<div class="console selectable" id="logBox"></div>`;
    const frag = document.createDocumentFragment();
    S.log.slice(-1500).forEach((e) => frag.appendChild(lineNode(e)));
    $("#logBox").appendChild(frag);
    body.scrollTop = body.scrollHeight;
  }
}

function toggleDrawer(open, tab) {
  const next = open ?? !drawerOpen();
  if (tab) S.drawerTab = tab;
  $("#drawer").classList.toggle("open", next);
  if (next) { renderDrawer(); $("#toasts").replaceChildren(); }
}

function logClass(line) {
  if (/✔|tamamlandı|başarı/i.test(line)) return "ok";
  if (/❌|hata|traceback|error/i.test(line)) return "err";
  if (/⚠|uyarı|warn/i.test(line)) return "warn";
  return "";
}

function lineNode(entry) {
  const div = document.createElement("div");
  const cls = logClass(entry.text);
  if (cls) div.className = cls;
  div.innerHTML = `<span class="t">${entry.time}</span>${esc(entry.text)}`;
  return div;
}

function appendLog(lines) {
  const time = new Date().toLocaleTimeString("tr-TR");
  const entries = lines.map((text) => ({ time, text }));
  S.log.push(...entries);
  if (S.log.length > 4000) S.log.splice(0, S.log.length - 4000);
  if (lines.length) S.lastLog = lines[lines.length - 1];
  const box = drawerOpen() && S.drawerTab === "log" ? $("#logBox") : null;
  if (box) {
    const body = $("#drawerBody");
    const stick = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
    const frag = document.createDocumentFragment();
    entries.forEach((e) => frag.appendChild(lineNode(e)));
    box.appendChild(frag);
    while (box.childElementCount > 1500) box.firstElementChild.remove();
    if (stick) body.scrollTop = body.scrollHeight;
  }
}

/* ── Kısa bildirim & onay ──────────────────────────────────────────── */
function toast({ title, text = "", tone = "info", icon: ic }) {
  const el = document.createElement("div");
  el.className = `toast ${tone}`;
  el.innerHTML = `<div class="notif-icon">${icon(ic && ic !== "bell" ? ic : NOTIF_ICON[tone] || "bell")}</div><div><b>${esc(title)}</b>${text ? `<span>${esc(text)}</span>` : ""}</div>`;
  el.addEventListener("click", () => { el.remove(); toggleDrawer(true, "notifs"); });
  $("#toasts").appendChild(el);
  while ($("#toasts").childElementCount > 3) $("#toasts").firstElementChild.remove();
  const ttl = tone === "error" ? 7000 : 4500;
  setTimeout(() => { el.style.transition = "opacity .3s"; el.style.opacity = "0"; }, ttl);
  setTimeout(() => el.remove(), ttl + 350);
}

/* ── Güncelleme penceresi ─────────────────────────────────────────── */
function openUpdate(recheck) {
  if (!$("#updateModal")) {
    const wrap = document.createElement("div");
    wrap.className = "modal-wrap";
    wrap.id = "updateModal";
    wrap.innerHTML = `<div class="modal update-modal"><div class="upd-head"><span class="brand-mark">${icon("logo")}</span>
      <div><h3>Güncellemeler</h3><div class="upd-current" id="updCurrent"></div></div></div>
      <div id="updBody"></div>
      <div class="row-actions"><label class="tx-auto"><span class="switch"><input type="checkbox" id="updAuto"><i></i></span>Açılışta kontrol et</label>
        <span class="grow"></span><span id="updActions"></span></div></div>`;
    wrap.addEventListener("click", (ev) => {
      if (ev.target === wrap || ev.target.closest("[data-upd='close']")) { if (!S.updateProgress) wrap.remove(); return; }
      if (ev.target.closest("[data-upd='install']")) { S.updateProgress = { done: 0, total: (S.update || {}).asset_size || 0 }; renderUpdate(); call("apply_update"); }
      if (ev.target.closest("[data-upd='page']")) call("open_url", S.update.url);
      if (ev.target.closest("[data-upd='retry']")) checkUpdate();
    });
    $("#updAuto", wrap).addEventListener("change", (e) => updateSettings({ update_check: e.target.checked }));
    document.body.appendChild(wrap);
    $("#updAuto").checked = S.settings.update_check !== false;
  }
  if (recheck || !S.update) checkUpdate(); else renderUpdate();
}

async function checkUpdate() {
  S.update = { checking: true };
  renderUpdate();
  const info = await call("check_update", true);
  if (info) HANDLERS.update(info);
}

function renderUpdate() {
  if (!$("#updateModal")) return;
  const u = S.update || {}, p = S.updateProgress;
  const mb = (n) => (n / 1048576).toFixed(1).replace(".", ",");
  $("#updCurrent").textContent = `Kullandığın sürüm: ${S.state ? S.state.version : ""}`;
  let body = "", actions = `<button class="btn" data-upd="close">Kapat</button>`;
  if (p) {
    const pct = p.total ? Math.min(100, (p.done / p.total) * 100) : 0;
    body = p.installing
      ? `<div class="upd-state"><span class="spinner"></span><div><b>Kuruluyor…</b><p>Capri birkaç saniye içinde ${esc(u.latest || "yeni")} sürümüyle yeniden açılacak. Ayarların ve çevirilerin korunur.</p></div></div>`
      : `<div class="upd-state"><div class="grow"><b>Capri ${esc(u.latest || "")} indiriliyor</b>
          <div class="bar upd-bar"><i style="width:${pct}%"></i></div><p class="num">${mb(p.done)} / ${p.total ? mb(p.total) : "?"} MB</p></div></div>`;
    actions = "";
  } else if (u.checking) {
    body = `<div class="upd-state"><span class="spinner"></span><div><b>Kontrol ediliyor…</b></div></div>`;
  } else if (u.error) {
    body = `<div class="upd-state warn">${icon("alert")}<div><b>Kontrol edilemedi</b><p>${esc(u.error)}</p></div></div>`;
    actions = `<button class="btn" data-upd="retry">Tekrar dene</button>` + actions;
  } else if (u.available) {
    body = `<div class="upd-state ok">${icon("sparkle")}<div><b>Yeni sürüm: ${esc(u.latest)}</b><p>${u.published ? esc(u.published) + " · " : ""}${u.asset_size ? mb(u.asset_size) + " MB" : ""}</p></div></div>
      ${(u.notes || []).length ? `<div class="upd-news"><div class="upd-news-title">Yeni sürümde</div><ul>${u.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>` : ""}`;
    actions = u.can_apply ? `<button class="btn" data-upd="close">Sonra</button><button class="btn lime" data-upd="install">${icon("download")}İndir ve kur</button>`
      : `<button class="btn" data-upd="close">Kapat</button><button class="btn lime" data-upd="page">${icon("globe")}Sürüm sayfası</button>`;
  } else if (u.latest) {
    body = `<div class="upd-state ok">${icon("check")}<div><b>Capri güncel</b><p>En son sürümü kullanıyorsun.</p></div></div>`;
  }
  const news = (S.state && S.state.whats_new) || [];
  if (!p && !u.available && news.length) {
    body += `<div class="upd-news"><div class="upd-news-title">Bu sürümde</div><ul>${news.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>`;
  }
  $("#updBody").innerHTML = body;
  $("#updActions").innerHTML = actions;
}

function openConfirm({ id, title, text }) {
  const wrap = document.createElement("div");
  wrap.className = "modal-wrap";
  wrap.innerHTML = `<div class="modal"><h3>${esc(title)}</h3><p>${esc(text)}</p>
    <div class="row-actions"><button class="btn" data-answer="0">Vazgeç</button><button class="btn lime" data-answer="1">Onayla</button></div></div>`;
  wrap.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-answer]");
    if (!btn) return;
    call("answer_confirm", id, btn.dataset.answer === "1");
    wrap.remove();
  });
  document.body.appendChild(wrap);
  $("[data-answer='1']", wrap).focus();
}

/* ── Olaylar ───────────────────────────────────────────────────────── */
document.addEventListener("click", async (ev) => {
  const el = ev.target.closest("[data-page],[data-action],[data-filter],[data-slide],[data-sample],[data-win],[data-prov],[data-gkind],[data-gdel],[data-notif-action],[data-tab]");
  if (!el) return;
  if (el.dataset.win) { call({ min: "win_minimize", max: "win_maximize", close: "win_close" }[el.dataset.win]); return; }
  if (el.dataset.notifAction) {
    const a = JSON.parse(el.dataset.notifAction);
    if (a.page === "log") { S.drawerTab = "log"; renderDrawer(); return; }
    if (a.update) { toggleDrawer(false); openUpdate(false); return; }
    if (a.url) { call("open_url", a.url); return; }
    toggleDrawer(false);
    if (a.page) showPage(a.page);
    if (a.path) call("open_path", a.path);
    return;
  }
  if (el.dataset.tab) { S.drawerTab = el.dataset.tab; renderDrawer(); return; }
  if (el.dataset.page) { showPage(el.dataset.page); return; }
  if (el.dataset.filter) { S.filter = el.dataset.filter; renderLibraries(); return; }
  if (el.dataset.slide) { S.slide = Number(el.dataset.slide); renderHero(); return; }
  if (el.dataset.sample) { $("#txInput").value = SAMPLES[Number(el.dataset.sample)][1]; runTranslate(true); return; }
  if (el.dataset.prov) { S.provSel = el.dataset.prov; renderProviders(); return; }
  if (el.dataset.gkind) { S.glossary.kind = el.dataset.gkind; loadGlossary(); return; }
  if (el.dataset.gdel) { S.glossary.rows.splice(Number(el.dataset.gdel), 1); renderGlossary(); return; }
  const path = el.dataset.path;
  switch (el.dataset.action) {
    case "pick": pickFolder(); break;
    case "open":
      if (activeProject() && keyOf(activeProject().path) === keyOf(path)) showPage("studio");
      else openProject(path);
      break;
    case "remove":
      ev.stopPropagation();
      await call("remove_project", path);
      S.projects = S.projects.filter((p) => keyOf(p.path) !== keyOf(path));
      buildSlides(); renderHero(); renderLibraries();
      break;
    case "scan-now": call("scan_games", true); break;
    case "play-game": call("play_game"); break;
    case "glossary-export": call("glossary_export", S.glossary.kind, S.glossary.rows); break;
    case "glossary-import": {
      const rows = await call("glossary_import");
      if (!rows) break;
      const map = new Map(S.glossary.rows.map((r) => [r[0], r]));
      for (const [a, b] of rows) map.set(a, [a, b]);
      S.glossary.rows = [...map.values()];
      renderGlossary();
      $("#glossaryStatus").className = "status-msg ok";
      $("#glossaryStatus").textContent = `${fmt(rows.length)} terim eklendi; kaydetmeyi unutma`;
      break;
    }
    case "scan-folder": { const r = await call("scan_pick_folder"); if (r) HANDLERS.scan(r); break; }
    case "scan-remove-folder": { const r = await call("scan_remove_folder", path); if (r) HANDLERS.scan(r); break; }
    case "scan-dismiss": { const r = await call("scan_dismiss", path); if (r) HANDLERS.scan(r); break; }
    case "scan-add": { const p = await call("scan_add", path); if (p) upsertProject(p); break; }
    case "scan-add-all":
      for (const g of [...((S.scan && S.scan.found) || [])]) { const p = await call("scan_add", g.path); if (p) upsertProject(p); }
      break;
    case "translate": startTranslate(); break;
    case "cancel": S.cancelling = true; renderHero(); call("cancel"); break;
    case "show-log": S.drawerTab = "log"; toggleDrawer(true); renderDrawer(); break;
    case "open-game": { const a = activeProject(); if (a) call("open_path", a.path); break; }
    case "analyze": call("analyze", true); break;
    case "restore": call("restore_backup", path || ""); break;
    case "restore-archive": call("restore_archive"); break;
    case "install-runtime": call("install_runtime"); break;
    case "open-url": call("open_url", path); break;
    case "open-path": call("open_path", path); break;
    case "test-provider": testProvider(); break;
    case "save-provider": saveProviders(); break;
    case "default-provider": saveProviders(S.provSel); break;
    case "download-model": call("download_model", el.dataset.id); break;
    case "compact-model": call("compact_model", el.dataset.id); break;
    case "quality-pass": call("quality_pass"); break;
    case "update-open": openUpdate(true); break;
    case "bepinex-install": call("install_bepinex"); break;
    case "bepinex-uninstall": call("uninstall_bepinex"); break;
    case "export-patch": call("export_patch"); break;
    case "import-patch": if (await call("import_patch")) loadEditor(true); break;
    case "json-file": case "json-folder": {
      const picked = await call("json_pick", el.dataset.action === "json-folder" ? "folder" : "file");
      if (picked) $("#jsonInput").value = picked;
      break;
    }
    case "json-run":
      if (!$("#jsonInput").value.trim()) { toast({ title: "Önce bir dosya veya klasör seç", tone: "warn" }); break; }
      call("json_translate", $("#jsonInput").value.trim(), $("#jsonOutput").value.trim());
      break;
    case "copy-log": navigator.clipboard.writeText(S.log.map((e) => `[${e.time}] ${e.text}`).join("\n")).then(() => toast({ title: "Günlük panoya kopyalandı", tone: "ok" })); break;
    case "clear-log": S.log = []; renderDrawer(); break;
    case "clear-notifs": S.notifs = []; renderDrawer(); break;
    case "gpu-optimize": S.gpuBusy = true; renderGpu(); call("optimize_gpu", true, false); break;
    case "ocr-once": call("ocr_start_ui", "once"); break;
    case "ocr-pin": call("ocr_start_ui", "pin"); break;
    case "ocr-unpin": call("ocr_pin_stop", false); break;
    default: break;
  }
});

/* Editör etkileşimleri */
$("#editorBody").addEventListener("input", (ev) => {
  const t = ev.target;
  if (t.dataset.edit === undefined) return;
  const it = S.editor.items[Number(t.dataset.edit)];
  if (t.value === it.tr) delete S.editor.dirty[it.src]; else S.editor.dirty[it.src] = t.value;
  t.closest(".trow").classList.toggle("dirty", it.src in S.editor.dirty);
  autoGrow(t);
  const n = Object.keys(S.editor.dirty).length;
  const save = $("#edSave");
  save.disabled = !n;
  save.innerHTML = `${icon("check")}Kaydet${n ? ` (${n})` : ""}`;
});
let edSearchTimer = null;
$("#editorBody").addEventListener("keyup", (ev) => {
  if (ev.target.id !== "edSearch") return;
  clearTimeout(edSearchTimer);
  edSearchTimer = setTimeout(async () => {
    S.editor.query = ev.target.value;
    await loadEditor(true);
    const s = $("#edSearch");
    s.focus();
    s.setSelectionRange(s.value.length, s.value.length);
  }, 300);
});
$("#editorBody").addEventListener("change", (ev) => {
  if (ev.target.id === "edModel") { S.editor.model = ev.target.value; S.editor.dirty = {}; loadEditor(true); }
});
$("#editorBody").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button");
  if (!btn || !S.editor) return;
  const ed = S.editor;
  if (btn.id === "edReview") { ed.onlyReview = !ed.onlyReview; loadEditor(true); }
  if (btn.id === "edMore") { ed.offset = ed.items.length; loadEditor(false); }
  if (btn.id === "edSave") {
    const res = await call("editor_save", ed.model, ed.dirty);
    if (!res) return;
    toast({ title: res.msg, tone: res.ok ? "ok" : "error" });
    if (res.ok) { ed.dirty = {}; loadEditor(true); }
  }
  if (btn.id === "edApply") {
    if (Object.keys(ed.dirty).length) { toast({ title: "Önce değişiklikleri kaydet", tone: "warn" }); return; }
    call("editor_apply", ed.model);
  }
});

/* Sözlük etkileşimleri */
$("#glossaryTable").addEventListener("input", (ev) => {
  const t = ev.target;
  if (t.dataset.g !== undefined) S.glossary.rows[Number(t.dataset.g)][Number(t.dataset.c)] = t.value;
});
$("#glossarySearch").addEventListener("input", (ev) => { S.glossary.filter = ev.target.value; renderGlossary(); });
$("#glossaryAdd").addEventListener("click", () => {
  S.glossary.rows.unshift(["", ""]);
  S.glossary.filter = "";
  $("#glossarySearch").value = "";
  renderGlossary();
  $('#glossaryTable [data-g="0"][data-c="0"]').focus();
});
$("#glossaryProject").addEventListener("click", async (e) => {
  const addr = e.target.closest("[data-addr]");
  if (addr) {
    S.glossary.address = addr.dataset.addr;
    $$("#gAddress button").forEach((b) => b.classList.toggle("on", b === addr));
  }
  if (e.target.closest("#gScan")) {
    const res = await call("project_scan_characters");
    if (!res) return;
    toast({ title: res.ok ? `${fmt(res.found)} karakter bulundu, ${fmt(res.added)} yeni eklendi` : res.msg, tone: res.ok ? "ok" : "warn" });
    if (res.ok) loadGlossary();
  }
});
$("#glossarySave").addEventListener("click", async () => {
  const g = S.glossary;
  const res = g.kind === "project"
    ? await call("project_glossary_save", g.rows, g.address || "sen", ($("#gNotes") || {}).value || "", $("#gAes") ? $("#gAes").value : null)
    : await call("glossary_save", g.kind, g.rows);
  if (!res) return;
  $("#glossaryStatus").className = "status-msg ok";
  $("#glossaryStatus").textContent = `${fmt(res.count)} terim kaydedildi`;
  loadGlossary();
});

$("#heroPrev").addEventListener("click", () => moveSlide(-1));
$("#heroNext").addEventListener("click", () => moveSlide(1));
$("#hero").addEventListener("mouseenter", () => { S.heroHover = true; });
$("#hero").addEventListener("mouseleave", () => { S.heroHover = false; });
$("#bellBtn").addEventListener("click", () => toggleDrawer(undefined, "notifs"));
$("#drawerClose").addEventListener("click", () => toggleDrawer(false));
$("#openFolderBtn").addEventListener("click", () => {
  const p = activeProject();
  if (p) call("open_path", p.path); else toast({ title: "Önce bir proje aç", tone: "warn" });
});
$("#refreshBackups").addEventListener("click", loadBackups);
/* Metin çevirici etkileşimleri */
$("#txGo").addEventListener("click", () => runTranslate(true));
$("#txInput").addEventListener("input", () => {
  $("#txCount").textContent = `${fmt($("#txInput").value.length)} karakter`;
  clearTimeout(txTimer);
  if ($("#txAuto").checked) txTimer = setTimeout(() => runTranslate(false), 900);
});
$("#txInput").addEventListener("keydown", (e) => { if (e.ctrlKey && e.key === "Enter") { e.preventDefault(); runTranslate(true); } });
$("#txSwap").addEventListener("click", () => {
  const src = $("#txSource").value, tgt = $("#txTarget").value;
  if (src === "auto" || !$(`#txTarget option[value="${src}"]`)) { toast({ title: "Bu yön değiştirilemez", text: "Kaynak dil “Otomatik” ya da hedef listesinde değil.", tone: "warn" }); return; }
  $("#txSource").value = tgt; $("#txTarget").value = src;
  const out = $("#txOutput").textContent;
  if (out && !$("#txOutput .tx-placeholder")) { $("#txInput").value = out; runTranslate(true); }
});
["#txSource", "#txTarget", "#txModel"].forEach((id) => $(id).addEventListener("change", () => { if ($("#txInput").value.trim()) runTranslate(true); }));
$("#txClear").addEventListener("click", () => { $("#txInput").value = ""; runTranslate(false); $("#txInput").focus(); });
$("#txCopy").addEventListener("click", () => {
  if ($("#txOutput .tx-placeholder")) return;
  navigator.clipboard.writeText($("#txOutput").textContent).then(() => toast({ title: "Çeviri panoya kopyalandı", tone: "ok" }));
});
$("#txHistory").addEventListener("click", (e) => {
  const item = e.target.closest("[data-tx-history]");
  if (!item) return;
  const h = txHistory()[Number(item.dataset.txHistory)];
  $("#txInput").value = h.src; $("#txOutput").textContent = h.tr; $("#txMeta").textContent = h.model;
});
$("#txHistoryClear").addEventListener("click", () => { try { localStorage.removeItem(TX_HISTORY_KEY); } catch { /* yok say */ } renderTxHistory(); });

/* GPU ve ekran çevirisi ayarları */
document.addEventListener("change", (e) => {
  if (e.target.id === "gpuAuto") updateSettings({ gpu_auto: e.target.checked });
  if (e.target.id === "ocrModel") updateSettings({ ocr_model: e.target.value });
});
$("#ocrInterval").addEventListener("input", (e) => { $("#ocrIntervalVal").textContent = `${e.target.value} ms`; });
$("#ocrInterval").addEventListener("change", (e) => updateSettings({ ocr_interval: Number(e.target.value) }));
$("#ocrPlace").addEventListener("click", (e) => { const b = e.target.closest("[data-place]"); if (b) updateSettings({ ocr_place: b.dataset.place }); });
$$(".hk-input").forEach((input) => {
  input.addEventListener("focus", () => { input.classList.add("recording"); input.value = "Tuş kombinasyonuna bas…"; });
  input.addEventListener("blur", () => { input.classList.remove("recording"); renderOcr(); });
  input.addEventListener("keydown", (e) => {
    e.preventDefault();
    if (e.key === "Escape") { input.blur(); return; }
    const combo = comboFromEvent(e);
    if (!combo) return;
    const other = input.id === "hkOnce" ? S.settings.pin_hotkey : S.settings.ocr_hotkey;
    if (combo.toLowerCase() === String(other).toLowerCase()) { toast({ title: "Bu kısayol diğer işlem için kullanılıyor", tone: "warn" }); return; }
    updateSettings({ [input.dataset.setting]: combo });
    input.blur();
    setTimeout(() => call("ocr_status").then((o) => { if (o) { S.ocr = o; renderOcr(); renderEngineCard(); } }), 400);
  });
});
$("#sourceSelect").addEventListener("change", (e) => updateSettings({ source: e.target.value }));
$("#targetSelect").addEventListener("change", (e) => updateSettings({ target: e.target.value }));
$("#modelSelect").addEventListener("change", (e) => updateSettings({ model: e.target.value }));
$("#backupToggle").addEventListener("change", (e) => updateSettings({ backup: e.target.checked }));
$("#nsfwToggle").addEventListener("change", (e) => updateSettings({ nsfw: e.target.checked }));
$("#qualityToggle").addEventListener("change", (e) => updateSettings({ quality_pass: e.target.checked }));
$("#updateBtn").addEventListener("click", () => openUpdate(!(S.update && S.update.available)));

const search = $("#searchInput");
search.addEventListener("input", () => { S.search = search.value; renderLibraries(); });
search.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { const first = filtered()[0]; if (first) openProject(first.path); }
  if (e.key === "Escape") { search.value = ""; S.search = ""; renderLibraries(); search.blur(); }
});
search.addEventListener("focus", () => {
  if (!$("#page-library").classList.contains("active") && !$("#page-studio").classList.contains("active")) showPage("library");
});

document.addEventListener("keydown", (e) => {
  const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
  const k = e.key.toLowerCase();
  if (e.ctrlKey && k === "k") { e.preventDefault(); search.focus(); search.select(); }
  else if (e.ctrlKey && k === "o") { e.preventDefault(); pickFolder(); }
  else if (e.ctrlKey && k === "b") { e.preventDefault(); toggleDrawer(undefined, "notifs"); }
  else if (e.key === "Escape") toggleDrawer(false);
  else if (!typing && $("#page-studio").classList.contains("active") && (e.key === "ArrowLeft" || e.key === "ArrowRight")) moveSlide(e.key === "ArrowLeft" ? -1 : 1);
});
document.addEventListener("dblclick", (e) => { if (e.target.closest(".titlebar") && !e.target.closest("button")) call("win_maximize"); });
setInterval(() => {
  if (drawerOpen() && S.drawerTab === "notifs") $$("#drawerBody time").forEach((t, i) => { if (S.notifs[i]) t.textContent = relTime(S.notifs[i].time); });
}, 30000);

/* Sürükle-bırak: görsel bırakma alanı (yolu Python tarafı WebView2'den alır) */
let dragDepth = 0;
const jsonPageActive = () => $("#page-json").classList.contains("active");
function setDropzone(show) {
  $("#dropzone").classList.toggle("hidden", !show);
  $("#dropzoneSub").textContent = jsonPageActive() ? "JSON dosyasını ya da klasörünü bırak" : "Klasör, oyunun .exe dosyası ya da masaüstü kısayolu olabilir";
  $(".dropzone-title").textContent = jsonPageActive() ? "JSON dosyasını bırak" : "Oyun klasörünü bırak";
}
document.addEventListener("dragenter", (e) => { if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) { dragDepth += 1; setDropzone(true); } });
document.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) setDropzone(false); });
document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("drop", (e) => { e.preventDefault(); dragDepth = 0; setDropzone(false); });

async function handleDropped(paths) {
  const path = paths[0];
  if (jsonPageActive()) { $("#jsonInput").value = path; toast({ title: "JSON girişi seçildi", text: path, tone: "ok" }); return; }
  selectProject(await call("open_dropped", path));
}

window.addEventListener("pywebviewready", () => boot(window.pywebview.api));
if (window.pywebview && window.pywebview.api) boot(window.pywebview.api);
