# Recette PyInstaller : un dossier dist/dracoconv avec la fenêtre (dracoconv-gui.exe) et la ligne de
# commande (dracoconv.exe), utilisables sans Python installé. Lancer par tools/build_exe.ps1.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

root = Path(SPECPATH).parent
datas = collect_data_files('dracoconv', includes=['locales/*.json', 'data/*.json'])
# Outils de référence Draco, s'ils ont été compilés par tools/build_draco.ps1 (facultatifs).
binaries = [(str(p), 'dracoconv/bin') for p in (root / 'dracoconv' / 'bin').glob('draco_*.exe')]
binaries += collect_dynamic_libs('DracoPy')
excludes = ['tkinter', 'pytest', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQml',
            'PySide6.QtQuick', 'PySide6.QtPdf', 'PySide6.QtMultimedia', 'PySide6.QtNetwork']


def analysis(script):
    return Analysis([str(root / 'tools' / script)], pathex=[str(root)], datas=datas, binaries=binaries,
                    hiddenimports=['dracoconv.cli', 'dracoconv.gui.app'], excludes=excludes, noarchive=False)


gui, cli = analysis('entry_gui.py'), analysis('entry_cli.py')
gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name='dracoconv-gui', console=False)
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name='dracoconv', console=True)
COLLECT(gui_exe, cli_exe, gui.binaries, gui.datas, cli.binaries, cli.datas, name='dracoconv')
