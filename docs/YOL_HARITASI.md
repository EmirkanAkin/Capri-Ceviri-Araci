# Capri — Yol Haritası

## Gerçek oyunlarda denenmesi gerekenler
- **Unreal `.pak` ve IoStore (`repak`, `retoc`):** kod sahte araçlarla uçtan uca test edildi; gerçek oyun paketlerinde çalıştırılmadı.
  Dune / Phantom Blade Zero gibi oyunlarda paketler çoğunlukla AES ile şifrelidir; oyunun AES anahtarı gerekir.
- **RPG Maker şifreli arşivleri:** biçim açık kaynak bir çözücüyle doğrulandı, gerçek bir oyun arşiviyle denenmedi.
- **Utage ve I2 Localization:** bir oyunda (Steamy Livestreams with My Girlfriend) okuma/yazma ve oyunun açılışı denendi;
  oyunun içinde diyalog ekranı otomatik olarak açılamadığı için metnin ekranda görünüşü elle kontrol edilmeli.
  Birden fazla senaryo sayfası olan Utage kitapları ve "Description" alanlı eski I2 sürümleri yalnızca sahte veriyle sınandı.
- **Sürükle-bırak:** Windows'un gerçek sürükleme döngüsü otomatik test edilemiyor; elle denenmeli.
- **Yerel model ortamı kurulumu:** gerçek indirme (≈2,9 GB) denenmedi; kurulum sahte sunucuyla test edildi.

## Yalnızca senin yapabileceğin
- **Kod imzalama sertifikası:** SmartScreen uyarısını yalnızca güvenilir bir sertifika kaldırır. SignPath Foundation (ücretsiz,
  açık kaynak) için başvuru; kabul edilirse README'ye SignPath'in istediği cümle eklenmeli ve iş akışı
  `signpath/github-action-submit-signing-request` adımına geçirilmeli (SignPath .pfx vermez).

## Yeni fikirler
- **TextMeshPro atlasına harf ekleme:** şu an fontta olmayan harfler en yakın harfle yazılıyor (ğ→g). Atlasa gerçek ğ/ş/ı
  glifleri çizmek (SDF üretimi + karakter tablosu) metni tam Türkçe gösterir; ham veriyle yapılması zor ama mümkün.
- **Çeviri sonrası açılış testi:** çeviri bitince oyunu arka planda kısa süre açıp ilk ekrana kadar çökme olup olmadığına
  bakmak (Ren'Py'de `compile`/`lint`, Unity'de Player.log). Mod çakışmaları (ör. Shelter) kullanıcıdan önce yakalanır.
- **Arayüz dilleri için hazır sözlükler:** Türkçe ve İngilizce dışındaki diller ilk seçimde bulut motoruyla üretiliyor;
  sık kullanılan birkaç dil (Almanca, İspanyolca, Rusça…) pakete hazır eklenebilir, anahtarı olmayan kullanıcılar da kullanır.
- **Topluluk yamaları için etiket:** depo sahibi "yama" etiketini oluşturup paylaşılan konulara eklerse liste daha temiz olur
  (şu an başlıktaki "Yama:" ön ekiyle aranıyor).
