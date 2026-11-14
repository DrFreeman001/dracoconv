"""Ouverture de la fenêtre sur des fichiers donnés, avec une seule fenêtre pour toute une sélection.

Le clic droit de l'Explorateur lance un processus par fichier sélectionné. Le premier devient la fenêtre ;
les suivants lui transmettent leur chemin par un tube nommé local, puis s'arrêtent sans charger Qt.
"""
from __future__ import annotations

import getpass
import hashlib
import os
import queue
import threading
import time
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client, Listener
from pathlib import Path

DIRECTIONS = ("encode", "decode")
_DRACO = ".drc"


def parse(argv: list[str]) -> tuple[str | None, list[Path]]:
    """Lit « [--encode|--decode] chemins... » ; le sens est None s'il n'est pas donné."""
    direction, paths = None, []
    for arg in argv:
        if arg in ("--encode", "--decode"):
            direction = arg[2:]
        elif arg:
            paths.append(Path(arg))
    return direction, paths


def infer_direction(paths: list[Path]) -> str:
    """Décoder seulement si tous les chemins sont des fichiers .drc ; sinon encoder."""
    files = [p for p in paths if p.suffix.lower() == _DRACO]
    return "decode" if paths and len(files) == len(paths) else "encode"


def _names() -> tuple[str, str, bytes]:
    user = hashlib.sha256(getpass.getuser().encode("utf-8")).hexdigest()[:16]
    return f"Local\\dracoconv-gui-{user}", rf"\\.\pipe\dracoconv-gui-{user}", f"dracoconv-{user}".encode()


class Channel:
    """Côté fenêtre : reçoit les demandes des autres lancements dans une file lue par Qt."""

    def __init__(self, address: str, authkey: bytes):
        self.requests: queue.Queue[tuple[str | None, list[Path]]] = queue.Queue()
        self._closed = False
        self._listener = Listener(address, family="AF_PIPE", authkey=authkey)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while not self._closed:
            try:
                with self._listener.accept() as connection:
                    direction, paths = connection.recv()
                    if direction in DIRECTIONS or direction is None:
                        self.requests.put((direction, [Path(p) for p in paths]))
            except (OSError, EOFError, ValueError, TypeError, AuthenticationError):
                time.sleep(0.05)

    def close(self) -> None:
        self._closed = True
        self._listener.close()


def forward(address: str, authkey: bytes, direction: str | None, paths: list[Path]) -> bool:
    try:
        with Client(address, family="AF_PIPE", authkey=authkey) as connection:
            connection.send((direction, [str(p) for p in paths]))
        return True
    except (OSError, EOFError, AuthenticationError):
        return False


def claim_or_forward(direction: str | None, paths: list[Path], wait_s: float = 15.0) -> Channel | None | bool:
    """Devient la fenêtre principale (renvoie un Channel), ou transmet à elle (renvoie True).

    Sans chemins, ou hors Windows, renvoie None : la fenêtre s'ouvre normalement, sans coordination.
    """
    if not paths or os.name != "nt":
        return None
    import ctypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    mutex_name, address, authkey = _names()
    mutex = kernel.CreateMutexW(None, False, mutex_name)
    if not mutex:
        return None
    deadline = time.monotonic() + wait_s
    while True:
        if kernel.WaitForSingleObject(mutex, 0) in (0, 0x80):  # acquis, ou abandonné par une fenêtre fermée
            try:
                return Channel(address, authkey)
            except OSError:
                return None
        if forward(address, authkey, direction, paths):
            return True
        if time.monotonic() > deadline:
            return None
        time.sleep(0.1)
