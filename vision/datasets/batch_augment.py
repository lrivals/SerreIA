"""Batch stage of the augmentations, run on the training device (docs/03 §3.1).

The DataLoader workers only decode, crop and apply the per-image geometric ops (uint8
tensors, see augment.build_transform); the per-pixel photometric ops and the normalization
run here on whole batches, on the GPU when there is one. Every sample draws its own
parameters, as albumentations would. Works on CPU too (tests, notebook 01).
"""

import math

import torch
import torch.nn.functional as F
from torch import nn
from torchvision.io import decode_jpeg, encode_jpeg

MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)
KMAX = 9  # largest blur kernel (motion blur up to 9 px)


def _u(n: int, lo: float, hi: float, ref: torch.Tensor) -> torch.Tensor:
    """(n, 1, 1, 1) uniform draws on ref's device."""
    return torch.empty(n, 1, 1, 1, device=ref.device).uniform_(lo, hi)


def _gate(x: torch.Tensor, p: float) -> torch.Tensor:
    return (torch.rand(len(x), 1, 1, 1, device=x.device) < p).to(x.dtype)


def _gray(x: torch.Tensor) -> torch.Tensor:
    return (0.299 * x[:, 0:1] + 0.587 * x[:, 1:2] + 0.114 * x[:, 2:3]).clamp(0, 1)


def color_jitter(x: torch.Tensor, strength: float = 0.4, hue: float = 0.05) -> torch.Tensor:
    """Brightness, contrast, saturation, then hue (rotation in YIQ, ±hue turn)."""
    n = len(x)
    x = (x * _u(n, 1 - strength, 1 + strength, x)).clamp(0, 1)
    mean = _gray(x).mean((2, 3), keepdim=True)
    x = ((x - mean) * _u(n, 1 - strength, 1 + strength, x) + mean).clamp(0, 1)
    g = _gray(x)
    x = ((x - g) * _u(n, 1 - strength, 1 + strength, x) + g).clamp(0, 1)
    theta = _u(n, -hue, hue, x)[:, 0] * 2 * math.pi  # (n, 1, 1)
    r, gr, b = x[:, 0], x[:, 1], x[:, 2]
    y = 0.299 * r + 0.587 * gr + 0.114 * b
    i = 0.596 * r - 0.274 * gr - 0.322 * b
    q = 0.211 * r - 0.523 * gr + 0.312 * b
    cos, sin = torch.cos(theta), torch.sin(theta)
    i, q = i * cos - q * sin, i * sin + q * cos
    rgb = (y + 0.956 * i + 0.621 * q, y - 0.272 * i - 0.647 * q, y - 1.106 * i + 1.703 * q)
    return torch.stack(rgb, 1).clamp(0, 1)


def led_tint(x: torch.Tensor) -> torch.Tensor:
    """Pink / violet cast of horticultural LEDs: red and blue gains, green attenuated."""
    n = len(x)
    gains = torch.cat([_u(n, 1.0, 1.4, x), _u(n, 0.7, 1.0, x), _u(n, 1.0, 1.5, x)], 1)
    return (x * gains).clamp(0, 1)


def random_gamma(x: torch.Tensor) -> torch.Tensor:
    return x.clamp_min(1e-6) ** _u(len(x), 0.7, 1.5, x)


