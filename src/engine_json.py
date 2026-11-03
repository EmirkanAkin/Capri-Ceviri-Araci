"""
Capri — Genel JSON/Dil Dosyası Çeviricisi
=====================================================

Motor bağımsız — herhangi bir oyunun JSON veya metin tabanlı dil
dosyasını Türkçeye çevirir. Shale Hill Secrets (VNE3), Wolf RPG,
Tyrano Builder ve diğer özel motorlar için uygundur.

Desteklenen JSON yapıları:
  1. Düz sözlük      : { "anahtar": "değer", ... }
  2. İç içe sözlük   : { "bölüm": { "0": "metin", "1": "metin" } }
  3. Karma (otomatik): Yukarıdakilerin karışımı

Komut satırı kullanımı:
  python engine_json.py --input ui_strings_en.json --output ui_strings_tr.json
  python engine_json.py --input ch18_strings.json  --output ch18_strings_tr.json --model opus
  python engine_json.py --input klasor/ --output cikti/ --model nllb
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

# engine_common bu dosyayla aynı klasörde olmalı
try:
    from engine_common import (
        BUILTIN_GLOSSARY,
        Glossary,
        LogFn,
        OllamaTranslationEngine,
        ProgressTracker,
        QAChecker,
        TranslationCache,
        TranslationEngine,
        cache_file_for,
        get_model_info,
        mask_text,
        model_ready,
        protected_content_valid,
        unmask_text,
    )
    ENGINE_COMMON_AVAILABLE = True
except ImportError:
    ENGINE_COMMON_AVAILABLE = False

from paths import APP_DIR
DATA_DIR = APP_DIR / "portable_cache"

# JSON dosyalarındaki oyun kontrol kodları (VNE3, TyranoBuilder, Wolf RPG vb.)
PROTECTED_JSON = re.compile(
    r"("
    r"\{[A-Za-z_][A-Za-z0-9_]*\}"       # {PlayerName}, {GameVar}
    r"|\[[A-Za-z_][A-Za-z0-9_]*\]"       # [name], [player]
    r"|%[A-Za-z_][A-Za-z0-9_]*%"         # %month%, %day%
    r"|%[sd]"                             # printf %s %d
    r"|\[i\].*?\[\/i\]"                  # [i]italik[/i]
    r"|\[b\].*?\[\/b\]"                  # [b]kalın[/b]
    r"|<[^>]{1,40}>"                      # <html_tag>
    r"|\\n|\\t|\\r"                       # kaçış karakterleri
    r"|\\\\n"                             # çift kaçış
    r")",
    re.IGNORECASE,
)


# ═══════════════════════════════════════════════════════════════════════════════
# JSON yapı analizi
# ═══════════════════════════════════════════════════════════════════════════════

def _is_translatable(value: Any) -> bool:
    """Bir JSON değerinin çevrilmesi gerekip gerekmediğini belirle."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if len(text) < 2:
        return False
    # Sadece sayı, URL veya dosya yolu ise atla
    if re.fullmatch(r"[\d\s\.\,\:\-\/\\%]+", text):
        return False
    if text.startswith("http") or text.startswith("www"):
        return False
    if re.fullmatch(r"[A-Za-z0-9_\-\.\/\\]+\.[a-z]{2,5}", text):
        return False
    # En az bir alfabetik karakter olmalı
    return bool(re.search(r"[A-Za-z]", text))


def collect_strings(obj: Any, path: str = "") -> list[tuple[str, str]]:
    """
    JSON nesnesinden çevrilecek (json_path, text) çiftlerini topla.
    json_path, değerin orijinal konumunu gösterir.
    """
    results: list[tuple[str, str]] = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            child_path = f"{path}.{key}" if path else key
            if isinstance(value, str) and _is_translatable(value):
                results.append((child_path, value))
            elif isinstance(value, (dict, list)):
                results.extend(collect_strings(value, child_path))

    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            child_path = f"{path}[{i}]"
            if isinstance(value, str) and _is_translatable(value):
                results.append((child_path, value))
            elif isinstance(value, (dict, list)):
                results.extend(collect_strings(value, child_path))

    return results


