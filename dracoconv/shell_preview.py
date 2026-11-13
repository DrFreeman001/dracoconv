"""Isolated software-only Shell preview helper (feasibility prototype)."""
from __future__ import annotations
import argparse
import ctypes
import math
from pathlib import Path
import sys
import threading
import numpy as np
import DracoPy
from PySide6.QtCore import Qt, QPointF, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF
from PySide6.QtWidgets import QApplication, QWidget

MAX_INPUT = 32 * 1024 * 1024


def prepare_mesh(data: bytes, face_limit: int = 12000):
    if not data or len(data) > MAX_INPUT:
        raise ValueError('Input exceeds preview limit or is empty')
    try:
        mesh = DracoPy.decode(data)
    except Exception as exc:
        raise ValueError('Invalid Draco input') from exc
    faces = getattr(mesh, 'faces', None)
    if faces is None or not len(faces):
        raise ValueError('Draco point clouds are not supported by this preview')
    points = np.asarray(mesh.points, dtype=np.float64)
    if not np.isfinite(points).all():
        raise ValueError('Non-finite geometry')
    low, high = points.min(axis=0), points.max(axis=0)
    scale = float(np.max(high - low))
    if scale <= 0:
        raise ValueError('Empty geometry bounds')
    reduced = len(faces) > face_limit
    faces = faces[::max(1, math.ceil(len(faces) / face_limit))]
    return ((points[faces] - (low + high) / 2) / scale), reduced


def project(triangles, yaw=30., pitch=-20., zoom=1.):
    y, p = np.radians([yaw, pitch])
    ry = np.array([[np.cos(y),0,np.sin(y)],[0,1,0],[-np.sin(y),0,np.cos(y)]])
    rx = np.array([[1,0,0],[0,np.cos(p),-np.sin(p)],[0,np.sin(p),np.cos(p)]])
    return triangles @ (rx @ ry).T * np.clip(zoom, .2, 5.)


def paint_mesh(painter, triangles, width, height, yaw=30., pitch=-20., zoom=1.):
    painter.fillRect(0, 0, width, height, QColor('#eef1f5'))
    transformed = project(triangles, yaw, pitch, zoom)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    for tri in transformed[np.argsort(transformed[:,:,2].mean(axis=1))]:
        normal = np.cross(tri[1]-tri[0], tri[2]-tri[0])
        norm = np.linalg.norm(normal)
        light = .45 + .5 * abs(float(normal[2] / norm)) if norm else .45
        painter.setBrush(QColor(int(65*light), int(135*light), int(205*light)))
        painter.drawPolygon(QPolygonF([QPointF(width/2+x*min(width,height)*.72, height/2-y*min(width,height)*.72) for x,y,z in tri]))


def render_image(triangles, size):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    paint_mesh(painter, triangles, size, size)
    painter.end()
    return image


class Preview(QWidget):
    loaded = Signal(object, str)

    def __init__(self, source, parent_hwnd):
        super().__init__()
        self.triangles = None
        self.message = 'Chargement…'
        self.yaw, self.pitch, self.zoom = 30., -20., 1.
        self.drag = None
        self.parent_hwnd = parent_hwnd
        self.source = source
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.loaded.connect(self.ready)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.resize(480, 400)
        hwnd = int(self.winId())
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetParent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.SetParent.restype = ctypes.c_void_p
        ctypes.set_last_error(0)
        previous = user32.SetParent(hwnd, parent_hwnd)
        if not previous and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW(hwnd, -16, 0x40000000 | 0x10000000 | 0x04000000)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.sync_parent)
        self.timer.start(100)
        self.show()
        threading.Thread(target=self.load, args=(source,), daemon=True).start()

    def load(self, source):
        try:
            tris, reduced = prepare_mesh(Path(source).read_bytes())
            self.loaded.emit(tris, 'Affichage simplifié · ' if reduced else '')
        except Exception as exc:
            self.loaded.emit(None, str(exc))

    def ready(self, triangles, message):
        self.triangles, self.message = triangles, message
        Path(self.source).with_name("ready").touch()
        self.update()

    def sync_parent(self):
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.IsWindow.argtypes = [ctypes.c_void_p]
        user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
        if not user32.IsWindow(self.parent_hwnd):
            QApplication.quit()
            return
        rect = wintypes.RECT()
        if not user32.GetClientRect(self.parent_hwnd, ctypes.byref(rect)):
            QApplication.quit()
            return
        ratio = self.devicePixelRatioF()
        self.setGeometry(0,0,round(rect.right / ratio),round(rect.bottom / ratio))

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.triangles is not None:
            paint_mesh(painter,self.triangles,self.width(),self.height(),self.yaw,self.pitch,self.zoom)
        else:
            painter.fillRect(self.rect(), QColor('#eef1f5'))
        painter.setPen(QColor('#26384c'))
        painter.drawText(self.rect().adjusted(10,10,-10,-10), Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap, self.message + ('Glisser : rotation · Molette : zoom · R : réinitialiser' if self.triangles is not None else ''))

    def mousePressEvent(self, event):
        self.drag = event.position()
        self.setFocus()

    def mouseReleaseEvent(self, event):
        self.drag = None

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            delta = event.position() - self.drag
            self.yaw += delta.x() * .5
            self.pitch += delta.y() * .5
            self.drag = event.position()
            self.update()

    def wheelEvent(self, event):
        self.zoom = float(np.clip(self.zoom * 1.15 ** (event.angleDelta().y()/120), .2, 5))
        self.update()

    def trace(self, event):
        with Path(self.source).with_name("events.log").open("a", encoding="utf-8") as output:
            output.write(f"qt {event}\n")

    def focusInEvent(self, event):
        self.trace("focus-in")
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.trace("focus-out")
        super().focusOutEvent(event)

    def focusNextPrevChild(self, forward):
        self.trace(f"tab forward={forward}")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SendMessageTimeoutW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
        user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
        result = ctypes.c_size_t()
        user32.SendMessageTimeoutW(self.parent_hwnd, 0x8001, int(forward), 0, 2, 1000, ctypes.byref(result))
        return True

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_R:
            self.trace("reset")
            self.yaw, self.pitch, self.zoom = 30., -20., 1.
            self.update()
        else:
            super().keyPressEvent(event)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output')
    parser.add_argument('--size', type=int, default=256)
    parser.add_argument('--parent', type=int)
    args = parser.parse_args()
    app = QApplication([])
    if args.output:
        triangles, _ = prepare_mesh(Path(args.input).read_bytes())
        return 0 if render_image(triangles, max(16,min(args.size,1024))).save(args.output) else 2
    widget = Preview(args.input, args.parent)
    return app.exec()

if __name__ == '__main__':
    sys.exit(main())
