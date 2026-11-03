"""
Testler: şifreli RPG Maker arşivleri, Unreal PAK araç kurulumu, yerel GPU çalışma ortamı,
paketlenmiş exe yolları ve Capri adına geçiş.
"""
import io
import json
import zipfile

import pytest

import app_modern
from test_app import fake_ollama, make_bridge, run_sync  # noqa: F401
from test_roadmap import _vxace_game


# ── RPG Maker şifreli arşivleri ──────────────────────────────────────────────
@pytest.mark.parametrize("version", [1, 3])
def test_rgss_archive_roundtrip(tmp_path, version):
    import rgss_archive as ra
    files = [("Data/Actors.rvdata2", b"\x04\x08[\x06" * 100), ("Data/Map001.rvdata2", bytes(range(256)) * 41 + b"xyz"),
             ("Graphics/Pictures/a.png", b"\x89PNG" + b"\0" * 5), ("Data/Empty.rvdata2", b"")]
    archive = tmp_path / "Game.rgss3a"
    ra.write_archive(archive, files, version=version)
    got_version, entries = ra.read_index(archive)
    assert got_version == version
    assert [(e.name, ra.read_entry(archive, e)) for e in entries] == files


def test_rgss_archive_header_is_encrypted(tmp_path):
    import rgss_archive as ra
    archive = tmp_path / "Game.rgss3a"
    ra.write_archive(archive, [("Data/System.rvdata2", b"secret-title")], version=3)
    raw = archive.read_bytes()
    assert raw.startswith(b"RGSSAD\x00\x03") and b"secret-title" not in raw and b"System" not in raw
    with pytest.raises(ValueError):
        (tmp_path / "bad.rgss3a").write_bytes(b"NOTRGSS\x03")
        ra.read_index(tmp_path / "bad.rgss3a")


def _encrypted_vxace_game(root):
    """Gerçek dağıtım düzeni: Data/ klasörü yok, veriler Game.rgss3a içinde."""
    import rgss_archive as ra
    data = _vxace_game(root)
    files = [(f"Data/{p.name}", p.read_bytes()) for p in sorted(data.iterdir())]
    files.append(("Graphics/System/Window.png", b"\x89PNG-window"))
    for p in data.iterdir():
        p.unlink()
    data.rmdir()
    ra.write_archive(root / "Game.rgss3a", files, version=3)
    (root / "Game.ini").write_text("[Game]\nLibrary=System\\RGSS301.dll\nTitle=Şifreli Macera\n", encoding="utf-8")
    return files


def test_rgss_unpack_and_restore(tmp_path):
    import rgss_archive as ra
    root = tmp_path / "Enc"
    files = _encrypted_vxace_game(root)
    (root / "Graphics" / "System").mkdir(parents=True)
    (root / "Graphics" / "System" / "Window.png").write_bytes(b"user-modified")  # var olan farklı dosya korunmalı
    original = (root / "Game.rgss3a").read_bytes()
    manifest = ra.unpack(root, log=lambda s: None)
    assert not (root / "Game.rgss3a").exists() and ra.is_unpacked(root)
    for name, data in files:
        assert (root / name).read_bytes() == data
    assert manifest["replaced"] == ["Graphics/System/Window.png"]
    ra.restore(root, log=lambda s: None)
    assert (root / "Game.rgss3a").read_bytes() == original
    assert not (root / "Data").exists()
    assert (root / "Graphics" / "System" / "Window.png").read_bytes() == b"user-modified"
    assert not (root / "_capri_backups" / "rgss_extract.json").exists()


