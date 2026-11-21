# Capri — Yol Haritası

## Gerçek oyunlarda denenmesi gerekenler
- **Unreal `.pak` / IoStore (`repak`, `retoc`):** araçların indirilip kurulması ve şifreli paket algılama gerçek bir UE5
  oyununda doğrulandı (salt okunur). Şifresiz bir oyunda `.locres` çıkarma ve `~mods` yama paketinin oyunda yüklenmesi
  henüz denenmedi. Çok yeni IoStore sürümlerini retoc okuyamıyor (anlaşılır not gösteriliyor).
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
- **TextMeshPro atlasına harf ekleme:** fontta olmayan ğ/ş/ı/İ'yi en yakın harf yerine oyunun kendi gliflerinden üretmek.
  (Elimizdeki Unity oyunlarının fontlarında Türkçe harfler tam; gerçek bir ihtiyaç çıkınca yapılmalı.)
- **RPG Maker MV eklenti komutları (356):** boşlukla ayrılmış komut satırları; hangi parçanın metin olduğu eklentiye
  göre değiştiği için şimdilik çevrilmiyor (MZ'nin 357 komutu çevriliyor).
- **Ekran çevirisi kıyas seti:** resmi fragmanlardan alınmış gerçek karelerle genişletmek.
- **Godot motoru desteği.**