def apply_translations(obj: Any, translations: dict[str, str], path: str = "") -> Any:
    """
    Çevirileri JSON nesnesi içine uygula.
    Orijinal yapıyı ve türleri tamamen koru.
    """
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            child_path = f"{path}.{key}" if path else key
            if isinstance(value, str) and value in translations:
                result[key] = translations[value]
            elif isinstance(value, (dict, list)):
                result[key] = apply_translations(value, translations, child_path)
            else:
                result[key] = value
        return result

    elif isinstance(obj, list):
        result = []
        for i, value in enumerate(obj):
            child_path = f"{path}[{i}]"
            if isinstance(value, str) and value in translations:
                result.append(translations[value])
            elif isinstance(value, (dict, list)):
                result.append(apply_translations(value, translations, child_path))
            else:
                result.append(value)
        return result

    return obj


# ═══════════════════════════════════════════════════════════════════════════════
# Ana çeviri pipeline
# ═══════════════════════════════════════════════════════════════════════════════

def translate_json_file(
    input_path: Path,
    output_path: Path,
    model_kind: str = "opus",
    ollama_model: str = "qwen2.5:7b",
    glossary_path: Path | None = None,
    nsfw: bool = False,
    log: LogFn = print,
    progress_cb=None,
) -> dict:
    """
    Tek bir JSON dosyasını çevir.

    Döndürür:
        { "total": int, "translated": int, "skipped": int, "output": Path }
    """
    log(f"Okunuyor: {input_path.name} ({input_path.stat().st_size // 1024} KB)")
    raw = input_path.read_text(encoding="utf-8")
    data = json.loads(raw)

    # Çevrilecek stringleri topla
    pairs = collect_strings(data)
    unique_sources = sorted({text for _, text in pairs if text.strip()})
    log(f"Çevrilecek benzersiz metin: {len(unique_sources)}")

    if not unique_sources:
        log("Çevrilecek metin bulunamadı, dosya kopyalanıyor.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(raw, encoding="utf-8")
        return {"total": 0, "translated": 0, "skipped": 0, "output": output_path}

    # Cache
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = input_path.resolve()
    cache_path = cache_file_for(cache_key, DATA_DIR, suffix=f"_json_{model_kind}")
    cache = TranslationCache(cache_path)
    cache.load()

    # Sözlük
    builtin = dict(BUILTIN_GLOSSARY)
    glossary = Glossary(builtin)
    if glossary_path and glossary_path.exists():
        extra = Glossary.from_file(glossary_path)
        glossary.entries.update(extra.entries)
    if nsfw:
        nsfw_path = APP_DIR / "data" / "glossary_nsfw.json"
        if nsfw_path.exists():
            nsfw_entries = json.loads(nsfw_path.read_text(encoding="utf-8"))
            nsfw_entries.pop("_aciklama", None)
            glossary.entries.update(nsfw_entries)
            log(f"NSFW sözlük yüklendi: {len(nsfw_entries)} terim")

    # Çeviri motoru oluştur
    tracker = ProgressTracker()
    tracker.start(len(unique_sources))

    if model_kind == "ollama":
        engine = OllamaTranslationEngine(
            model_name=ollama_model,
            cache=cache,
            glossary=glossary,
            protected_pattern=PROTECTED_JSON,
            log=log,
        )
        translations = engine.translate_batch(
            unique_sources,
            progress=progress_cb,
            tracker=tracker,
        )
    else:
        model_info = get_model_info(model_kind, APP_DIR)
        engine = TranslationEngine(
            model_dir=model_info.directory,
            model_kind=model_kind,
            cache=cache,
            glossary=glossary,
            protected_pattern=PROTECTED_JSON,
            log=log,
        )
        translations = engine.translate_batch(
            unique_sources,
            progress=progress_cb,
            tracker=tracker,
        )
        engine.unload_model()

    log(f"Çeviri tamamlandı: {len(translations)} metin")

    # Çevirileri JSON yapısına uygula
    translated_data = apply_translations(data, translations)

    # Dosyayı kaydet — orijinal biçimlendirmeye mümkün olduğunca yakın
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(translated_data, ensure_ascii=False, indent="\t"),
        encoding="utf-8",
    )
    log(f"Kaydedildi: {output_path}")

    translated_count = sum(1 for s in unique_sources if s in translations and translations[s] != s)
    return {
        "total": len(unique_sources),
        "translated": translated_count,
        "skipped": len(unique_sources) - translated_count,
        "output": output_path,
        "eta_summary": tracker.summary(),
    }


