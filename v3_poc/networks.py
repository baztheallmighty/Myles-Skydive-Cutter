"""Exact inference architectures used by the selected campaign checkpoints."""
import torch
from torch import nn
from torch.nn import functional as F


class Normalise(nn.Module):
    def __init__(self, mean, std):
        super().__init__()
        self.register_buffer('mean', mean)
        self.register_buffer('std', std)

    def forward(self, x):
        return (x - self.mean) / self.std


class ContextHead(nn.Module):
    def __init__(self, state):
        super().__init__()
        self.normalise = Normalise(torch.zeros_like(state['normalise.mean']), torch.ones_like(state['normalise.std']))
        classes, dim, width = state['conv.weight'].shape
        self.radius = width // 2
        self.conv = nn.Conv1d(dim, classes, width)
        self.load_state_dict(state)

    def forward(self, x):
        x = self.normalise(x).t().unsqueeze(0)
        return self.conv(F.pad(x, (self.radius, self.radius), mode='replicate')).squeeze(0).t()


class AudioHead(nn.Module):
    def __init__(self, state):
        super().__init__()
        self.norm = Normalise(torch.zeros_like(state['norm.mean']), torch.ones_like(state['norm.std']))
        hidden, dim = state['project.0.weight'].shape
        self.project = nn.Sequential(nn.Linear(dim, hidden), nn.ReLU())
        self.rnn = nn.GRU(hidden, hidden, num_layers=1, batch_first=True, bidirectional=True)
        self.drop = nn.Dropout(.1)
        self.out = nn.Linear(hidden * 2, state['out.weight'].shape[0])
        self.load_state_dict(state)

    def forward(self, x):
        x, _ = self.rnn(self.project(self.norm(x)).unsqueeze(0))
        return self.out(self.drop(x.squeeze(0)))
