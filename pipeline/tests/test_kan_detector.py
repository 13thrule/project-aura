"""Correctness tests for the KAN prototype (design doc section 4.4).

The important test here is `test_gradient_is_localized_to_input_bucket`
— it's specifically designed to catch the exact bug class an earlier
draft of this module had (spline_weight collapsed via .mean() before
ever touching the input, making every "spline" behave like a single
shared scalar). A genuine spline's gradient should only touch the grid
control points that bracket the actual input value; a collapsed-mean
implementation would spread gradient across every control point equally
regardless of input.
"""

import pytest

torch = pytest.importorskip("torch")  # optional 'kan' extra (design doc section 4.4) — not installed by default, see pyproject.toml

from aura_pipeline.kan_detector import AuraPreIctalKAN, KANLinearLayer  # noqa: E402


def test_output_shape():
    model = AuraPreIctalKAN(num_features=24)
    x = torch.randn(4, 24)
    out = model(x)
    assert out.shape == (4, 1)
    assert torch.all((out >= 0) & (out <= 1))  # sigmoid output


def test_gradient_is_localized_to_input_bucket():
    layer = KANLinearLayer(in_features=1, out_features=1, grid_size=4, grid_range=(-1.0, 1.0))

    # x=-0.6 with grid [-1, 1] split into 4 intervals of width 0.5:
    # buckets are [-1,-0.5], [-0.5,0], [0,0.5], [0.5,1] -> control points
    # at indices 0..4. -0.6 clamps to -1.0 -> t=0 -> idx0=0, so only
    # spline_weight[..., 0] and [..., 1] should receive gradient.
    x = torch.tensor([[-0.6]])
    out = layer(x)
    out.sum().backward()

    grad = layer.spline_weight.grad[0, 0]  # shape (grid_size + 1,) = (5,)
    touched = grad.abs() > 0
    assert touched[0] and touched[1], "the bracketing control points should get gradient"
    assert not touched[2:].any(), "control points far from the input should NOT get gradient"


def test_different_inputs_touch_different_buckets():
    """A second, independent check that the function is genuinely
    piecewise/input-dependent: two inputs in different grid intervals
    should produce gradient in different places."""
    layer = KANLinearLayer(in_features=1, out_features=1, grid_size=4, grid_range=(-1.0, 1.0))

    x_low = torch.tensor([[-0.9]])
    layer.zero_grad()
    layer(x_low).sum().backward()
    grad_low = layer.spline_weight.grad[0, 0].clone()

    x_high = torch.tensor([[0.9]])
    layer.zero_grad()
    layer(x_high).sum().backward()
    grad_high = layer.spline_weight.grad[0, 0].clone()

    touched_low = set((grad_low.abs() > 0).nonzero().flatten().tolist())
    touched_high = set((grad_high.abs() > 0).nonzero().flatten().tolist())
    assert touched_low != touched_high
