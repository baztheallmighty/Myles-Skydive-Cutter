"""The two V4 networks, exactly as trained: an R3D-18 window classifier and the T2 temporal head.

The temporal head's layer names and shapes must match scripts/run_temporal_improvement.py (``DirectTCN``), because the
shipped weights were saved from it.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

DILATIONS = (1, 2, 4, 8, 8, 4, 2, 1, 0, 0)


class Normalize(nn.Module):
    def __init__(self, mean: torch.Tensor, std: torch.Tensor):
        super().__init__()
        self.register_buffer('mean', mean)
        self.register_buffer('std', std)

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return (values - self.mean) / self.std


class ResidualBlock(nn.Module):
    def __init__(self, channels: int, dilation: int):
        super().__init__()
        kernel = 1 if dilation == 0 else 3
        self.conv = nn.Conv1d(channels, channels, kernel, padding=0 if dilation == 0 else dilation,
                              dilation=max(1, dilation))
        self.dropout = nn.Dropout(0.2)

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return values + self.dropout(F.relu(self.conv(values)))


class Stage(nn.Module):
    def __init__(self, input_dim: int, classes: int, dilations: tuple[int, ...]):
        super().__init__()
        self.input = nn.Conv1d(input_dim, 64, 1)
        self.blocks = nn.ModuleList([ResidualBlock(64, dilation) for dilation in dilations])
        self.output = nn.Conv1d(64, classes, 1)

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        hidden = self.input(values.t().unsqueeze(0))
        for block in self.blocks:
            hidden = block(hidden)
        return self.output(hidden).squeeze(0).t()


class TemporalHead(nn.Module):
    """T2 recipe: two dilated temporal-convolution stages over the per-window embeddings."""

    def __init__(self, dim: int, classes: int, mean: torch.Tensor, std: torch.Tensor):
        super().__init__()
        self.normalize = Normalize(mean, std)
        self.first = Stage(dim, classes, DILATIONS)
        self.refine = Stage(classes, classes, DILATIONS)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        first = self.first(self.normalize(features))
        return self.refine(F.softmax(first, dim=1))


def visual_model(class_count: int) -> tuple[nn.Module, nn.Module]:
    """R3D-18 split into the embedding trunk and its linear phase head."""
    from torchvision.models.video import r3d_18

    model = r3d_18(weights=None)
    model.fc = nn.Linear(model.fc.in_features, class_count)
    return model, model.fc
