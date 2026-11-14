"""Capri arayüzünün İngilizce sözlüğü (anahtar: Türkçe arayüz metni). Diğer diller bundan üretilir (bkz. i18n.py).
{0}, {1}… değişken yerleridir; çeviride aynen korunmalıdır."""

EN = {
    # ── Genel gezinme ve düğmeler ───────────────────────────────────────────
    "Stüdyo": "Studio", "Kütüphane": "Library", "Çeviri Editörü": "Translation Editor", "Çeviri editörü": "Translation editor",
    "Yedekler": "Backups", "Araçlar": "Tools", "Sözlük": "Glossary", "Metin Çevirici": "Text Translator",
    "Metin çevirici": "Text translator", "Ekran Çevirisi": "Screen Translation", "Ekran çevirisi": "Screen translation",
    "JSON Çevirici": "JSON Translator", "JSON çevirici": "JSON translator", "Sistem": "System", "Sağlayıcılar": "Providers",
    "Yerel Modeller": "Local Models", "Yerel modeller": "Local models", "Rehber": "Guide", "Oyun ekle": "Add game",
    "Metin çevir": "Translate text", "Kütüphanede ara": "Search library", "Bildirimler": "Notifications",
    "Kapat": "Close", "Sonra": "Later", "Vazgeç": "Cancel", "Onayla": "Confirm", "Kaydet": "Save", "Kopyala": "Copy",
    "Temizle": "Clear", "Yenile": "Refresh", "Tekrar dene": "Try again", "Geri al": "Undo", "Göster": "Show",
    "Tümü": "All", "Tümünü gör": "See all", "Önceki": "Previous", "Sonraki": "Next", "Ayarla": "Set", "Ayarlar": "Settings",
    "Menü": "Menu", "Küçült": "Minimize", "Ekranı kapla": "Maximize", "Çıkış": "Exit", "Durdur": "Stop", "Çevir": "Translate",
    "İçe aktar": "Import", "Dışa aktar": "Export", "Dosya seç": "Choose file", "Klasör seç": "Choose folder",
    "Klasörü aç": "Open folder", "Editörde aç": "Open in editor", "Güncelle": "Update", "Hazır": "Ready", "Kurulu": "Installed",
    "Kurulu değil": "Not installed", "Kuruluyor…": "Installing…", "Kullanılamıyor": "Unavailable", "Bulunamadı": "Not found",
    "Kayıtlı": "Saved", "Açıldı": "Opened", "Tamamlandı": "Completed", "Çevrildi": "Translated", "Çevriliyor": "Translating",
    "Çevriliyor…": "Translating…", "Bekleniyor": "Waiting", "Durduruldu": "Stopped", "Durduruldu.": "Stopped.",
    "Durduruluyor…": "Stopping…", "Lütfen bekle…": "Please wait…", "Hazırlanıyor…": "Preparing…", "hazırlanıyor…": "preparing…",
    "hesaplanıyor…": "calculating…", "az önce": "just now", "az kaldı": "almost done", "yaklaşık": "about",
    "{0} dk önce": "{0} min ago", "{0} sa önce": "{0} h ago", "Kontrol ediliyor…": "Checking…",
    "Kontrol edilemedi": "Couldn't check", "Durum": "Status", "Donanım": "Hardware", "Aktif motor": "Active engine",
    "Anahtar gerekli": "Key required", "Motoru değiştir": "Change engine", "Algılanıyor…": "Detecting…", "Genel": "General",
    "Yerel": "Local", "Bulut": "Cloud", "Model": "Model", "Proje": "Projects", "Projelerim": "My projects",
    "Yeni proje": "New project", "Tüm projeler": "All projects", "Yenilikler": "What's new", "Bu sürümde": "In this version",
    "Henüz bildirim yok.": "No notifications yet.", "Geçmişi temizle": "Clear history", "Teknik günlük": "Technical log",
    "Teknik ayrıntılar": "Technical details", "Ayrıntılı işlem kaydı": "Detailed activity log",
    "Günlük panoya kopyalandı": "Log copied to clipboard", "İşlem": "Activity", "Seçenekler": "Options", "Bitince": "When finished",
    "Hoş geldin": "Welcome", "Nasıl çalışır?": "How it works?", "Oyununu Türkçeye çevir.": "Translate your game.",
    "Oyun klasörünü seç; motoru otomatik algılayıp yedekleyelim ve seçtiğin yapay zekayla tek tıkla çevirelim.":
        "Pick your game folder; we detect the engine, back it up and translate it in one click with the AI you choose.",
    "Oyun klasörünü seç": "Pick the game folder", "Otomatik analiz": "Automatic analysis", "Tek tıkla çeviri": "One-click translation",
    "etiketler korunur": "tags are preserved", "Ekran (OCR)": "Screen (OCR)", "Proje açılamadı": "Couldn't open project",
    "kütüphanede ara ·": "search library ·", "oyun ekle ·": "add game ·", "bildirimler ·": "notifications ·",
    "vitrinde gezin ·": "browse showcase ·", "paneli kapat.": "close panel.", "Her yerde:": "Everywhere:",

    # ── İstatistikler ve kütüphane ─────────────────────────────────────────
    "Çevrilen oyun": "Translated games", "Önbellekteki çeviri": "Cached translations", "Oyuna yazılan satır": "Lines written to games",
    "Son çeviriler": "Recent translations", "Son çevirinin süresi": "Last translation took",
    "Analiz ettiğin ve çevirdiğin oyunlar. Bir karta tıklayarak projeyi aç.":
        "Games you analyzed and translated. Click a card to open the project.",
    "Kütüphanen henüz boş": "Your library is empty",
    "İlk oyununu ekle; motor otomatik algılanır, kapak görseli Steam'den gelir.":
        "Add your first game; the engine is detected automatically and cover art comes from Steam.",
    "Henüz proje yok. “Oyun ekle” ile ilk oyununu seç.": "No projects yet. Choose your first game with “Add game”.",
    "Bilgisayarındaki oyunlar": "Games on your computer", "Açılışta otomatik tara": "Scan automatically at startup",
    "Steam, Epic, GOG ve Games/Oyunlar klasörleri taranır; yalnızca okunur, hiçbir dosya değişmez.":
        "Steam, Epic, GOG and Games folders are scanned read-only; no file is changed.",
    "Yeni oyun bulunamadı. Oyunların başka bir yerdeyse klasör ekleyebilirsin.":
        "No new games found. If your games are somewhere else, you can add a folder.",
    "{0} yeni oyun bulundu": "{0} new games found", "Kütüphane sayfasından tek tıkla ekleyebilirsin.":
        "You can add them from the Library page in one click.",
    "Şimdi tara": "Scan now", "Klasör ekle": "Add folder", "Oyun klasörü": "Game folder", "Oyun klasörünü aç": "Open game folder",
    "Önceki çeviri yarıda kaldı; açıp kaldığı yerden devam edebilirsin.":
        "The previous translation was interrupted; open it to continue where it left off.",
    "Yeni Oyun · Devam Et · Ayarlar": "New Game · Continue · Settings",

    # ── Çeviri ayarları ────────────────────────────────────────────────────
    "Çeviri ayarları": "Translation settings", "Kaynak dil": "Source language", "Hedef dil": "Target language",
    "Çeviri motoru": "Translation engine", "Çeviri motoru seç": "Choose a translation engine",
    "Çeviri öncesi yedek al": "Back up before translating", "Değişen dosyalar tek tıkla orijinaline döner.":
        "Changed files return to their originals in one click.",
    "Kalite editörü geçişi": "Quality editor pass",
    "Sorunlu taslakları (İngilizce kalıntı, robotik ifade) bağlamıyla bir sohbet modeline düzelttirir.":
        "Has a chat model fix problematic drafts (leftover English, robotic phrasing) with their context.",
    "Yetişkin (NSFW) sözlüğü": "Adult (NSFW) glossary", "Argo ve yetişkin sahneleri doğal günlük dille aktarır.":
        "Renders slang and adult scenes in natural everyday language.",
    "Ortak çeviri belleği": "Shared translation memory",
    "\"Save\", \"Options\" gibi arayüz metinleri bir oyunda çevrilince diğer oyunlarda yeniden çevrilmez.":
        "Interface text like \"Save\" or \"Options\" is translated once and reused in other games.",
    "Ses çal": "Play a sound", "Çeviri bitince ya da durunca kısa, yumuşak bir ses.": "A short, soft sound when a translation finishes or stops.",
    "Windows bildirimi göster": "Show Windows notification",
    "Capri arka plandayken çeviri bitince ekranın köşesinde bildirim çıkar.":
        "When Capri is in the background, a notification appears in the corner when the translation finishes.",
    "Analiz": "Analysis",
    "Bir oyun eklediğinde burada kaç satır çevrileceğini, ne kadar süreceğini ve dikkat etmen gereken bir şey olup olmadığını görürsün.":
        "When you add a game, you'll see here how many lines will be translated, how long it takes and anything to watch out for.",
    "Otomatik": "Auto", "Ana motorla aynı ({0})": "Same as main engine ({0})",

    # ── Analiz paneli ──────────────────────────────────────────────────────
    "Oyun motoru": "Game engine", "Çevrilecek metin": "Text to translate", "Hazır çeviri": "Ready translations",
    "Tahmini süre": "Estimated time", "Türkçe harfler": "Turkish letters", "Oyunun fontu destekliyor": "The game's font supports them",
    "Önbellekte; tekrar ücret ödemezsin": "Cached; you won't pay again", "Bu motorla henüz çevrilmiş satır yok":
        "No lines translated with this engine yet",
    "Tüm satırlar önbellekte": "All lines are cached",
    "Tüm satırlar önbellekte hazır; çeviri birkaç saniyede biter, API harcanmaz.":
        "All lines are ready in the cache; the translation finishes in seconds without using the API.",
    "Analiz bekleniyor…": "Waiting for analysis…", "Analiz ediliyor": "Analyzing", "Oyun analiz ediliyor": "Analyzing game",
    "Oyunun metinleri taranıyor. Büyük oyunlarda biraz sürebilir; bu sırada başka bir projeye geçebilirsin.":
        "Scanning the game's text. Large games may take a while; you can switch to another project meanwhile.",
    "Metinler, fontlar ve dosya yapısı kontrol ediliyor. Sonucu bir sonraki açılışta anında gelir.":
        "Checking text, fonts and file layout. The result appears instantly next time.",
    "Analiz tamamlanamadı: {0}": "Analysis couldn't finish: {0}", "{0} satır ({1} benzersiz) bulundu.": "{0} lines ({1} unique) found.",
    "Toplam {0}{1} satır · {2}{3} kelime": "Total {0}{1} lines · {2}{3} words", "{0} satır": "{0} lines",
    "{0} betik dosyası": "{0} script files", "{0} betik dosyası bulundu.": "{0} script files found.",
    "{0} .rpy / {1} .rpyc betik dosyası, {2} RPA arşivi": "{0} .rpy / {1} .rpyc script files, {2} RPA archives",
    "Çevrilebilir metin: {0} satır ({1} benzersiz)": "Translatable text: {0} lines ({1} unique)",
    "Lokalizasyon varlığı: {0}": "Localization assets: {0}", "Mevcut Türkçe çeviri dosyası: {0}": "Existing translation files: {0}",
    "Maliyet: {0} (fiyatlar değişebilir)": "Cost: {0} (prices may change)",
    "Oyunda daha önce yapılmış {0} çeviri dosyaları var; mevcut çalışmanın üzerine devam edilir.":
        "The game already has {0} translation files; work continues on top of them.",
    "{0} fontta {1} harfleri eksik. Capri çeviride otomatik font yaması uygular.":
        "{0} fonts are missing {1} letters. Capri applies an automatic font patch while translating.",
    "Oyunun fontları {0} karakterlerini içermiyor. Bu yazı sistemi için otomatik font yaması yok; oyuna uygun bir font eklemezsen metinler görünmeyebilir.":
        "The game's fonts don't contain {0} characters. There is no automatic font patch for this script; without a suitable font the text may not show.",
    "Utage senaryosu bulundu: çeviri oyunun İngilizce metninin yerine yazılır. Oyunda dil seçeneğinden English'i seçince Türkçe görünür.":
        "Utage scenario found: the translation replaces the game's English text. Choose English in the game's language option to see it.",
    "Utage senaryosu dosyada açık: {0} satır doğrudan çevrilir (BepInEx gerekmez). Oyunda dil olarak English seçilince Türkçe görünür.":
        "Utage scenario is readable: {0} lines are translated directly (no BepInEx needed). Choose English in the game to see the translation.",
    "Veri dosyaları şifreli {0} arşivinde. Çeviri başlarken Capri arşivi oyun klasörüne açar (sana sorulur); orijinal arşiv yedeklenir.":
        "Data files are in an encrypted {0} archive. When translation starts, Capri extracts it into the game folder (you'll be asked); the original is backed up.",
    "Veriler şifreli {0} arşivinde. Çeviri başlarken arşiv oyun klasörüne açılır (iznin istenir), orijinali yedeklenir.":
        "Data is in an encrypted {0} archive. When translation starts it is extracted into the game folder (with your permission); the original is backed up.",
    "Şifreli arşiv · {0}": "Encrypted archive · {0}", "Metinler .pak paketlerinde": "Text is inside .pak packages",
    "Dosyalarda okunabilir metin yok": "No readable text in the files", "Eksik: {0}{1}": "Missing: {0}{1}",
    "Unreal {0} · Proje: {1}": "Unreal {0} · Project: {1}", "PAK: {0} · IoStore: {1}": "PAK: {0} · IoStore: {1}",
    "{0} · Unity {1}": "{0} · Unity {1}", "{0} · {1} harita · {2} JSON": "{0} · {1} maps · {2} JSON",
    ".locres dosyası: {0}": ".locres files: {0}", "Açıkta .locres bulunamadı.": "No loose .locres files found.",

    # ── Çeviri akışı ve kahraman alanı ─────────────────────────────────────
    "Çeviriyi başlat": "Start translation", "Kaldığı yerden devam et": "Continue where it left off", "Baştan çevir": "Translate again",
    "Editör": "Editor", "Orijinale dön": "Revert to original", "Oyna": "Play", "Çeviri tamamlandı": "Translation completed",
    "Çeviri devam ediyor": "Translation in progress", "Çeviri başlatılıyor": "Starting translation", "Çeviriye hazır": "Ready to translate",
    "Çeviriye hazır: {0} satır, {1}. İstediğin an durdurabilirsin.": "Ready to translate: {0} lines, {1}. You can stop anytime.",
    "Çeviri başarısız": "Translation failed", "İşlem yapılamadı": "Couldn't complete",
    "Çeviri durdu; şu an çalışan bir işlem yok.": "Translation stopped; nothing is running right now.",
    "Yapılan çeviriler kaydedildi; devam ettiğinde kaldığı yerden sürer.":
        "Translations so far are saved; continuing picks up where it left off.",
    "Geçerli parti bitince duracak. Yapılan çeviriler kaydediliyor.": "It will stop after the current batch. Translations are being saved.",
    "Durduruluyor… (geçerli parti bitince)": "Stopping… (after the current batch)", "Kalan süre": "Time left", "Geçen": "Elapsed",
    "Süre": "Time", "Hız": "Speed", "İlk sonuçlar bekleniyor; gelince süre netleşir.": "Waiting for first results; the estimate will firm up.",
    "ilk sonuç bekleniyor": "waiting for first result", "Hazırlık": "Preparing", "Yedek": "Backup", "Yazma": "Writing",
    "Mevcut çeviri dosyaları yedekleniyor": "Backing up existing translation files", "Orijinal dosyalar yedekleniyor": "Backing up original files",
    "Oyunun metinleri hazırlanıyor": "Preparing the game's text", "Çeviri oyuna uygulanıyor": "Applying translation to the game",
    "Çeviri oyuna yazılıyor": "Writing translation to the game", "Çeviri oyuna yazıldı": "Translation written to the game",
    "{0} çeviriyor": "{0} is translating", "{0} satır oyuna yazıldı": "{0} lines written to the game", "{0} satır · {1}": "{0} lines · {1}",
    "{0}{1} satır": "{0}{1} lines", "{0}{1} satırın tamamı işlendi": "All {0}{1} lines processed", "{0} satır incelenmeli": "{0} lines need review",
    "{0} sürüyor": "{0} running", "Son işlem: {0} · {1}.": "Last action: {0} · {1}.", "{0} yapılamadı": "{0} failed",
    "Kalite editörü": "Quality editor", "Kalite editörü sorunlu satırları düzeltiyor": "Quality editor is fixing problem lines",
    "Kalite editörü sorunlu satırları düzeltiyor ({0})": "Quality editor is fixing problem lines ({0})",
    "Kalite editörü çalışıyor ({0})…": "Quality editor running ({0})…", "Kalite editörü tamamlandı": "Quality editor finished",
    "{0} satır düzeltildi ({1}).": "{0} lines fixed ({1}).", "{0} sorunlu taslaktan {1} satır düzeltildi ({2}).":
        "{1} of {0} problem drafts fixed ({2}).",
    "Kalite editörü bir sohbet modeli ister: Gemini, OpenAI, Claude veya Ollama seçin.":
        "The quality editor needs a chat model: choose Gemini, OpenAI, Claude or Ollama.",
    "Oyunun çalıştırılabilir dosyası bulunamadı; oyun klasöründen açabilirsin.":
        "The game's executable wasn't found; you can start it from the game folder.",
    "Oyun içinde kontrol et": "Check in game",

    # ── Hatalar ve uyarılar ────────────────────────────────────────────────
    "Beklenmeyen bir hata oluştu": "An unexpected error occurred", "Beklenmeyen hata": "Unexpected error",
    "Yapılan çeviriler kaybolmadı. Tekrar dene; sürerse aşağıdaki ayrıntıyı bize ilet.":
        "No translations were lost. Try again; if it keeps happening, send us the details below.",
    "API anahtarı kabul edilmedi": "API key was rejected",
    "Anahtar yanlış, süresi dolmuş ya da yetkisiz olabilir. Sağlayıcılar sayfasından kontrol et.":
        "The key may be wrong, expired or unauthorized. Check it on the Providers page.",
    "API kotası doldu": "API quota exhausted",
    "Sağlayıcının kullanım sınırına ulaşıldı. Biraz bekleyip kaldığın yerden devam et ya da başka bir anahtar ekle. Yapılan çeviriler kaybolmadı.":
        "The provider's usage limit was reached. Wait a bit and continue, or add another key. No translations were lost.",
    "İnternet bağlantısı kurulamadı": "Couldn't connect to the internet",
    "Bağlantını kontrol edip kaldığın yerden devam et. Yapılan çeviriler kaybolmadı.":
        "Check your connection and continue where you left off. No translations were lost.",
    "Sunucu yanıt vermedi": "The server didn't respond",
    "Bağlantın yavaş ya da sağlayıcı yoğun olabilir. Biraz sonra tekrar dene.":
        "Your connection may be slow or the provider busy. Try again a bit later.",
    "Oyun dosyalarına yazılamadı": "Couldn't write to the game files",
    "Oyun açıksa kapat. Klasör Program Files altındaysa Capri'yi yönetici olarak çalıştır ya da oyunu başka bir klasöre taşı.":
        "Close the game if it's running. If the folder is under Program Files, run Capri as administrator or move the game elsewhere.",
    "Diskte yer kalmadı": "Out of disk space", "Biraz yer açıp kaldığın yerden devam et.": "Free up some space and continue where you left off.",
    "Bellek yetmedi": "Out of memory",
    "Diğer uygulamaları kapatıp tekrar dene. Sürerse bulut motoruna geç; yapılan çeviriler kaybolmadı.":
        "Close other apps and try again. If it persists, switch to a cloud engine; no translations were lost.",
    "Dosya bulunamadı": "File not found", "Oyun klasörü bulunamadı": "Game folder not found",
    "Oyun klasörü taşınmış ya da silinmiş olabilir. Oyun dosyalarını doğrulayıp yeniden dene.":
        "The game folder may have been moved or deleted. Verify the game files and try again.",
    "Uygulamanın bir parçası eksik": "Part of the app is missing",
    "Bu bir Capri paketleme hatası. Son sürümü indirip aynı klasöre açman sorunu çözer; ayarların ve çevirilerin korunur.":
        "This is a Capri packaging error. Download the latest version into the same folder; your settings and translations are kept.",
    "Bu motor için gereken kütüphaneler kurulu değil. Yerel Modeller sayfasından tek tıkla kurabilirsin.":
        "The libraries this engine needs aren't installed. You can install them from the Local Models page in one click.",
    "Devam eden bir işlem var, lütfen bitmesini bekleyin.": "Something is still running; please wait for it to finish.",
    "Devam eden işlem bitmeden analiz yapılamaz.": "Can't analyze until the current task finishes.",
    "Devam eden işlem bitmeden proje değiştirilemez.": "Can't switch projects until the current task finishes.",
    "Devam eden işlem bitmeden yeni oyun eklenemez.": "Can't add a game until the current task finishes.",
    "Oyun bulunamadı": "Game not found",
    "Seçilen klasörde desteklenen bir oyun bulunamadı (Ren'Py, Unity, Unreal, RPG Maker).":
        "No supported game found in the selected folder (Ren'Py, Unity, Unreal, RPG Maker).",
    "Bırakılan öğe açılamadı": "Couldn't open the dropped item", "Önce bir oyun klasörü seçin.": "Choose a game folder first.",
    "Önce bir proje aç": "Open a project first", "Önce bir proje aç.": "Open a project first.",
    "Bu oyunda çevrilecek metin bulunamadı.": "No translatable text found in this game.",
    "Bu oyunun metinleri dosyalarda açık değil; BepInEx olmadan çeviri uygulanamaz. Fikrini değiştirirsen çeviriyi yeniden başlatıp izin verebilirsin.":
        "This game's text isn't stored in readable files; the translation can't be applied without BepInEx. If you change your mind, restart the translation and allow it.",
    "Oyuna yazılacak satır bulunamadı, oyunda bir değişiklik yapılmadı. Çeviriler önbellekte duruyor; Teknik günlükten ayrıntıya bakabilirsin.":
        "No lines to write were found, so the game wasn't changed. Translations stay in the cache; see the technical log for details.",
    "{0} satırın hiçbiri çevrilemedi, oyuna bir şey yazılmadı. Teknik günlükte ayrıntı var; API anahtarını ve kotanı kontrol edip tekrar dene.":
        "None of the {0} lines could be translated, so nothing was written. See the technical log; check your API key and quota, then try again.",
    "Gemini API anahtarı yok. Sağlayıcılar sayfasından ekleyin.": "No Gemini API key. Add one on the Providers page.",
    "{0} API anahtarı yok. Sağlayıcılar sayfasından ekleyin.": "No {0} API key. Add one on the Providers page.",
    "{0} yalnızca Türkçeye çevirebilir.": "{0} can only translate into Turkish.",
    "{0} yalnızca İngilizce → Türkçe çeviri yapabilir.": "{0} can only translate English → Turkish.",
    "Kaynak dil “Otomatik” ya da hedef listesinde değil.": "The source language is “Auto” or not in the target list.",
    "{0} modeli eksik ({1}/{2} dosya). Yerel Modeller sayfasından indirin.":
        "{0} model is missing ({1}/{2} files). Download it from the Local Models page.",
    "{0} için yerel model ortamı (PyTorch) kurulu değil. Yerel Modeller sayfasından tek tıkla kurabilirsin.":
        "The local model runtime (PyTorch) for {0} isn't installed. Install it from the Local Models page in one click.",
    "Bu proje için henüz çeviri yok. Stüdyo'dan çeviriyi başlat.": "No translations for this project yet. Start translating from the Studio.",
    "Bu oyunda henüz çeviri yapılmadı.": "This game hasn't been translated yet.", "Henüz çeviri yok.": "No translations yet.",
    "Bu model için önbellekte çeviri yok.": "No cached translations for this model.",
    "Oyunda bu dilin çeviri klasörü yok; önce çeviriyi başlatın.": "The game has no translation folder for this language; start the translation first.",
    "Önce çeviriyi başlatın; Türkçe çeviri klasörü yok.": "Start the translation first; there's no translation folder.",
    "Önce çeviriyi başlat; düzeltilecek çeviri yok.": "Start the translation first; there's nothing to fix.",
    "Kaynak metinle bırakıldı; tekrar çalıştırınca yeniden denenir.": "Left as source text; it will be retried next run.",
    "Bu satırlar için geçerli çeviri alınamadı ve İngilizce bırakıldı. Editörde düzeltebilir ya da çeviriyi tekrar başlatarak yeniden deneyebilirsin.":
        "No valid translation was received for these lines, so they were left in English. Fix them in the editor or restart the translation to retry.",
    "{0} metin çevrilemedi": "{0} texts couldn't be translated", "Bilinmeyen sağlayıcı.": "Unknown provider.",
    "Giriş dosyası/klasörü bulunamadı.": "Input file/folder not found.", "Seçilen yedek bulunamadı.": "The selected backup wasn't found.",
    "Bu oyun için kayıtlı yedek bulunamadı.": "No saved backup found for this game.",

    # ── Editör ─────────────────────────────────────────────────────────────
    "Çevirileri düzenle": "Edit translations",
    "Önbellekteki çevirileri ara, düzelt ve kaydet. “Oyuna uygula” düzenlemeleri oyun dosyalarına yazar — API harcamaz. Turuncu çizgili satırlar incelenmeli.":
        "Search, fix and save cached translations. “Apply to game” writes your edits to the game files without using the API. Lines with an orange stripe need review.",
    "Editörü kullanmak için önce kütüphaneden bir proje aç.": "Open a project from the library to use the editor.",
    "Sadece incelenecekler": "Only lines to review", "İncelenmeli": "Needs review", "Kaynak": "Source", "Karşılığı": "Translation",
    "Önce değişiklikleri kaydet": "Save your changes first", "Düzenlemeler oyuna uygulandı": "Edits applied to the game",
    "Düzenlemeler uygulandı: {0} satır.": "Edits applied: {0} lines.", "Düzeltmeler oyuna yazıldı: {0} satır.": "Fixes written to the game: {0} lines.",
    "{0} · {1} satır güncellendi": "{0} · {1} lines updated",
    "Orijinal dosyaların yedeği yok. Düzenlemeleri uygulamak için 'Çeviriyi başlat' kullanın (önbellekteki satırlar için API harcanmaz).":
        "There's no backup of the original files. Use 'Start translation' to apply edits (cached lines don't use the API).",
    "“{0}” için sonuç yok.": "No results for “{0}”.",
    "Yamayı dışa aktar": "Export patch", "Yama içe aktar": "Import patch", "Yama dışa aktarıldı": "Patch exported",
    "Yama içe aktarıldı": "Patch imported", "Yama okunamadı": "Couldn't read the patch", "Dosya geçerli bir Capri yaması değil.":
        "The file isn't a valid Capri patch.", "Yama bu oyuna uymuyor": "The patch doesn't match this game",
    "Yama {0} için, açık oyun {1}.": "The patch is for {0}, the open game is {1}.", "Dışa aktarılacak çeviri yok": "No translations to export",
    "{0} önbelleği boş.": "{0} cache is empty.", "Toplulukla paylaş": "Share with the community",
    "{0} satır ({1}). 'Çeviriyi başlat' ile oyuna uygula — bu satırlar için API harcanmaz.":
        "{0} lines ({1}). Apply them with 'Start translation' — these lines don't use the API.",
    "Önce yamanın ait olduğu oyunu aç.": "Open the game the patch belongs to first.",
    "Capri yaması (*.capripatch)": "Capri patch (*.capripatch)", "Capri yaması (*.capripatch;*.omnipatch;*.zip)":
        "Capri patch (*.capripatch;*.omnipatch;*.zip)",

    # ── Topluluk yamaları ──────────────────────────────────────────────────
    "Topluluk yamaları": "Community patches",
    "Başkalarının paylaştığı çeviriler. Uygulanan satırlar için API harcanmaz.":
        "Translations shared by others. Applied lines don't use the API.",
    "Oyun adıyla ara": "Search by game name", "Yamalar aranıyor…": "Searching patches…", "Liste alınamadı": "Couldn't load the list",
    "Henüz paylaşılmış yama yok": "No patches shared yet", "Eşleşen yama yok": "No matching patches",
    "Bir oyunu çevirdikten sonra Çeviri Editörü'nden yamayı dışa aktarıp \"Toplulukla paylaş\" diyerek ilk sen paylaşabilirsin.":
        "After translating a game, export the patch from the Translation Editor and choose \"Share with the community\" to be the first.",
    "Açık oyun: {0} · {1}": "Open game: {0} · {1}", "Yamayı uygulamak için önce oyunu aç.": "Open the game to apply a patch.",
    "Sayfa": "Page", "İndir ve uygula": "Download and apply", "İndiriliyor": "Downloading", "Uygulandı": "Applied",
    "Dosya eklenmemiş": "No file attached", "Yama indirilemedi": "Couldn't download the patch",

    # ── Yedekler ───────────────────────────────────────────────────────────
    "Etkin projenin çeviri öncesi alınan yedekleri burada listelenir.": "Backups taken before translating the active project are listed here.",
    "Yedekleri görmek için önce kütüphaneden bir proje aç.": "Open a project from the library to see its backups.",
    "Bu proje için henüz yedek yok. Çeviri başlatıldığında otomatik alınır.": "No backups for this project yet. One is taken automatically when translation starts.",
    "{0} için alınan yedekler. Geri yükleme, dosyaları orijinal hâline döndürür.": "Backups of {0}. Restoring returns the files to their original state.",
    "Yedeği geri yükle": "Restore backup", "Geri yükle": "Restore", "Yedek geri yüklendi": "Backup restored",
    "Yedek geri yüklendi: {0} dosya.": "Backup restored: {0} files.", "Orijinal dosyalar geri yükleniyor": "Restoring original files",
    "{0} tarihli yedek ({1} dosya) oyun klasörüne geri yüklenecek. Devam edilsin mi?":
        "The backup from {0} ({1} files) will be restored into the game folder. Continue?",
    "{0} · {1} dosya orijinal hâline döndü": "{0} · {1} files restored to original", "{0} · {1} dosya · {2} MB": "{0} · {1} files · {2} MB",
    "Orijinal dosyalar": "Original files", "Şifreli arşivi geri koy": "Put the encrypted archive back", "Arşivi geri koy": "Put archive back",
    "Arşiv açıldı": "Archive extracted", "Arşiv geri konuldu": "Archive restored", "Şifreli arşiv açılacak": "The encrypted archive will be extracted",
    "{0} arşivi açılıyor": "Extracting {0} archive", "{0} oyun klasörüne çıkarıldı; orijinali yedeklendi.": "{0} extracted into the game folder; the original was backed up.",
    "{0} · {1} dosya çıkarıldı · orijinal arşiv {2} MB": "{0} · {1} files extracted · original archive {2} MB",
    "{0} · {1} açılmış dosya kaldırıldı": "{0} · {1} extracted files removed",
    "{0} oyununun dosyaları şifreli {1} arşivinde. Çeviri için Capri arşivi oyun klasörüne açacak (yaklaşık {2} MB dosya yazılır) ve orijinal arşivi _capri_backups klasörüne taşıyacak; oyun açılan dosyalarla aynı şekilde çalışır. Yedekler sayfasından tek tıkla geri alınabilir. Devam edilsin mi?":
        "{0}'s files are in an encrypted {1} archive. To translate, Capri will extract it into the game folder (about {2} MB is written) and move the original archive to _capri_backups; the game runs the same with the extracted files. You can undo this from the Backups page in one click. Continue?",
    "Capri'nin açtığı dosyalar (çevrilmiş veri dosyaları dahil) silinecek ve orijinal arşiv yerine konacak. Oyun ilk hâline döner. Devam edilsin mi?":
        "Files extracted by Capri (including translated data files) will be deleted and the original archive put back. The game returns to its original state. Continue?",
    "{0}: çevrilecek veri dosyası bulunamadı.": "{0}: no data files to translate.",

    # ── BepInEx, Unreal ve araçlar ─────────────────────────────────────────
    "BepInEx köprüsü": "BepInEx bridge", "BepInEx kurulumu": "BepInEx installation", "BepInEx kuruldu": "BepInEx installed",
    "BepInEx hazır": "BepInEx ready", "BepInEx kaldırıldı": "BepInEx removed", "BepInEx'i kaldır": "Remove BepInEx",
    "BepInEx bu oyunda zaten kurulu.": "BepInEx is already installed in this game.", "BepInEx yalnızca Unity oyunları içindir.":
        "BepInEx is for Unity games only.", "BepInEx ve XUnity.AutoTranslator kuruluyor…": "Installing BepInEx and XUnity.AutoTranslator…",
    "BepInEx ve XUnity.AutoTranslator GitHub'dan indirilip oyun klasörüne kurulacak. Üzerine yazılan dosyalar yedeklenir ve kurulum tek tıkla kaldırılabilir.":
        "BepInEx and XUnity.AutoTranslator will be downloaded from GitHub and installed into the game folder. Overwritten files are backed up and the installation can be removed in one click.",
    "Capri'nin kurduğu BepInEx ve XUnity.AutoTranslator dosyaları silinecek, üzerine yazılan dosyalar geri yüklenecek.":
        "The BepInEx and XUnity.AutoTranslator files Capri installed will be deleted and overwritten files restored.",
    "{0} dosya silindi; oyun klasörü kurulum öncesi hâline döndü.": "{0} files deleted; the game folder is back to its pre-install state.",
    "BepInEx {0} + XUnity.AutoTranslator {1} · {2} {3}": "BepInEx {0} + XUnity.AutoTranslator {1} · {2} {3}",
    "Ek araç kurulacak": "An extra tool will be installed", "repak aracı indiriliyor": "Downloading the repak tool",
    "retoc aracı indiriliyor": "Downloading the retoc tool", "repak kuruldu": "repak installed", "retoc kuruldu": "retoc installed",
    "Unreal paketleri artık açılabiliyor.": "Unreal packages can now be opened.", "IoStore kapsayıcıları artık okunabiliyor.":
        "IoStore containers can now be read.",
    "Metinler .pak paketlerinden çıkarılıyor": "Extracting text from .pak packages", "Metinler IoStore kapsayıcılarından çıkarılıyor":
        "Extracting text from IoStore containers",
    "Bu oyunun metinleri .pak paketlerinin içinde. Paketleri açabilmek için Capri, açık kaynak repak aracını (github.com/trumank/repak, yaklaşık 2 MB) GitHub'dan indirip kendi tools klasörüne kuracak. Oyun dosyalarına dokunulmaz; çeviri ayrı bir yama paketi olarak eklenir. Devam edilsin mi?":
        "This game's text is inside .pak packages. To open them, Capri will download the open-source repak tool (github.com/trumank/repak, about 2 MB) from GitHub into its tools folder. Game files are not touched; the translation is added as a separate patch package. Continue?",
    "Metinler .pak paketlerinde bulunamadı; bu oyun IoStore (.utoc) biçimini de kullanıyor. Capri, bu kapsayıcıları okumak için açık kaynak retoc aracını (github.com/trumank/retoc, yaklaşık 3 MB) GitHub'dan indirip kendi tools klasörüne kuracak. Oyun dosyalarına dokunulmaz. Devam edilsin mi?":
        "No text was found in .pak packages; this game also uses IoStore (.utoc). To read these containers, Capri will download the open-source retoc tool (github.com/trumank/retoc, about 3 MB) from GitHub into its tools folder. Game files are not touched. Continue?",
    "Bu oyunun paketleri AES ile şifreli. Oyunun AES anahtarını Sözlük → Bu oyun sekmesindeki 'AES anahtarı' alanına girip tekrar dene.":
        "This game's packages are AES-encrypted. Enter the game's AES key in Glossary → This game → 'AES key' and try again.",
    "Paketlerde kaynak dilde (.locres) metin bulunamadı.": "No source-language (.locres) text found in the packages.",
    "Bu oyunda çevrilebilir .locres metni bulunamadı.": "No translatable .locres text found in this game.",
    "Yama paketi oluşturuluyor": "Building the patch package", "Yama paketi eklendi": "Patch package added",
    "{0} · Paks/~mods klasörüne yazıldı. Kaldırmak için bu dosyayı silmen yeterli.": "{0} · written to Paks/~mods. Delete this file to remove it.",
    "Yazı tipi indirilecek": "A font will be downloaded", "Yazı tipi indiriliyor": "Downloading font",
    "Oyunun fontları bu dilin karakterlerini içermiyor; metinler oyunda görünmez. Capri, Google'ın açık kaynak Noto Sans yazı tipini (yaklaşık 5-8 MB, SIL Open Font License) GitHub'dan indirip çeviri klasörüne ekleyecek. Devam edilsin mi?":
        "The game's fonts don't contain this language's characters, so the text won't show. Capri will download Google's open-source Noto Sans font (about 5-8 MB, SIL Open Font License) from GitHub into the translation folder. Continue?",

    # ── Sözlük ─────────────────────────────────────────────────────────────
    "Terim sözlüğü": "Term glossary", "Terim ekle": "Add term", "Terimlerde ara": "Search terms", "Kaynak terim": "Source term",
    "Tam eşleşen metinler model kullanılmadan bu karşılıklarla çevrilir (menüler, karakter adları, özel terimler).":
        "Exactly matching text is translated with these entries without using a model (menus, character names, special terms).",
    "Bu oyun · {0}": "This game · {0}", "Oyuna özel bağlam": "Game-specific context", "Oyun hakkında notlar": "Notes about the game",
    "Hitap": "Form of address", "Sen (samimi)": "Informal (you)", "Siz (resmi)": "Formal (you)", "Romantik": "Romantic",
    "Bu bilgiler Gemini, OpenAI ve Claude'a talimat olarak gönderilir; terimler tüm motorlarda tam eşleşmede kullanılır.":
        "This information is sent to Gemini, OpenAI and Claude as instructions; terms are used on exact matches with every engine.",
    "Oyuna özel bilgiler — {0}:": "Game-specific information — {0}:", "Sözlük (*.json;*.csv)": "Glossary (*.json;*.csv)",
    "{0} terim dışa aktarıldı.": "{0} terms exported.", "0x… (64 hane onaltılık veya base64)": "0x… (64 hex digits or base64)",

    # ── Metin ve JSON çevirici ─────────────────────────────────────────────
    "Metni yaz ya da yapıştır; seçtiğin motorla anında çevrilsin. Satır yapısı ve oyun etiketleri korunur.":
        "Type or paste text and it's translated instantly with your chosen engine. Line breaks and game tags are kept.",
    "Çevrilecek metni yaz veya yapıştır…": "Type or paste text to translate…", "Çeviri burada görünecek.": "The translation will appear here.",
    "Yazarken çevir": "Translate as you type", "Çeviri panoya kopyalandı": "Translation copied to clipboard", "Dilleri değiştir": "Swap languages",
    "Bu yön değiştirilemez": "This direction can't be swapped", "Motor bağımsız JSON": "Engine-independent JSON",
    "Kendi motorunu kullanan oyunlarda (ör. VNE, Electron) metin dosyalarını çevir. Anahtarlar ve kod parçaları korunur; düz ve iç içe yapılar desteklenir.":
        "Translate text files of games with their own engine (e.g. VNE, Electron). Keys and code fragments are kept; flat and nested structures are supported.",
    "JSON dosyasını bırak": "Drop a JSON file", "JSON dosyasını ya da klasörünü bırak": "Drop a JSON file or folder",
    "Tek bir .json dosyası ya da içinde .json dosyaları olan bir klasör.": "A single .json file or a folder containing .json files.",
    "JSON girişi seçildi": "JSON input selected", "JSON çevirisi tamamlandı": "JSON translation finished",
    "JSON çevirisi tamamlandı: {0} metin → {1}": "JSON translation finished: {0} texts → {1}", "{0}: {1} metin çevriliyor…": "{0}: translating {1} texts…",
    "{0} dosya · {1} metin": "{0} files · {1} texts", "Önce bir dosya veya klasör seç": "Choose a file or folder first",
    "Dosya veya klasör yolu": "File or folder path",
    "Boş bırakılırsa dosya adının sonuna “_tr” eklenir; orijinal dosyaya dokunulmaz.":
        "If left empty, “_tr” is added to the file name; the original file is not touched.",
    "JSON dosyası (*.json)": "JSON file (*.json)", "{0}/{1} dosya": "{0}/{1} files", "0 karakter": "0 characters",

    # ── Ekran çevirisi ─────────────────────────────────────────────────────
    "Oyun ekranını çevir": "Translate the game screen",
    "Kısayola bas: ekran donar, çevirmek istediğin yeri sürükleyip seç, çeviri hemen yanında belirir. Sabit modda seçtiğin alan canlı izlenir ve metin her değiştiğinde yeniden çevrilir.":
        "Press the shortcut: the screen freezes, drag over the area you want translated and the translation appears next to it. In pinned mode the area is watched live and re-translated whenever the text changes.",
    "Alan seç": "Select area", "Alan seç ve çevir": "Select area and translate", "Alanı sabitle (canlı)": "Pin area (live)",
    "Sabitlemeyi kaldır": "Unpin", "Tek seferlik": "One-time", "Sabit / kapat": "Pin / close",
    "Tek seferlik: diyalog, menü ya da görev metnini seç, çeviri açılır pencerede görünsün.":
        "One-time: select a dialogue, menu or quest text and the translation appears in a popup.",
    "Altyazı ve diyalog kutuları için: seçilen alan sürekli izlenir, değişen metin otomatik çevrilir.":
        "For subtitles and dialogue boxes: the selected area is watched and changing text is translated automatically.",
    "Ekran çevirisi motoru": "Screen translation engine",
    "En hızlısı ekran kartında çalışan OPUS'tur (~50 ms). Gemini daha doğal ama ~1 sn sürer.":
        "The fastest is OPUS on your graphics card (~50 ms). Gemini is more natural but takes ~1 s.",
    "Canlı yenileme aralığı ·": "Live refresh interval ·", "Sabit çeviri penceresi": "Pinned translation window",
    "Alanın altında": "Below the area", "Orijinalin üstünde": "Over the original", "Seçim ekranında": "On the selection screen",
    "Kısayollar": "Shortcuts", "Kısayollar ve ayarlar": "Shortcuts and settings", "Kısayola bas…": "Press a shortcut…",
    "Tuş kombinasyonuna bas…": "Press a key combination…", "Kısayol kutusuna tıklayıp yeni tuş kombinasyonuna bas.":
        "Click the shortcut box and press a new key combination.", "Kısayol kaydedilemedi": "Couldn't save the shortcut",
    "Bu kısayol diğer işlem için kullanılıyor": "This shortcut is used by the other action", "Başka uygulamada kullanılıyor": "Used by another app",
    "{0} başka bir uygulama tarafından kullanılıyor. Ekran Çevirisi sayfasından farklı bir kısayol seç.":
        "{0} is used by another app. Choose a different shortcut on the Screen Translation page.",
    "Canlı": "Live", "Canlı ekran çevirisi açık": "Live screen translation on", "Canlı ekran çevirisi kapatıldı": "Live screen translation off",
    "Canlı çeviri açık": "Live translation on", "OCR {0} ms · çevriliyor…": "OCR {0} ms · translating…", "OCR {0} ms": "OCR {0} ms",
    "Ekran yakalanamadı": "Couldn't capture the screen", "Ekran çevirisi kullanılamıyor": "Screen translation unavailable",
    "Oyun “özel tam ekran” modundaysa ekran üstüne pencere çizilemez; oyunu “kenarlıksız / pencereli tam ekran” çalıştır.":
        "Windows can't be drawn over a game in “exclusive fullscreen”; run the game in “borderless / windowed fullscreen”.",
    "Metinler Windows'un yerleşik OCR motoruyla okunur; ek model indirmek gerekmez.":
        "Text is read with Windows' built-in OCR; no extra model download needed.",
    "Daha iyi tanıma için Windows'a İngilizce dil paketini ekleyebilirsin (Ayarlar › Saat ve dil › Dil ve bölge).":
        "For better recognition, add the English language pack to Windows (Settings › Time & language › Language & region).",
    "Çeviri pencereleri ekran yakalamaya görünmez yapılır, bu yüzden orijinal yazının üstünde dursalar bile kendi yazılarını okumazlar.":
        "Translation windows are hidden from screen capture, so they never read their own text even when placed over the original.",
    "{0}×{1} piksellik alan izleniyor. Kapatmak için {2} veya penceredeki ✕.": "Watching a {0}×{1} px area. Close with {2} or the ✕ on the window.",
    "alan seç ve çevir ·": "select area and translate ·", "alanı sabitle / kaldır (Ekran Çevirisi sayfasından değiştirilebilir).":
        "pin / unpin area (change it on the Screen Translation page).", "veya sağ tık iptal eder.": "or right-click to cancel.",
    "Diyalog": "Dialogue", "Görev": "Quest", "Etiketli": "Tagged",

    # ── Sağlayıcılar ve modeller ───────────────────────────────────────────
    "Bir motora tıklayıp ayarlarını yap. API anahtarları Windows Kimlik Bilgisi Yöneticisi'nde, Windows hesabına bağlı olarak şifreli saklanır.":
        "Click an engine to configure it. API keys are stored encrypted in Windows Credential Manager, tied to your Windows account.",
    "API anahtarı": "API key", "API anahtarları (her satıra bir tane)": "API keys (one per line)", "Sunucu adresi": "Server address",
    "Yerel sunucu": "Local server", "Sağlayıcı ayarları kaydedildi": "Provider settings saved", "Sağlayıcılara git": "Go to Providers",
    "{0} varsayılan motor yapıldı": "{0} set as the default engine", "Hazır · {0} anahtar": "Ready · {0} keys",
    "Otomatik — tüm modelleri hız sırasıyla dene (önerilen)": "Auto — try every model by speed (recommended)",
    "Binlerce satırı dakikalar içinde, doğal ve akıcı çevirir. “Otomatik” modda anahtarının erişebildiği tüm modeller hız sırasıyla denenir; biri kotaya takılırsa sıradakine geçilir. Birden fazla anahtar paralel kullanılır.":
        "Translates thousands of lines in minutes, naturally and fluently. In “Auto” mode the fastest models your key can use are tried in order; if one hits its quota the next is used. Multiple keys run in parallel.",
    "GPT modelleriyle bağlamsal, akıcı çeviri.": "Contextual, fluent translation with GPT models.",
    "Diyalog akıcılığı ve karakter tonunu korumada güçlü.": "Strong at keeping dialogue flow and character tone.",
    "Dilbilgisine sadık profesyonel çeviri (Free anahtarlar “:fx” ile biter). Oyun etiketleri otomatik korunur.":
        "Grammatically faithful professional translation (Free keys end with “:fx”). Game tags are preserved automatically.",
    "Bilgisayarında çalışan açık kaynak modeller (Qwen 2.5, Llama 3…). İnternet ve kota gerekmez; Ollama uygulaması açık olmalı.":
        "Open-source models running on your computer (Qwen 2.5, Llama 3…). No internet or quota needed; the Ollama app must be running.",
    "Bulut · en hızlı": "Cloud · fastest", "Bulut · GPT": "Cloud · GPT", "Bulut · edebi ton": "Cloud · literary tone",
    "Bulut · makine çevirisi": "Cloud · machine translation", "Yerel LLM · sansürsüz": "Local LLM · uncensored",
    "Çevrimdışı · EN→TR": "Offline · EN→TR", "Çevrimdışı · çok dilli": "Offline · multilingual", "(çevrimdışı)": "(offline)",
    "Gemini hızlı ve doğaldır; birden fazla anahtar girersen paralel çalışır. OpenAI, Claude ve DeepL bulut seçenekleridir. OPUS (EN→TR) ve NLLB (200 dil) ekran kartında internetsiz çalışır. Ollama yerel LLM ile sansürsüz çeviri sağlar.":
        "Gemini is fast and natural; with several keys it runs in parallel. OpenAI, Claude and DeepL are cloud options. OPUS (EN→TR) and NLLB (200 languages) run offline on your graphics card. Ollama gives uncensored translation with a local LLM.",
    "İnternet ve kota gerektirmeyen, ekran kartında çalışan nöral çeviri modelleri.":
        "Neural translation models running on your graphics card, with no internet or quota needed.",
    "Çevrimdışı modeller": "Offline models", "OPUS-MT · İngilizce → Türkçe": "OPUS-MT · English → Turkish",
    "Helsinki-NLP İngilizce → Türkçe modeli. Hafif ve hızlı, ekran kartında internetsiz çalışır.":
        "Helsinki-NLP English → Turkish model. Light and fast, runs offline on your graphics card.",
    "Helsinki-NLP opus-mt-tc-big-en-tr. ~450 MB, hızlı ve hafif.": "Helsinki-NLP opus-mt-tc-big-en-tr. ~450 MB, fast and light.",
    "NLLB-200 · 600M · çok dilli": "NLLB-200 · 600M · multilingual",
    "Meta'nın 200 dilli modeli; ekran kartında internetsiz çalışır. Türkçe dışındaki hedef dillere de çevirebilir (Almanca, İspanyolca, Rusça, Japonca…).":
        "Meta's 200-language model; runs offline on your graphics card. It can also translate into languages other than Turkish (German, Spanish, Russian, Japanese…).",
    "facebook/nllb-200-distilled-600M. 200 dil; Türkçe dışı hedeflere de çevirir.": "facebook/nllb-200-distilled-600M. 200 languages; also translates into non-Turkish targets.",
    "Model kullanıma hazır.": "Model ready to use.", "Model sayfası": "Model page", "Modeli küçült": "Compress model",
    "Optimize edilmedi": "Not optimized", "Hazır · optimize edildi": "Ready · optimized", "{0} hazır": "{0} ready",
    "{0} küçültüldü": "{0} compressed", "{0} küçültülüyor…": "Compressing {0}…", "{0} zaten küçültülmüş.": "{0} is already compressed.",
    "{0} fp16 biçimine dönüştürülecek: dosya boyutu yaklaşık yarıya iner ve model daha hızlı yüklenir. Çeviri kalitesi pratikte değişmez. Yeni model deneme çevirisiyle doğrulanır; eski dosya Geri Dönüşüm Kutusu'na taşınır.":
        "{0} will be converted to fp16: the file shrinks by about half and loads faster. Translation quality practically doesn't change. The new model is verified with a test translation; the old file goes to the Recycle Bin.",
    "Tüm dosyalar yerinde ({0} MB).": "All files present ({0} MB).", "{0} indiriliyor…": "Downloading {0}…", "{0} indirildi": "{0} downloaded",
    "{0} durduruldu": "{0} stopped", "Model indirirken de otomatik önerilir.": "It's also suggested automatically when downloading a model.",
    "Yerel model ortamı eksik": "Local model runtime missing", "Yerel model ortamı hazır": "Local model runtime ready",
    "Yerel model ortamı kurulacak": "The local model runtime will be installed", "Yerel model ortamı kuruldu": "Local model runtime installed",
    "Yerel model ortamı kurulu değil": "Local model runtime not installed", "Yerel model ortamı kuruluyor…": "Installing local model runtime…",
    "Ortamı kur": "Install runtime", "PyTorch ve Transformers zaten kurulu.": "PyTorch and Transformers are already installed.",
    "OPUS-MT ve NLLB, PyTorch + Transformers ile çalışır. Capri ekran kartına uygun resmi PyTorch sürümünü seçip indirir ve kendi klasörüne kurar (NVIDIA kartta ≈2,9 GB, kartsız ≈260 MB). Bulut motorları ve ekran çevirisi bu ortam olmadan da çalışır.":
        "OPUS-MT and NLLB run on PyTorch + Transformers. Capri picks the official PyTorch build for your graphics card and installs it into its own folder (≈2.9 GB with NVIDIA, ≈260 MB without). Cloud engines and screen translation work without it.",
    "Yerel modeller (OPUS-MT, NLLB) PyTorch ve Transformers kütüphanelerine ihtiyaç duyar. Capri, {0} ile birlikte bu kütüphaneleri resmi kaynaklardan (download.pytorch.org, pypi.org) indirip kendi klasörüne (runtime) kuracak. İndirme yaklaşık {1} MB; bir kez yapılır. Devam edilsin mi?":
        "Local models (OPUS-MT, NLLB) need the PyTorch and Transformers libraries. Capri will download them with {0} from the official sources (download.pytorch.org, pypi.org) into its own folder (runtime). The download is about {1} MB and happens once. Continue?",
    "Yerel modellere git": "Go to Local Models", "GPU hızlandırma (CUDA)": "GPU acceleration (CUDA)", "Ekran kartı algılanmadı": "No graphics card detected",
    "GPU hazırlandı": "GPU prepared", "Şimdi optimize et": "Optimize now", "Yerel motor seçiliyse açılışta hazırla": "Prepare at startup when a local engine is selected",
    "Bu ayar neden var?": "Why does this setting exist?",
    "{0} · {1} TFLOPS (FP16) · {2}/{3} GB boş{4}": "{0} · {1} TFLOPS (FP16) · {2}/{3} GB free{4}",
    "Ekran kartı ilk kez kullanıldığında sürücü bağlamı ve cuBLAS çekirdekleri hazırlanır; bu, ilk çeviride 1-3 saniyelik bir donma yaratır. Optimizasyon bunu önceden yapar, RTX kartlarda":
        "The first time the graphics card is used, the driver context and cuBLAS kernels are prepared, causing a 1-3 second freeze on the first translation. Optimization does this ahead of time, on RTX cards",
    "hızlandırmayı açar, kullanılmayan VRAM'i boşaltarak “bellek yetmedi” hatalarını azaltır ve seçili yerel modeli (OPUS/NLLB) VRAM'e yükler. Böylece OPUS/NLLB çevirileri, canlı önizleme ve ekran çevirisi ilk tıklamadan itibaren anında yanıt verir. Gemini gibi bulut motorları GPU kullanmaz; bu ayar yalnızca yerel modelleri hızlandırır.":
        "enables acceleration, frees unused VRAM to reduce “out of memory” errors and loads the selected local model (OPUS/NLLB) into VRAM. OPUS/NLLB translations, live preview and screen translation then respond instantly from the first click. Cloud engines like Gemini don't use the GPU; this only speeds up local models.",
    "Hız": "Speed",

    # ── Güncellemeler ──────────────────────────────────────────────────────
    "Güncellemeler": "Updates", "Güncellemeleri kontrol et": "Check for updates", "Açılışta kontrol et": "Check at startup",
    "Kullandığın sürüm: {0}": "Your version: {0}", "Capri güncel": "Capri is up to date", "En son sürümü kullanıyorsun.": "You're on the latest version.",
    "Yeni sürüm: {0}": "New version: {0}", "Yeni sürüm hazır: {0}": "New version ready: {0}", "Yeni sürümde": "In the new version",
    "İndir ve kur": "Download and install", "Sürüm sayfası": "Release page", "Capri {0} indiriliyor": "Downloading Capri {0}",
    "Capri {0} indiriliyor…": "Downloading Capri {0}…", "Kuruluyor…": "Installing…",
    "Capri birkaç saniye içinde {0} sürümüyle yeniden açılacak. Ayarların ve çevirilerin korunur.":
        "Capri will reopen with version {0} in a few seconds. Your settings and translations are kept.",
    "Capri {0} sürümüne güncellendi": "Capri updated to version {0}", "Capri {0} hazır.": "Capri {0} is ready.",
    "Değişiklikleri görmek ve tek tıkla kurmak için Güncelle'ye bas.": "Press Update to see the changes and install in one click.",
    "Yenilikleri görmek için güncelleme penceresini aç.": "Open the update window to see what's new.",
    "Güncelleme uygulanamadı": "The update couldn't be applied", "Önceki sürüm olduğu gibi duruyor. Ayrıntı: {0}": "The previous version is unchanged. Details: {0}",
    "İndirilen paket eksik; güncelleme uygulanmadı. Daha sonra tekrar dene.": "The downloaded package is incomplete; the update wasn't applied. Try again later.",
    "Kurulacak bir güncelleme yok.": "There's no update to install.", "Kaynak koddan çalışıyorsun; güncellemek için 'git pull' kullan.":
        "You're running from source; use 'git pull' to update.",
    "Yeni sürüm çıktığında Capri haber verir; tek tıkla indirip kurar ve yeniden açılır. Ayarların, önbelleklerin, modellerin ve API anahtarların korunur.":
        "When a new version is out, Capri lets you know; it downloads, installs and reopens in one click. Your settings, caches, models and API keys are kept.",

    # ── Sürüm notları (WHATS_NEW) ──────────────────────────────────────────
    "Çeviri bitince Capri'ye özel ince bir ses (ayarlardan kapatılabilir)": "A subtle Capri sound when a translation finishes (can be turned off in settings)",
    "Ren'Py: DLC/Live2D içeren oyunlarda \"translate komutu başarısız\" hatası düzeltildi":
        "Ren'Py: fixed the \"translate command failed\" error in games with DLC/Live2D",
    "Ren'Py: Rusça, Japonca gibi dillerde yazılmış oyunların metin sayısı artık doğru":
        "Ren'Py: line counts for games written in Russian, Japanese, etc. are now correct",
    "Ren'Py: oyunun paketli İngilizcesi varsa çeviri ondan yapılıyor": "Ren'Py: if the game ships a packed English version, it's used as the source",
    "Gemini çevirisi yaklaşık 5 kat hızlı; yarıda takılma düzeltildi": "Gemini translation is about 5× faster; stalls fixed",
    "İlerleme çubuğu sürekli ilerliyor, kalan süre gerçekçi": "The progress bar moves steadily and the time left is realistic",
    "Unity oyunlarında yazma hatası (UnityPy.resources) düzeltildi": "Fixed a write error in Unity games (UnityPy.resources)",
    "Güncelleme artık siyah pencere açmadan arayüzden kuruluyor": "Updates now install from the app without a black window",
    "GPU paneli \"Algılanıyor\"da kalmıyor; Durdur düğmesi yenilendi": "The GPU panel no longer sticks on \"Detecting\"; the Stop button was refreshed",
    "Oyna düğmesi, sözlük içe/dışa aktarma, yama paylaşma": "Play button, glossary import/export, patch sharing",

    # ── Rehber ─────────────────────────────────────────────────────────────
    "1 · Oyunu ekle": "1 · Add the game", "2 · Motoru seç": "2 · Choose the engine", "3 · Çevir, durdur, devam et": "3 · Translate, stop, continue",
    "4 · Düzelt ve paylaş": "4 · Fix and share",
    "“Oyun ekle” ile oyun klasörünü seç. Motor otomatik algılanır ve oyun analiz edilir; indirme sarmalayıcısı klasörü seçsen bile içteki oyun bulunur. Kapak görseli Steam'den gelir.":
        "Choose the game folder with “Add game”. The engine is detected and the game analyzed automatically; even if you pick a download wrapper folder, the game inside is found. Cover art comes from Steam.",
    "“Çeviriyi başlat” önce dosyaları yedekler. İstediğin an “Durdur”a bas; çeviriler önbellekte kalır ve tekrar başlatınca kaldığı yerden, aynı satırlar için API harcamadan devam eder.":
        "“Start translation” backs up the files first. Press “Stop” anytime; translations stay in the cache and restarting continues where it left off without paying again for the same lines.",
    "Çeviri Editörü'nde satırları düzelt, “Oyuna uygula” ile yaz. Yamayı .capripatch olarak dışa aktarıp arkadaşlarınla paylaşabilir, onların yamasını içe aktarabilirsin.":
        "Fix lines in the Translation Editor and write them with “Apply to game”. Export the patch as .capripatch to share with friends, or import theirs.",
    "Yedekler sayfasından istediğin yedeği geri yükleyerek oyunu orijinal hâline döndür. Unity IL2CPP oyunlarında çeviri BepInEx + XUnity.AutoTranslator dosyaları olarak yazılır (onayın istenir).":
        "Restore any backup from the Backups page to return the game to its original state. In Unity IL2CPP games the translation is written as BepInEx + XUnity.AutoTranslator files (with your approval).",
    "Tek tıkla çevir; istediğin an durdur, düzelt ya da orijinal dosyalarına dön.": "Translate in one click; stop, fix or return to the original files anytime.",
    "Analiz, çeviri ve yedek işlemleri burada özetlenir.": "Analysis, translation and backup activity is summarized here.",
    "Klasör, oyunun .exe dosyası ya da masaüstü kısayolu olabilir": "It can be the folder, the game's .exe or a desktop shortcut",
    "Oyun klasörünü bırak": "Drop the game folder", "Görev tamamlandı! \\C[3]50 altın\\C[0] kazandın.": "Quest complete! You earned \\C[3]50 gold\\C[0].",
    "Meyhanemize hoş geldin, kahraman!": "Welcome to our tavern, hero!", "Seni bir daha göreceğimi hiç düşünmemiştim.": "I never thought I'd see you again.",
    "Haritayı açmak için {0} tuşuna bas.": "Press {0} to open the map.",
    "Birkaç saniye": "A few seconds", "Kalmadı": "Nothing left", "Giriş": "Input",
    "Çeviri": "Translation", "Şimdi dene": "Try now", "Projeyi aç {0}": "Open project {0}", "Motor: {0}": "Engine: {0}",
    "Model dosyaları eksik": "Model files missing", "Modeller yükleniyor…": "Loading models…", "Ön yüklenen model": "Preloaded model",
    "Boş / toplam VRAM": "Free / total VRAM", "CUDA başlatma (bir kez)": "CUDA startup (once)", "FP16 matris hızı": "FP16 matrix speed",
    "Görev tamamlandı! \C[3]50 altın\C[0] kazandın.": "Quest complete! You earned \C[3]50 gold\C[0].",
    "{0} çevrilebilir oyun bulundu.": "{0} translatable games found.", "Bu öneriyi gizle": "Hide this suggestion",
    "Bağlantıyı test et": "Test connection", "Doğrula": "Verify", "Varsayılan": "Default", "Varsayılan motor": "Default engine",
    "Görsel romanlar: .rpy/.rpyc/.rpa, otomatik Türkçe font yaması.": "Visual novels: .rpy/.rpyc/.rpa, automatic font patch.",
    "MV / MZ veri dosyaları, kontrol kodları korunur.": "MV / MZ data files; control codes are kept.",
    "UE4/UE5 .locres tabloları, ~mods yapısı.": "UE4/UE5 .locres tables, ~mods layout.",
    "resources.assets metinleri; IL2CPP oyunlarda BepInEx köprüsü.": "resources.assets text; BepInEx bridge for IL2CPP games.",
    "{0} (çevrimdışı)": "{0} (offline)", "Otomatik Algıla (Auto)": "Auto-detect", "fp16 · küçültülmüş": "fp16 · compressed",
    "Önce {0}, sonra diğerleri": "First {0}, then the others",
    "Toplam yaklaşık {0} satır · yaklaşık {1} kelime": "Total about {0} lines · about {1} words",
    "Toplam {0} satır · {1} kelime": "Total {0} lines · {1} words",
    "Arayüz dili": "Interface language", "Arayüz çevriliyor…": "Translating the interface…",
    "Arayüz {0} diline çevrildi.": "The interface was translated into {0}.",
    "Bu dilin arayüzü için bir bulut çeviri anahtarı gerekiyor (Gemini, OpenAI, Claude veya DeepL). Şimdilik İngilizce gösteriliyor.":
        "This interface language needs a cloud translation key (Gemini, OpenAI, Claude or DeepL). Showing English for now.",
    "Hedef dil de {0} yapıldı.": "The target language was also set to {0}.",

    # ── Analiz notları, uyarılar, onaylar, hata ve sağlayıcı mesajları ─────────
    # Yenilikler (1.0.5)
    "Unity: Utage ve I2 Localization oyunları artık doğrudan çevriliyor (BepInEx gerekmeden)":
        "Unity: Utage and I2 Localization games are now translated directly (no BepInEx needed)",
    "Unity: oyunun fontunda olmayan harfler kutu yerine en yakın harfle yazılıyor (ğ→g)":
        "Unity: letters missing from the game's font are written as the closest letter instead of boxes (ğ→g)",
    "Arayüz dili: 17 dil, hata mesajları dahil; seçtiğin dil çeviri hedefi de olur":
        "Interface language: 17 languages, error messages included; your choice also becomes the target language",
    "Topluluk yamaları: paylaşılan çevirileri uygulama içinden bul, indir ve uygula":
        "Community patches: find, download and apply shared translations inside the app",
    'Ortak çeviri belleği: "Save", "Options" gibi metinler her oyunda yeniden çevrilmez':
        'Shared translation memory: texts like "Save" and "Options" aren\'t translated again for every game',
    "Çeviri bitince Windows bildirimi (Capri arka plandayken)":
        "Windows notification when a translation finishes (while Capri is in the background)",
    "Capri ikinci kez açılınca yeni pencere açılmaz, açık olan öne gelir":
        "Opening Capri a second time brings the open window to the front instead of opening a new one",
    "Taramada Unity ve Unreal oyunlarının satır sayısı da görünüyor": "The scan now shows line counts for Unity and Unreal games too",
    "Çeviri ayarları sadeleştirildi; dar pencerede üst üste binmiyor":
        "Translation settings were simplified and no longer overlap in a narrow window",
    "Görev çubuğunda çeviri ilerlemesi; bitince Windows bildirimi (arka plandayken)":
        "Translation progress on the taskbar; a Windows notification when it finishes (in the background)",

    # Analiz
    "Uyumlu": "Compatible", "Eksik": "Missing", "Eksik: {0}": "Missing: {0}", "Font gerekli": "Font needed",
    "Otomatik düzeltilecek": "Will be fixed automatically", "Bilinmiyor": "Unknown", "Destekleniyor": "Supported",
    "Font: Türkçe karakter uyumlu": "Font: supports Turkish characters",
    "Font: eksik karakterler {0}": "Font: missing characters {0}",
    "Font: {0} uyumlu, {1} Türkçe karakter eksik": "Font: {0} compatible, {1} missing Turkish characters",
    "Font: {0} uyumlu, {1} Türkçe karakter eksik (otomatik font yaması uygulanacak)":
        "Font: {0} compatible, {1} missing Turkish characters (an automatic font patch will be applied)",
    "Metinler dosyada açık değil: çeviri BepInEx + XUnity.AutoTranslator ile uygulanır (kurulu).":
        "Text isn't readable in the files: the translation is applied with BepInEx + XUnity.AutoTranslator (installed).",
    "Metinler dosyada açık değil: çeviri BepInEx + XUnity.AutoTranslator ile uygulanır — tek tıkla kurulabilir.":
        "Text isn't readable in the files: the translation is applied with BepInEx + XUnity.AutoTranslator — it can be installed in one click.",
    "Metinler oyun dosyalarında açık değil. Çeviri, oyun içinde BepInEx aracılığıyla gösterilir; BepInEx bu oyunda kurulu.":
        "The text isn't readable in the game files. The translation is shown in the game through BepInEx; BepInEx is installed in this game.",
    "Metinler oyun dosyalarında açık değil. Çeviri, oyun içinde BepInEx aracılığıyla gösterilir; kurulum için çeviri sırasında iznin istenir.":
        "The text isn't readable in the game files. The translation is shown in the game through BepInEx; you'll be asked to allow "
        "the installation during translation.",
    "Oyunun fontunda {0} harfleri yok. Kutu olarak görünmesinler diye Capri bunları en yakın harfle yazar (ğ→g, ş→s, ı→i); diğer harfler olduğu gibi kalır.":
        "The game's font lacks the letters {0}. So they don't show as boxes, Capri writes them as the closest letter (ğ→g, ş→s, ı→i); "
        "other letters stay as they are.",
    "Oyunun fontunda bazı Türkçe harfler yok; bu harfler oyunda boş ya da farklı görünebilir.":
        "The game's font lacks some Turkish letters; they may appear blank or different in the game.",
    "Metinler .pak paketlerinde. Çeviri başlarken Capri, paketleri açmak için açık kaynak repak aracını indirip kurmak üzere izin isteyecek (~2 MB).":
        "The text is in .pak packages. When the translation starts, Capri will ask permission to download the open-source repak tool "
        "to open them (~2 MB).",
    "Metinler .pak içinde bulunamadı. IoStore kapsayıcılarında da yok.": "No text was found in the .pak files, nor in the IoStore containers.",
    "Metinler .pak içinde bulunamadı. Bu oyun IoStore kullanıyorsa çeviri başlarken retoc aracı için izin istenir (~3 MB).":
        "No text was found in the .pak files. If this game uses IoStore, you'll be asked to allow the retoc tool when the translation "
        "starts (~3 MB).",
    "Paketlerde kaynak dilde metin bulunamadı.": "No text in the source language was found in the packages.",
    "Metinler .pak içinden okundu; çeviri Paks/~mods altına yama paketi olarak yazılır.":
        "The text was read from the .pak files; the translation is written as a patch package under Paks/~mods.",
    "Paketler AES ile şifreli. Oyunun AES anahtarını Sözlük → Bu oyun sekmesine girip yeniden analiz et.":
        "The packages are AES-encrypted. Enter the game's AES key under Glossary → This game and analyze again.",
    "{0} için karakter taraması desteklenmiyor.": "Character scanning isn't supported for {0}.",

    # Görev adları ("{0} sürüyor", "{0} yapılamadı" kalıplarının içinde)
    "Uygulama": "Applying", "Ortam kurulumu": "Runtime setup", "Model indirme": "Model download",
    "BepInEx kaldırma": "BepInEx removal", "JSON çevirisi": "JSON translation", "Güncelleme": "Update",
    "Model küçültme": "Model compression", "Arşivi geri koyma": "Archive restore", "Geri yükleme": "Restore",
    "Şifreli arşiv": "Encrypted archive", "Orijinal arşiv geri konuldu": "Original archive restored",
    "Orijinal dosyalara dönüldü": "Original files restored", "Çeviri durduruldu": "Translation stopped",

    # Çeviri, yedek, onaylar
    "{0} satır oyuna yazıldı · {1}": "{0} lines written to the game · {1}", "{0} satır kaydedildi.": "{0} lines saved.",
    "{0} satırda etiket/değişken eksik veya fazla: {1}": "{0} lines have missing or extra tags/variables: {1}",
    "Oyun orijinal dosyalarına döndürülüp baştan çevrilecek. Önbellekteki satırlar yeniden kullanılır, onlar için API harcanmaz. Devam edilsin mi?":
        "The game will be restored to its original files and translated from scratch. Cached lines are reused and don't use the API. Continue?",
    "Oyun baştan çevrilecek. Önbellekteki satırlar yeniden kullanılır, onlar için API harcanmaz. Devam edilsin mi?":
        "The game will be translated from scratch. Cached lines are reused and don't use the API. Continue?",
    "Bu oyunun metinlerinin bir kısmı ya da tamamı dosyalarda açık değil (IL2CPP / paketli).\n\n"
    "Çevirileri oyun içinde göstermek için XUnity.AutoTranslator çeviri dosyaları yazılsın mı?":
        "Some or all of this game's text isn't readable in the files (IL2CPP / packed).\n\n"
        "Write XUnity.AutoTranslator translation files to show the translations in the game?",
    "Bu oyunun metinlerinin bir kısmı ya da tamamı dosyalarda açık değil (IL2CPP / paketli).\n\n"
    "Çevirileri oyun içinde göstermek için XUnity.AutoTranslator çeviri dosyaları yazılsın mı?\n\n"
    "Hayır dersen bu oyun çevrilemez: başka çevrilecek metin yok.":
        "Some or all of this game's text isn't readable in the files (IL2CPP / packed).\n\n"
        "Write XUnity.AutoTranslator translation files to show the translations in the game?\n\n"
        "If you say no, this game can't be translated: there's no other text to translate.",
    "Bu oyunun metinlerinin bir kısmı ya da tamamı dosyalarda açık değil (IL2CPP / paketli).\n\n"
    "Çevirilerin oyun içinde görünmesi için BepInEx ve XUnity.AutoTranslator GitHub'dan indirilip oyun klasörüne kurulsun mu?\n\n"
    "Kurulum tek tıkla geri alınabilir.":
        "Some or all of this game's text isn't readable in the files (IL2CPP / packed).\n\n"
        "Download BepInEx and XUnity.AutoTranslator from GitHub and install them in the game folder so the translations show in the game?\n\n"
        "The installation can be undone in one click.",
    "Bu oyunun metinlerinin bir kısmı ya da tamamı dosyalarda açık değil (IL2CPP / paketli).\n\n"
    "Çevirilerin oyun içinde görünmesi için BepInEx ve XUnity.AutoTranslator GitHub'dan indirilip oyun klasörüne kurulsun mu?\n\n"
    "Kurulum tek tıkla geri alınabilir.\n\n"
    "Hayır dersen bu oyun çevrilemez: başka çevrilecek metin yok.":
        "Some or all of this game's text isn't readable in the files (IL2CPP / packed).\n\n"
        "Download BepInEx and XUnity.AutoTranslator from GitHub and install them in the game folder so the translations show in the game?\n\n"
        "The installation can be undone in one click.\n\n"
        "If you say no, this game can't be translated: there's no other text to translate.",
    "BepInEx kuruldu. Oyunu açınca metinler yakalanır; çevrilecek satırlar oyunu oynadıkça oluşur.":
        "BepInEx is installed. Text is captured when you open the game; lines to translate appear as you play.",
    "Yapılan çeviriler kayıtlı; devam ettiğinde kaldığı yerden sürer, tekrar ücret ödemezsin.":
        "Finished translations are saved; continuing picks up where it left off and you don't pay again.",
    "%{0} tamamlanmıştı. Yapılan çeviriler kayıtlı; devam ettiğinde kaldığı yerden sürer, tekrar ücret ödemezsin.":
        "{0}% was done. Finished translations are saved; continuing picks up where it left off and you don't pay again.",
    "{0} dosya basariyla eski orijinal haline getirildi.": "{0} files were restored to their originals.",
    "Yedek bulunamadı: {0}": "Backup not found: {0}",

    # Topluluk, güncelleme
    "Topluluk deposu ayarlı değil.": "The community repository isn't set.",
    "GitHub'a ulaşılamadı. İnternet bağlantını kontrol edip tekrar dene.": "Couldn't reach GitHub. Check your internet connection and try again.",
    "Bu bağlantıdan indirme yapılmaz (yalnızca GitHub konu ekleri).": "Downloads aren't allowed from this link (GitHub issue attachments only).",
    "Yama dosyası çok büyük (50 MB üstü).": "The patch file is too large (over 50 MB).",
    "Bu derlemede güncelleme kaynağı tanımlı değil.": "This build has no update source.",
    "Sunucuya ulaşılamadı ({0}).": "Couldn't reach the server ({0}).",
    "Geçerli bir GitHub deposu girin (kullanici/depo).": "Enter a valid GitHub repository (user/repo).",
    "Henüz yayımlanmış bir sürüm yok.": "No release has been published yet.",
    "İndirilen paket bir Capri sürümü gibi görünmüyor.": "The downloaded package doesn't look like a Capri release.",

    # Yerel modeller, GPU, OCR
    "NVIDIA ekran kartın için CUDA destekli PyTorch": "CUDA-enabled PyTorch for your NVIDIA graphics card",
    "NVIDIA ekran kartı bulunamadığı için CPU sürümü PyTorch": "CPU version of PyTorch, since no NVIDIA graphics card was found",
    "Eksik kütüphaneler kuruldu.": "Missing libraries were installed.",
    "{0} VRAM'e yüklendi": "{0} loaded into VRAM",
    "{0} MB → {1} MB · yükleme {2} sn → {3} sn · aynı çıktı {4}": "{0} MB → {1} MB · load {2} s → {3} s · same output {4}",
    "eski dosya taşınamadı, elle silebilirsin": "the old file couldn't be moved; you can delete it manually",
    "Dönüştürme başarısız.": "Conversion failed.", "Kurulu ({0} MB)": "Installed ({0} MB)",
    "PyTorch kurulu değil.": "PyTorch isn't installed.",
    "CUDA bulunamadı; yerel modeller CPU'da çalışır.": "CUDA not found; local models run on the CPU.",
    "Bu sisteme uygun PyTorch sürümü bulunamadı.": "No PyTorch version suitable for this system was found.",
    "{0} {1} için Windows paketi bulunamadı.": "No Windows package found for {0} {1}.",
    "OCR {0} ms · çeviri {1}": "OCR {0} ms · translation {1}", "OCR hatası: {0}": "OCR error: {0}",
    "Alan izleniyor…": "Watching the area…",
    "Windows'ta OCR dil paketi yüklü değil (Ayarlar > Dil > dil ekle).":
        "No OCR language pack is installed in Windows (Settings > Language > add a language).",
    "Windows OCR kullanılamıyor: {0}": "Windows OCR is unavailable: {0}",
    "Ollama (yerel LLM)": "Ollama (local LLM)", "Ollama LLM (doğal çeviri)": "Ollama LLM (natural translation)", "OPUS hızlı": "OPUS fast",

    # Süreler
    "birkaç saniye": "a few seconds", "yaklaşık {0} sn": "about {0} s", "yaklaşık {0} dk": "about {0} min",
    "yaklaşık {0} sa": "about {0} h", "yaklaşık {0} sa {1} dk": "about {0} h {1} min",
    "{0} dk": "{0} min", "{0} sn": "{0} s", "{0} dk {1} sn": "{0} min {1} s", "{0} sa": "{0} h", "{0} sa {1} dk": "{0} h {1} min",

    # Sağlayıcı testleri ve hataları
    "Hiçbir model yanıt vermedi ({0}).": "No model responded ({0}).",
    "{0} serbest metin üretemez (kalite editörü için Gemini, OpenAI, Claude veya Ollama gerekir).":
        "{0} can't generate free text (the quality editor needs Gemini, OpenAI, Claude or Ollama).",
    "API anahtarı girilmedi.": "No API key entered.", "OpenAI API anahtarı girilmedi.": "No OpenAI API key entered.",
    "Anthropic API anahtarı girilmedi.": "No Anthropic API key entered.", "DeepL API anahtarı girilmedi.": "No DeepL API key entered.",
    "OpenAI API Anahtarı girilmedi.": "No OpenAI API key entered.", "Anthropic API Anahtarı girilmedi.": "No Anthropic API key entered.",
    "DeepL API Anahtarı girilmedi.": "No DeepL API key entered.", "{0} API anahtarı girilmemiş.": "No {0} API key entered.",
    "Model dosyası bulunamadı.": "Model file not found.",
    "fp16 model doğrulanamadı; orijinal korundu.": "The fp16 model couldn't be verified; the original was kept.",
    "zaman aşımı": "timeout", "Metin boş.": "The text is empty.",
    "Gemini: hiçbir model çeviremedi — {0}": "Gemini: no model could translate — {0}",
    "Bağlantı hatası: {0}": "Connection error: {0}",
    "Bağlantı başarılı ({0} ms) · {1} · {2} model erişilebilir": "Connected ({0} ms) · {1} · {2} models available",
    "Geçersiz API anahtarı ({0}).": "Invalid API key ({0}).",
    "Bağlantı Başarılı ({0} ms) — {1} Hazır": "Connected ({0} ms) — {1} ready",
    "Bağlantı Başarılı ({0} ms) — Claude Hazır": "Connected ({0} ms) — Claude ready",
    "Bağlantı Başarılı ({0} ms) — Kota: {1} / {2} karakter": "Connected ({0} ms) — Quota: {1} / {2} characters",
    "OpenAI Hatası {0}: {1}": "OpenAI error {0}: {1}", "Claude Hatası {0}: {1}": "Claude error {0}: {1}",
    "DeepL Hatası {0}: {1}": "DeepL error {0}: {1}",
    "OpenAI Hatası: {0}": "OpenAI error: {0}", "Claude Hatası: {0}": "Claude error: {0}", "DeepL Hatası: {0}": "DeepL error: {0}",
    "Ollama HTTP {0} yanıtı verdi.": "Ollama responded with HTTP {0}.",
    "Ollama servisi çalışmıyor! Lütfen Ollama uygulamasını başlatın veya komut satırından 'ollama serve' yazın.":
        "The Ollama service isn't running. Start the Ollama app or run 'ollama serve' from the command line.",
    "Ollama Servisi Aktif ({0} ms) — {1} model yüklü": "Ollama service running ({0} ms) — {1} models installed",
    "Ollama Aktif ama hiç model yüklenmemiş. 'ollama pull qwen2.5:7b' çalıştırın.":
        "Ollama is running but no model is installed. Run 'ollama pull qwen2.5:7b'.",
    "Ollama Bağlantı Hatası: {0}": "Ollama connection error: {0}",
    "İndiriliyor: {0}": "Downloading: {0}",
    "{0} indirilemedi! İnternet bağlantınızı kontrol edin: {1}": "Couldn't download {0}. Check your internet connection: {1}",
    "Gemini API anahtarı yok.": "No Gemini API key.", "safetensors dosyası üretilemedi.": "The safetensors file couldn't be created.",
    "Gemini API Anahtarı bulunamadı! 'API ve Ajanlar' sekmesinden ekleyin.": "No Gemini API key found. Add one on the Providers page.",
    "{0}: yanıt okunamadı ({1})": "{0}: couldn't read the response ({1})",
    "OPUS modeli eksik ({0}/{1} dosya). 'Yerel Modeller' sekmesinden indirin.":
        "OPUS model is missing ({0}/{1} files). Download it from the Local Models page.",
    "NLLB-200 modeli eksik ({0}/{1} dosya). 'Yerel Modeller' sekmesinden indirin.":
        "NLLB-200 model is missing ({0}/{1} files). Download it from the Local Models page.",
    "OPUS Çeviri Hatası: {0}": "OPUS translation error: {0}", "NLLB-200 Çeviri Hatası: {0}": "NLLB-200 translation error: {0}",
    "Gemini günlük kotası (RESOURCE_EXHAUSTED) tüm anahtarlarda doldu.":
        "The daily Gemini quota (RESOURCE_EXHAUSTED) is used up on all keys.",
    "Gemini geç yanıt veriyor; başka bir modelle deneniyor.": "Gemini is responding slowly; trying another model.",
    "Gemini hız sınırına takıldı; birkaç saniye bekleyip devam ediyor.": "Gemini hit its rate limit; continuing after a few seconds.",

    # Motor hataları
    "Desteklenmeyen RPA biçimi: {0}": "Unsupported RPA format: {0}",
    "Oyun ana klasöründe Ren'Py çalıştırılabilir dosyası bulunamadı.": "No Ren'Py executable was found in the game's main folder.",
    "Diskte yer yok: {0} için geçici olarak {1} MB boş alan gerekiyor.": "Not enough disk space: {0} temporarily needs {1} MB free.",
    "Geri alınacak Türkçe yedek bulunamadı.": "No translation backup to undo was found.",
    "Yedek dosyası oyun klasörünün _turkish_backups dizininde olmalı.":
        "The backup file must be in the game folder's _turkish_backups directory.",
    "Ren'Py çalışma cache yedeği kayboldu.": "The Ren'Py cache backup is missing.",
    "Çevrilebilir Ren'Py betiği bulunamadı.": "No translatable Ren'Py script was found.",
    "Ren'Py Türkçe çeviri şablonu üretmedi.": "Ren'Py didn't generate a translation template.",
    "Önceki işlemden kalan Ren'Py cache yedeği bulundu: {0}": "A Ren'Py cache backup from a previous run was found: {0}",
    "Ren'Py translate komutu başarısız: {0}": "The Ren'Py translate command failed: {0}",
    "Bu oyun yalnızca .rpyc içeriyor ve rpycdec destek paketi eksik (pip install -r requirements.txt).":
        "This game only contains .rpyc files and the rpycdec package is missing (pip install -r requirements.txt).",
    "Çıkarılabilecek RPYC betiği bulunamadı.": "No RPYC script to extract was found.",
    "RPYC çeviri çıkarımı başarısız:\n{0}": "RPYC translation extraction failed:\n{0}",
    "RPYC ayrıştırıcısı çeviri şablonu üretmedi.": "The RPYC parser didn't generate a translation template.",
    "İngilizce dil paketi okunamadı: {0}": "The English language pack couldn't be read: {0}",
    "glossary.json bir JSON nesnesi olmalı.": "glossary.json must be a JSON object.",
    "Seçilen klasörde 'game' klasörü bulunamadı.": "No 'game' folder was found in the selected folder.",
    "Önceki işlemden kalan arşiv yedeği var: {0}": "There's an archive backup left from a previous run: {0}",
    "Arşiv okunamadı: {0} / {1}": "Couldn't read the archive: {0} / {1}",
    "Geçerli bir RPG Maker oyunu bulunamadı: {0}": "No valid RPG Maker game was found: {0}",
    "Oyun klasöründe RGSS arşivi bulunamadı.": "No RGSS archive was found in the game folder.",
    "Bu oyunda Capri ile açılmış bir arşiv yok.": "This game has no archive opened by Capri.",
    "RGSS arşivi değil: {0}": "Not an RGSS archive: {0}",
    "{0} sürümünde Windows paketi bulunamadı.": "No Windows package found in release {0}.",
    "repak kurulu değil.": "repak isn't installed.", "retoc kurulu değil.": "retoc isn't installed.",
    "{0} hatası: {1}": "{0} error: {1}", "İndirilen pakette {0}.exe yok.": "The downloaded package doesn't contain {0}.exe.",
    "{0} geçerli bir zip değil.": "{0} isn't a valid zip.",
    "Bu oyunda Capri ile yapılmış bir BepInEx kurulumu bulunamadı.": "No BepInEx installation made by Capri was found in this game.",
    "{0} için uygun paket bulunamadı ({1}, {2}).": "No suitable package found for {0} ({1}, {2}).",

    # Arayüz (JS) eksikleri
    "Kütüphaneden kaldır": "Remove from library", "Taramadan çıkar": "Remove from scan",
    "Kaynak veya çeviride ara": "Search source or translation",
    "Ör. Ortaçağ fantastik dünya. Elena kraliçe, Marcus onun ağabeyi. Küfürler yumuşatılmasın.":
        "E.g. Medieval fantasy world. Elena is the queen, Marcus her older brother. Don't soften swearing.",
    "Taranıyor: Steam, Epic, GOG ve oyun klasörlerin…": "Scanning: Steam, Epic, GOG and your game folders…",
    "AES anahtarı": "AES key", "· yalnızca paketleri şifreli Unreal oyunları için": "· only for Unreal games with encrypted packages",
    "{0} dosya çıkarıldı": "{0} files extracted", "orijinal arşiv {0} MB": "original archive {0} MB", "{0} dosya": "{0} files",
    "Durumu kontrol et": "Check status", "Sil": "Delete",
    "Duraklat / sürdür": "Pause / resume", "Kapat (Esc)": "Close (Esc)",
    "Bu alanı canlı çeviri için sabitle": "Pin this area for live translation",
    "Çevrilecek alanı sürükleyerek seç": "Drag to select the area to translate",
    "Sabitlenecek alanı seç — bu alan canlı olarak çevrilecek": "Select the area to pin — it will be translated live",
    "Bu alanda okunabilir metin bulunamadı.": "No readable text was found in this area.",
    "Kopyalandı": "Copied", "Sabitle": "Pin", "Duraklatıldı": "Paused", "Hata": "Error", "iptal": "cancel",
    "Ekle": "Add", "Tümünü ekle": "Add all", "İndir": "Download", "Varsayılan yap": "Make default",
    "…ve {0} oyun daha.": "…and {0} more games.", "Eşleşen satır yok.": "No matching lines.",
    "Daha fazla yükle ({0} kaldı)": "Load more ({0} left)",
    "{0} uygun model bulundu. Seçilen model önce denenir; çalışmazsa diğerlerine geçilir.":
        "{0} suitable models found. The selected model is tried first; if it fails, the others are used.",
    "Küçült (fp16)": "Compress (fp16)", "Yerel ortam gerekli": "Local runtime needed", "CUDA yok": "No CUDA",
    "VRAM'de hazır · {0} ms": "Ready in VRAM · {0} ms",
    "Önceki çevirilerindeki hızına göre": "Based on your previous translation speed",
    "Ortalama hıza göre; çeviri başlayınca netleşir": "Based on average speed; it gets more precise once translation starts",
    "{0} anahtar": "{0} keys", "%{0}": "{0}%",
}