def test_encrypted_vxace_detect_analyze_translate(tmp_path, monkeypatch, fake_ollama):
    import providers
    import engine_rpgmaker as er
    import rgss_archive as ra
    root = tmp_path / "EncGame"
    _encrypted_vxace_game(root)
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    asked = []
    monkeypatch.setattr(bridge, "_ask", lambda title, text, timeout=300.0: asked.append((title, text)) or True)
    bridge._select_game(str(root))
    assert bridge._game["type"] == "rpgmaker" and bridge._game["title"] == "Şifreli Macera"
    run_sync(bridge, "analyze")
    analysis = bridge._game["analysis"]
    assert analysis["unique"] == 6, "analiz arşivin içinden okunmalı"
    assert any("Game.rgss3a" in n for n in analysis["notes"])
    assert (root / "Game.rgss3a").exists() and not (root / "Data").exists(), "analiz oyuna dokunmamalı"
    run_sync(bridge, "translate")
    assert asked and "Game.rgss3a" in asked[0][1], "arşiv açılmadan önce kullanıcıya sorulmalı"
    after = {t.original for t in er.extract_texts_vxace(root / "Data", log=lambda s: None)}
    assert "TR(Welcome, \\N[1]!)" in after
    assert ra.is_unpacked(root) and not (root / "Game.rgss3a").exists()
    backups = bridge.list_backups()
    assert backups[0]["archive"] == "Game.rgss3a"
    run_sync(bridge, "restore_archive")
    assert (root / "Game.rgss3a").exists() and not (root / "Data").exists()


def test_encrypted_archive_declined_leaves_game_untouched(tmp_path, monkeypatch, fake_ollama):
    import providers
    root = tmp_path / "EncGame"
    _encrypted_vxace_game(root)
    before = sorted(p.name for p in root.iterdir())
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    monkeypatch.setattr(bridge, "_ask", lambda *a, **k: False)
    bridge._select_game(str(root))
    run_sync(bridge, "translate")
    assert sorted(p.name for p in root.iterdir()) == before


def test_vx_and_xp_archive_only_games_are_detected(tmp_path):
    import engine_rpgmaker as er
    import rgss_archive as ra
    for name, kind in (("Game.rgss2a", "vx"), ("Game.rgssad", "xp")):
        root = tmp_path / kind
        root.mkdir()
        ra.write_archive(root / name, [("Data/System.rxdata", b"\x04\x080")], version=1)
        info = er.detect_rpgmaker_game(root)
        assert info.engine_type == kind and info.has_encrypted_archive


# ── Unreal .pak (repak) ──────────────────────────────────────────────────────
def _locres_bytes(tmp_path, entries):
    from pylocres import Entry, LocresFile, Namespace
    loc = LocresFile()
    ns = Namespace("")
    for key, text in entries.items():
        ns.add(Entry(key, text, text, is_hash=False))
    loc.add(ns)
    out = tmp_path / "tmp.locres"
    loc.write(str(out))
    return out.read_bytes()


def _pak_game(root):
    (root / "Engine").mkdir(parents=True)
    paks = root / "MyGame" / "Content" / "Paks"
    paks.mkdir(parents=True)
    (root / "MyGame" / "Binaries" / "Win64").mkdir(parents=True)
    (paks / "pakchunk0-Windows.pak").write_bytes(b"PAK")
    return paks


class FakeRepak:
    """repak.exe yerine: list / unpack / pack / info komutlarını taklit eder."""

    def __init__(self, files, encrypted=False):
        self.files, self.encrypted, self.calls, self.packed = files, encrypted, [], None

    def __call__(self, args, aes_key="", timeout=600):
        import unreal_pak
        self.calls.append((args[0], aes_key))
        if self.encrypted and args[0] != "pack" and aes_key != "0xABC":   # pack anahtar kullanmaz
            raise unreal_pak.NeedsAesKey("Error: AES key required")
        if args[0] == "info":
            return "mount point: ../../../\nversion: V11\nencrypted index: false\n"
        if args[0] == "list":
            return "\n".join(list(self.files) + ["MyGame/Content/Movies/intro.mp4"])
        if args[0] == "unpack":
            out = Path(args[args.index("--output") + 1])
            wanted = [args[i + 1] for i, a in enumerate(args) if a == "--include"]
            for name in wanted:
                (out / name).parent.mkdir(parents=True, exist_ok=True)
                (out / name).write_bytes(self.files[name])
            return ""
        if args[0] == "pack":
            staging, target = Path(args[1]), Path(args[2])
            self.packed = {p.relative_to(staging).as_posix(): p.read_bytes() for p in staging.rglob("*") if p.is_file()}
            target.write_bytes(b"MODPAK")
            assert args[args.index("--version") + 1] == "V11"
            return ""
        raise AssertionError(args)


