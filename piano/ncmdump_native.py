"""在独立进程调用上游动态库，隔离其控制台提示与本程序的进度输出。"""
import ctypes
from pathlib import Path
import sys


def dump(source, folder, dll):
    library = ctypes.CDLL(str(dll))
    library.CreateNeteaseCrypt.argtypes = [ctypes.c_char_p]
    library.CreateNeteaseCrypt.restype = ctypes.c_void_p
    library.Dump.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    library.Dump.restype = ctypes.c_int
    library.DestroyNeteaseCrypt.argtypes = [ctypes.c_void_p]
    library.DestroyNeteaseCrypt.restype = None
    handle = library.CreateNeteaseCrypt(str(Path(source).resolve()).encode("utf-8"))
    if not handle:
        return 1
    try:
        return library.Dump(handle, str(Path(folder).resolve()).encode("utf-8"))
    finally:
        library.DestroyNeteaseCrypt(handle)


if __name__ == "__main__":
    sys.exit(dump(*sys.argv[1:]))
