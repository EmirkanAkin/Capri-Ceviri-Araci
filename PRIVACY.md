# Gizlilik

Capri bir hesap istemez, kullanım verisi toplamaz ve geliştiriciye hiçbir veri göndermez. Ayarlar, önbellekler ve
günlükler bilgisayarında, uygulama klasöründe kalır. API anahtarları Windows Kimlik Bilgisi Yöneticisi'nde şifreli saklanır.

## Capri'nin internete bağlandığı durumlar

| Ne zaman | Nereye | Ne gönderilir |
|---|---|---|
| Bulut motoruyla çeviri yaparken | Seçtiğin sağlayıcı (Google Gemini, OpenAI, Anthropic, DeepL) | Çevrilecek metinler, oyuna özel notların ve API anahtarın |
| Açılışta güncelleme kontrolü (kapatılabilir) | GitHub | Standart istek; kişisel veri yok |
| Oyun eklenince kapak görseli ararken | Steam | Oyunun adı veya Steam numarası |
| Ollama kullanırken | Ayarladığın Ollama adresi (varsayılan: kendi bilgisayarın) | Çevrilecek metinler |
| Yerel model veya ortam indirirken (onayınla) | Hugging Face, PyTorch, PyPI | Standart indirme isteği |
| BepInEx, repak veya retoc kurarken (onayınla) | GitHub | Standart indirme isteği |

Bulut motorlarına gönderilen metinler o sağlayıcının kendi gizlilik koşullarına tabidir. OPUS-MT ve NLLB gibi yerel
modellerle çeviri yaparken metinler bilgisayarından çıkmaz.

Otomatik oyun tarama yalnızca bilgisayarında çalışır ve taranan klasörler hiçbir yere gönderilmez.
