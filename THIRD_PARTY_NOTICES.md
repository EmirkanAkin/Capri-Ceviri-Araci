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
| Geist ve Geist Mono yazı tipleri | SIL Open Font License 1.1 |

`fmod_toolkit` paketinin içerdiği kapalı kaynak `fmod.dll`, Capri sürüm paketine dahil değildir.

**Paketle gelmeyen, yalnızca onayınla indirilenler:** PyTorch ve Transformers, BepInEx, XUnity.AutoTranslator, repak ve
retoc ile aşağıdaki modeller. Bunlar kendi lisanslarına tabidir.

| Model | Lisans |
|---|---|
| Helsinki-NLP OPUS-MT (opus-mt-tc-big-en-tr) | CC-BY 4.0 |
| Meta NLLB-200 (nllb-200-distilled-600M) | CC-BY-NC 4.0 — yalnızca ticari olmayan kullanım |
| Google TranslateGemma (GGUF) | Gemma Kullanım Şartları |
| Xiaomi MiLMMT-46 (GGUF) | Gemma Kullanım Şartları |
| llama.cpp (llama-server, Vulkan derlemesi; dahili yerel modeller için) | MIT |
| TypeTreeGeneratorAPI 0.0.10 (Unity bileşen okuyucusu; pakette yok, isteğe bağlı indirilir) | MIT; yerel DLL'i AssetRipper (GPL-3.0), AssetsTools.NET, Cpp2IL, AsmResolver, Mono.Cecil, Iced (MIT) ve Capstone (BSD-3) içerir |

Unity bileşen okuyucusu Capri ile dağıtılmaz: kullanıcı izin verirse PyPI'dan (files.pythonhosted.org) sabit sürüm ve SHA-256 doğrulamasıyla `tools/typetree/0.0.10` klasörüne indirilir; lisans dosyası ve kaynak bağlantısı yanına yazılır (kaynak: https://github.com/K0lb3/TypeTreeGeneratorAPI, https://github.com/AssetRipper/AssetRipper).

Dahili yerel modellerin GGUF dosyaları Hugging Face'teki mradermacher dönüştürmeleridir (sabit sürüm, SHA-256 doğrulamalı).
Hazır gelen arayüz sözlükleri (data/ui_lang) Capri'nin İngilizce sözlüğünden makine çevirisiyle üretilmiştir.
