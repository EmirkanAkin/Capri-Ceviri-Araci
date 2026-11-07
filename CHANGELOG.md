# Capri — Değişim Günlüğü

## [1.0.1] - 2026-11-07
### Düzeltmeler
- **Çeviri başlamıyordu:** Türkçe Windows'ta exe sürümünde `→`, `✔` gibi karakterler içeren her günlük satırı işi düşürüyordu
  (`'charmap' codec can't encode`). Günlük yazmak artık hiçbir koşulda işi durduramaz.
- Hata yolunun kendisi de düşebildiği için proje "Çeviri sürüyor" durumunda takılı kalıyordu; artık her hata açıkça bildirilir,
  uygulama çeviri sırasında kapansa bile proje takılı kalmaz.
- Açılışta her proje "son işlem az önce" görünüyordu: kapak görseli yüklemek işlem sayılıyordu.
- Güncellemeden sonra yeni kod eski arayüz dosyalarıyla açılabiliyordu (WebView2 önbelleği); arayüz değişince önbellek temizlenir.
- **Unity StreamingAssets metinleri çevriliyor ama oyuna yazılmıyordu;** artık yazılıyor ve yedekleniyor.
- BepInEx reddedilince oyuna hiçbir şey yazılmadığı hâlde "Çeviri tamamlandı" deniyordu. İzin artık çeviriden önce isteniyor (boşuna API
  harcanmaz) ve yazılan satır yoksa bu açıkça söyleniyor.
- Ollama çevirileri hedef dil ne olursa olsun Türkçe talimat kullanıyordu; artık hedef dile göre.
- Çevrilmiş oyunda çeviri tekrar başlatılınca Türkçe metin yeniden çevrilebiliyordu; "Baştan çevir" önce orijinalleri geri yükler.
- Süre tahmini her oyunda ~5 sn çıkıyordu. Artık metin miktarı, önbellek, motor ve anahtar sayısına göre hesaplanır;
  gerçek çevirilerden öğrenir.
- Gevşek Steam eşleşmesi başka oyunun adını ve kapağını getirebiliyordu.
- Unity analizi oyun klasörüne geçici font dosyası yazıyordu; artık yazmıyor.
### Arayüz
- Çeviri durumları netleşti: düğme "Çeviri devam ediyor %31" olur, bitince kilitlenip "Çeviri tamamlandı"ya döner;
  durdurulunca "Kaldığı yerden devam et", hata olunca "Tekrar dene".
- İlerleme paneli: Yedek · Hazırlık · Çeviri · Yazma adımları, yüzde, satır sayısı, hız, canlı kalan ve geçen süre.
- Hatalar anlaşılır dilde: ne oldu, ne yapmalı, gerekiyorsa ilgili sayfaya düğme; teknik ayrıntı katlanır bölümde.
- Analiz paneli: çevrilecek satır, kelime, hazır çeviri, tahmini süre ve font uyumu; teknik notlar katlanır bölümde.
- Teknik günlük `portable_cache/capri.log` dosyasına da yazılır.
### Yeni
- **Otomatik oyun bulma:** Kütüphane; Steam, Epic, GOG, sürücülerdeki Games/Oyunlar klasörleri ve eklediğin klasörleri tarar (yalnızca okur).
  Bulunanlar öneri olarak listelenir, tek tıkla eklenir. Açılışta otomatik çalışır, kapatılabilir.
- **Ren'Py çok dilli hedef:** Türkçe dışındaki 16 dile de çeviri (`tl/<Dil>`); fontlar hedef dilin karakterlerine göre denetlenir.
- **Unreal IoStore:** metinler .pak içinde yoksa `.utoc` kapsayıcıları açık kaynak `retoc` ile okunur (araç onay alınarak indirilir).
- Güncelleme penceresinde "Bu sürümde" notları.
- GitHub Actions: test ve etiketle otomatik sürüm; sertifika tanımlanırsa exe imzalama.
### Performans
- Unity oyun açma: 14 sn → 5 ms (`resources.assets` algılamada 3 kez ayrıştırılıyordu; artık analizde 1 kez).
- Analiz arka planda çalışır ve uygulamayı kilitlemez; değişmeyen oyunun sonucu diskten anında gelir.
- Kapak görselleri her olayda base64 olarak taşınmıyor (proje başına ~280 KB → ~0,5 KB).
- Çeviri önbelleği yazımı yaklaşık 10 kat hızlı; editör araması her tuşta dosya okumuyor ve tüm satırları doğrulamıyor.
- Açılışta PyTorch yüklenmiyor; yalnızca yerel motor seçiliyse hazırlanır.
- Arayüz değişmeyen içeriği yeniden çizmiyor; olay kanalı boştayken uyuyor ve tepki süresi 100 ms'den 40 ms'ye indi.

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
