"""Augmentations and background replacement against the lab -> greenhouse gap (docs/03 §3)."""

import random
from collections.abc import Sequence
from pathlib import Path

import albumentations as A
import cv2
import numpy as np
from albumentations.pytorch import ToTensorV2

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
LEVELS = ("eval", "light", "strong")


class LedTint(A.ImageOnlyTransform):
    """Pink / violet cast of horticultural LEDs: red and blue gains, green attenuated."""

    def __init__(
        self,
        r_gain: tuple[float, float] = (1.0, 1.4),
        g_gain: tuple[float, float] = (0.7, 1.0),
        b_gain: tuple[float, float] = (1.0, 1.5),
        p: float = 0.5,
    ):
        super().__init__(p=p)
        self.r_gain, self.g_gain, self.b_gain = r_gain, g_gain, b_gain

    def get_params(self) -> dict:
        return {"gains": [random.uniform(*g) for g in (self.r_gain, self.g_gain, self.b_gain)]}

    def apply(self, img: np.ndarray, gains: Sequence[float], **params) -> np.ndarray:
        out = img.astype(np.float32) * np.asarray(gains, dtype=np.float32)
        return np.clip(out, 0, 255).astype(np.uint8)

    def get_transform_init_args_names(self) -> tuple[str, ...]:
        return ("r_gain", "g_gain", "b_gain")


def _strong(size: int) -> list[A.BasicTransform]:
    return [
        A.RandomResizedCrop(size=(size, size), scale=(0.3, 1.0)),
        A.HorizontalFlip(),
        A.VerticalFlip(),
        A.Rotate(limit=30, border_mode=cv2.BORDER_REFLECT_101, p=0.5),
        A.Perspective(scale=(0.02, 0.08), p=0.3),
        A.ColorJitter(brightness=0.4, contrast=0.4, saturation=0.4, hue=0.05, p=0.8),
        LedTint(p=0.3),
        A.RandomGamma(gamma_limit=(70, 150), p=0.3),
        A.CLAHE(clip_limit=(1, 4), p=0.2),
        A.OneOf([A.MotionBlur(blur_limit=(3, 9)), A.GaussianBlur(blur_limit=(3, 7))], p=0.3),
        A.ISONoise(color_shift=(0.01, 0.05), intensity=(0.1, 0.5), p=0.3),
        A.ImageCompression(quality_range=(30, 90), p=0.5),
        A.RandomShadow(shadow_roi=(0, 0, 1, 1), num_shadows_limit=(1, 2), p=0.3),
        A.CoarseDropout(
            num_holes_range=(1, 4),
            hole_height_range=(0.1, 0.25),
            hole_width_range=(0.1, 0.25),
            p=0.3,
        ),
    ]


def build_transform(level: str, size: int) -> A.Compose:
    """eval: resize only; light: crop + flip (ablation A); strong: everything in §3.1."""
    if level == "eval":
        ops = [A.Resize(size, size)]
    elif level == "light":
        ops = [A.RandomResizedCrop(size=(size, size), scale=(0.6, 1.0)), A.HorizontalFlip()]
    elif level == "strong":
        ops = _strong(size)
    else:
        raise ValueError(f"niveau d'augmentation {level!r} hors de {LEVELS}")
    return A.Compose([*ops, A.Normalize(), ToTensorV2()])


def leaf_mask(segmented: np.ndarray, thresh: int = 20) -> np.ndarray:
    """uint8 {0, 1} mask of the leaf in a PlantVillage `segmented/` image (black background).

    Keeps the largest component and fills its holes (dark lesions must stay leaf).
    """
    fg = (segmented.max(axis=2) > thresh).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mask = np.zeros_like(fg)
    if contours:
        cv2.drawContours(mask, [max(contours, key=cv2.contourArea)], -1, 1, cv2.FILLED)
    return mask


def _alpha(mask: np.ndarray, feather: int) -> np.ndarray:
    a = mask.astype(np.float32)
    if feather > 1:
        k = feather | 1
        a = cv2.GaussianBlur(a, (k, k), 0)
    return a[..., None]


def harmonize_luminance(
    leaf: np.ndarray, mask: np.ndarray, bg: np.ndarray, strength: float
) -> np.ndarray:
    """Moves the leaf's L (LAB) mean/std towards the background's.

    Chroma is left untouched: yellowing and lesion colours are the symptoms to learn.
    """
    if strength <= 0 or mask.sum() < 16:
        return leaf
    lab = cv2.cvtColor(leaf, cv2.COLOR_RGB2LAB).astype(np.float32)
    bg_l = cv2.cvtColor(bg, cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32)
    inside = mask.astype(bool)
    mu_l, sd_l = lab[..., 0][inside].mean(), lab[..., 0][inside].std() + 1e-6
    mu_t = mu_l + strength * (bg_l.mean() - mu_l)
    sd_t = sd_l + strength * (bg_l.std() - sd_l)
    lab[..., 0] = (lab[..., 0] - mu_l) / sd_l * sd_t + mu_t
    lab = np.clip(lab, 0, 255).astype(np.uint8)
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)


