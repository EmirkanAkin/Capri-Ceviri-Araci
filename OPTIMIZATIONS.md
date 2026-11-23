# Capri — Optimizasyon Denetimi

Kapsam: `src/` (özellikle 1.0.9 dalında eklenen motorlar: `engine_kag`, `archives`, `engine_godot`, `godot_formats`,
`engine_wolf`, `wolf_formats`, `text_fit`, `subtitles`, kuyruk ve editör kodu) ve `web/app.js`. Kodda değişiklik
yapılmadı; bu dosya yalnızca bulguları ve önerileri içerir.

## Uygulama durumu (2026-11-22)

Bütün bulgular uygulandı; testler `tests/test_optimizations.py` içinde.

| Bulgu | Durum | Ölçülen / doğrulanan |
|---|---|---|
| F1 terim denetimi | Uygulandı: `TermRules` (birleşik ön eleme + yalnızca geçen terimlerin kuralı) | 50 bin satır × 205 terim: 8,60 sn → 0,11 sn; sonuç eski yöntemle birebir aynı |
| F2 kuyruk yarışı | Uygulandı: kilit + yerinde değişen liste + her turda "sıradaki bekleyen" | Çalışırken çıkarılan oyun çevrilmiyor, eklenen çevriliyor (test) |
| F3 tarama | Uygulandı: satır sayısı parmak izine göre `scan.json`'da; Godot algılaması hafifletildi (`load_details`) | Değişmemiş oyun yeniden sayılmıyor (test). KiriKiri algılaması xp3 dizinlerini hâlâ açıyor (küçük) |
| F4 Godot G/Ç | Uygulandı: `Pck.opened()`, tablo dilleri önbellekte, analizdeki birimler yazmaya geçiyor | Çıkarım ve yazmada paket en çok 2 kez açılıyor (test) |
| F5 zip yazımı | Uygulandı: değişmeyen girdiler ham kopya, doğrudan geçici dosyaya akış; zip64'te genel yol | 80 MB paket: 0,07 sn, tepe bellek 2 MB; .NET zip okuyucusu doğruladı |
| F6 zip okuma | Uygulandı: dizin bir kez okunuyor, girdi CRC ile doğrulanıyor; tutamak açık bırakılmıyor | CRC bozukluğu yakalanıyor (test) |
| F7 editör bağlamı | Uygulandı: mtime anahtarlı bellek önbelleği; Ren'Py'de "çeviri klasörü yok" da önbellekte | 4 aramada sınır dosyası 1 kez okunuyor (test) |
| F8 editör araması | Uygulandı: küçük harfli kaynak/çeviri bir kez üretiliyor | Arama sonuçları aynı (test) |
| F9 çeviri sonu | Uygulandı: önbellek bir kez okunup üç denetime veriliyor | (test) |
| F10 girintili yazım | Uygulandı: `indent=None` | — |
| F11 kopya motor kodu | Uygulandı: `_translate_file_engine`, `_file_engine_analysis`, `_unreadable_analysis` | 216 → 179 satır; dört motorun uçtan uca testleri değişmeden geçiyor |
| F12 atomik yazma | Uygulandı: `src/fileio.py` (fsync + hata yolunda temizlik); 13 dosyadaki 26 yazım buna geçti | Yazma yarıda kalırsa asıl dosya korunuyor (test). Klasör hazırlama (yerel model, Unity okuyucusu) ayrı desen, dokunulmadı |
| F13 ölü kod | Uygulandı: 7 parça silindi | — |
| F14 WOLF çözümleme | Uygulandı: belge (boy + mtime) değişmediyse yeniden kullanılıyor | Analiz + yazma: dosya başına 1 çözümleme + 1 doğrulama (test) |
| F15 kuyruk soruları | Uygulandı: toplu çeviride soru en çok 60 sn bekliyor, soru oyunun notuna yazılıyor | (test) |
| F16 kuyruk arayüzü | Uygulandı: yalnızca kart düğmeleri güncelleniyor, `Set` ile arama | Arayüz testleri geçiyor |

Uygulama sırasında yakalanan iki ek kusur da düzeltildi: büyük "İ" ile başlayan terimler birleşik desende kaçıyordu
(özgün yazımla kurularak çözüldü) ve editör aramasında ayraç karakteri yanlış eşleşme üretebiliyordu.