from pathlib import Path  # noqa: E402


def test_unreal_pak_install_prompt_translate_and_mod_pak(tmp_path, monkeypatch, fake_ollama):
    import providers
    import unreal_pak
    from pylocres import LocresFile
    root = tmp_path / "UEGame"
    paks = _pak_game(root)
    en = "MyGame/Content/Localization/Game/en/Game.locres"
    fr = "MyGame/Content/Localization/Game/fr/Game.locres"
    fake = FakeRepak({en: _locres_bytes(tmp_path, {"k1": "Start Game", "k2": "Open the gate"}),
                      fr: _locres_bytes(tmp_path, {"k1": "Commencer"})})
    monkeypatch.setattr(unreal_pak, "run", fake)
    monkeypatch.setattr(unreal_pak, "TOOLS_DIR", tmp_path / "tools")
    installed = []

    def fake_install(log=print):
        (tmp_path / "tools").mkdir()
        (tmp_path / "tools" / "repak.exe").write_bytes(b"MZ")
        installed.append(True)
        return tmp_path / "tools" / "repak.exe"

    monkeypatch.setattr(unreal_pak, "install_repak", fake_install)
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    asked = []
    monkeypatch.setattr(bridge, "_ask", lambda title, text, timeout=300.0: asked.append(text) or True)
    bridge._select_game(str(root))
    assert bridge._game["type"] == "unreal"
    run_sync(bridge, "analyze")
    assert any("repak" in n for n in bridge._game["analysis"]["notes"]), "kurulmadan önce bilgilendirmeli"
    assert not installed, "analiz izin almadan araç kurmamalı"
    run_sync(bridge, "translate")
    assert installed and "repak" in asked[0] and "indirip" in asked[0]
    mod = paks / "~mods" / "zzz_Capri_TR_P.pak"
    assert mod.exists()
    assert list(fake.packed) == [en], "yalnızca kaynak dil dosyası paketlenmeli"
    staged = tmp_path / "staged.locres"
    staged.write_bytes(fake.packed[en])
    loc = LocresFile()
    loc.read(str(staged))
    assert {e.translation for ns in loc for e in ns} == {"TR(Start Game)", "TR(Open the gate)"}
    assert (paks / "pakchunk0-Windows.pak").read_bytes() == b"PAK", "oyunun paketi değişmemeli"
    assert unreal_pak.remove_mod(root, log=lambda s: None) and not mod.exists()


def test_unreal_pak_encrypted_needs_aes_key(tmp_path, monkeypatch, fake_ollama):
    import providers
    import unreal_pak
    root = tmp_path / "UEGame"
    paks = _pak_game(root)
    en = "MyGame/Content/Localization/Game/en/Game.locres"
    fake = FakeRepak({en: _locres_bytes(tmp_path, {"k1": "Start Game"})}, encrypted=True)
    monkeypatch.setattr(unreal_pak, "run", fake)
    monkeypatch.setattr(unreal_pak, "TOOLS_DIR", tmp_path / "tools")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "repak.exe").write_bytes(b"MZ")
    bridge = make_bridge(tmp_path, monkeypatch, model="ollama")
    monkeypatch.setattr(app_modern.prov, "load_provider_config", lambda: providers.ProviderConfig(ollama_host=fake_ollama))
    bridge._select_game(str(root))
    run_sync(bridge, "analyze")
    assert any("AES" in n for n in bridge._game["analysis"]["notes"])
    bridge.project_glossary_save([], "sen", "", " 0xABC ")
    assert bridge.project_glossary_load()["aes_key"] == "0xABC"
    bridge.project_glossary_save([["Start", "Başla"]], "sen", "")  # anahtar alanı gönderilmezse korunmalı
    assert bridge.project_glossary_load()["aes_key"] == "0xABC"
    run_sync(bridge, "translate")
    assert (paks / "~mods" / "zzz_Capri_TR_P.pak").exists()
    assert [key for cmd, key in fake.calls if cmd == "unpack"] == ["0xABC"]


