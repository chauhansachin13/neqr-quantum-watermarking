"""
Local content manipulations for the tamper-localisation experiments.

The nine attacks of :mod:`qwm.attacks` are *global* signal-processing
operations used by the robustness study and the attack classifier.  Fragile
watermarks are judged differently: can they tell *where* an image was edited,
and can an informed attacker edit it without being caught?  Every function
here returns ``(manipulated_image, changed_mask)`` where ``changed_mask`` marks
the pixels whose value actually changed (the ground truth).

* ``text_overlay``          - a caption burnt into a region
* ``blackout``              - a rectangle erased to black (object removal / cropping)
* ``copy_move``             - a region duplicated elsewhere in the same image
* ``splice``                - a region pasted from another image
* ``lsb_preserving_splice`` - a splice that keeps the receiver's two LSBs: the
  content changes but every embedded bit survives, an attack the base scheme
  cannot see
* ``local_blur``            - a region smoothed (retouching)
* ``reembed_forgery``       - an attacker who knows the base algorithm splices a
  region and re-embeds the *public* content-code watermark of the edited image
"""

from __future__ import annotations

import cv2
import numpy as np

MANIPULATIONS = (
    "text_overlay",
    "blackout",
    "copy_move",
    "splice",
    "lsb_preserving_splice",
    "local_blur",
    "reembed_forgery",
)

PRETTY = {
    "text_overlay": "Text overlay",
    "blackout": "Blackout (object removal)",
    "copy_move": "Copy-move",
    "splice": "Splice from another image",
    "lsb_preserving_splice": "LSB-preserving splice",
    "local_blur": "Local blur (retouch)",
    "reembed_forgery": "Splice + re-embedded base watermark",
}


def _u8(image) -> np.ndarray:
    img = np.asarray(image)
    if img.dtype != np.uint8 or img.ndim != 2:
        raise ValueError("expected a 2-D uint8 image")
    return img


def random_region(shape, fraction: float, rng: np.random.Generator) -> tuple[int, int, int, int]:
    """Random square ``(r0, r1, c0, c1)`` whose side is ``fraction`` of the image side."""
    h, w = shape[:2]
    side_h, side_w = max(2, int(round(h * fraction))), max(2, int(round(w * fraction)))
    r0 = int(rng.integers(0, h - side_h + 1))
    c0 = int(rng.integers(0, w - side_w + 1))
    return r0, r0 + side_h, c0, c0 + side_w


def _changed(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.asarray(a) != np.asarray(b)


def text_overlay(image, rng: np.random.Generator, fraction: float = 0.2, text: str | None = None):
    img = _u8(image).copy()
    h, w = img.shape
    text = text or str(rng.choice(["FAKE", "EDITED", "VOID", "COPY"]))
    scale = max(0.5, w / 256.0) * float(rng.uniform(0.9, 1.4))
    thick = max(1, int(round(w / 128.0)))
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
    x = int(rng.integers(0, max(1, w - tw)))
    y = int(rng.integers(th + 1, max(th + 2, h - 2)))
    color = int(rng.choice([0, 255]))
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)
    return img, _changed(image, img)


def blackout(image, rng: np.random.Generator, fraction: float = 0.2):
    img = _u8(image).copy()
    r0, r1, c0, c1 = random_region(img.shape, fraction, rng)
    img[r0:r1, c0:c1] = 0
    return img, _changed(image, img)


def copy_move(image, rng: np.random.Generator, fraction: float = 0.2):
    img = _u8(image).copy()
    r0, r1, c0, c1 = random_region(img.shape, fraction, rng)
    for _ in range(20):  # destination that does not coincide with the source
        d0, d1, e0, e1 = random_region(img.shape, fraction, rng)
        if (d0, e0) != (r0, c0):
            break
    img[d0:d1, e0:e1] = _u8(image)[r0:r1, c0:c1]
    return img, _changed(image, img)


