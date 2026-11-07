# Capri — Yol Haritası

## Gerçek oyunlarda denenmesi gerekenler
- **Unreal `.pak` ve IoStore (`repak`, `retoc`):** kod sahte araçlarla uçtan uca test edildi; gerçek oyun paketlerinde çalıştırılmadı.
  Dune / Phantom Blade Zero gibi oyunlarda paketler çoğunlukla AES ile şifrelidir; oyunun AES anahtarı gerekir.
- **RPG Maker şifreli arşivleri:** biçim açık kaynak bir çözücüyle doğrulandı, gerçek bir oyun arşiviyle denenmedi.
- **Sürükle-bırak:** Windows'un gerçek sürükleme döngüsü otomatik test edilemiyor; elle denenmeli.
- **Yerel model ortamı kurulumu:** gerçek indirme (≈2,9 GB) denenmedi; kurulum sahte sunucuyla test edildi.

## Yalnızca senin yapabileceğin
- **Kod imzalama sertifikası:** SmartScreen uyarısını yalnızca güvenilir bir sertifika kaldırır. SignPath Foundation (ücretsiz,
  açık kaynak) için başvuru; kabul edilirse README'ye SignPath'in istediği cümle eklenmeli ve iş akışı
  `signpath/github-action-submit-signing-request` adımına geçirilmeli (SignPath .pfx vermez).

## Yeni fikirler
- Yerleşik Windows bildirim balonu (şu an görev çubuğu yanıp sönüyor; balon için uygulama kimliği kaydı gerekiyor).
- Topluluk yamaları için uygulama içinde arama/indirme sayfası (şu an GitHub konusu açılıyor).
- Tarama önerilerinde Unity ve Unreal için de satır tahmini (şu an yalnızca Ren'Py ve RPG Maker; diğerleri analiz ister).
- Çeviri belleğini oyunlar arasında paylaşma: aynı arayüz metinleri her oyunda yeniden çevrilmesin.
- Tek pencere kuralı: Capri ikinci kez açılınca açık olanı öne getirsin.
