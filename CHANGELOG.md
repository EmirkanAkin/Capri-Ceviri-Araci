# Capri — Değişim Günlüğü

## [1.0.7] - 2026-11-18
### Yeni
- **Sade sağlayıcılar:** Sağlayıcılar sayfası "Bulut" ve "Bilgisayarında" olarak ikiye ayrıldı. Capri'nin içinde
  çalışan bütün yerel motorlar (TranslateGemma, OPUS-MT, NLLB) tek "Yerel model" kartında; hangisinin kullanılacağı
  kartın içinden seçiliyor. Ollama ayrı bir program gerektirdiği için ayrı kartta kaldı.
- **Kısa açıklamalar:** Arayüzdeki ~80 uzun açıklama ve onay penceresi kısaltıldı (8 hazır dilde de). Ana sayfadaki
  motor etiketlerine "Ekran (OCR)" eklendi.
- **README:** Kısaltıldı; GIF'ler ve ekran görüntüleri temiz bir kurulumdan yeniden alındı (sarımsı lekeler giderildi).
- **Naninovel oyunları:** Naninovel motoruyla yapılmış Unity görsel romanları artık dosyadan çevriliyor. Derlenmiş
  senaryolar (`Naninovel.Script`) Unity'nin yönetilen referans kayıt defterinde (`[SerializeReference]`) duruyor;
  UnityPy bunun yalnızca tek kayıtlı biçimini okuyabildiği için Capri iki biçimi de (sürüm 1: Unity 2019.3–2021.1,
  sürüm 2: 2021.2+) kendisi okuyup yazıyor. Kaynak, oyunun İngilizce yerelleştirmesi (yoksa İngilizce yazılmış
  senaryonun kendisi); yalnızca diyalog (`PrintText`) ve seçenek (`AddChoice`) metinleri çevriliyor, konuşmacı
  kimliği, etiketler, atlama hedefleri değişmiyor. Menü metinleri ("managed text" belgeleri) de çevriliyor; dil
  listesinde English'in adı Türkçe oluyor. Her senaryo okunup yeniden yazıldığında bayt bayt aynı çıkmazsa ona
  dokunulmuyor; kayıttan sonra dosya yeniden okunup doğrulanıyor. Örnek bir oyunda: 117 senaryo, 14.333 satır + 272
  menü metni; 53.476 nesneden yalnızca 119'u değişti, oyun açılışta hatasız yükleniyor.