def test_repak_asset_selection(monkeypatch):
    import unreal_pak

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"tag_name": "v0.2.3", "assets": [
                {"name": "repak_cli-x86_64-unknown-linux-gnu.tar.xz", "browser_download_url": "L", "size": 1},
                {"name": "repak_cli-x86_64-pc-windows-msvc.msi", "browser_download_url": "M", "size": 1},
                {"name": "repak_cli-x86_64-pc-windows-msvc.zip", "browser_download_url": "W", "size": 2022374}]}

    monkeypatch.setattr(unreal_pak.requests, "get", lambda *a, **k: Resp())
    assert unreal_pak.latest_asset() == {"version": "v0.2.3", "url": "W", "size": 2022374}


# ── Yerel model çalışma ortamı (PyTorch) ─────────────────────────────────────
INDEX = "".join(f'<a href="/whl/{v}/torch-{ver}%2B{v}-cp311-cp311-win_amd64.whl#sha256=x">t</a>\n'
                for ver, v in [("2.9.0", "cpu"), ("2.9.0", "cu126"), ("2.10.0", "cu128"), ("2.11.0", "cu130"),
                               ("2.11.0", "cpu"), ("2.12.0", "cu134")]) + \
        '<a href="/whl/cu134/torch-2.13.0.dev20260101%2Bcu134-cp311-cp311-win_amd64.whl">dev</a>' + \
        '<a href="/whl/cu126/torch-2.11.0%2Bcu126-cp312-cp312-win_amd64.whl">py312</a>'


def test_torch_wheel_matches_driver():
    import gpu_runtime as g
    assert g.pick_torch_wheel(INDEX, (13, 4))["variant"] == "cu134"
    assert g.pick_torch_wheel(INDEX, (13, 0)) == {
        "url": "https://download.pytorch.org/whl/cu130/torch-2.11.0%2Bcu130-cp311-cp311-win_amd64.whl",
        "name": "torch-2.11.0+cu130-cp311-cp311-win_amd64.whl", "version": "2.11.0", "variant": "cu130"}
    assert g.pick_torch_wheel(INDEX, (12, 6))["name"] == "torch-2.9.0+cu126-cp311-cp311-win_amd64.whl"
    assert g.pick_torch_wheel(INDEX, None)["name"] == "torch-2.11.0+cpu-cp311-cp311-win_amd64.whl"
    with pytest.raises(RuntimeError):
        g.pick_torch_wheel(INDEX, (11, 0))


def test_pypi_wheel_choice():
    import gpu_runtime as g
    files = [{"filename": "regex-1.tar.gz"}, {"filename": "regex-1-cp312-cp312-win_amd64.whl"},
             {"filename": "regex-1-py3-none-any.whl"}, {"filename": "regex-1-cp311-cp311-win_amd64.whl"}]
    assert g.pick_pypi_wheel(files)["filename"] == "regex-1-cp311-cp311-win_amd64.whl"
    assert g.pick_pypi_wheel(files[:3])["filename"] == "regex-1-py3-none-any.whl"
    assert g.pick_pypi_wheel([{"filename": "x-1-cp39-cp39-manylinux.whl"}]) is None


def _wheel(path, files):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path.read_bytes()


