/* Capri — ekran çevirisini sesli okuma (Windows'un yüklü sesleri, Web Speech API). İnternet gerekmez ve metin
   bilgisayardan çıkmaz (çevrimiçi sesler kullanılmaz); seçilen dilin
   Windows konuşma paketi yüklü değilse ses bulunamaz ve kullanıcıya nasıl ekleyeceği söylenir. */
"use strict";
window.CapriSpeech = (() => {
  const BCP = { tr: "tr-TR", en: "en-US", de: "de-DE", fr: "fr-FR", es: "es-ES", it: "it-IT", pl: "pl-PL", ru: "ru-RU",
    "pt-BR": "pt-BR", pt: "pt-PT", ja: "ja-JP", "zh-CN": "zh-CN", "zh-TW": "zh-TW", ko: "ko-KR", ar: "ar-SA",
    uk: "uk-UA", nl: "nl-NL" };
  const synth = window.speechSynthesis;
  let lang = "tr", voice = null, last = "";

  function pick() {
    if (!synth) { voice = null; return; }
    const want = (BCP[lang] || lang).toLowerCase();
    const base = want.split("-")[0];
    // Yalnızca bilgisayardaki sesler: "Online (Natural)" sesler metni Microsoft'un sunucusuna gönderir
    const voices = (synth.getVoices() || []).filter((v) => v.localService === true);
    const norm = (v) => String(v.lang || "").replace("_", "-").toLowerCase();
    voice = voices.find((v) => norm(v) === want) || voices.find((v) => norm(v).split("-")[0] === base) || null;
  }
  if (synth && "onvoiceschanged" in synth) synth.onvoiceschanged = pick;

  return {
    setLang(code) { lang = code || "tr"; pick(); },
    available() { pick(); return !!voice; },
    voiceName() { return voice ? voice.name : ""; },
    speak(text, force) {
      text = String(text || "").trim();
      if (!synth || !text || (!force && text === last)) return false;
      pick();
      if (!voice) return false;
      last = text;
      synth.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.voice = voice;
      u.lang = voice.lang;
      u.rate = 1.05;
      synth.speak(u);
      return true;
    },
    stop() { last = ""; if (synth) synth.cancel(); },
    missingHint() { return "Bu dil için Windows sesi yok. Ayarlar › Saat ve dil › Konuşma'dan ses ekleyebilirsin."; },
  };
})();