---

Varsayımlar: Capri tek kullanıcılı bir masaüstü uygulaması; "ölçek" burada büyük oyunlar (50 bin–300 bin satır, yüzlerce
MB'lık paketler) ve geniş oyun kütüphaneleri (yüzlerce klasör) demektir. Ağ maliyeti bulut çeviri API'lerinin
çağrılarıdır.

---

### 1) Optimization Summary

Genel durum iyi: çeviri önbelleği, analiz önbelleği (parmak izine göre), toplu API çağrıları ve dosya yazımında
doğrulama zaten var. Sorunlar daha çok **büyük oyunlarda doğrusal olmayan büyüyen işler** ve **aynı işin tekrar
tekrar yapılması** biçiminde.

**En yüksek etkili 3 iyileştirme**
1. **Terim denetimi O(satır × terim):** 50 bin satır × 201 terimle her çeviri sonunda **7,4 sn** (ölçüldü). Tek birleşik
   desenle ön eleme 0,12 sn sürüyor → ~60 kat hızlanma.
2. **Toplu çeviri kuyruğunda yarış:** Çalışan iş parçacığı eski liste nesnesini dolaşırken arayüz `self._queue`'yu yeni
   bir listeyle değiştiriyor: sıradan çıkarılan oyun yine çevrilebiliyor, sonradan eklenen oyun atlanabiliyor.
   (Doğruluk sorunu; düzeltmesi küçük.)
3. **Oyun taraması her bulunan oyunu baştan sona çözümlüyor:** `quick_line_count` her öneri için motoru yeniden algılayıp
   bütün metni çıkarıyor (Godot'da bütün sahneler, WOLF'ta bütün haritalar LZ4 açılarak, Tyrano/KiriKiri'de bütün
   senaryolar). Algılama aşaması da Godot/KiriKiri'de kaynak ve dizin çözümlüyor.

**Değişiklik yapılmazsa en büyük risk:** Büyük oyunlarda çeviri bittikten sonra uygulamanın saniyelerce "donmuş" gibi
görünmesi (terim denetimi + taşma denetimi) ve kuyrukta kullanıcının çıkardığı bir oyunun yine de değiştirilmesi.

---

### 2) Findings (Prioritized)

#### F1 — Terim denetimi her satır için her terimi ayrı regex'le arıyor
* **Category:** Algorithm / CPU
* **Severity:** High
* **Impact:** Çeviri sonu gecikmesi, editörde "İncelenmelileri düzelt" ve canlı işaretleme süresi
* **Evidence:** `app_modern.term_inconsistencies` → `term_rules` + `term_lost`: her `(src, tr)` için
  `any(rx.search(src) and target not in folded for rx, target in rules)`. `_record_review` her çeviriden sonra bütün
  önbellekte çalıştırıyor; `_auto_character_names` 200'e kadar terim ekliyor. `_review_sources` aynı döngüyü tekrarlıyor.
* **Why it's inefficient:** n satır × m terim kadar regex araması. Ölçüm: 50.000 satır, 201 terim → 7,38 sn.
* **Recommended fix:** Terimlerden tek bir alternasyon deseni kur (`(?<!\w)(?:Uzun|Kısa…)(?!\w)`, büyük/küçük harf
  duyarlı ve duyarsız iki desen). Her satırda `finditer` ile yalnızca geçen terimleri bul, sonra yalnızca onlar için
  `target in folded` denetimini yap. Derlenmiş deseni terim sözlüğünün özetine göre önbelleğe al.
* **Tradeoffs / Risks:** İç içe terimlerde ("Ann" / "Anna") en uzun eşleşme önce gelmeli; mevcut testler
  (`test_lost_game_terms_are_flagged_for_review`) davranışı korur.
* **Expected impact estimate:** Bu adımda ~%95–98 azalma (7,4 sn → ~0,1–0,3 sn).
* **Removal Safety:** Safe (davranış aynı, testli)
* **Reuse Scope:** module (`term_inconsistencies`, `term_lost`, `_review_sources`, `editor_load`)

#### F2 — Kuyruk listesi iş parçacıkları arasında kilitsiz paylaşılıyor
* **Category:** Concurrency / Reliability
* **Severity:** High
* **Impact:** Doğruluk (istenmeyen oyunun çevrilmesi / eklenen oyunun atlanması)
* **Evidence:** `queue_start.task`: `for item in self._queue:`; `queue_remove` / `queue_clear`:
  `self._queue = [ … ]` (yeni nesne). `queue_add`: `self._queue.append(...)`.
* **Why it's inefficient:** Döngü eski listeyi tutar; yeniden atanan liste görünmez. Ayrıca durum güncellemeleri
  kilit olmadan aynı sözlüklere yazılıyor.
* **Recommended fix:** `threading.Lock` ile korunan tek liste; listeyi yeniden atamak yerine yerinde değiştir
  (`self._queue[:] = …`). Çalışan döngü her turda kilit altında "sıradaki bekleyen" öğeyi seçsin
  (`next(i for i in self._queue if i["state"] == "waiting")`), çıkarılmış öğe böylece seçilemez.
* **Tradeoffs / Risks:** Yok denecek kadar az; kilit yalnızca kısa liste işlemlerinde tutulur.
* **Expected impact estimate:** Hata sınıfını tamamen kapatır.
* **Removal Safety:** Safe
* **Reuse Scope:** local file (`app_modern.py` kuyruk bölümü)

#### F3 — Oyun taraması her öneri için tam metin çıkarımı yapıyor
* **Category:** I/O / CPU
* **Severity:** High (geniş kütüphanelerde)
* **Impact:** Açılış taraması süresi, disk okuma, CPU
* **Evidence:** `scan_games.work`: `for game in self._scan_found: game.update(lines=quick_line_count(game))`.
  `quick_line_count` Godot/WOLF/KAG için `detect_*` + `extract_texts` çağırıyor (sahne/harita/senaryo başına tam
  çözümleme). Algılamada da iş var: `detect_godot` → `_source_locale` → her çeviri tablosunu `read_resource` ile
  çözümlüyor; `detect_kirikiri` bütün xp3 dizinlerini açıp bir dosyayı okuyor; `detect_tyrano` exe'lerin zip dizinini
  okuyor.
* **Why it's inefficient:** Öneri listesinde yalnızca yaklaşık satır sayısı gösteriliyor; bunun için bütün oyunu
  çözümlemek gereksiz. Aynı oyun her taramada yeniden sayılıyor.
* **Recommended fix:** (a) Satır sayısını oyunun ana dosyalarının parmak izine (`game_files_stamp`) göre
  `scan.json` içinde önbelleğe al; değişmemiş oyun yeniden sayılmasın. (b) Algılamayı hafif tut: Godot'da yalnızca pck
  başlığı ve dizini, kaynak dili analiz aşamasına ertele. (c) Sayımı kullanıcı öneri kartını görünce ya da boşta
  (düşük öncelikli tek iş parçacığı) yap.
* **Tradeoffs / Risks:** İlk taramada sayı gecikmeli gelir; önbellek geçersiz kılma parmak izine bağlı (zaten var).
* **Expected impact estimate:** Tekrarlanan taramalarda %80–95 daha az okuma; ilk taramada orta kazanç.
* **Removal Safety:** Likely Safe
* **Reuse Scope:** service-wide (tarama, algılama)

#### F4 — Godot: aynı paket girdileri ve tablolar defalarca okunup çözümleniyor
* **Category:** I/O / CPU
* **Severity:** Medium
* **Impact:** Analiz ve yazma süresi büyük Godot oyunlarında
* **Evidence:** `Pck.read` her çağrıda dosyayı yeniden açıyor (`open` + `seek`). `_locale_of` bir tabloyu
  `_source_locale` içinde ve `extract_texts` içinde ayrı ayrı çözümlüyor. `write_translations` başında
  `extract_texts(info)` yeniden çağrılıyor: analizde zaten okunmuş bütün `.scn` sahneleri ikinci kez okunup çözümleniyor.
* **Why it's inefficient:** Binlerce sahneli oyunda binlerce `open` (Windows'ta virüs tarayıcısı her açılışı denetler)
  ve iki kat çözümleme.
