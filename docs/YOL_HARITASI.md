# Capri — Yol Haritası

## Gerçek oyunlarda denenmesi gerekenler
- **Unreal `.pak` ve IoStore (`repak`, `retoc`):** kod sahte araçlarla uçtan uca test edildi; gerçek oyun paketlerinde çalıştırılmadı.
  Bakılacaklar: paket listesi okunuyor mu, `.locres` çıkıyor mu, oyun `~mods` altındaki yama paketini yüklüyor mu. Dune / Phantom
  Blade Zero gibi oyunlarda paketler çoğunlukla AES ile şifrelidir; oyunun AES anahtarı gerekir.
- **RPG Maker şifreli arşivleri:** biçim açık kaynak bir çözücüyle doğrulandı, gerçek bir oyun arşiviyle denenmedi.
- **Sürükle-bırak:** Windows'un gerçek sürükleme döngüsü otomatik test edilemiyor; elle denenmeli.
- **Yerel model ortamı kurulumu:** gerçek indirme (≈2,9 GB) denenmedi; kurulum sahte sunucuyla test edildi.
- **GitHub Actions:** iş akışları ilk kez GitHub'a gönderilince çalışacak; yerelde çalıştırılamaz.

## Yalnızca senin yapabileceğin
- **Kod imzalama sertifikası:** SmartScreen uyarısını yalnızca güvenilir bir sertifika kaldırır, satın alınması veya başvurulması gerekir.
  Altyapı hazır: `CAPRI_SIGN_PFX` / `CAPRI_SIGN_PASSWORD` (yerelde), `SIGN_PFX_BASE64` / `SIGN_PFX_PASSWORD` (GitHub Secrets).
  Açık kaynak projelere ücretsiz seçenek olarak SignPath Foundation var. Kabul edilirse README'ye SignPath'in istediği
  "Free code signing provided by SignPath.io, certificate by SignPath Foundation" cümlesi eklenmeli ve iş akışı
  `signpath/github-action-submit-signing-request` adımına geçirilmeli (SignPath .pfx vermez).

## Yeni fikirler
- Çeviriyi oyun içinde kontrol: oyunu Capri'den açan "Oyna" düğmesi.
- Sözlük içe/dışa aktarma; topluluk yamalarını paylaşma sayfası.
- Çeviri sırasında maliyet tahmini (ücretli API'ler için kaç token, yaklaşık ne kadar).
- Çeviri bitince isteğe bağlı Windows bildirimi; uzun çevirilerde uygulama simge durumundayken haber verir.
- Kalite editörünü Ren'Py dışındaki motorlara ve Türkçe dışındaki dillere genişletmek.
- Ren'Py'de Çince, Japonca, Korece için uygun açık font (Noto) indirip otomatik yamalamak.
- Tarama sonuçlarında oyunun yaklaşık satır sayısı ve süresi.
- Uygulamaya farklı dil destekleri, buna uygun dil seçme menüsü ve otomatik sistem dilini algılayarak kullanıcıya kullandığı dili verme.