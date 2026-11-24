import numpy as np
import pytest

from qwm.metrics.image import psnr
from qwm.secure import (
    SecureWatermark,
    SelfRecoveringWatermark,
    ToeplitzMAC,
    content_code,
    keyed_derangement,
    keystream,
    msb_message_bits,
    recovery_codes,
)
from qwm.secure.recovery import decode_recovery_codes
from qwm.watermark.generation import arithmetic_average, generate_watermark


# --------------------------------------------------------------------------- keys
def test_keystream_is_deterministic_and_domain_separated():
    a = keystream("k", "n", "dom", 64)
    assert np.array_equal(a, keystream("k", "n", "dom", 64))
    assert not np.array_equal(a, keystream("k", "n", "other", 64))
    assert not np.array_equal(a, keystream("k", "m", "dom", 64))
    assert not np.array_equal(a, keystream("K", "n", "dom", 64))
    # length-prefixed encoding: ("ab", "c") and ("a", "bc") must differ
    assert not np.array_equal(keystream("ab", "c", "d", 32), keystream("a", "bc", "d", 32))


def test_empty_key_rejected():
    with pytest.raises(ValueError):
        keystream("", "n", "d", 8)


def test_toeplitz_mac_vectorised_matches_per_block_and_is_affine():
    mac = ToeplitzMAC("key", "nonce", "test", n_blocks=50, msg_bits=24, tag_bits=8)
    rng = np.random.default_rng(0)
    m1 = rng.integers(0, 2, (50, 24), dtype=np.uint8)
    m2 = rng.integers(0, 2, (50, 24), dtype=np.uint8)
    t1, t2, t12 = mac.tags(m1), mac.tags(m2), mac.tags(m1 ^ m2)
    for b in range(50):
        assert np.array_equal(t1[b], mac.tag(b, m1[b]))
        T = mac.matrix(b)
        # Toeplitz structure: constant along diagonals
        assert all(T[i, j] == T[i + 1, j + 1] for i in range(7) for j in range(23))
    # T(m1) ^ T(m2) = T(m1 ^ m2) (the masks cancel in pairs): t1 ^ t2 = t12 ^ mask
    masks = np.stack([mac.mask(b) for b in range(50)])
    assert np.array_equal(t1 ^ t2, t12 ^ masks)


def test_toeplitz_family_is_xor_universal():
    # for fixed m != m', P_key[T m = T m'] = 2^-t
    m = np.zeros(10, dtype=np.uint8)
    m2 = m.copy()
    m2[3] = 1
    mac = ToeplitzMAC("universal", "", "u", n_blocks=6000, msg_bits=10, tag_bits=3)
    coll = np.mean(np.all(mac.tags(np.tile(m, (6000, 1))) == mac.tags(np.tile(m2, (6000, 1))), axis=1))
    assert abs(coll - 1 / 8) < 0.02


def test_keyed_derangement_properties():
    for n in (2, 3, 10, 1000):
        p = keyed_derangement("k", "n", "d", n)
        assert sorted(p.tolist()) == list(range(n))
        assert np.all(p != np.arange(n))
    assert np.array_equal(keyed_derangement("k", "n", "d", 50), keyed_derangement("k", "n", "d", 50))
    assert not np.array_equal(keyed_derangement("k", "n", "d", 50), keyed_derangement("k2", "n", "d", 50))


# --------------------------------------------------------------------------- 2x2 keyed scheme
def test_msb_message_and_content_code(natural_image):
    msg = msb_message_bits(natural_image)
    assert msg.shape == (32, 32, 24)
    # the message ignores the two LSBs
    assert np.array_equal(msg, msb_message_bits(natural_image ^ 0b11))
    assert np.array_equal(content_code(natural_image), generate_watermark(natural_image & 0xFC))


def test_secure_roundtrip_and_quality(natural_image):
    sw = SecureWatermark("secret", nonce="img-1")
    wm = sw.embed(natural_image)
    assert wm.dtype == np.uint8 and wm.shape == natural_image.shape
    assert np.array_equal(wm & 0xFC, natural_image & 0xFC)  # only the two LSBs change
    res = sw.verify(wm)
    assert res.authentic and res.tampered_fraction == 0.0
    assert 42.0 < psnr(natural_image, wm) < 46.5