def test_runtime_install_downloads_missing_and_activates(tmp_path, monkeypatch):
    import sys
    import gpu_runtime as g
    monkeypatch.setattr(g, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(g, "SITE_DIR", tmp_path / "runtime" / "site-packages")
    monkeypatch.setattr(g, "PACKAGES", [("capri-demo-dep", "1.0", "capri_demo_dep")])
    monkeypatch.setattr(g, "driver_cuda", lambda: (12, 6))
    dep = _wheel(tmp_path / "d.whl", {"capri_demo_dep/__init__.py": "VALUE = 7\n",
                                       "capri_demo_dep-1.0.dist-info/METADATA": "Name: capri-demo-dep\n"})
    torch_whl = _wheel(tmp_path / "t.whl", {"capri_fake_torch/__init__.py": "OK = True\n",
                                             "capri_fake_torch-2.9.0.data/purelib/capri_fake_extra.py": "X = 1\n",
                                             "capri_fake_torch-2.9.0.data/scripts/evil.exe": "no"})
    seen = []

    class Resp:
        def __init__(self, body=b"", js=None, text=""):
            self.content, self._js, self.text = body, js, text
            self.headers = {"content-length": str(len(body))}

        def json(self):
            return self._js

        def raise_for_status(self):
            pass

        def iter_content(self, size):
            yield self.content

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_get(url, **kw):
        seen.append(url)
        if "pypi.org" in url:
            return Resp(js={"urls": [{"filename": "capri_demo_dep-1.0-py3-none-any.whl", "url": "https://files/dep.whl"}]})
        if url == g.TORCH_INDEX:
            return Resp(text=INDEX)
        return Resp(body=dep if "dep.whl" in url else torch_whl)

    torch_present = [False]
    real_has = g._has
    monkeypatch.setattr(g, "_has", lambda m: torch_present[0] if m == "torch" else real_has(m))
    monkeypatch.setattr(g.requests, "get", fake_get)
    assert set(g.missing()) == {"capri-demo-dep", "torch"}
    progress = []
    info = g.install(log=lambda s: None, progress=lambda a, b: progress.append((a, b)))
    torch_present[0] = True
    assert info["variant"] == "cu126" and "pypi.org/pypi/capri-demo-dep/1.0/json" in seen[0]
    site = tmp_path / "runtime" / "site-packages"
    assert (site / "capri_fake_extra.py").exists() and not list(site.rglob("evil.exe"))
    assert str(site) in sys.path
    import capri_demo_dep
    assert capri_demo_dep.VALUE == 7 and g.ready()
    assert not (tmp_path / "runtime" / "downloads").exists()
    sys.path.remove(str(site))


def test_local_model_requires_runtime(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch, model="opus")
    monkeypatch.setattr(app_modern.gpu_runtime, "ready", lambda: False)
    with pytest.raises(app_modern.UserError, match="PyTorch"):
        bridge._check_model_ready("unity")
    monkeypatch.setattr(bridge, "_ask", lambda *a, **k: False)
    monkeypatch.setattr(app_modern.gpu_runtime, "driver_cuda", lambda: None)
    assert bridge._ensure_runtime() is False, "onay verilmezse hiçbir şey indirilmemeli"
    assert bridge.model_status()["runtime"]["ready"] is False


# ── Paketlenmiş exe yolları ve ad ────────────────────────────────────────────
def test_frozen_paths_and_seed(tmp_path, monkeypatch):
    import importlib
    import sys
    import paths
    exe_dir, meipass = tmp_path / "Capri", tmp_path / "Capri" / "_internal"
    (meipass / "data").mkdir(parents=True)
    (meipass / "data" / "glossary.json").write_text('{"Save": "Kaydet"}', encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "Capri.exe"))
    frozen = importlib.reload(paths)
    try:
        assert frozen.APP_DIR == exe_dir and frozen.RES_DIR == meipass and frozen.WEB_DIR == meipass / "web"
        frozen.seed_user_files()
        assert json.loads((exe_dir / "data" / "glossary.json").read_text(encoding="utf-8")) == {"Save": "Kaydet"}
        (exe_dir / "data" / "glossary.json").write_text('{"Save": "Kullanıcının"}', encoding="utf-8")
        frozen.seed_user_files()
        assert "Kullanıcının" in (exe_dir / "data" / "glossary.json").read_text(encoding="utf-8"), "kullanıcı sözlüğü ezilmemeli"
    finally:
        monkeypatch.undo()
        importlib.reload(paths)


