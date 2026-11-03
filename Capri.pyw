"""Capri — kaynak koddan konsolsuz başlatıcı (çift tıkla açılır; pythonw ile çalışır)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
import app_modern  # noqa: E402

if __name__ == "__main__":
    app_modern.main()
