# Capri — Yol Haritası

## Gerçek oyunlarda denenmesi gerekenler
- **Unreal `.pak` / IoStore (`repak`, `retoc`):** sahte araçlarla uçtan uca test edildi; gerçek paketlerde denenmedi.
  Büyük yapımlarda paketler çoğunlukla AES ile şifreli; oyunun AES anahtarı gerekir.
- **RPG Maker şifreli arşivleri:** biçim açık kaynak bir çözücüyle doğrulandı, gerçek bir arşivle denenmedi.
- **Utage / I2 Localization:** bir oyunda okuma/yazma ve açılış denendi; diyalogun ekranda görünüşü elle kontrol edilmeli.
- **Naninovel ve PlayMaker:** birer oyunda yazma ve açılış (batchmode) denendi; oyun içi görünüm elle kontrol edilmeli.
- **Sürükle-bırak:** Windows'un gerçek sürükleme döngüsü otomatik test edilemiyor.
- **Yerel model ortamı (PyTorch):** gerçek indirme (≈2,9 GB) denenmedi; kurulum sahte sunucuyla test edildi.

## Yalnızca proje sahibinin yapabileceği
- **Kod imzalama:** SmartScreen uyarısını yalnızca güvenilir bir sertifika kaldırır. SignPath Foundation (ücretsiz, açık
  kaynak) başvurusu kabul edilirse iş akışı `signpath/github-action-submit-signing-request` adımına geçirilmeli.

## Fikirler
- **CTranslate2 ile NLLB/OPUS (int8):** PyTorch (≈2,9 GB) yerine ~40 MB'lık çalışma ortamı; ekran kartsız da hızlı.
- **Ren'Py derleme denetimi:** çeviriden sonra oyunun kendi Ren'Py'siyle `compile` çalıştırıp hataları önceden yakalamak.
- **TextMeshPro atlasına harf ekleme:** fontta olmayan ğ/ş/ı/İ'yi en yakın harf yerine oyunun kendi gliflerinden üretmek.
- **Ekran çevirisi kıyas seti:** resmi fragmanlardan alınmış gerçek karelerle genişletmek.
- **Godot motoru desteği.**
