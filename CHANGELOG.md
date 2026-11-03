# Capri — Değişim Günlüğü

## [1.0.0] - 2026-11-03
İlk herkese açık sürüm.

### Oyun çevirisi
- **Ren'Py:** `.rpy`, `.rpyc`, `.rpa`; diyalog sırasıyla bağlamlı çeviri, kalite düzeltme turu, Türkçe font yaması.
- **Unity:** `resources.assets` TextAsset ve StreamingAssets; BepInEx + XUnity.AutoTranslator otomatik kurulumu
  (Mono → BepInEx 5, IL2CPP → BepInEx 6) ve tek tıkla kaldırma.
- **Unreal Engine 4/5:** açık `.locres` dosyaları ve `.pak` içindekiler. Paketler açık kaynak `repak` aracıyla açılır
  (araç onay alınarak indirilir); çeviri `Paks/~mods` altına yama paketi olarak eklenir. Şifreli paketler için AES anahtarı.
- **RPG Maker MV / MZ** (JSON) ve **XP / VX / VX Ace** (Ruby Marshal; değişmeyen her bayt korunur). Şifreli arşivler
  (`Game.rgss3a`, `.rgss2a`, `.rgssad`) uygulamanın içinde açılır, yedeklenir ve tek tıkla geri konur.
- **JSON Çevirici:** motor bağımsız dil dosyaları.
- Etiket ve değişken koruması, bozulan satırlar için inceleme listesi, durdur / kaldığı yerden devam.
- Çeviri Editörü (düzelt, API harcamadan oyuna uygula) ve `.capripatch` yama paylaşımı.
- Oyuna özel bağlam: karakter tarama, terimler, hitap (sen/siz), oyun notları.
- Her değişiklikten önce otomatik yedek; Yedekler sayfasından geri yükleme.

### Çeviri motorları
- Google Gemini (tüm uygun modeller hız sırasıyla, çoklu anahtarla paralel), OpenAI, Claude, DeepL, Ollama.
- Çevrimdışı OPUS-MT ve NLLB-200 (GPU); NLLB fp16'ya küçültülebilir (2,3 → 1,2 GB).
- Yerel model ortamı (PyTorch), ekran kartının sürücüsüne uygun sürümle uygulama içinden kurulur.
- GPU hızlandırma: CUDA ön hazırlığı, TF32, VRAM temizliği, modelin VRAM'e ön yüklenmesi.

### Ekran çevirisi (OCR)
- `Ctrl+Shift+T` ile alan seç ve çevir; `Ctrl+Shift+Y` ile alanı sabitle, canlı çevrilsin.
- Windows'un yerleşik OCR motoru, çoklu monitör ve DPI desteği; çeviri pencereleri ekran yakalamaya görünmez.

### Uygulama
- Kurulumsuz, taşınabilir Windows sürümü (`Capri.exe`).
- Uygulama içi güncelleme: yeni sürüm ve notları gösterilir, tek tıkla indirilip kurulur.
- API anahtarları Windows Kimlik Bilgisi Yöneticisi'nde şifreli saklanır.
- Metin Çevirici, sürükle-bırak ile oyun ekleme, Steam kapak görselleri, bildirim merkezi.
