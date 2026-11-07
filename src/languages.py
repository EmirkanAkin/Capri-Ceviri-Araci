"""
Evrensel Çoklu Dil Desteği Modülü (Multi-Language Support)
=========================================================
Oyun çevirilerinde kaynak ve hedef dil tanımları, dil kodları,
doğal adlar ve yapay zeka sistem talimatı (prompt) oluşturucu.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Language:
    code: str              # Standart ISO kodu (örn: 'tr', 'es', 'ru')
    name_en: str          # İngilizce adı (örn: 'Turkish')
    name_native: str      # Kendi dilindeki adı (örn: 'Türkçe')
    icon: str = ""        # Bayrak / simge


SUPPORTED_LANGUAGES: Dict[str, Language] = {
    "tr": Language(code="tr", name_en="Turkish", name_native="Türkçe", icon="🇹🇷"),
    "en": Language(code="en", name_en="English", name_native="English", icon="🇬🇧"),
    "es": Language(code="es", name_en="Spanish", name_native="Español", icon="🇪🇸"),
    "ru": Language(code="ru", name_en="Russian", name_native="Русский", icon="🇷🇺"),
    "de": Language(code="de", name_en="German", name_native="Deutsch", icon="🇩🇪"),
    "fr": Language(code="fr", name_en="French", name_native="Français", icon="🇫🇷"),
    "it": Language(code="it", name_en="Italian", name_native="Italiano", icon="🇮🇹"),
    "pt-BR": Language(code="pt-BR", name_en="Portuguese (Brazil)", name_native="Português (Brasil)", icon="🇧🇷"),
    "pt": Language(code="pt", name_en="Portuguese", name_native="Português", icon="🇵🇹"),
    "pl": Language(code="pl", name_en="Polish", name_native="Polski", icon="🇵🇱"),
    "ja": Language(code="ja", name_en="Japanese", name_native="日本語", icon="🇯🇵"),
    "zh-CN": Language(code="zh-CN", name_en="Simplified Chinese", name_native="简体中文", icon="🇨🇳"),
    "zh-TW": Language(code="zh-TW", name_en="Traditional Chinese", name_native="繁體中文", icon="🇹🇼"),
    "ko": Language(code="ko", name_en="Korean", name_native="한국어", icon="🇰🇷"),
    "ar": Language(code="ar", name_en="Arabic", name_native="العربية", icon="🇸🇦"),
    "uk": Language(code="uk", name_en="Ukrainian", name_native="Українська", icon="🇺🇦"),
    "nl": Language(code="nl", name_en="Dutch", name_native="Nederlands", icon="🇳🇱"),
}


def normalize_language_code(input_str: str) -> str:
    """Metin veya isimden standart dil kodunu bulur."""
    cleaned = input_str.strip().lower()
    for code, lang in SUPPORTED_LANGUAGES.items():
        if (
            cleaned == code.lower()
            or cleaned == lang.name_en.lower()
            or cleaned == lang.name_native.lower()
        ):
            return code
    return "tr"


def get_language(code_or_name: str) -> Language:
    """Belirtilen koda ait Language nesnesini döndürür."""
    code = normalize_language_code(code_or_name)
    return SUPPORTED_LANGUAGES.get(code, SUPPORTED_LANGUAGES["tr"])


def get_all_target_languages() -> List[Tuple[str, str]]:
    """Arayüz açılır menüsü için liste döndürür: [('Türkçe (tr)', 'tr'), ...]"""
    res = []
    for code, lang in SUPPORTED_LANGUAGES.items():
        if code == "en":
            continue  # İngilizce hedef değil genellikle kaynaktır
        label = f"{lang.name_native} ({lang.name_en})"
        res.append((label, code))
    return res


def get_all_source_languages() -> List[Tuple[str, str]]:
    """Arayüz kaynak dili için liste döndürür."""
    res = [("Otomatik Algıla (Auto)", "auto")]
    for code, lang in SUPPORTED_LANGUAGES.items():
        label = f"{lang.name_native} ({lang.name_en})"
        res.append((label, code))
    return res


def build_system_instruction(
    target_lang_code: str = "tr",
    source_lang_code: str = "en",
    game_engine: str = "visual novel",
) -> str:
    """
    Yapay zeka (Gemini / Ollama) için seçilen kaynak ve hedef dile
    göre kusursuz sistem talimatı oluşturur.
    """
    target = get_language(target_lang_code)
    source = get_language(source_lang_code) if source_lang_code != "auto" else None
    src_name = source.name_en if source else "source language"

    if target.code == "tr":
        return (
            f"Sen profesyonel bir video oyunu ve görsel roman ({game_engine}) {src_name}-Türkçe çevirmenisin.\n"
            "Görevin: Verilen JSON string listesini (list of strings) Türkçeye çevirmek.\n"
            "Kurallar:\n"
            "1. Tamamen doğal, akıcı günlük konuşma dili kullan. Deyimleri Türkçe konuşma diline uyarla.\n"
            "2. Sansür yapma, yetişkin/argo ifadeleri sahnenin doğallığına uygun çevir.\n"
            "3. Oyun etiketlerini ({i}, {b}, {color=...}, [NAME], {0}, [mc] vb.) ve değişkenlerini harfi harfine koru.\n"
            "4. Giriş listesindeki string sayısı ile çıkıştaki string sayısı BİREBİR AYNI olmalıdır.\n"
            "5. YALNIZCA geçerli bir JSON listesi (array of strings) döndür."
        )
    else:
        return (
            f"You are a professional video game and visual novel ({game_engine}) translator from {src_name} to {target.name_en}.\n"
            f"Your task: Translate the given JSON list of strings to natural, fluent {target.name_en} ({target.name_native}).\n"
            "Rules:\n"
            f"1. Use natural, conversational, fluent {target.name_en}. Adapt idioms accurately to colloquial speech.\n"
            "2. Never censor: translate adult/mature content, slang, and profanity faithfully to fit character personalities.\n"
            "3. Strictly preserve all game tags, codes, formatters, and variables ({i}, {b}, {0}, [NAME], <color=...>, [mc], etc.) verbatim.\n"
            "4. The output array MUST have the EXACT SAME length and element order as the input array.\n"
            "5. Return ONLY a valid JSON array of strings (no markdown wrapping, no extra keys)."
        )


# Font uyumu için her dilin ayırt edici karakterleri
LANGUAGE_CHARS: Dict[str, str] = {
    "tr": "çğıİöşüÇĞÖŞÜ", "de": "äöüßÄÖÜ", "es": "áéíñóúü¿¡", "fr": "àâçéèêëîïôùûœ", "it": "àèéìòù",
    "pt": "ãáâçéêíóõú", "pt-BR": "ãáâçéêíóõú", "pl": "ąćęłńóśźżŁŚŻ", "nl": "ëéï",
    "ru": "абвгдеёжзийклмнопрстуфхцчшщъыьэюя", "uk": "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя",
    "ar": "ابتثجحخدذرزسشصضطظعغفقكلمنهوي", "ja": "あいうアイウ日本語", "ko": "한국어가나다", "zh-CN": "简体中文的是", "zh-TW": "繁體中文的是",
}
# DejaVu bu yazı sistemlerini içermez; Ren'Py'de otomatik font yaması uygulanamaz
NO_FONT_FALLBACK = ("ja", "ko", "zh-CN", "zh-TW")


def renpy_language_name(code: str) -> str:
    """Ren'Py dil klasörü adı: tl/<ad>. Yalnızca harf: 'Simplified Chinese' → 'SimplifiedChinese'."""
    language = SUPPORTED_LANGUAGES.get(code) or SUPPORTED_LANGUAGES["tr"]
    return "".join(ch for ch in language.name_en if ch.isalnum())


def code_for_renpy_name(name: str) -> str:
    for code in SUPPORTED_LANGUAGES:
        if renpy_language_name(code) == name:
            return code
    return "tr"