def test_capri_branding_and_legacy_patch_import(tmp_path, monkeypatch):
    assert app_modern.PATCH_SUFFIX == ".capripatch"
    html = (app_modern.WEB_DIR / "index.html").read_text(encoding="utf-8")
    assert "<title>Capri</title>" in html and "OmniTrans" not in html
    assert (app_modern.ICON_FILE).exists()


def test_credentials_migrate_from_legacy_prefix(monkeypatch):
    import secrets_store as ss
    store = {"OmniTrans/gemini_api_key": "old-secret"}
    monkeypatch.setattr(ss, "_read", lambda target: store.get(target))
    monkeypatch.setattr(ss, "set", lambda name, value: store.__setitem__("Capri/" + name, value) or True)
    deleted = []
    monkeypatch.setattr(ss, "_adv", type("A", (), {"CredDeleteW": staticmethod(lambda t, *a: deleted.append(t))})())
    assert ss.get("gemini_api_key") == "old-secret"
    assert store["Capri/gemini_api_key"] == "old-secret" and deleted == ["OmniTrans/gemini_api_key"]


# ── Güncelleme kaynağı ve uygulama içi güncelleme ────────────────────────────
def test_update_repo_from_git_and_build_info(tmp_path, monkeypatch):
    import updater
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text('[core]\n\tbare = false\n[remote "origin"]\n\turl = https://github.com/ali/Capri.git\n'
                                              '\tfetch = +refs/heads/*:refs/remotes/origin/*\n', encoding="utf-8")
    assert updater.repo_from_git(tmp_path) == "ali/Capri"
    (tmp_path / ".git" / "config").write_text('[remote "origin"]\n\turl = git@github.com:veli/capri-tr\n', encoding="utf-8")
    assert updater.repo_from_git(tmp_path) == "veli/capri-tr"
    assert updater.repo_from_git(tmp_path / "yok") == ""
    monkeypatch.setattr(updater, "BUILD_INFO", tmp_path / "build_info.json")
    (tmp_path / "build_info.json").write_text('{"repo": "gomulu/Capri"}', encoding="utf-8")
    assert updater.default_repo() == "gomulu/Capri"


def test_check_update_dialog_states(tmp_path, monkeypatch):
    import updater
    bridge = make_bridge(tmp_path, monkeypatch)
    monkeypatch.setattr(bridge, "_update_repo", lambda: "ali/Capri")
    monkeypatch.setattr(updater, "check", lambda cur, repo: {"available": True, "latest": "9.0.0", "asset": "http://x/C.zip",
                                                             "url": "http://x", "notes": "Yeni", "asset_size": 10})
    monkeypatch.setattr(app_modern, "FROZEN", True)
    info = bridge.check_update(manual=True)
    assert info["can_apply"] and info["current"] == app_modern.APP_VERSION
    assert ("update", info) in bridge._ui.events
    assert not [e for e in bridge._ui.events if e[0] == "notify"], "elle kontrolde ayrıca bildirim gerekmez"
    bridge.check_update(manual=False)
    assert any(e[0] == "notify" and e[1]["action"]["update"] for e in bridge._ui.events), "açılışta yeni sürüm bildirilmeli"
    monkeypatch.setattr(app_modern, "FROZEN", False)
    assert bridge.check_update(manual=True)["can_apply"] is False, "kaynak kodda exe paketi uygulanmaz"
    monkeypatch.setattr(bridge, "_update_repo", lambda: "")
    assert "kaynağı" in bridge.check_update(manual=True)["error"]


def test_apply_update_failure_unlocks_dialog(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, monkeypatch)
    monkeypatch.setattr(app_modern, "FROZEN", False)
    bridge._update_info = {"available": True, "asset": "http://x/C.zip", "latest": "9.0.0"}
    run_sync(bridge, "apply_update")
    assert ("update_progress", None) in bridge._ui.events