* **Recommended fix:** `Pck` için tek dosya tanıtıcısı tutan bir okuyucu (bağlam yöneticisi) ya da `mmap`; tablo
  başına `(locale, Resource)` sonucunu `GodotGameInfo` içinde sakla; `write_translations`'a analizde üretilen birimleri
  (`units`) parametre olarak geçir, yalnızca birimler yoksa yeniden çıkar.
* **Tradeoffs / Risks:** Açık tanıtıcı yazma sırasında kapatılmalı (yama ayrı dosyaya yazıldığı için çakışma yok).
* **Expected impact estimate:** Godot yazma adımında ~%50 daha az çözümleme; açılış sayısında 10–100 kat azalma.
* **Removal Safety:** Safe
* **Reuse Scope:** module (`godot_formats`, `engine_godot`)

#### F5 — Zip / NW.js exe yeniden yazımı bütün girdileri açıp yeniden sıkıştırıyor ve exe'de tamamını bellekte tutuyor
* **Category:** Memory / CPU / I/O
* **Severity:** Medium (büyük Tyrano oyunlarında High)
* **Impact:** Yazma süresi, en yüksek bellek kullanımı
* **Evidence:** `archives.ZipContainer.write`: her girdi için `zin.read(info)` + `zout.writestr(clone, data)`
  (DEFLATE yeniden sıkıştırma). Exe yolunda `buffer = io.BytesIO()`: yeni zip'in tamamı RAM'de toplanıp sonra yazılıyor.