def composite(fg: np.ndarray, mask: np.ndarray, bg: np.ndarray, feather: int) -> np.ndarray:
    a = _alpha(mask, feather)
    return (fg.astype(np.float32) * a + bg.astype(np.float32) * (1 - a)).astype(np.uint8)


def _read_rgb(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise OSError(f"image illisible : {path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


class BackgroundPaster:
    """Pastes the masked leaf on a random greenhouse background (docs/03 §3.2).

    Called as paster(color_img, segmented_img) before the albumentations pipeline. With
    probability p_multi, 1-3 extra leaves from extra_leaf_pool (segmented images) are pasted
    first, smaller and around the centre; the labelled leaf stays in front.
    """

    def __init__(
        self,
        bg_dir: Path,
        extra_leaf_pool: Sequence[Path] = (),
        p: float = 0.5,
        p_multi: float = 0.3,
        extra_leaves: tuple[int, int] = (1, 3),
        feather: int = 7,
        harmonize: float = 0.5,
    ):
        bg_dir = Path(bg_dir)
        self.backgrounds = (
            sorted(f for f in bg_dir.rglob("*") if f.suffix.lower() in IMAGE_EXTS)
            if bg_dir.is_dir()
            else []
        )
        if not self.backgrounds:
            raise FileNotFoundError(
                f"aucun fond dans {bg_dir} : remplir data/backgrounds/ (docs/03 §3.2) "
                "ou désactiver augment.background.enabled"
            )
        self.pool = list(extra_leaf_pool)
        self.p, self.p_multi = p, p_multi
        self.extra_leaves = extra_leaves
        self.feather, self.harmonize = feather, harmonize

    def random_background(self, h: int, w: int) -> np.ndarray:
        bg = _read_rgb(random.choice(self.backgrounds))
        bh, bw = bg.shape[:2]
        scale = random.uniform(0.4, 1.0)
        ch, cw = max(1, int(bh * scale)), max(1, int(bw * scale))
        y, x = random.randint(0, bh - ch), random.randint(0, bw - cw)
        return cv2.resize(bg[y : y + ch, x : x + cw], (w, h), interpolation=cv2.INTER_AREA)

    def _paste_extra(self, canvas: np.ndarray) -> np.ndarray:
        h, w = canvas.shape[:2]
        for _ in range(random.randint(*self.extra_leaves)):
            seg = _read_rgb(random.choice(self.pool))
            scale = random.uniform(0.4, 0.8)
            sh, sw = max(8, int(h * scale)), max(8, int(w * scale))
            seg = cv2.resize(seg, (sw, sh), interpolation=cv2.INTER_AREA)
            if random.random() < 0.5:
                seg = seg[:, ::-1].copy()
            m = leaf_mask(seg)
            # Anchor anywhere, the leaf may overflow the frame (cropped by the slicing).
            y, x = random.randint(-sh // 2, h - sh // 2), random.randint(-sw // 2, w - sw // 2)
            y0, x0, y1, x1 = max(y, 0), max(x, 0), min(y + sh, h), min(x + sw, w)
            if y1 <= y0 or x1 <= x0:
                continue
            sy, sx = y0 - y, x0 - x
            crop = (slice(sy, sy + y1 - y0), slice(sx, sx + x1 - x0))
            canvas[y0:y1, x0:x1] = composite(seg[crop], m[crop], canvas[y0:y1, x0:x1], self.feather)
        return canvas

    def __call__(self, img: np.ndarray, segmented: np.ndarray) -> np.ndarray:
        if random.random() >= self.p:
            return img
        h, w = img.shape[:2]
        if segmented.shape[:2] != (h, w):
            segmented = cv2.resize(segmented, (w, h), interpolation=cv2.INTER_NEAREST)
        mask = leaf_mask(segmented)
        if mask.sum() < 0.02 * h * w:  # failed segmentation: keep the original
            return img
        bg = self.random_background(h, w)
        if self.pool and random.random() < self.p_multi:
            bg = self._paste_extra(bg)
        leaf = harmonize_luminance(img, mask, bg, self.harmonize)
        return composite(leaf, mask, bg, self.feather)
