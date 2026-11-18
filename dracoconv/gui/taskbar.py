"""Avancement d'un lot dans l'icône de la barre des tâches de Windows (interface ITaskbarList3).

Appels COM directs par ctypes, sans dépendance. Hors de Windows, ou si l'interface manque, tout devient sans effet.
"""
from __future__ import annotations

import ctypes
import sys
import uuid

_CLSID_TASKBAR_LIST = "56FDF344-FD6D-11D0-958A-006097C9A090"
_IID_TASKBAR_LIST3 = "EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF"
_CLSCTX_INPROC_SERVER = 1
# Rang des méthodes dans la table virtuelle : IUnknown (0-2), ITaskbarList (3-7), ITaskbarList2 (8), ITaskbarList3.
_HR_INIT, _SET_PROGRESS_VALUE, _SET_PROGRESS_STATE = 3, 9, 10

NO_PROGRESS, INDETERMINATE, NORMAL, ERROR, PAUSED = 0, 1, 2, 4, 8


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]


def _guid(text: str) -> _GUID:
    return _GUID.from_buffer_copy(uuid.UUID(text).bytes_le)


class TaskbarProgress:
    """Barre d'avancement verte (ou rouge, ou jaune) dans l'icône de la fenêtre ``hwnd``."""

    def __init__(self) -> None:
        self._pointer: ctypes.c_void_p | None = None
        self._failed = sys.platform != "win32"

    def _call(self, index: int, argtypes: tuple, *args) -> None:
        if self._pointer is None and not self._failed:
            self._create()
        if self._pointer is None:
            return
        table = ctypes.cast(self._pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        method = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(table[index])
        method(self._pointer, *args)

    def _create(self) -> None:
        try:
            ole32 = ctypes.OleDLL("ole32")
            try:
                ole32.CoInitialize(None)  # déjà fait par Qt d'habitude ; sans effet dans ce cas
            except OSError:
                pass
            pointer = ctypes.c_void_p()
            ole32.CoCreateInstance(ctypes.byref(_guid(_CLSID_TASKBAR_LIST)), None, _CLSCTX_INPROC_SERVER,
                                   ctypes.byref(_guid(_IID_TASKBAR_LIST3)), ctypes.byref(pointer))
            self._pointer = pointer
            self._call(_HR_INIT, ())
        except OSError:
            self._pointer = None
            self._failed = True

    def set_value(self, hwnd: int, done: int, total: int) -> None:
        self._call(_SET_PROGRESS_STATE, (ctypes.c_void_p, ctypes.c_int), hwnd, NORMAL)
        self._call(_SET_PROGRESS_VALUE, (ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_ulonglong),
                   hwnd, max(0, done), max(1, total))

    def set_state(self, hwnd: int, state: int) -> None:
        self._call(_SET_PROGRESS_STATE, (ctypes.c_void_p, ctypes.c_int), hwnd, state)

    def clear(self, hwnd: int) -> None:
        self.set_state(hwnd, NO_PROGRESS)
