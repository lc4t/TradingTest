"""api.py 的策略 spec 校验测试（不触发实际回测）。"""
import pytest

from trading.api import MomentumBasket, MomentumTopN


class TestMomentumBasketSpec:
    def test_basic_build(self):
        s = MomentumBasket(weights={"A": 0.5, "B": 0.3})
        state = s._build_state()
        assert state.target_weights == {"A": 0.5, "B": 0.3}
        assert state.lookback == 63
        assert state.threshold == pytest.approx(-0.99)

    def test_weights_sum_over_one_rejected(self):
        s = MomentumBasket(weights={"A": 0.6, "B": 0.5})
        with pytest.raises(ValueError, match="超过 1.0"):
            s._build_state()

    def test_negative_weight_rejected(self):
        s = MomentumBasket(weights={"A": -0.1, "B": 0.5})
        with pytest.raises(ValueError, match="不能为负"):
            s._build_state()

    def test_empty_rejected(self):
        s = MomentumBasket(weights={})
        with pytest.raises(ValueError, match="不能为空"):
            s._build_state()

    def test_cash_buffer_via_partial_weights(self):
        # 0.4 + 0.3 = 0.7 → 30% 现金底仓
        s = MomentumBasket(weights={"A": 0.4, "B": 0.3})
        state = s._build_state()
        assert sum(state.target_weights.values()) == pytest.approx(0.7)


class TestMomentumTopNSpec:
    def test_basic_build(self):
        s = MomentumTopN(universe=["A", "B", "C"], top_n=2, cash_buffer=0.1)
        state = s._build_state()
        assert state.top_n == 2
        assert state.cash_buffer == pytest.approx(0.1)

    def test_top_n_too_large_rejected(self):
        s = MomentumTopN(universe=["A", "B"], top_n=5)
        with pytest.raises(ValueError, match="top_n"):
            s._build_state()

    def test_empty_universe_rejected(self):
        s = MomentumTopN(universe=[])
        with pytest.raises(ValueError, match="不能为空"):
            s._build_state()

    def test_cash_buffer_range(self):
        s = MomentumTopN(universe=["A"], cash_buffer=1.0)
        with pytest.raises(ValueError, match="cash_buffer"):
            s._build_state()