def translate_json_folder(
    input_dir: Path,
    output_dir: Path,
    pattern: str = "*.json",
    model_kind: str = "opus",
    ollama_model: str = "qwen2.5:7b",
    glossary_path: Path | None = None,
    nsfw: bool = False,
    log: LogFn = print,
) -> list[dict]:
    """
    Bir klasördeki tüm eşleşen JSON dosyalarını çevir.
    Klasör yapısı korunur.
    """
    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()
    files = sorted(input_dir.rglob(pattern))
    log(f"Bulundu: {len(files)} JSON dosyası")
    results = []
    for i, f in enumerate(files, 1):
        relative = f.relative_to(input_dir)
        out = output_dir / relative
        log(f"\n[{i}/{len(files)}] {relative}")
        try:
            result = translate_json_file(
                f, out, model_kind=model_kind, ollama_model=ollama_model,
                glossary_path=glossary_path, nsfw=nsfw, log=log,
            )
            results.append(result)
        except Exception as e:
            log(f"HATA: {f.name} — {e}")
            results.append({"error": str(e), "file": str(f)})
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Komut satırı arayüzü
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Herhangi bir oyunun JSON dil dosyasını Türkçeye çevir.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  # Tek dosya
  python engine_json.py --input ui_strings_en.json --output ui_strings_tr.json

  # Tüm bölüm dosyaları (klasör)
  python engine_json.py --input data/ --output data_tr/ --pattern "*_strings.json"

  # NLLB modeli + NSFW sözlük
  python engine_json.py --input ch18_strings.json --output ch18_strings_tr.json --model nllb --nsfw

  # Ollama
  python engine_json.py --input ch18_strings.json --output ch18_strings_tr.json --model ollama --ollama-model qwen2.5:7b
        """,
    )
    parser.add_argument("--input", "-i", required=True, help="Giriş JSON dosyası veya klasörü")
    parser.add_argument("--output", "-o", required=True, help="Çıkış JSON dosyası veya klasörü")
    parser.add_argument("--model", "-m", default="opus", choices=["opus", "nllb", "ollama"],
                        help="Çeviri modeli (varsayılan: opus)")
    parser.add_argument("--ollama-model", default="qwen2.5:7b",
                        help="Ollama model adı (varsayılan: qwen2.5:7b)")
    parser.add_argument("--glossary", "-g", help="Ek sözlük dosyası (.json)")
    parser.add_argument("--nsfw", action="store_true",
                        help="Yetişkin içerik sözlüğünü de kullan (glossary_nsfw.json)")
    parser.add_argument("--pattern", default="*.json",
                        help="Klasör modunda dosya kalıbı (varsayılan: *.json)")

    args = parser.parse_args()

    if not ENGINE_COMMON_AVAILABLE:
        print("HATA: engine_common.py bulunamadı. engine_json.py ile aynı klasörde olmalı.")
        sys.exit(1)

    input_path = Path(args.input)
    output_path = Path(args.output)
    glossary_path = Path(args.glossary) if args.glossary else None

    start = time.time()

    if input_path.is_dir():
        results = translate_json_folder(
            input_path, output_path,
            pattern=args.pattern,
            model_kind=args.model,
            ollama_model=args.ollama_model,
            glossary_path=glossary_path,
            nsfw=args.nsfw,
        )
        total = sum(r.get("total", 0) for r in results)
        translated = sum(r.get("translated", 0) for r in results)
        print(f"\n✓ Tamamlandı: {len(results)} dosya | {translated}/{total} metin çevrildi | {time.time()-start:.0f}s")
    else:
        result = translate_json_file(
            input_path, output_path,
            model_kind=args.model,
            ollama_model=args.ollama_model,
            glossary_path=glossary_path,
            nsfw=args.nsfw,
        )
        print(f"\n✓ Tamamlandı: {result['translated']}/{result['total']} metin | {time.time()-start:.0f}s")
        if "eta_summary" in result:
            print(result["eta_summary"])


if __name__ == "__main__":
    main()
