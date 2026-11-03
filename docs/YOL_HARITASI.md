# Capri — Yol Haritası

## Gerçek oyunlarda denenmesi gerekenler
- **Unreal `.pak`:** kod sahte bir repak ile uçtan uca test edildi; gerçek oyun paketlerinde denenmedi. Bakılacaklar:
  paket listesi okunuyor mu, `.locres` çıkıyor mu, oyun `~mods` altındaki yama paketini yüklüyor mu. UE5 IoStore
  oyunlarında `.locres` genellikle klasik `.pak` içinde durur; durmuyorsa `retoc` desteği gerekir. Dune / Phantom
  Blade Zero gibi oyunlarda paketler çoğunlukla AES ile şifrelidir; oyunun AES anahtarı gerekir.
- **RPG Maker şifreli arşivleri:** biçim açık kaynak bir çözücüyle doğrulandı, gerçek bir oyun arşiviyle denenmedi.
- **Sürükle-bırak:** Windows'un gerçek sürükleme döngüsü otomatik test edilemiyor; elle denenmeli.
- **Yerel model ortamı kurulumu:** gerçek indirme (≈2,9 GB) denenmedi; sürüm seçimi gerçek PyTorch dizini üzerinde
  doğrulandı, kurulum sahte sunucuyla test edildi.

## Önerilen yeni sistemler
- Kod imzalama sertifikası (Windows SmartScreen uyarısını kaldırır).
- GitHub Actions ile otomatik test ve sürüm derleme.
- Ren'Py için çok dilli hedef (şu an yalnızca Türkçe).
- Unreal IoStore için `retoc` desteği.