def splice(image, rng: np.random.Generator, donor: np.ndarray, fraction: float = 0.2):
    img = _u8(image).copy()
    donor = _u8(donor)
    if donor.shape != img.shape:
        donor = cv2.resize(donor, img.shape[::-1], interpolation=cv2.INTER_AREA)
    r0, r1, c0, c1 = random_region(img.shape, fraction, rng)
    img[r0:r1, c0:c1] = donor[r0:r1, c0:c1]
    return img, _changed(image, img)


def lsb_preserving_splice(image, rng: np.random.Generator, donor: np.ndarray, fraction: float = 0.2):
    """Splice the six MSBs of ``donor`` but keep the two LSBs of ``image``."""
    img = _u8(image).copy()
    donor = _u8(donor)
    if donor.shape != img.shape:
        donor = cv2.resize(donor, img.shape[::-1], interpolation=cv2.INTER_AREA)
    r0, r1, c0, c1 = random_region(img.shape, fraction, rng)
    img[r0:r1, c0:c1] = (donor[r0:r1, c0:c1] & 0xFC) | (img[r0:r1, c0:c1] & 0x03)
    return img, _changed(image, img)


def local_blur(image, rng: np.random.Generator, fraction: float = 0.2):
    img = _u8(image).copy()
    r0, r1, c0, c1 = random_region(img.shape, fraction, rng)
    img[r0:r1, c0:c1] = cv2.GaussianBlur(img, (9, 9), 3.0)[r0:r1, c0:c1]
    return img, _changed(image, img)


def reembed_forgery(image, rng: np.random.Generator, donor: np.ndarray, fraction: float = 0.2):
    """Splice, then re-embed the base scheme's content-code watermark of the edited image."""
    from qwm.watermark.embedding import embed_image

    edited, _ = splice(image, rng, donor, fraction)
    forged, _ = embed_image(edited, mode="lsb")
    return forged, _changed(image, forged)


def apply_manipulation(name: str, image, rng: np.random.Generator, donor=None, fraction: float = 0.2):
    if name == "text_overlay":
        return text_overlay(image, rng, fraction)
    if name == "blackout":
        return blackout(image, rng, fraction)
    if name == "copy_move":
        return copy_move(image, rng, fraction)
    if name == "local_blur":
        return local_blur(image, rng, fraction)
    if name in ("splice", "lsb_preserving_splice", "reembed_forgery"):
        if donor is None:
            raise ValueError(f"{name} needs a donor image")
        return {"splice": splice, "lsb_preserving_splice": lsb_preserving_splice, "reembed_forgery": reembed_forgery}[name](image, rng, donor, fraction)
    raise KeyError(f"unknown manipulation {name!r}; choose from {MANIPULATIONS}")


def block_truth(changed_mask: np.ndarray, block: int) -> np.ndarray:
    """Block-level ground truth: a block is tampered if any of its pixels changed."""
    m = np.asarray(changed_mask, dtype=bool)
    h, w = (m.shape[0] // block) * block, (m.shape[1] // block) * block
    return m[:h, :w].reshape(h // block, block, w // block, block).any(axis=(1, 3))


def detection_scores(pred: np.ndarray, truth: np.ndarray) -> dict[str, float]:
    """Block-level recall (TPR), false-positive rate, precision, F1 and IoU."""
    pred, truth = np.asarray(pred, dtype=bool), np.asarray(truth, dtype=bool)
    tp = int((pred & truth).sum())
    fp = int((pred & ~truth).sum())
    fn = int((~pred & truth).sum())
    tn = int((~pred & ~truth).sum())
    tpr = tp / (tp + fn) if tp + fn else 1.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    prec = tp / (tp + fp) if tp + fp else (1.0 if fn == 0 else 0.0)
    f1 = 2 * prec * tpr / (prec + tpr) if prec + tpr else 0.0
    iou = tp / (tp + fp + fn) if tp + fp + fn else 1.0
    return {"tpr": tpr, "fpr": fpr, "precision": prec, "f1": f1, "iou": iou, "tampered_blocks": int(truth.sum())}
