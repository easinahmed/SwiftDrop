"""Hardware video decode probe (macOS VideoToolbox through ctypes).

On Windows, Media Player plays AV1, VP9 and HEVC (with Microsoft's Store
extensions), so those codecs count as playable and nothing is converted.
"""

from __future__ import annotations

import ctypes
import functools
import sys

_VT_PATH = "/System/Library/Frameworks/VideoToolbox.framework/VideoToolbox"
_WINDOWS_PLAYABLE = frozenset({"av01", "vp09", "hvc1", "hev1"})


@functools.cache
def hardware_decodes(fourcc: str) -> bool:
    """True when this Mac decodes the codec in hardware; False on any error."""
    if sys.platform == "win32":
        return fourcc.lower() in _WINDOWS_PLAYABLE
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
