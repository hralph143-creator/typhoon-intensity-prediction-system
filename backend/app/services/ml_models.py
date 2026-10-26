from __future__ import annotations

import torch
from torch import nn


class RecurrentRegressor(nn.Module):
    def __init__(self, kind="lstm", input_size=1, hidden_size=16, num_layers=1, dropout=0.0):
        super().__init__()
        layer = nn.LSTM if kind == "lstm" else nn.GRU
        self.kind = kind
        self.recurrent = layer(input_size, hidden_size, num_layers=num_layers, batch_first=True, dropout=dropout if num_layers > 1 else 0)
        self.head = nn.Sequential(nn.Linear(hidden_size, 8), nn.ReLU(), nn.Linear(8, 1))

    def forward(self, values):
        output, _ = self.recurrent(values)
        return self.head(output[:, -1, :]).squeeze(-1)
