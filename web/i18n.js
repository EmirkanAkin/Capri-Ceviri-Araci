/* Capri arayüz dili.
   Arayüz Türkçe yazılır; seçilen dilin sözlüğü (anahtar: Türkçe metin) ekrandaki metin düğümlerine ve
   placeholder/title özniteliklerine uygulanır. Sonradan eklenen ya da değişen metinler gözlemciyle çevrilir.
   "{0}" gibi yer tutuculu anahtarlar kalıp olarak eşlenir ("18.724 satır" → "{0} satır" → "18,724 lines").
   Kullanıcı içeriği (çeviri satırları, günlük, yazı kutuları) asla çevrilmez. */
(function () {
  const SKIP = "textarea, input, code, pre, .cell-src, .cell-tr, .selectable, #logBox, #txOutput, [data-no-i18n]";
  const ATTRS = ["placeholder", "title", "aria-label"];
  const state = { lang: "tr", exact: new Map(), templates: [], observer: null, busy: false };
  const SRC = new WeakMap();   // metin düğümü → { src: Türkçe asıl, out: yazdığımız çeviri }

  const norm = (s) => s.replace(/\s+/g, " ").trim();
  const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  function compile(dict) {
    state.exact = new Map();
    state.templates = [];
    const bare = [];
    for (const [rawKey, value] of Object.entries(dict || {})) {
      if (!value) continue;
      const key = norm(rawKey);
      if (/\{\d+\}/.test(key)) {
        const order = [];
        const re = escapeRe(key).replace(/\\\{(\d+)\\\}/g, (_, n) => { order.push(+n); return "(.+?)"; });
        state.templates.push({ re: new RegExp(`^${re}$`), order, out: value, weight: key.replace(/\{\d+\}/g, "").length });
        // "Projeyi aç {0}" gibi: baştaki/sondaki yer tutucu çoğu zaman bir simgedir (ayrı öğe), metin düğümü onsuzdur
        const m = key.match(/^\{(\d+)\}\s*([^{}]+)$/) || key.match(/^([^{}]+?)\s*\{(\d+)\}$/);
        if (m) {
          const lead = key.startsWith("{");
          const n = lead ? m[1] : m[2], text = (lead ? m[2] : m[1]).trim();
          const v = value.trim(), ph = `{${n}}`;
          if (lead && v.startsWith(ph)) bare.push([text, v.slice(ph.length).trim()]);
          else if (!lead && v.endsWith(ph)) bare.push([text, v.slice(0, -ph.length).trim()]);
        }
      } else {
        state.exact.set(key, value);
      }
    }
    for (const [k, v] of bare) if (v && !state.exact.has(k)) state.exact.set(k, v);
    state.templates.sort((a, b) => b.weight - a.weight);   // en özgül kalıp önce
  }

  // Python metinleri Türkçe binlik ayırıcıyla gelir ("2.575 satır"): kalıp değişkeni böyle bir sayıysa dilin biçimine
  // çevrilir (2,575). "1.0.5" gibi sürüm numaraları üçlü gruplanmadığı için dokunulmaz.
  function localNumber(v) {
    if (!/^\d{1,3}(?:\.\d{3})+$/.test(v)) return null;
    try { return Number(v.replace(/\./g, "")).toLocaleString(state.lang); } catch { return null; }
  }

  // Birebir ya da {0} kalıbı (kalıp değişkenleri bir seviye daha aranır). "Analiz ediliyor…", "2 satır incelenmeli."
  // gibi anahtarda olmayan sondaki nokta / üç nokta korunarak çevrilir.
  function lookup(key, depth) {
    const hit = state.exact.get(key);
    if (hit !== undefined) return hit;
    if (depth > 1) return null;
    for (const t of state.templates) {
      const m = t.re.exec(key);
      if (!m) continue;
      // "{0} anahtar" gibi kısa bir kalıp "Bulut · en hızlı · Hazır · 3 anahtar"ı yutmasın: ayraçlı metin parça parça çevrilir
      if (m.slice(1).some((v) => v.includes(" · ") || v.includes(" — "))) continue;
      const values = {};
      t.order.forEach((n, i) => { const v = m[i + 1]; values[n] = localNumber(v) ?? lookup(norm(v), depth + 1) ?? v; });
      return t.out.replace(/\{(\d+)\}/g, (_, n) => values[n] ?? "");
    }
    const end = key.match(/^(.*?[^.…])(…|\.\.\.|\.)$/);    // içteki metin noktayla bitmez: döngü olmaz
    const inner = end ? lookup(end[1].trim(), depth) : null;
    return inner == null ? null : inner.replace(/[….]+$/, "") + end[2];
  }

  const lookupLoose = (key) => lookup(key, 0);

  function translate(text) {
    const key = norm(text);
    if (!key || state.lang === "tr") return null;
    const whole = lookupLoose(key);
    if (whole != null) return whole;
    // "Bulut · en hızlı · Anahtar gerekli" gibi birleşik metinler: yalnızca en üst seviyede, en uzun eşleşen parça
    // önce ("Bulut · en hızlı" tek anahtar). Parçalar yeniden bölünmez (çok ayraçlı metinde üstel büyümesin).
    for (const sep of [" · ", " — ", ": "]) {
      if (!key.includes(sep)) continue;
      const parts = key.split(sep);
      if (parts.length > 12) continue;
      const out = [];
      let changed = false;
      for (let i = 0; i < parts.length;) {
        let j = parts.length, hit = null;
        for (; j > i; j--) {
          if (j - i === parts.length) continue;
          hit = lookupLoose(parts.slice(i, j).join(sep));
          if (hit != null) break;
        }
        if (hit != null) { out.push(hit); changed = true; i = j; } else { out.push(parts[i]); i += 1; }
      }
      if (changed) return out.join(sep);
    }
    return null;
  }

  function wrapLike(original, translated) {   // baştaki/sondaki boşluklar korunur
    const lead = original.match(/^\s*/)[0], trail = original.match(/\s*$/)[0];
    return lead + translated + trail;
  }

  function skipped(el) { return !el || (el.closest && el.closest(SKIP)); }

  function applyText(node) {
    if (skipped(node.parentElement)) return;
    const rec = SRC.get(node);
    let src = node.nodeValue;
    if (rec && node.nodeValue === rec.out) src = rec.src;          // bizim yazdığımız: asıl metinden çevir
    if (!/[A-Za-zÇĞİÖŞÜçğıöşü]/.test(src)) return;
    const out = translate(src);
    const value = out == null ? src : wrapLike(src, out);
    SRC.set(node, { src, out: value });
    if (node.nodeValue !== value) node.nodeValue = value;
  }

  function applyAttrs(el) {
    if (skipped(el) && !(el.matches && el.matches("textarea, input"))) return;
    for (const name of ATTRS) {
      if (!el.hasAttribute || !el.hasAttribute(name)) continue;
      const store = `i18n${name}`;
      let src = el.getAttribute(name);
      if (el[store] && src === el[store].out) src = el[store].src;
      const out = translate(src);
      const value = out == null ? src : out;
      el[store] = { src, out: value };
      if (el.getAttribute(name) !== value) el.setAttribute(name, value);
    }
  }

  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) { applyText(root); return; }
    if (root.nodeType !== 1) return;
    applyAttrs(root);
    if (skipped(root)) return;
    const it = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    let node = it.nextNode();
    while (node) {
      if (node.nodeType === 3) applyText(node); else applyAttrs(node);
      node = it.nextNode();
    }
  }

  function observe() {
    if (state.observer) return;
    state.observer = new MutationObserver((records) => {
      if (state.busy) return;
      state.busy = true;
      try {
        for (const r of records) {
          if (r.type === "characterData") applyText(r.target);
          else if (r.type === "attributes") applyAttrs(r.target);
          else r.addedNodes.forEach(walk);
        }
      } finally { state.busy = false; }
    });
    state.observer.observe(document.documentElement, { subtree: true, childList: true, characterData: true,
                                                       attributes: true, attributeFilter: ATTRS });
  }

  window.I18N = {
    get lang() { return state.lang; },
    get locale() { return state.lang === "tr" ? "tr-TR" : state.lang; },
    t(text) { return translate(text) ?? text; },
    set(lang, dict) {
      state.lang = lang || "tr";
      compile(state.lang === "tr" ? {} : dict);
      document.documentElement.lang = state.lang;
      state.busy = true;
      try { walk(document.body); } finally { state.busy = false; }
      observe();
    },
  };
})();
