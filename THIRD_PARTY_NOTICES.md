# Üçüncü taraf bileşenler

Capri'nin kendi kodu [MIT lisansı](LICENSE) ile dağıtılır. Sürüm paketindeki başlıca bileşenler:

| Bileşen | Lisans |
|---|---|
| Python | PSF-2.0 |
| pywebview | BSD-3-Clause |
| pythonnet, clr-loader | MIT |
| Microsoft Edge WebView2 SDK | Microsoft'un WebView2 lisansı |
| requests | Apache-2.0 |
| Pillow | MIT-CMU |
| NumPy | BSD-3-Clause ve bağlı lisanslar |
| UnityPy, etcpak, texture2ddecoder, astc-encoder-py, tpk_ar, fmod_toolkit (Python kodu) | MIT |
| rpycdec, pylocres, mss, bottle, proxy_tools, attrs, winrt paketleri, brotli | MIT |
| lz4, fsspec | BSD |
| zstandard (python-zstandard) | BSD-3-Clause |
| Geist ve Geist Mono yazı tipleri | SIL Open Font License 1.1 |

`fmod_toolkit` paketinin içerdiği kapalı kaynak `fmod.dll`, Capri sürüm paketine dahil değildir.

**Dosya biçimleri için yararlanılan açık kaynak projeler** (kod Capri'ye kopyalanmadı; biçimler Python'da yeniden
yazıldı, aşağıdaki tablo dışında):

| Proje | Kullanım | Lisans |
|---|---|---|
| Godot Engine | .pck paketleri, ikili kaynaklar, OptimizedTranslation biçimi (`src/godot_formats.py`) | MIT |
| Smaz (Salvatore Sanfilippo; Godot'nun `thirdparty/misc/smaz.c` kopyası) | Godot çeviri metinlerini açmak için sözlük tablosu `src/godot_formats.py` içinde | BSD-3-Clause |
| WolfTL (Sinflower) | WOLF RPG harita ve ortak olay biçimi (`src/wolf_formats.py`) | MIT |
| UberWolf / WolfDec (Sinflower) | WOLF veritabanı biçimi, .wolf arşiv anahtarları ve WOLF 3.x ek şifrelemesi (`src/wolf_archive.py`) | MIT |
| DXライブラリ (DxLib, 山田 巧) | DXArchive arşiv biçimi, LZ ve Huffman açıcı (`src/wolf_archive.py`) | DxLib lisansı (serbest kullanım) |
| Godot Engine GDScript | Betik belirteç biçimleri (`src/godot_script.py`) | MIT |
| Unity Addressables / Localization | Katalog ve dize tablosu biçimleri (`src/unity_localization.py`) | Unity Companion License (yalnızca biçim) |
| TyranoScript / KiriKiri KAG | Senaryo sözdizimi (`src/kag_script.py`) | MIT / zlib benzeri |
| Electron asar | Arşiv biçimi (`src/archives.py`) | MIT |

Smaz lisans metni: Copyright (c) 2006-2009, Salvatore Sanfilippo. All rights reserved. Redistribution and use in source
and binary forms, with or without modification, are permitted provided that the following conditions are met: (1)
Redistributions of source code must retain the above copyright notice, this list of conditions and the following
disclaimer. (2) Redistributions in binary form must reproduce the above copyright notice, this list of conditions and
the following disclaimer in the documentation and/or other materials provided with the distribution. (3) Neither the
name of Smaz nor the names of its contributors may be used to endorse or promote products derived from this software
without specific prior written permission. THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES ARE DISCLAIMED.

`tests/data/godot*_demo.pck` dosyaları Capri'nin kendi deneme projesinden Godot 4.7.2 ve 3.6.3 ile dışa aktarılmıştır.

**Paketle gelmeyen, yalnızca onayınla indirilenler:** CTranslate2 (MIT) ve sentencepiece (Apache-2.0), eski kurulumlar
için PyTorch ve Transformers, BepInEx, XUnity.AutoTranslator, repak ve retoc ile aşağıdaki modeller. Bunlar kendi
lisanslarına tabidir.

| Model | Lisans |
|---|---|
| Helsinki-NLP OPUS-MT (opus-mt-tc-big-en-tr; CTranslate2 dönüştürmesi ooeoeo/opus-mt-tc-big-en-tr-ct2-float16) | CC-BY 4.0 |
| Meta NLLB-200 (nllb-200-distilled-600M; CTranslate2 int8 dönüştürmesi JustFrederik/nllb-200-distilled-600M-ct2-int8) | CC-BY-NC 4.0 — yalnızca ticari olmayan kullanım |
| Google TranslateGemma 4B / 12B / 27B (GGUF) | Gemma Kullanım Şartları |
| Xiaomi MiLMMT-46 4B / 12B (GGUF) | Gemma Kullanım Şartları |
| Google Gemma 4 E2B / E4B / 12B / 26B-A4B (resmî QAT q4_0 GGUF) | Apache-2.0 |
| Tencent Hy-MT2 1.8B / 7B / 30B-A3B (resmî GGUF) | Apache-2.0 |
| llama.cpp (llama-server, Vulkan derlemesi; dahili yerel modeller için) | MIT |
| TypeTreeGeneratorAPI 0.0.10 (Unity bileşen okuyucusu; pakette yok, isteğe bağlı indirilir) | MIT; yerel DLL'i AssetRipper (GPL-3.0), AssetsTools.NET, Cpp2IL, AsmResolver, Mono.Cecil, Iced (MIT) ve Capstone (BSD-3) içerir |

Unity bileşen okuyucusu Capri ile dağıtılmaz: kullanıcı izin verirse PyPI'dan (files.pythonhosted.org) sabit sürüm ve SHA-256 doğrulamasıyla `tools/typetree/0.0.10` klasörüne indirilir; lisans dosyası ve kaynak bağlantısı yanına yazılır (kaynak: https://github.com/K0lb3/TypeTreeGeneratorAPI, https://github.com/AssetRipper/AssetRipper).

Dahili yerel modellerin GGUF dosyaları Hugging Face'ten iner: Gemma 4 ve Hy-MT2 üreticilerin kendi yayımları, TranslateGemma ve MiLMMT mradermacher dönüştürmeleridir (hepsi sabit sürüm, SHA-256 doğrulamalı).
Hazır gelen arayüz sözlükleri (data/ui_lang) Capri'nin İngilizce sözlüğünden makine çevirisiyle üretilmiştir.
