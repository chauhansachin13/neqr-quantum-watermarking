"""
Proposed extensions of the base scheme: keyed, blind and self-recovering.

* :class:`SecureWatermark` - 2x2 blocks, 8-bit keyed tag per block (base
  content code xor a one-time Toeplitz MAC of the MSBs); blind tamper
  localisation, forgery probability ``2**-8`` per block.
* :class:`SelfRecoveringWatermark` - 4x4 blocks carrying 20 recovery bits for a
  keyed partner block plus a 12-bit tag; blind localisation and repair.

Both keep the base payload (two LSBs per pixel, 2 bpp) and support colour
images channel by channel.
"""

from qwm.secure.authentication import (
    AuthenticationResult,
    SecureWatermark,
    content_code,
    msb_message_bits,
)
from qwm.secure.keys import ToeplitzMAC, keyed_derangement, keystream, keystream_bits
from qwm.secure.recovery import (
    RecoveryResult,
    SelfRecoveringWatermark,
    decode_recovery_codes,
    recovery_codes,
)

__all__ = [
    "AuthenticationResult",
    "RecoveryResult",
    "SecureWatermark",
    "SelfRecoveringWatermark",
    "ToeplitzMAC",
    "content_code",
    "decode_recovery_codes",
    "keyed_derangement",
    "keystream",
    "keystream_bits",
    "msb_message_bits",
    "recovery_codes",
]