* **Why it's inefficient:** Yalnızca birkaç `.ks` dosyası değişirken yüzlerce MB'lık görsel/ses yeniden sıkıştırılıyor;
  500 MB'lık pakette ~500 MB+ ek bellek.
* **Recommended fix:** (a) Exe yolunda BytesIO yerine geçici dosyaya yaz, sonra stub ile birleştir (akış hâlinde
  kopyala). (b) Değişmeyen girdileri sıkıştırılmış hâlleriyle ham kopyala (yerel başlık + veri bloğunu kaynaktan aynen
  aktarıp merkezi dizini yeniden kur; Python'da `zipfile` bunu doğrudan sunmadığı için küçük bir yardımcı gerekir) ya da
  en azından `ZIP_STORED` girdileri ve zaten sıkıştırılmış biçimleri (png/ogg/webm) `ZIP_STORED` bırak.
* **Tradeoffs / Risks:** Ham kopya için merkezi dizin ofsetleri dikkatle yeniden yazılmalı; mevcut `testzip()`
  doğrulaması korunmalı.
* **Expected impact estimate:** Bellek: O(paket) → O(en büyük girdi). Süre: %70–95 azalma (değişen dosya oranına bağlı).
* **Removal Safety:** Needs Verification (gerçek NW.js oyunuyla açılış testi)
* **Reuse Scope:** module (`archives`)

#### F6 — Zip kabı her `names()` / `read()` çağrısında zip dizinini yeniden çözümlüyor
* **Category:** I/O
* **Severity:** Medium
* **Evidence:** `archives.ZipContainer`: `zipfile.ZipFile(self.path)` beş ayrı yerde açılıyor; `load_scenario`
  senaryo başına `read()` çağırıyor.
* **Why it's inefficient:** Binlerce girdili bir exe'de her okuma merkezi dizini baştan okuyor (N senaryo × dizin boyu).
* **Recommended fix:** `ZipFile` nesnesini kabın ömrü boyunca bir kez aç (ya da `infolist()` + ofsetleri önbelleğe al),
  yazmadan önce kapat.
* **Tradeoffs / Risks:** Açık tanıtıcı Windows'ta dosya değiştirmeyi engeller; `write()` başında kapatılmalı.
* **Expected impact estimate:** Senaryo okuma süresinde 2–10 kat iyileşme (girdi sayısına bağlı).
* **Removal Safety:** Safe
* **Reuse Scope:** local file

#### F7 — Editör her tuşa basışta tablo ve sınır dosyalarını yeniden okuyor; Ren'Py'de analiz tekrar edebiliyor
* **Category:** I/O / Caching / Frontend gecikmesi
* **Severity:** Medium
* **Evidence:** `editor_load` → `_review_context` → `_fit_limits` (her çağrıda `load_limits` = JSON okuma) +
  `_project_glossary()` (JSON okuma) + `term_rules` (yeniden derleme). Ren'Py'de sınır dosyası yoksa
  `_fit_limits` her çağrıda `analyze_game(...)` çalıştırıyor; `tl` klasörü yoksa dosya hiç yazılmadığından **her
  aramada** analiz yineleniyor. Arama kutusu 300 ms'lik gecikmeyle `editor_load` çağırıyor.
* **Why it's inefficient:** 50 bin satırlık RPG Maker sınır dosyası (~2 MB JSON) her tuş vuruşunda çözümleniyor;
  Ren'Py'de bütün oyun klasörü taranabiliyor.
* **Recommended fix:** `_review_context` sonucunu `(önbellek dosyası mtime, sınır dosyası mtime, sözlük mtime)`
  anahtarıyla bellekte tut (mevcut `_editor_cache` gibi). Ren'Py için "tl yok" sonucunu da (negatif) önbelleğe al.
* **Tradeoffs / Risks:** Önbellek anahtarına mtime dahil olduğu için bayat veri riski düşük.
* **Expected impact estimate:** Arama gecikmesinde büyük oyunlarda %50–90 azalma; Ren'Py kenar durumunda saniyeler.
* **Removal Safety:** Safe
* **Reuse Scope:** local file

#### F8 — Editör araması her seferinde bütün önbelleği doğrusal tarıyor (önceden var olan)
* **Category:** Algorithm / CPU
* **Severity:** Low–Medium
* **Evidence:** `editor_load`: `for src in list(cache) + [...]` + her satırda `casefold()` iki kez.
* **Why it's inefficient:** 200 bin satırda tuş başına ~400 bin `casefold`; liste her çağrıda yeniden kuruluyor.
* **Recommended fix:** `_editor_data` önbelleğinde `(src, src.casefold(), tr.casefold())` üçlülerini bir kez üret;
  aramayı bunlar üzerinde yap. İsteğe bağlı: sonuçlar `limit` kadar dolunca dur, toplamı ayrıca say.
* **Tradeoffs / Risks:** Bellek: önbelleğin iki katı kadar dize (büyük oyunlarda onlarca MB) — kabul edilebilir.
* **Expected impact estimate:** Arama başına %50–70 CPU azalması.
* **Removal Safety:** Safe
* **Reuse Scope:** local file

#### F9 — Çeviri sonrası denetimler sırayla ve ayrı ayrı bütün önbelleği dolaşıyor
* **Category:** CPU / I/O
* **Severity:** Medium
* **Evidence:** `_translate_game` sonunda: `_overflow_after_translate` (önbelleği okur + Ren'Py'de bütün `tl` dosyalarını
  yeniden okur), `_record_review` (önbelleği yeniden okur, F1'i çalıştırır), `_learn_memory` (önbelleği üçüncü kez okur).
* **Why it's inefficient:** Aynı JSON dosyası (büyük oyunlarda 10–50 MB) üç kez okunup çözümleniyor.
* **Recommended fix:** Önbelleği bir kez oku, üç işleve parametre olarak geçir.
* **Tradeoffs / Risks:** Yok.
* **Expected impact estimate:** Çeviri sonu adımında %30–60 azalma (F1 ile birlikte).
* **Removal Safety:** Safe
* **Reuse Scope:** local file

#### F10 — `_seed_memory` bütün önbelleği girintili JSON olarak yeniden yazıyor
* **Category:** I/O
* **Severity:** Low
* **Evidence:** `_seed_memory`: `_write_json(cache_path, cache)` (varsayılan `indent=2`); başka yerlerde aynı dosya
  `indent=None` ile yazılıyor.
* **Why it's inefficient:** Büyük önbellekte dosya boyu %20–40 artıyor ve yazma uzuyor; yalnızca birkaç satır eklenmişken
  dosyanın tamamı yeniden yazılıyor.
* **Recommended fix:** `indent=None`; eklenecek satır yoksa (zaten öyle) yazma.
* **Expected impact estimate:** Küçük; disk ve süre.
* **Removal Safety:** Safe
* **Reuse Scope:** local file

#### F11 — Yeni motorların analiz/çeviri/uygulama yöntemleri neredeyse kopya
* **Category:** Maintainability (Reuse Opportunity)
* **Severity:** Medium
* **Evidence:** `_analyze_kag` / `_analyze_godot` / `_analyze_wolf`, `_translate_kag` / `_translate_godot` /
  `_translate_wolf`: aynı adımlar (şifreli/arşivli durum sözlüğü, `detect_source_language` + `TURKISH_ONLY_MODELS`
  denetimi (3 kopya), yedek, sözlük seçimi, `_translate_strings`, kalite geçişi, `game["texts"]=None`).
* **Why it's inefficient:** Bir kuralı değiştirmek (ör. kaynak dil denetimi) üç yerde değişiklik ister; sapma riski.
* **Recommended fix:** Küçük bir `FileEngine` tanımı (algıla, çıkar, yaz, yedeklenecek/oluşturulacak dosyalar, etiket
  deseni, ek talimat) ve tek bir `_translate_file_engine(spec)` / `_analyze_file_engine(spec)`.
* **Tradeoffs / Risks:** Soyutlama yalnızca bu üç (ileride daha fazla) motoru kapsamalı; Ren'Py/Unity'ye dokunmamalı.
* **Expected impact estimate:** ~150 satır azalır; yeni motor eklemek tek tanım olur.
* **Removal Safety:** Likely Safe (mevcut uçtan uca testler kapsıyor)
* **Reuse Scope:** module

#### F12 — Atomik dosya yazımı 14 dosyada ~30 kez elle yazılmış
* **Category:** Maintainability / Reliability (Reuse Opportunity)
* **Severity:** Low–Medium
* **Evidence:** `.tmp` / `.capri_tmp` + `replace` deseni: `app_modern`, `archives._replace_file`,
  `engine_unity._replace_file`, `engine_wolf.write_translations`, `subtitles.save`, `godot_formats.write_pck`,
  `text_fit.save_limits`, `library`, `providers`, `engine_renpy`… Bazılarında `fsync` var, bazılarında yok; bazıları
  hata yolunda geçici dosyayı silmiyor.
* **Recommended fix:** Tek `atomic_write(path, data | writer)` yardımcısı (fsync + hata yolunda temizlik).
* **Expected impact estimate:** Güvenilirlik tutarlılığı; elektrik kesintisinde bozuk dosya riskinin her yerde aynı
  düzeyde düşmesi.
* **Removal Safety:** Safe
* **Reuse Scope:** service-wide

#### F13 — Kullanılmayan kod
* **Category:** Dead Code
* **Severity:** Low
* **Evidence (grep ile doğrulandı):**
  * `godot_formats.translation_kind` — hiç çağrılmıyor.
  * `text_fit.limits_for` — yalnızca `__all__`'da.
  * `engine_godot.character_names` — çağrılmıyor (uygulama yalnızca KAG'ınkini kullanıyor).
  * `engine_kag.KagGameInfo.extra` — hiç yazılıp okunmuyor.
  * `engine_godot.GodotGameInfo.has_override` — yazılıyor, okunmuyor.
  * `godot_formats.Resource.fmt` — saklanıyor, kullanılmıyor.
  * `kag_script.TEXT_ATTRS` içindeki boş girdiler (`"dialog_config": ()`, `"glyph": ()`).
* **Recommended fix:** Kaldır.
* **Removal Safety:** Safe (hepsi tek dosya içinde; testler kullanmıyor)
* **Reuse Scope:** local file

#### F14 — WOLF dosyaları üç kez çözümleniyor
* **Category:** CPU
* **Severity:** Low
* **Evidence:** `extract_texts` → `_docs` (LZ4 aç + çözümle), `write_translations` → `_docs` (yeniden), `rebuild`
  içinde doğrulama için bir kez daha.
* **Why it's inefficient:** Dosyalar küçük (örnek oyunda < 1 MB), bu yüzden etkisi düşük; doğrulama çözümlemesi
  bilinçli bir güvenlik adımı ve korunmalı.
* **Recommended fix:** Analizde üretilen `WolfDoc` nesnelerini yazmaya kadar sakla (dosya mtime'ı değişmediyse).
* **Removal Safety:** Safe
* **Reuse Scope:** local file

#### F15 — Kuyruk gözetimsizken onay soruları 5 dakika bekletiyor
* **Category:** Reliability / Cost
* **Severity:** Low–Medium
* **Evidence:** `_ask(..., timeout=300)` kuyruktaki her oyunda çağrılabiliyor (şifreli RGSS arşivi, font indirme,
  pahalı çeviri onayı, BepInEx).
* **Why it's inefficient:** Gece çalışan bir kuyrukta her soru 5 dakika boşta bekliyor, sonra oyun atlanıyor.
* **Recommended fix:** Kuyruğu başlatırken "sorulara verilecek varsayılan yanıtlar"ı bir kez sor (ör. arşiv açma: evet,
  ücretli çeviri: hayır) ya da kuyruk modunda `_ask`'i hemen "hayır" dönecek biçimde kısa zaman aşımıyla çalıştır ve
  oyunu "Onay gerekiyor" notuyla bırak.
* **Removal Safety:** Likely Safe
* **Reuse Scope:** local file

#### F16 — Arayüz: kuyruk olayı her durum değişiminde bütün kütüphane ızgarasını yeniden çiziyor
* **Category:** Frontend
* **Severity:** Low
* **Evidence:** `HANDLERS.queue` → `later(renderLibraries)`; `cardHtml` her kart için `inQueue` (liste taraması).
* **Why it's inefficient:** Yüzlerce kartlı kütüphanede her kuyruk adımında bütün kartların `innerHTML`'i yeniden kuruluyor.
* **Recommended fix:** Yalnızca kart düğmesinin `on` sınıfını güncelle; `inQueue` için anahtar kümesi (`Set`).
* **Removal Safety:** Safe
* **Reuse Scope:** local file (`web/app.js`)

---

### 3) Quick Wins (Do First)

| Sıra | Değişiklik | Süre | Etki |
|---|---|---|---|
| 1 | F2 kuyruk kilidi + yerinde liste | 20 dk | Doğruluk hatası kapanır |
| 2 | F1 birleşik terim deseni | 30 dk | Çeviri sonu 7 sn → ~0,2 sn (50 bin satır) |
| 3 | F9 önbelleği bir kez okuyup geçir | 15 dk | Büyük oyunlarda çeviri sonu ~yarıya iner |
| 4 | F7 `_review_context` önbelleği + Ren'Py negatif önbellek | 30 dk | Editör araması akıcı |
| 5 | F13 ölü kod temizliği, F10 `indent=None` | 10 dk | Bakım, küçük I/O |
| 6 | F6 zip nesnesini bir kez aç | 20 dk | Tyrano exe/package.nw okumaları hızlanır |

### 4) Deeper Optimizations (Do Next)

* **F3 tarama önbelleği ve hafif algılama:** satır sayısının parmak izine göre saklanması; algılamanın yalnızca başlık
  okuması; sayımın boşta yapılması.
* **F5 akışlı zip yeniden yazımı:** ham girdi kopyası ve geçici dosyaya yazım (gerçek bir NW.js oyunuyla doğrulanarak).
* **F11 ortak dosya motoru şablonu:** yeni motor eklemeyi tek tanıma indirir; F4/F14'teki "analizde üretileni yazmaya
  taşı" iyileştirmesini de doğal olarak sağlar.
* **F12 tek atomik yazma yardımcısı** ve kademeli geçiş.
* **F15 kuyruk için önceden verilmiş yanıtlar** (gözetimsiz çalışma modu).

### 5) Validation Plan

**Kıyas testleri (yeni `tests/bench_*.py`, CI'da `-m slow` ile):**
* F1: 50.000 sentetik satır × 200 terim; `term_inconsistencies` süresi (bugün 7,38 sn bu makinede). Hedef < 0,5 sn,
  sonuç listesi eskisiyle **birebir aynı**.
* F7/F8: 200.000 satırlık önbellekle `editor_load(query=…)` ortalama süresi (10 farklı sorgu).
* F5: 500 MB'lık sentetik zip (çoğu `ZIP_STORED` görseller) + 10 `.ks`; `tracemalloc` tepe belleği ve süre.
* F3: 300 sahte oyun klasörü (her motordan) ile `scan_games` süresi; ikinci taramada okunan bayt (`psutil` I/O sayaçları).
* F4: 2.000 sahneli sentetik pck ile `extract_texts` + `write_translations` süresi ve `open` sayısı (`builtins.open`
  sayacıyla).

**Profil:** `python -m cProfile -o out.prof` ile analiz ve çeviri sonu adımları; `snakeviz` ile sıcak işlevler.
Windows'ta Defender etkisi için aynı kıyas Defender dışlamalı ve dışlamasız çalıştırılmalı.

**Önce/sonra metrikler:** çeviri sonu adımının süresi (günlükte zaten süre var), editör arama gecikmesi, tarama süresi,
tepe bellek, yazılan bayt.

**Doğruluk testleri (mevcutlar korunmalı + yeniler):**
* `test_lost_game_terms_are_flagged_for_review` ve `test_quality_tools.py` (terim/taşma/inceleme) aynen geçmeli.
* F2 için yeni test: kuyruk çalışırken `queue_remove` edilen oyunun **çevrilmediği**, `queue_add` edilenin **çevrildiği**
  (iş parçacığı içinde `_translate_game` yerine olay bekleyen sahte işlevle).
* F5/F6: `test_kag.py::test_zip_and_exe_appended_zip_roundtrip` + değişmeyen girdilerin baytlarının aynı kaldığını
  doğrulayan yeni test.
* F4/F14: `test_godot.py`, `test_wolf.py` uçtan uca testleri.

### 6) Optimized Code / Patch (when possible)

Aşağıdakiler öneridir; uygulanmadı.

**F1 — birleşik terim deseni (`app_modern.py`)**
```python
def term_rules(terms):
    """(desen, {kaynak_casefold: hedef_casefold}) — büyük harfle başlayanlar harf duyarlı, diğerleri duyarsız."""
    exact, loose = {}, {}
    for source, target in (terms or {}).items():
        source, target = str(source).strip(), str(target or "").strip()
        if len(source) >= 3 and target:
            (exact if source[:1].isupper() else loose)[source] = target.casefold()
    def build(items, flags):
        if not items:
            return None
        alt = "|".join(re.escape(s) for s in sorted(items, key=len, reverse=True))
        return re.compile(rf"(?<!\w)(?:{alt})(?!\w)", flags)
    return (build(exact, 0), exact, build(loose, re.IGNORECASE), {k.casefold(): v for k, v in loose.items()})

def term_lost(src, tr, rules):
    if not rules or not tr or tr == src:
        return False
    rx_exact, exact, rx_loose, loose = rules
    folded = tr.casefold()
    if rx_exact and any(exact[m.group(0)] not in folded for m in rx_exact.finditer(src)):
        return True
    return bool(rx_loose and any(loose[m.group(0).casefold()] not in folded for m in rx_loose.finditer(src)))
```
Değişen: m regex yerine satır başına en fazla 2 arama. Not: alternasyonda en uzun terim önce geldiği için
"Anna" satırı "Ann" kuralına takılmaz; bugünkü davranış da bu (`(?<!\w)…(?!\w)` sınırları).

**F2 — kuyruk (`app_modern.py`)**
```python
self._queue_lock = threading.Lock()

def _next_waiting(self):
    with self._queue_lock:
        return next((i for i in self._queue if i["state"] == "waiting"), None)

def queue_remove(self, path):
    key = ProjectLibrary.key(path)
    with self._queue_lock:
        self._queue[:] = [i for i in self._queue if ProjectLibrary.key(i["path"]) != key or i["state"] == "running"]
    ...

# task():
while not self._cancel.is_set():
    item = self._next_waiting()
    if item is None:
        break
    outcome, note = self._queue_one(item)
    ...
```

**F9 — çeviri sonu (`_translate_game`)**
```python
cache = _read_json(self._cache_path(), {})
overflow = self._overflow_after_translate(game, cache)
self._record_review(self._cache_path(), failed, terms, forced | set(overflow), cache=cache)
self._safely(lambda: self._learn_memory(self._cache_path(), cache=cache))
```

**F13 — silinecekler:** `godot_formats.translation_kind`, `text_fit.limits_for` (+ `__all__` girdisi),
`engine_godot.character_names`, `KagGameInfo.extra`, `GodotGameInfo.has_override` (ve `detect_godot`'daki ataması),
`Resource.fmt`, `TEXT_ATTRS`'taki boş girdiler.
