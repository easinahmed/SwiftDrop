"""Hardware video decode probe (macOS VideoToolbox through ctypes)."""

from __future__ import annotations

import ctypes
import functools
import sys

_VT_PATH = "/System/Library/Frameworks/VideoToolbox.framework/VideoToolbox"


@functools.cache
def hardware_decodes(fourcc: str) -> bool:
    """True when this Mac decodes the codec in hardware; False on any error."""
    try:
        if sys.platform != "darwin":
            return False
        code = fourcc.encode("ascii")
        if len(code) != 4:
            return False
        vt = ctypes.CDLL(_VT_PATH)
        vt.VTIsHardwareDecodeSupported.restype = ctypes.c_bool
        vt.VTIsHardwareDecodeSupported.argtypes = [ctypes.c_uint32]
        return bool(vt.VTIsHardwareDecodeSupported(int.from_bytes(code, "big")))
    except Exception:
        return False
