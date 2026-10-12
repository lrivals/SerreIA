"""Multi-head classifier: timm backbone + espece / sante / classe heads (docs/03 §1)."""

import timm
import torch
from torch import nn

HEADS = ("espece", "sante", "classe")  # output order, also the ONNX / HEF output order


class MultiHeadClassifier(nn.Module):
    def __init__(
        self,
        backbone: str,
        n_espece: int,
        n_sante: int,
        n_classe: int,
        pretrained: bool = True,
        drop: float = 0.2,
    ):
        super().__init__()
        self.backbone = timm.create_model(backbone, pretrained=pretrained, num_classes=0)
        dim = self.backbone.num_features
        self.heads = nn.ModuleDict(
            {
                name: nn.Sequential(nn.Dropout(drop), nn.Linear(dim, n))
                for name, n in zip(HEADS, (n_espece, n_sante, n_classe), strict=True)
            }
        )

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        f = self.backbone(x)
        return tuple(self.heads[name](f) for name in HEADS)

    @staticmethod
    def as_dict(outputs: tuple[torch.Tensor, ...]) -> dict[str, torch.Tensor]:
        return dict(zip(HEADS, outputs, strict=True))

    def set_backbone_trainable(self, trainable: bool) -> None:
        for p in self.backbone.parameters():
            p.requires_grad = trainable

    def param_groups(self, lr_head: float, lr_backbone: float, weight_decay: float) -> list[dict]:
        def split(params):
            decay, no_decay = [], []
            for name, p in params:
                (no_decay if p.ndim <= 1 or name.endswith(".bias") else decay).append(p)
            return decay, no_decay

        groups = []
        for module, lr in ((self.backbone, lr_backbone), (self.heads, lr_head)):
            decay, no_decay = split(module.named_parameters())
            groups.append({"params": decay, "lr": lr, "weight_decay": weight_decay})
            groups.append({"params": no_decay, "lr": lr, "weight_decay": 0.0})
        return groups

    @torch.no_grad()
    def last_conv(self, size: int = 224) -> nn.Module:
        """Last Conv2d of the backbone with a spatial output, the Grad-CAM target layer.

        Some backbones (mobilenetv3) have a conv_head after global pooling (1x1 output),
        useless for Grad-CAM: those are skipped.
        """
        spatial: list[nn.Module] = []
        hooks = [
            m.register_forward_hook(
                lambda mod, _, out: spatial.append(mod) if min(out.shape[-2:]) > 1 else None
            )
            for m in self.backbone.modules()
            if isinstance(m, nn.Conv2d)
        ]
        was_training = self.training
        try:
            self.eval()
            self.backbone(torch.zeros(1, 3, size, size, device=next(self.parameters()).device))
        finally:
            for h in hooks:
                h.remove()
            self.train(was_training)
        if not spatial:
            raise ValueError("aucune couche Conv2d spatiale dans le backbone")
        return spatial[-1]


def build_model(cfg: dict, sizes: dict[str, int], pretrained: bool | None = None) -> nn.Module:
    m = cfg["model"]
    return MultiHeadClassifier(
        m["backbone"],
        sizes["espece"],
        sizes["sante"],
        sizes["classe"],
        pretrained=m.get("pretrained", True) if pretrained is None else pretrained,
        drop=m.get("drop", 0.2),
    )
