# Capri — Yol Haritası

## Sıradaki
- **Unity: fontta olmayan Türkçe harfler.** Bir kullanıcının denediği Unity oyununda ğ, ş, ı gibi harfler fontta
  yoktu; Capri bunları şu an en yakın harfle (g, s, i) yazıyor. Yapılacak: eksik harfleri oyunun TextMeshPro
  atlasına eklemek (oyunun kendi fontundan ya da açık lisanslı bir fonttan SDF olarak üretip), olmazsa BepInEx
  yolunda XUnity.AutoTranslator'ın yedek font ayarıyla Türkçe harfli bir font vermek. Eski "fikirler" listesindeki
  TextMeshPro maddesinin yerine geçer; artık gerçek bir ihtiyaç.

## Gerçek oyunlarda denenmesi gerekenler
- **Godot:** yama gerçek Godot 4.7.2 ve 3.6.3 motorlarında (headless, Türkçe ve İngilizce sistem dilinde) doğrulandı;
  satışta olan bir oyunda henüz denenmedi. Exe'ye gömülü paketler ve oyunun kendi override.cfg'si testlerde var.
- **TyranoScript:** senaryo çözümleyici resmi örnek oyunla, asar yazımı resmi `@electron/asar` aracıyla doğrulandı.
  NW.js exe'si içindeki paketin yeniden yazılması gerçek bir oyunda denenmeli.
- **KiriKiri:** yama arşivinin (patch.xp3) asıl arşivin üstüne bindirilmesi gerçek bir oyunda denenmeli; şifreli
  arşivler okunamıyor (anlaşılır not gösteriliyor).
- **WOLF RPG:** WOLF RPG Editor 2.281 ve 3.737 örnek oyunlarının bütün harita ve ortak olay dosyaları çözümlendi ve
  yazıldı; şifreli arşivler 17 ücretsiz oyunda açıldı. Veritabanı çevirisi ve arşivin açılıp geri konması oyun içinde
  elle kontrol edilmeli; WOLF Pro (oyuna özel anahtar) arşivleri açılamıyor.
- **Unity Localization (dosyadan) ve Godot betik metinleri:** testlerde üretilen tablolar ve betiklerle doğrulandı;
  satışta olan bir oyunda henüz denenmedi.
- **Unreal `.pak` / IoStore (`repak`, `retoc`):** araçların indirilip kurulması ve şifreli paket algılama gerçek bir UE5
  oyununda doğrulandı (salt okunur). Şifresiz bir oyunda `.locres` çıkarma ve `~mods` yama paketinin oyunda yüklenmesi
  henüz denenmedi. Çok yeni IoStore sürümlerini retoc okuyamıyor (anlaşılır not gösteriliyor).
- **RPG Maker şifreli arşivleri:** biçim açık kaynak bir çözücüyle doğrulandı, gerçek bir arşivle denenmedi.
- **Utage / I2 Localization:** bir oyunda okuma/yazma ve açılış denendi; diyalogun ekranda görünüşü elle kontrol edilmeli.
- **Naninovel ve PlayMaker:** birer oyunda yazma ve açılış (batchmode) denendi; oyun içi görünüm elle kontrol edilmeli.
- **Sürükle-bırak:** Windows'un gerçek sürükleme döngüsü otomatik test edilemiyor.
- **OPUS-MT / NLLB ortamı (CTranslate2):** exe içinde gerçek kurulum (PyPI'dan ctranslate2 + sentencepiece, 23 MB) ve
  OPUS çevirisi doğrulandı. Ekran kartında çalışması için cuBLAS 12 gerekir (yoksa işlemcide int8 çalışır); ekran
  kartı yolu cuBLAS'ı olan bir bilgisayarda denenmeli.

## Yalnızca proje sahibinin yapabileceği
- **Kod imzalama:** SmartScreen uyarısını yalnızca güvenilir bir sertifika kaldırır. SignPath Foundation (ücretsiz, açık
  kaynak) başvurusu kabul edilirse iş akışı `signpath/github-action-submit-signing-request` adımına geçirilmeli.

## Fikirler
- **RPG Maker MV eklenti komutları (356):** boşlukla ayrılmış komut satırları; hangi parçanın metin olduğu eklentiye
  göre değiştiği için şimdilik çevrilmiyor (MZ'nin 357 komutu çevriliyor).
- **Ekran çevirisi kıyas seti:** resmi fragmanlardan alınmış gerçek karelerle genişletmek.
- **Maskotun göz kırpma ve konuşma kareleri:** pozların gözü kapalı / ağzı açık hâlleriyle canlandırma.
- **Ekran kartında OPUS-MT / NLLB:** cuBLAS'ı (NVIDIA) isteğe bağlı indirip CTranslate2'yi ekran kartında çalıştırmak;
  şu an cuBLAS yoksa işlemcide çalışıyor (yine de eski PyTorch'tan hızlı).
- **Diğer motorlarda font yardımı:** Ren'Py dışındaki motorlarda (Godot, RPG Maker) fontta Türkçe harf yoksa uyarı ve
  tek tıkla açık lisanslı bir yedek font.
- **Editörde model karşılaştırma:** seçili satırı iki modelle çevirip daha iyisini seçmek.
- **Ekran çevirisinde pencere takibi:** sabit alan, oyun penceresi taşınınca onunla birlikte kaysın.
- **Hy-MT2 1.8B (1,25 bit):** llama.cpp bu sayı biçimini desteklediğinde kitaplığa eklemek (en küçük iyi model olur).
