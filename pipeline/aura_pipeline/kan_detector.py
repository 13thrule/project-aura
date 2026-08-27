"""Phase 4 exploratory: a Kolmogorov-Arnold Network (KAN) for pre-ictal
detection (design doc section 4.4). NOT the Phase 2 baseline — CLAUDE.md
still specifies scikit-learn threshold classifiers as the thing every
detector is compared against; this is an addition, not a replacement.

Why a real spline implementation matters here specifically: an earlier
draft of this module computed `spline_weight.mean(dim=-1)` before ever
touching the input value. That collapses a KAN's entire defining property
— an edge function whose *shape* depends on where the input falls on a
grid — into an ordinary elementwise-gated linear layer wearing a KAN's
variable names. It trains, it runs, the shapes all line up, and it
delivers none of the accuracy or interpretability properties the KAN
literature (Section 10) actually reports. `tests/test_kan_detector.py`
has a test specifically designed to catch that exact bug class again if
it ever creeps back in: it checks that a gradient with respect to
`spline_weight` is *localized* to the grid bucket(s) the input actually
falls into, not spread uniformly across the whole grid.

This implements a piecewise-linear (degree-1) spline basis rather than
the cubic B-splines used in most published KAN implementations — simpler
to get right, still a genuine, input-dependent, differentiable-almost-
everywhere basis function per edge, at the cost of a slightly less smooth
learned function than cubic splines would give. Treat this as a
correctness baseline to validate against, not a substitute for using a
maintained reference implementation (e.g. `efficient-kan`) if this moves
past prototyping.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn


class KANLinearLayer(nn.Module):
    """A KAN edge layer: one learnable piecewise-linear spline function
    per (output, input) pair, plus a base linear residual term (as in
    published KAN implementations, to keep early training stable before
    the splines have learned anything useful).
    """

    def __init__(
        self,
        in_features: int,
        out_features: int,
        grid_size: int = 8,
        grid_range: tuple[float, float] = (-2.0, 2.0),
    ):
        super().__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.grid_size = grid_size
        self.grid_min, self.grid_max = grid_range

        self.base_weight = nn.Parameter(torch.empty(out_features, in_features))
        # grid_size + 1 control points per edge, so there are grid_size
        # piecewise-linear intervals between them.
        self.spline_weight = nn.Parameter(torch.empty(out_features, in_features, grid_size + 1))

        nn.init.kaiming_uniform_(self.base_weight, a=5**0.5)
        nn.init.normal_(self.spline_weight, mean=0.0, std=0.1)

    def _bucket(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """x: (batch, in_features). Returns (idx0, frac) where idx0 is the
        lower grid index each value falls into and frac in [0,1] is its
        fractional position within that interval — the actual
        input-dependent part of a spline evaluation."""
        x_clamped = x.clamp(self.grid_min, self.grid_max)
        t = (x_clamped - self.grid_min) / (self.grid_max - self.grid_min) * self.grid_size
        idx0 = t.floor().clamp(0, self.grid_size - 1).long()
        frac = (t - idx0).clamp(0.0, 1.0)
        return idx0, frac, x_clamped

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, in_features) -> (batch, out_features)
        batch = x.shape[0]
        idx0, frac, _ = self._bucket(x)  # each: (batch, in_features)

        # Gather the two control points bracketing each input value, per
        # (batch, out_features, in_features) edge.
        idx0_exp = idx0.unsqueeze(1).expand(batch, self.out_features, self.in_features).unsqueeze(-1)
        idx1_exp = (idx0_exp + 1).clamp(max=self.grid_size)
        spline_exp = self.spline_weight.unsqueeze(0).expand(batch, -1, -1, -1)

        w0 = torch.gather(spline_exp, dim=-1, index=idx0_exp).squeeze(-1)
        w1 = torch.gather(spline_exp, dim=-1, index=idx1_exp).squeeze(-1)

        frac_exp = frac.unsqueeze(1)  # (batch, 1, in_features), broadcasts over out_features
        edge_output = w0 * (1.0 - frac_exp) + w1 * frac_exp  # (batch, out_features, in_features)
        spline_output = edge_output.sum(dim=-1)  # (batch, out_features)

        base_output = F.linear(x, self.base_weight)
        return base_output + spline_output


class AuraPreIctalKAN(nn.Module):
    """KAN model over windowed EEG feature vectors (design doc section
    4.3): 8 channels x {line_length, hjorth_mobility, hjorth_complexity}
    = 24 features in, one pre-ictal probability out.
    """

    def __init__(self, num_features: int = 24, hidden_dim: int = 32, grid_size: int = 8):
        super().__init__()
        self.layer1 = KANLinearLayer(num_features, hidden_dim, grid_size=grid_size)
        self.norm = nn.LayerNorm(hidden_dim)
        self.layer2 = KANLinearLayer(hidden_dim, 1, grid_size=grid_size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.norm(self.layer1(x))
        return torch.sigmoid(self.layer2(x))