def test_secure_detects_lsb_and_msb_changes_and_localises(natural_image):
    sw = SecureWatermark("secret", nonce="img-1")
    wm = sw.embed(natural_image)
    bad = wm.copy()
    bad[10:20, 30:40] ^= 0b100  # MSB-only change (LSBs kept)
    bad[40:44, 0:8] ^= 0b01  # LSB-only change
    res = sw.verify(bad)
    truth = np.zeros((32, 32), bool)
    truth[5:10, 15:20] = True
    truth[20:22, 0:4] = True
    assert res.tamper_map[truth].mean() > 0.9
    assert not res.tamper_map[~truth].any()  # untouched blocks are never flagged
    assert res.pixel_mask(bad.shape).shape == bad.shape


def test_secure_wrong_key_or_nonce_fails_everywhere(natural_image):
    wm = SecureWatermark("secret", nonce="a").embed(natural_image)
    assert SecureWatermark("secret!", nonce="a").verify(wm).tampered_fraction > 0.95
    assert SecureWatermark("secret", nonce="b").verify(wm).tampered_fraction > 0.95


def test_secure_colour_and_odd_sizes():
    rng = np.random.default_rng(5)
    img = rng.integers(0, 256, (33, 47, 3), dtype=np.uint8)
    sw = SecureWatermark("k", "colour")
    wm = sw.embed(img)
    assert wm.shape == img.shape and sw.verify(wm).authentic
    bad = wm.copy()
    bad[4, 4, 2] ^= 0x40
    res = sw.verify(bad)
    assert res.tamper_map[2, 2] and res.tamper_map.sum() == 1


# --------------------------------------------------------------------------- 4x4 self-recovery
def test_recovery_codes_are_truncated_base_averages(natural_image):
    codes = recovery_codes(natural_image)
    block = natural_image[4:8, 8:12]
    b = (1 * (64 // 4)) + 2  # block row 1, column 2
    expected = [arithmetic_average(block[r : r + 2, c : c + 2]) >> 3 for r, c in ((0, 0), (0, 2), (2, 0), (2, 2))]
    assert codes[b].tolist() == expected
    assert decode_recovery_codes(np.array([0, 31])).tolist() == [4, 252]


@pytest.mark.parametrize("reconstruction", ["interpolate", "flat"])
def test_self_recovery_roundtrip_and_repair(natural_image, reconstruction):
    srw = SelfRecoveringWatermark("secret", nonce="x", reconstruction=reconstruction)
    wm = srw.embed(natural_image)
    assert not srw.verify(wm).any()
    assert np.array_equal(wm & 0xFC, natural_image & 0xFC)
    bad = wm.copy()
    bad[16:32, 16:32] = 0
    res = srw.recover(bad)
    truth = np.zeros((16, 16), bool)
    truth[4:8, 4:8] = True
    assert np.array_equal(res.tamper_map, truth)
    assert res.restored_fraction > 0.8
    assert np.array_equal(res.inpainted_map | res.restored_map, res.tamper_map)
    # repaired region is far closer to the cover than the blacked-out one
    region = (slice(16, 32), slice(16, 32))
    assert psnr(natural_image[region], res.recovered[region]) > psnr(natural_image[region], bad[region]) + 10
    # authentic pixels are untouched
    keep = ~res.pixel_mask("tamper", bad.shape)
    assert np.array_equal(res.recovered[keep], bad[keep])


def test_self_recovery_partner_map_is_a_derangement():
    srw = SelfRecoveringWatermark("k", "n")
    p = srw.partners((64, 64))
    assert sorted(p.tolist()) == list(range(256)) and np.all(p != np.arange(256))


def test_self_recovery_colour():
    rng = np.random.default_rng(1)
    img = np.clip(rng.normal(128, 30, (32, 32, 3)), 0, 255).astype(np.uint8)
    srw = SelfRecoveringWatermark("k", "c")
    wm = srw.embed(img)
    assert not srw.verify(wm).any()
    bad = wm.copy()
    bad[0:8, 0:8, 1] = 255
    res = srw.recover(bad)
    assert res.tamper_map[:2, :2].all() and res.tamper_map.sum() == 4
    assert res.recovered.shape == img.shape
