# Capri — Yol Haritası

## Gerçek oyunlarda denenmesi gerekenler
- **Unreal `.pak` ve IoStore (`repak`, `retoc`):** kod sahte araçlarla uçtan uca test edildi; gerçek oyun paketlerinde çalıştırılmadı.
  Büyük yapımlarda paketler çoğunlukla AES ile şifrelidir; oyunun AES anahtarı gerekir.
- **RPG Maker şifreli arşivleri:** biçim açık kaynak bir çözücüyle doğrulandı, gerçek bir oyun arşiviyle denenmedi.
- **Utage ve I2 Localization:** bir oyunda okuma/yazma ve oyunun açılışı denendi;
  oyunun içinde diyalog ekranı otomatik olarak açılamadığı için metnin ekranda görünüşü elle kontrol edilmeli.
  Birden fazla senaryo sayfası olan Utage kitapları ve "Description" alanlı eski I2 sürümleri yalnızca sahte veriyle sınandı.
- **RPG Maker MZ ortak olaylar ve konuşmacı adları:** bir oyunun kopyasında gerçek Gemini ile denendi; oyun
  içinde ekranda elle kontrol edilmeli.
- **Sürükle-bırak:** Windows'un gerçek sürükleme döngüsü otomatik test edilemiyor; elle denenmeli.
- **Yerel model ortamı kurulumu:** gerçek indirme (≈2,9 GB) denenmedi; kurulum sahte sunucuyla test edildi.

## Yalnızca senin yapabileceğin
- **Kod imzalama sertifikası:** SmartScreen uyarısını yalnızca güvenilir bir sertifika kaldırır. SignPath Foundation (ücretsiz,
  açık kaynak) için başvuru; kabul edilirse README'ye SignPath'in istediği cümle eklenmeli ve iş akışı
  `signpath/github-action-submit-signing-request` adımına geçirilmeli (SignPath .pfx vermez).

## Yeni fikirler
- **CTranslate2 ile NLLB/OPUS (int8)** (dahili TranslateGemma geldiği için önceliği düştü): PyTorch (≈2,9 GB) yerine ~40 MB'lık CTranslate2 ve int8 modeller; yerel çeviri 3-4 kat
  hızlanır, ekran kartı olmadan da kullanılabilir hale gelir. Hazır dönüştürülmüş NLLB-600M int8 modelleri var
  (ör. JustFrederik/nllb-200-distilled-600M-ct2-int8); kendi dönüştürmemizi yayımlamak daha güvenli. Paket boyutu ve CUDA
  kitaplıkları gerçek kurulumda ölçülmeli.
- **Ren'Py derleme denetimi:** çeviriden sonra oyunun kendi Ren'Py'siyle `compile` çalıştırıp sözdizimi hatalarını oyuncudan önce
  yakalamak. Hata durumunda Ren'Py'nin görünür pencere (errors.txt) açıp açmadığı gerçek bir oyunda denenmeli; denenmeden
  eklenmedi.
- **TextMeshPro atlasına harf ekleme:** fontta olmayan ğ/ş/ı/İ şu an en yakın harfle yazılıyor. Oyunun kendi glifleri
  birleştirilerek (g + kısa çizgi, s + ç'nin çengeli, noktasız i) SDF atlasına eklenebilir; gerçek bir TMP oyunuyla denenmeli.
- **Ekran çevirisi kıyas seti:** yapay altyazı kareleriyle yapılan ölçüm, resmi oyun fragmanlarından alınmış gerçek karelerle
  genişletilmeli (sızdırılmış görüntüler kullanılmamalı).
