"""Dossiers surveillés : conversion automatique des nouveaux modèles, sans programme qui tourne en permanence.

Une tâche du Planificateur de tâches de Windows lance ``dracoconv-gui --watch`` à l'ouverture de session puis à
intervalle régulier. Chaque passage recense les dossiers, convertit ce qui n'a pas encore de .drc, écrit une
ligne dans le journal de surveillance, puis s'arrête : rien ne reste en mémoire entre deux passages.

Les fichiers modifiés depuis moins de cinq minutes sont laissés pour le passage suivant (téléchargement en
cours). Le passage tourne en priorité basse, avec un seul processus de conversion par défaut.
"""
from __future__ import annotations

import getpass
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from .config import data_dir, load_prefs, save_prefs

TASK_NAME = "dracoconv-surveillance"
INTERVALS_MIN = (15, 60, 360, 1440)
SETTLE_S = 300  # un fichier plus récent que cela est peut-être encore en cours d'écriture
_BELOW_NORMAL = 0x00004000
_NO_WINDOW = 0x08000000


@dataclass
class WatchConfig:
    folders: list[str] = field(default_factory=list)
    profile: str = "lossless"
    originals: str = "keep"  # « keep » ou « replace » (corbeille après vérification)
    interval_min: int = 60
    workers: int = 1

    @classmethod
    def load(cls) -> "WatchConfig":
        raw = load_prefs().get("watch") or {}
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        config = cls(**known)
        if config.interval_min not in INTERVALS_MIN:
            config.interval_min = 60
        if config.originals not in ("keep", "replace"):
            config.originals = "keep"
        return config

    def save(self) -> None:
        save_prefs({"watch": asdict(self)})


def log_path() -> Path:
    return data_dir() / "surveillance.log"


def journal_path() -> Path:
    return data_dir() / "surveillance" / "dernier-passage.sqlite"


def read_log(lines: int = 50) -> list[str]:
    try:
        return log_path().read_text(encoding="utf-8").splitlines()[-lines:]
    except OSError:
        return []


def _append_log(text: str) -> None:
    try:
        with open(log_path(), "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M}  {text}\n")
    except OSError:
        pass


def _lower_priority() -> None:
    """Priorité basse pour ce processus et ceux qu'il lance : le PC reste fluide pendant un passage."""
    if os.name == "nt":
        import ctypes

        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), _BELOW_NORMAL)


def run_once(config: WatchConfig, stop: threading.Event | None = None, now: float | None = None) -> dict:
    """Un passage : recense, convertit ce qui est nouveau, journalise. Rend le résumé du lot."""
    from .batch import BatchOptions, Journal, build_plan, run
    from .io.sniff import MODEL_KINDS
    from .scan import ScanOptions, scan
    from .settings import PROFILES, user_profiles

    _lower_priority()
    folders = [Path(f) for f in config.folders if Path(f).is_dir()]
    empty = {"total": 0, "done": 0, "skipped": 0, "failed": 0, "pending": 0, "bytes_before": 0,
             "bytes_after": 0, "reasons": {}, "paused": None, "waiting": 0}
    if not folders:
        _append_log("aucun dossier surveillé accessible")
        return empty
    settings = {**PROFILES, **user_profiles()}.get(config.profile, PROFILES["lossless"])
    options = BatchOptions(direction="encode", originals=config.originals,
                           confirm_replace=config.originals == "replace", workers=max(1, config.workers))
    inventory = scan(folders, ScanOptions(kinds=frozenset(MODEL_KINDS), look_inside_zips=False), stop=stop)
    now = time.time() if now is None else now
    settled = [e for e in inventory.entries if now - e.mtime >= SETTLE_S]
    waiting = len(inventory.entries) - len(settled)
    inventory.entries = settled
    items = [i for i in build_plan(inventory, folders, settings, options) if not i.skip_reason]
    if not items:
        summary = dict(empty, waiting=waiting)
        if waiting:
            _append_log(f"rien à convertir ({waiting} fichier(s) récent(s) gardés pour le passage suivant)")
        return summary
    path = journal_path()
    for old in (path, path.with_name(path.name + "-journal")):
        try:
            old.unlink()
        except OSError:
            pass
    journal = Journal(path)
    try:
        journal.add_plan(items, settings, options)
        summary = run(journal, settings, options, stop=stop)
    finally:
        journal.close()
    summary["waiting"] = waiting
    saved = summary["bytes_before"] - summary["bytes_after"]
    _append_log(f"{summary['done']} converti(s), {summary['failed']} échec(s), {summary['skipped']} ignoré(s), "
                f"{saved / 2**20:.1f} Mo gagnés" + (f", {waiting} récent(s) en attente" if waiting else ""))
    return summary


# -- tâche planifiée -------------------------------------------------------------------------------------------


def launch_command() -> tuple[str, str, str]:
    """(programme, arguments, dossier de travail) que la tâche lance, sans fenêtre de console."""
    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        gui = exe.with_name("dracoconv-gui.exe")
        return str(gui if gui.exists() else exe), "--watch", str(exe.parent)
    windowless = exe.with_name("pythonw.exe")
    return str(windowless if windowless.exists() else exe), "-m dracoconv.gui.app --watch", str(Path.cwd())


def task_xml(interval_min: int, command: tuple[str, str, str], user: str | None = None,
             start: datetime | None = None) -> str:
    user = user or _user_id()
    start = (start or datetime.now()).replace(second=0, microsecond=0) + timedelta(minutes=1)
    program, arguments, folder = (escape(part) for part in command)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>dracoconv</Author>
    <Description>dracoconv : convertit en Draco les nouveaux modèles des dossiers surveillés, puis s'arrête.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user)}</UserId>
      <Delay>PT2M</Delay>
    </LogonTrigger>
    <TimeTrigger>
      <Repetition>
        <Interval>PT{interval_min}M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{start:%Y-%m-%dT%H:%M:%S}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>true</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <ExecutionTimeLimit>PT6H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{program}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{folder}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _user_id() -> str:
    domain = os.environ.get("USERDOMAIN")
    user = os.environ.get("USERNAME") or getpass.getuser()
    return f"{domain}\\{user}" if domain else user


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True, creationflags=_NO_WINDOW
                          if os.name == "nt" else 0)


def install_task(config: WatchConfig) -> None:
    """Crée ou remplace la tâche planifiée. Lève OSError avec le message de schtasks en cas d'échec."""
    xml = task_xml(config.interval_min, launch_command())
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as f:
        f.write(xml)
        name = f.name
    try:
        result = _schtasks("/Create", "/TN", TASK_NAME, "/XML", name, "/F")
    finally:
        os.unlink(name)
    if result.returncode != 0:
        raise OSError((result.stderr or result.stdout).strip())


def remove_task() -> None:
    if task_installed():
        result = _schtasks("/Delete", "/TN", TASK_NAME, "/F")
        if result.returncode != 0:
            raise OSError((result.stderr or result.stdout).strip())


def task_installed() -> bool:
    return os.name == "nt" and _schtasks("/Query", "/TN", TASK_NAME).returncode == 0


def run_task_now() -> None:
    result = _schtasks("/Run", "/TN", TASK_NAME)
    if result.returncode != 0:
        raise OSError((result.stderr or result.stdout).strip())