### Düzeltmeler
- **Ren'Py:** Diyaloğu bir yardımcıya argüman olarak veren oyunlarda (`call show_line(..., text="…")`) arayüz
  metni taraması 6.000 metinde kesiliyordu; alfabetik sırada sonra gelen karakterlerin sahneleri İngilizce kalıyordu
  (bir oyunda 17.273 diyalogun 11.772'si). Sınır kaldırıldı (aşılırsa günlüğe uyarı düşer). `look="smile"` gibi
  görünüm kodları artık çeviriye gönderilmiyor; "A-Alright.", "Aaah..." gibi kısa ünlemler dosya adı sanılmıyor.
- **Unity:** Naninovel oyunlarında sahnedeki UI kalıp yazıları ("Lorem ipsum", "Choice text") metin sayılıp "66 satır"
  gibi yanıltıcı bir sonuç veriyordu; artık alınmıyor. TextMeshPro'da eksik harf denetimi dinamik atlasları ve yedek
  font zincirini de hesaba katıyor (gereksiz ğ→g, ş→s dönüşümü yapılmıyor).
- **Unity:** Tek parça `.assets` dosyalarına bileşen metni yazılırken nesneler eşleşmiyor, hiçbir şey yazılmıyordu.
- **Unity / Naninovel:** Capri oyun klasörü dışından çalıştırıldığında senaryoların tip bilgisi
  (`globalgamemanagers.assets`) bulunamıyor, yalnızca menü metinleri yazılıp çeviri "tamamlandı" görünüyordu. Bağlı
  dosyalar artık oyunun klasöründe aranıyor; bir senaryo bile yazılamazsa oyun dosyasına dokunulmuyor ve hata gösteriliyor.
- Yerel model kartının durumu, Yerel Modeller sayfası açılmadan da doğru görünüyor.

## [1.0.6] - 2026-11-16
### Yeni
- **Unity bileşen metinleri, BepInEx'siz:** Metnini tablo yerine bileşenlerinde tutan Unity oyunları (PlayMaker
  durum makineleri, sahnedeki UI Text / TextMeshPro, `<Language en="…" jp="…"/>` gibi çok dilli XML tabloları; tümü
  tek paket `data.unity3d` içinde de olabilir) artık doğrudan dosyadan çevriliyor. Alanlar, oyunun kendi DLL'lerinden
  üretilen tip bilgisiyle okunur (Mono: Managed/*.dll, IL2CPP: GameAssembly + metadata). Her bileşen tam okunmalı ve
  geri yazılınca bayt bayt aynı çıkmalı; tutmayanlara dokunulmaz. PlayMaker'da yalnızca oyunun dil dalında (English
  durumu ve ondan zincirlenen durumlar) dile göre değer alan metin çevrilir: her dilde aynı kalan oda/poz/kayıt
  anahtarları, sahne ve değişken adları korunur. Sayılı dil seçicileri (dil değişkeni 0/1/2…) adlı seçicilerden
  öğrenilir. Kişi adı tabloları çevrilmez; dil menüsündeki "English" yazısı "Türkçe" olur. TextMeshPro'da eksik harf,
  fontun yedekleri, TMP Ayarları'ndaki genel yedekler ve varsayılan font zinciriyle birlikte değerlendirilir.
  Kayıttan sonra paket yeniden okunup her değişiklik doğrulanır; tutmazsa oyun dosyası değiştirilmez. Paket LZ4 ile
  kaydedilir (boyut aynı kalır). Örnek bir oyunda: 380 PlayMaker, 379 arayüz, 102 tablo metni; 46.502 nesneden
  yalnızca metin taşıyan 426'sı değişti, oyun açılışta hatasız yükleniyor.
- **Unity bileşen okuyucusu isteğe bağlı:** Tip bilgisi üreticisi (TypeTreeGeneratorAPI 0.0.10, 7,5 MB) yerel DLL'inde
  GPL-3.0 lisanslı AssetRipper kodu içerdiği için Capri paketine konmuyor; gereken oyunda bir kez izin istenip
  PyPI'dan sabit sürüm ve SHA-256 doğrulamasıyla `tools/typetree` klasörüne indiriliyor. "Hayır" denirse BepInEx yolu
  aynen kalır.
- **Yerel model (dahili), Ollama'sız:** TranslateGemma 4B/12B ve MiLMMT-46 4B, Capri'nin içinde llama.cpp
  (llama-server, Vulkan) ile çalışıyor. Yerel Modeller sayfasından tek tıkla indirilir; 37 MB'lık çalışma ortamı ilk
  indirmede kurulur. Sürümler sabit, her dosya SHA-256 ile doğrulanır, zararlı arşiv yolları reddedilir. Sunucu
  yalnızca 127.0.0.1'i dinler; ilk çeviride açılır, 5 dakika kullanılmazsa ya da Capri kapanınca (çökse bile) kapanır.
  `--fit` ile model ekran kartına sığdırılır, sığmayan kısım işlemciye düşer. Her modelde "Hafif" / "Yüksek sistem
  gerektirir" etiketi, gereken ekran kartı belleği ve RAM, ölçülen hız yazıyor; kart yetersizse uyarı çıkıyor.
  Ölçüm (RTX 5070): TranslateGemma 4B ~10 satır/sn, 12B ~4 satır/sn (Ollama'da 1,4: Ollama paketi 12 GB kartta
  işlemciye taşıyor), MiLMMT tek satır ~0,1 sn. Ekran çevirisinde MiLMMT kuruluysa o kullanılır. Vulkan, CUDA ile
  neredeyse aynı hızda olduğu için (8,5 / 9,4 satır/sn) 630 MB'lık CUDA paketi sunulmuyor. Uygulama güncellemesi
  indirilen modelleri silmez.
- **Yerel çeviri modelleri (Ollama):** TranslateGemma (4B/12B) ve MiLMMT-46 4B, model kartlarındaki resmi istem
  biçimleriyle çalışıyor. TranslateGemma ardışık satırları tek blokta (bağlamıyla) çevirir; satır sayısı tutmazsa
  satır satır yeniden dener. Sağlayıcılar → Ollama'da ekran kartına göre önerilen model işaretlenir ve Capri içinden
  ilerleme çubuğuyla indirilir. Varsayılan Ollama modeli artık `translategemma:4b`; Qwen önerileri kaldırıldı.
  Yalnızca çeviri yapan modeller kalite editörü olarak kullanılmaz (düzeltmeleri Gemini yazar).
- **Ekran çevirisi:** Okuma zayıfsa altyazı yazısı arka plandan ayıklanıp (koyu konturun içi / parlak ya da sarı
  pikseller) yeniden okunur. Yapay altyazı karelerinde: gökyüzü + konturlu yazı %73 → %97, gökyüzü + sarı yazı
  %48 → %96, karmaşık sahne + ince yazı %51 → %79. Koyu sahnelerde değişiklik yok; ek süre en fazla ~40 ms.
- **Hazır arayüz sözlükleri:** İspanyolca, Almanca, Fransızca, Rusça, Portekizce (Brezilya), İtalyanca ve Lehçe
  pakete eklendi; bulut anahtarı olmayan kullanıcılar da kullanabilir. Yeni sürümle eklenen metinler gerekirse
  anahtarla tamamlanır. Çeviri yer tutucuyu başka yere taşısa da simgeli düğmeler doğru çevrilir.
- Yerel modellerin lisansları (NLLB-200: CC-BY-NC 4.0) Yerel Modeller sayfasında ve üçüncü taraf bildirimlerinde.
- **Yama güvenliği:** İçe aktarılan yamanın her satırı motorun etiket kuralıyla kaynağa göre denetleniyor. Kaynakta
  olmayan etiket, kod ya da bağlantı (Ren'Py `{a=…}` / `[…]`, RPG Maker eklentilerinin çalıştırdığı `\js<…>`), fazladan
  satır sonu, kontrol karakteri ve anlamsız uzunluktaki satırlar alınmıyor; kaç satırın alınmadığı bildiriliyor. Arşiv
  boyutu ve satır sayısı sınırlı (sıkıştırma bombasına karşı).
### Kaldırılanlar
- **Topluluk yamaları** (uygulama içinden GitHub'da yama arama ve indirme, "Toplulukla paylaş"): yabancıların dosyalarını
  indirip oyun dosyalarına yazmak güvenlik riski taşıyordu. Yamalar artık yalnızca elle, bilinen birinden alınan dosyayla
  içe aktarılıyor.
### Düzeltmeler
- **Ollama çok yavaştı:** (1) Windows'ta `localhost` önce IPv6 (`::1`) deneniyor, Ollama orada dinlemediği için her
  istek ~2 sn bekliyordu; artık `127.0.0.1` kullanılıyor (kayıtlı adresler de düzeltiliyor). (2) Her istekte farklı
  bağlam boyutu (`num_ctx`) gidiyor, Ollama da modeli her seferinde yeniden yüklüyordu; boyut artık kademeli.
  RTX 5070'te ölçüm: TranslateGemma 4B 2,4 → 11,6 satır/sn, MiLMMT 4B 0,47 → 8,9 satır/sn (tek satır ~0,1 sn).
- Yerel modeller etiketlerin içine boşluk koyabiliyordu ("{i} Gerçekten…"); kaynakta bitişik olan boşluk siliniyor.
- TranslateGemma 12B yalnızca 16 GB ve üstü kartlara öneriliyor: Ollama paketi 12 GB kartta işlemciye taşıyor.
- Japonca/Çince kaynaklı oyunlarda yalnızca Latin harfi "harf" sayılıyordu: Ren'Py çeviri şablonları, arayüz metni
  taraması, kalite editörü, yerel modeller ve RPG Maker XP/VX/VX Ace okuyucusu bu satırları atlıyordu.
- **RPG Maker MV/MZ:** `CommonEvents.json` (ortak olaylar: telefon, gün sonu, menüden çağrılan konuşmalar),
  `Troops.json` (savaş konuşmaları) ve kayan metin (405) hiç okunmuyordu; bir oyunda konuşmaların üçte biri
  İngilizce kalıyordu. Artık hepsi çevriliyor.
- **RPG Maker:** `System.json` menü ve savaş terimleri çıkarılıyor ama oyuna yazılmıyordu; artık yazılıyor
  (ilk harf büyük). Eklentilerin okuduğu "not" alanları çevrilmiyor.
- **RPG Maker:** Bulut motorları Ren'Py'nin etiket kuralını kullanıyordu; "[Axe] …" gibi açıklamalar ve
  `\name[…]` içeren satırlar "etiket bozuldu" sayılıp İngilizce bırakılıyordu. RPG Maker artık kendi kodlarıyla
  (`\C[n]`, `\V[n]`, `\pop<1>`, `%1`, seçenek koşulları `if(...)`) denetleniyor.
- **RPG Maker:** Satır başındaki konuşmacı adı (`\name[...]`) satırdan ayrı çevriliyor; aynı ad her satırda aynı
  kalıyor ve Çeviri Editörü'nde ayrı düzenlenebiliyor.
- Yalnızca Çince/Japonca karakterden oluşan satırlar "harf yok" sayılıp atlanıyordu; artık çevriliyor. Önbellekte
  çevrilmeden kalmış bu tür satırlar yeniden deneniyor.
- RPG Maker: Ses efekti nesnelerindeki dosya adlarına (`"name": "Attack"`) asla dokunulmuyor.

## [1.0.5] - 2026-11-14
### Yeni
- **Utage desteği (Unity):** Japon görsel roman motoru Utage'nin senaryo kitapları IL2CPP oyunlarda da (tip bilgisi
  olmadan) okunup yazılıyor; yalnızca değişen metin hücrelerinin baytları değişir. Çeviri oyunun İngilizce sütununa
  yazılır, oyunda English seçilince görünür. BepInEx gerekmez.
- **I2 Localization desteği (Unity):** Yaygın yerelleştirme eklentisinin `I2Languages` kaynağındaki metin terimleri
  çevriliyor; resim/ses terimlerine (ör. logo) dokunulmuyor.
- **Çok dilli tablolar:** `Key / Japanese / English` gibi başlıklı TextAsset tablolarının İngilizce sütunu çevriliyor;
  `sharedassets` dosyaları da taranıyor.
- **TextMeshPro font kontrolü:** Oyunun TMP fontlarında olmayan harfler (ör. ğ ş ı İ) oyuna yazılırken en yakın harfle
  değiştiriliyor (ğ→g, ş→s, ı→i), böylece kutu olarak görünmüyorlar. Analiz bunu açıkça gösteriyor.
- **Arayüz dili:** Üst çubuktaki dil seçiciyle 17 dil. Türkçe ve İngilizce hazır gelir; diğer diller ilk seçildiğinde
  bulut motoruyla bir kez çevrilip saklanır. Seçilen dil çeviri hedefi de olur. İlk açılışta Windows'un dili kullanılır.
- **Topluluk yamaları:** Kütüphane ve Editör'deki "Topluluk yamaları" ile GitHub'da paylaşılmış yamaları ara, indir
  ve açık oyuna uygula (yalnızca GitHub konu eklerinden indirilir). Paylaşırken GitHub'ın kabul ettiği `.zip` kopyası
  da hazırlanır.
- **Ortak çeviri belleği:** Kısa arayüz metinleri ("Save", "Load Game") bir oyunda çevrilince diğer oyunlarda
  API'ye gitmeden kullanılır; dile göre ayrı tutulur, oyunun kendi çevirisini ezmez.
- **Windows bildirimi:** Capri arka plandayken çeviri bitince ya da hata olunca bildirim (ayarlardan kapatılabilir).
- **Tek pencere:** Aynı Capri ikinci kez açılınca açık pencere öne gelir.
- **Tarama tahmini:** Bulunan Unity ve Unreal (açık .locres) oyunlarında da satır sayısı gösteriliyor.
- **Görev çubuğu ilerlemesi:** Çeviri sürerken Capri'nin görev çubuğu simgesi ilerlemeyi gösteriyor; hazırlık
  adımlarında kayan çubuk, durdurulunca sarı, hata olunca kırmızı (kısa süre sonra kaybolur).
### Değişiklikler
- Çeviri ayarları tek bir "Seçenekler" kartında toplandı; dar pencerede kartlar üst üste binmiyor.
- Kod temizliği: hiçbir yerden çağrılmayan eski yardımcılar (eski yedek/geri yükleme ve QA fonksiyonları, kullanılmayan
  RPG Maker/Unreal yardımcıları) ve kullanılmayan importlar kaldırıldı; davranış değişmedi.
### Düzeltmeler
- Unity: yazma sırasında UnityPy dosyayı açık tuttuğu için Windows'ta "Erişim engellendi" hatası oluşabiliyordu.
- Arayüz dili: analiz notları, uyarılar, onay pencereleri, hata ve sağlayıcı mesajları, simgeli düğmeler ("Projeyi aç"),
  "…" ile biten durum etiketleri ve ekran çevirisi pencereleri Türkçe kalıyordu. Tarih, yüzde ve binlik ayırıcı da
  seçilen dile göre yazılıyor. Bir test, Python'dan ekrana giden her mesajın İngilizce karşılığı olduğunu denetliyor.
- Eski sürümden kalan analiz sonuçları yok sayılıyor: 1.0.4'te "metin bulunamadı" denen Utage oyunları yeniden analiz edilir.

## [1.0.4] - 2026-11-08
### Yeni
- Çeviri bitince Windows'un uyarı sesi yerine Capri'ye özel kısa, ince bir çan sesi; hata olursa daha kısık, alçalan bir ses.
  Çeviri ayarlarındaki "Bitince ses çal" ile kapatılabilir.

### Düzeltmeler
- **Ren'Py "translate komutu başarısız: 1":** şablon üretilirken betik arşivleri geçici olarak gizleniyordu; aynı arşivde
  resim/ses/Live2D modeli olan oyunlarda (ör. DLC arşivleri) bunlar da kayboluyor, oyunun açılış kodu çöküyordu.
  Artık gizlenen arşivin yerine yalnızca betik dışı dosyaları içeren geçici bir arşiv konuyor; işlem sonunda orijinal
  arşiv aynen geri geliyor.
- **Ren'Py font yaması orijinal motordaki gibi:** 1.0.3'te Türkçe harfi eksik tek bir font bile olsa oyunun bütün
  arayüz fontları DejaVu'ya zorlanıyordu. Artık yalnızca eksik font, `tl/<dil>/` içinde aynı adla değiştiriliyor
  (Ren'Py onu sadece o dil seçiliyken kullanır); zorlama yalnızca Çince/Japonca/Korece'de, gerektiğinde yapılıyor.
- **Ren'Py oyunu çeviriden sonra hâlâ İngilizce açılıyordu:** Türkçe yalnızca ilk açılışta bir kez seçiliyordu; kendi
  dil seçim ekranı olan oyunlarda (ör. English/中文/Русский) oyuncunun seçimi bunu kalıcı olarak
  eziyordu. Artık oyun, ayarlardaki Capri düğmesiyle başka dil seçilmedikçe her açılışta çeviri dilinde başlıyor.
  "English" düğmesi de oyunun hazır İngilizcesi varsa ona geçiyor (eskiden orijinal dile, ör. Rusçaya dönüyordu).
- **Gemini uzun oyunlarda çok yavaşlıyordu (18 bin satır 2 sa 22 dk):** hız sınırına takılınca anahtarın erişebildiği
  21 modelin hepsine (yavaş "pro" ve "düşünen" modeller dahil) kayıyordu; içerik filtresine takılan tek bir satır da
  40'lık partiyi 21 model × 4 tur denetip dakikalarca bekletiyordu. Artık orijinal motordaki gibi yalnızca hızlı
  (lite) modeller kullanılıyor (ayarlardan seçilen model başta kalır); engellenen satır tek istekle ayrıştırılıyor.
  Zaman aşımı 60 sn.
- **Ollama Latin harfi olmayan satırları atlıyordu:** Rusça/Japonca gibi kaynak satırlar çevrilmeden kalıyordu.
- **Ren'Py analizi bazı oyunlarda metinleri çok eksik sayıyordu:** yalnızca Latin harfli satırlar sayılıyordu, bu yüzden
  Rusça/Japonca/Çince yazılmış oyunlarda diyalogların neredeyse hepsi atlanıyordu (ör. 17.500 yerine 1.357). Artık her
  alfabe sayılıyor, ses/resim dosya yolları ayıklanıyor.
- **Paketli İngilizce kaynak kullanılmıyordu:** oyunun İngilizce çevirisi `scripts.rpa` içinde (`tl/english`) duruyorsa
  görülmüyor, çeviri oyunun orijinal dilinden yapılıyordu. Artık bu dosyalar geçici bir klasöre çıkarılıp kaynak olarak
  kullanılıyor (oyun klasörüne yazılmaz); analiz de bu İngilizce metinleri sayıyor.

## [1.0.3] - 2026-11-08
### Düzeltmeler
- **Gemini çok yavaştı ve yarıda takılıyordu:** 15 sn zaman aşımı uzun partileri kesiyor, biten iş çöpe gidip başka modelle
  baştan deneniyordu. Zaman aşımı 120 sn, parti 40 satır, anahtar başına 2 eşzamanlı istek, 2.5 Flash'ta "düşünme" kapalı.
  Ölçüm: 300 satır 8 sn (saniyede ~37 satır, önce ~7). Günlük kota dolunca sonsuz deneme yerine açık bir hata.
- **İlerleme:** çubuk yalnızca ileri gider ve partiler arasında gerçek hıza göre ilerler; ilk sonuç gelmeden tahmin geri sayılır,
  aşılırsa bunu söyler; sağlayıcı hız sınırı gibi durumlar çubuğun altında yazar.
- **Unity'de yazma adımı exe'de çöküyordu** (`UnityPy.resources` pakete girmemişti).
- **Güncelleme:** artık bat dosyası ve konsol penceresi yok; yeni sürümün kendi exe'si dosyaları değiştirir, bir dosya
  değiştirilemezse her şeyi geri alır, Capri yeniden açılınca sonucu bildirir.
- GPU paneli "Algılanıyor…"da kalıyordu.
- Eksik paket hatası "Yerel model ortamı eksik" olarak gösteriliyordu.
### Yeni
- Oyunu Capri'den açan **Oyna** düğmesi.
- Sözlük **içe / dışa aktarma** (JSON, CSV).
- Yama dışa aktarılınca **Toplulukla paylaş**: GitHub'da hazır bir konu açılır.
- OpenAI, Claude ve DeepL için **tahmini maliyet**.
- Çeviri biter ya da hata verirse, Capri arka plandaysa görev çubuğu yanıp söner.
- **Kalite editörü** Ren'Py dışındaki motorlarda ve Türkçe dışındaki dillerde de çalışıyor.
- Ren'Py'de Çince, Japonca, Korece için oyunun fontu yetmezse açık kaynak **Noto Sans** (onayla) indirilir.
- Tarama önerilerinde Ren'Py ve RPG Maker oyunları için yaklaşık satır sayısı.
- Yeni Durdur düğmesi.

## [1.0.2] - 2026-11-07
### Düzeltmeler
- Güncelleme penceresi: notlar kısa ve düzgün liste olarak görünüyor, düğmeler hizalı.
- Aynı anda iki Capri açıkken ikincisi birincinin (belki eski sürümün) arayüzüyle açılıyordu; artık her biri kendi arayüzünü kullanır.
- GitHub'ın derlediği pakette eksik kalan `numpy` eklendi (şifreli RPG Maker arşivleri hızlı açılır).

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