def _odd(n: int, lo: int, hi: int, device: torch.device) -> torch.Tensor:
    """(n, 1, 1) random odd sizes in [lo, hi]."""
    return (torch.randint(lo // 2, hi // 2 + 1, (n, 1, 1), device=device) * 2 + 1).float()


def blur_kernels(n: int, device: torch.device) -> torch.Tensor:
    """(n, KMAX, KMAX) kernels: half motion blur (3-9 px, any angle), half gaussian (3-7)."""
    c = torch.arange(KMAX, device=device, dtype=torch.float32) - KMAX // 2
    yy, xx = torch.meshgrid(c, c, indexing="ij")
    # motion: segment of the given length through the centre
    length = _odd(n, 3, 9, device)
    angle = torch.rand(n, 1, 1, device=device) * math.pi
    along = xx * torch.cos(angle) + yy * torch.sin(angle)
    across = -xx * torch.sin(angle) + yy * torch.cos(angle)
    motion = ((across.abs() <= 0.5) & (along.abs() <= (length - 1) / 2)).float()
    # gaussian: OpenCV's sigma for a given kernel size
    k = _odd(n, 3, 7, device)
    sigma = 0.3 * ((k - 1) * 0.5 - 1) + 0.8
    inside = (xx.abs() <= (k - 1) / 2) & (yy.abs() <= (k - 1) / 2)
    gauss = torch.exp(-(xx**2 + yy**2) / (2 * sigma**2)) * inside
    kern = torch.where(torch.rand(n, 1, 1, device=device) < 0.5, motion, gauss)
    return kern / kern.sum((1, 2), keepdim=True)


def blur(x: torch.Tensor) -> torch.Tensor:
    n, ch, h, w = x.shape
    weight = blur_kernels(n, x.device).repeat_interleave(ch, 0)[:, None]
    pad = F.pad(x.reshape(1, n * ch, h, w), (KMAX // 2,) * 4, mode="reflect")
    return F.conv2d(pad, weight, groups=n * ch).reshape(n, ch, h, w)


def iso_noise(x: torch.Tensor) -> torch.Tensor:
    """Sensor noise (approximation of albumentations' ISONoise): grey luminance noise
    scaled by the image contrast, plus a weaker per-channel colour noise."""
    n, _, h, w = x.shape
    intensity = _u(n, 0.1, 0.5, x)
    shift = _u(n, 0.01, 0.05, x)
    contrast = _gray(x).std((2, 3), keepdim=True)
    lum = torch.randn(n, 1, h, w, device=x.device) * intensity * contrast
    col = torch.randn_like(x) * shift
    return (x + lum + col).clamp(0, 1)


def jpeg(x: torch.Tensor, gate: torch.Tensor, quality: tuple[int, int] = (30, 90)) -> torch.Tensor:
    """JPEG round trip of the gated samples, nvjpeg on CUDA, libjpeg on CPU."""
    idx = gate.flatten().nonzero().flatten().tolist()
    if not idx:
        return x
    q = torch.randint(quality[0], quality[1] + 1, (len(idx),)).tolist()
    u8 = (x * 255).round().to(torch.uint8)
    out = x.clone()
    for qual in set(q):  # encode_jpeg takes one quality per call
        sel = [i for i, qi in zip(idx, q, strict=True) if qi == qual]
        data = encode_jpeg([u8[i] for i in sel], quality=qual)
        dec = decode_jpeg([d.cpu() for d in data], device=x.device)
        out[sel] = torch.stack(dec).to(x.dtype) / 255
    return out


def coarse_dropout(x: torch.Tensor, holes: tuple[int, int] = (1, 4)) -> torch.Tensor:
    """1-4 black rectangles of 10-25 % of the side (occlusion by other leaves)."""
    n, _, h, w = x.shape
    k = holes[1]
    dev = x.device
    active = torch.arange(k, device=dev) < torch.randint(holes[0], k + 1, (n, 1), device=dev)
    hh = (torch.empty(n, k, device=dev).uniform_(0.1, 0.25) * h).long()
    hw = (torch.empty(n, k, device=dev).uniform_(0.1, 0.25) * w).long()
    y0 = (torch.rand(n, k, device=dev) * (h - hh + 1)).long()
    x0 = (torch.rand(n, k, device=dev) * (w - hw + 1)).long()
    ys = torch.arange(h, device=dev)[None, None, :, None]
    xs = torch.arange(w, device=dev)[None, None, None, :]
    inside = (
        (ys >= y0[..., None, None])
        & (ys < (y0 + hh)[..., None, None])
        & (xs >= x0[..., None, None])
        & (xs < (x0 + hw)[..., None, None])
        & active[..., None, None]
    ).any(1, keepdim=True)
    return x.masked_fill(inside, 0.0)


class BatchAugment(nn.Module):
    """uint8 (n, 3, H, W) batch -> normalized float32, on the batch's device.

    level "strong": the per-pixel ops of docs/03 §3.1, in this order: ColorJitter (p 0.8),
    LED tint (0.3), gamma (0.3), motion or gaussian blur (0.3), ISO noise (0.3), JPEG 30-90
    (0.5), CoarseDropout (0.3). "light" and "eval": normalization only.
    """

    def __init__(self, level: str = "eval"):
        super().__init__()
        self.strong = level == "strong"
        self.register_buffer("mean", torch.tensor(MEAN).view(1, 3, 1, 1), persistent=False)
        self.register_buffer("std", torch.tensor(STD).view(1, 3, 1, 1), persistent=False)

    def _strong(self, x: torch.Tensor) -> torch.Tensor:
        for op, p in ((color_jitter, 0.8), (led_tint, 0.3), (random_gamma, 0.3), (blur, 0.3),
                      (iso_noise, 0.3)):  # fmt: skip
            g = _gate(x, p)
            x = torch.lerp(x, op(x), g)
        x = jpeg(x, _gate(x, 0.5))
        g = _gate(x, 0.3)
        return torch.lerp(x, coarse_dropout(x), g)

    @torch.no_grad()
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.float() / 255
        if self.strong:
            x = self._strong(x)
        return (x - self.mean.to(x.device)) / self.std.to(x.device)
