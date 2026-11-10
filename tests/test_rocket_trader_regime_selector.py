import unittest
from datetime import datetime
from rocket_trader_regime_selector import (
    MarketState, RegimeClassifier, RegimeLabel, NewsAssessment, NewsSeverity,
    NewsRiskOverlay, StrategyCandidate, RegimeAwarePortfolioSelector,
)

class RegimeSelectorTests(unittest.TestCase):
    def state(self, **kw):
        values = dict(trend_strength=.8, trend_direction=.7,
                      volatility_percentile=.2, breadth=.8, correlation=.3,
                      stress=.1, data_quality=.99, timestamp="2026-11-10T12:00:00Z")
        values.update(kw)
        return MarketState(**values)

    def candidate(self, **kw):
        values = dict(strategy_id="trend-1", family="TREND", score=.8,
                      expected_net_edge_bps=12, lower_confidence_bound_bps=2,
                      uncertainty=.1, data_quality=.99, oos_validated=True,
                      costs_empirically_validated=True, evidence_class="PRECEDENTED",
                      benchmark_support=.7)
        values.update(kw)
        return StrategyCandidate(**values)

    def test_low_data_quality_forces_cash(self):
        result = RegimeClassifier().assess(self.state(data_quality=.5))
        self.assertEqual(result.label, RegimeLabel.UNKNOWN)
        self.assertEqual(result.exposure_cap, 0)

    def test_stress_regime_caps_exposure(self):
        result = RegimeClassifier().assess(self.state(stress=.9, volatility_percentile=.9,
                                                      correlation=.9))
        self.assertEqual(result.label, RegimeLabel.STRESS)
        self.assertLessEqual(result.exposure_cap, .20)

    def test_no_valid_candidate_abstains(self):
        result = RegimeAwarePortfolioSelector().select(
            self.state(), [self.candidate(costs_empirically_validated=False)])
        self.assertTrue(result.abstain)
        self.assertEqual(result.cash_weight, 1)

    def test_candidate_allocation_and_cash_residual(self):
        result = RegimeAwarePortfolioSelector().select(self.state(), [self.candidate()])
        self.assertFalse(result.abstain)
        self.assertGreater(result.total_exposure, 0)
        self.assertAlmostEqual(result.cash_weight + result.total_exposure, 1.0)

    def test_critical_point_in_time_news_blocks(self):
        news = NewsAssessment("event-1", "2026-11-10T11:59:00Z",
                              NewsSeverity.CRITICAL, 1, 1, 1, ("SPY",),
                              True, "human-reviewed-v1", "systemic event")
        result = RegimeAwarePortfolioSelector().select(self.state(), [self.candidate()], [news],
            now=datetime.fromisoformat("2026-11-10T12:00:00+00:00"))
        self.assertTrue(result.abstain)
        self.assertEqual(result.cash_weight, 1)

    def test_news_assessment_is_filtered_by_active_universe_symbols(self):
        from datetime import datetime
        news = NewsAssessment("btc-event", "2026-11-10T11:59:00+00:00",
                              NewsSeverity.CRITICAL, 1, 1, 1, ("BTCUSD",),
                              True, "human-reviewed-v1", "crypto-specific event")
        now = datetime.fromisoformat("2026-11-10T12:00:00+00:00")
        equity = NewsRiskOverlay().evaluate([news], symbols=("SPY", "QQQ"), now=now)
        crypto = NewsRiskOverlay().evaluate([news], symbols=("BTCUSD",), now=now)
        self.assertFalse(equity.block_new_entries)
        self.assertEqual(equity.exposure_multiplier, 1)
        self.assertTrue(crypto.block_new_entries)
        self.assertEqual(crypto.exposure_multiplier, 0)

    def test_stale_critical_news_expires(self):
        from datetime import datetime
        news = NewsAssessment("old-critical", "2026-11-10T00:00:00+00:00",
                              NewsSeverity.CRITICAL, 1, 1, 1, ("SPY",),
                              True, "human-reviewed-v1", "stale")
        risk = NewsRiskOverlay().evaluate([news], "SPY",
            now=datetime.fromisoformat("2026-11-10T12:00:00+00:00"))
        self.assertFalse(risk.block_new_entries)
        self.assertEqual(risk.exposure_multiplier, 1)

    def test_low_confidence_critical_does_not_hard_block(self):
        from datetime import datetime
        news = NewsAssessment("weak-critical", "2026-11-10T11:59:00+00:00",
                              NewsSeverity.CRITICAL, .3, .5, .5, ("SPY",),
                              True, "human-reviewed-v1", "weak evidence")
        risk = NewsRiskOverlay().evaluate([news], "SPY",
            now=datetime.fromisoformat("2026-11-10T12:00:00+00:00"))
        self.assertFalse(risk.block_new_entries)
        self.assertLess(risk.exposure_multiplier, 1)

    def test_naive_news_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            NewsAssessment("bad-time", "2026-11-10T11:59:00",
                           NewsSeverity.HIGH, 1, 1, 1, (), True,
                           "human-reviewed-v1", "naive timestamp")

    def test_historical_backfill_cannot_change_risk(self):
        news = NewsAssessment("old", "2020-01-01T00:00:00Z",
                              NewsSeverity.CRITICAL, 1, 1, 1, ("SPY",),
                              False, "human-reviewed-v1", "backfill")
        risk = NewsRiskOverlay().evaluate([news], "SPY")
        self.assertFalse(risk.block_new_entries)
        self.assertEqual(risk.exposure_multiplier, 1)

    def test_novel_risk_is_capped_and_not_promoted(self):
        novel = self.candidate(strategy_id="novel-1", evidence_class="NOVEL",
                               uncertainty=.1, benchmark_support=0)
        result = RegimeAwarePortfolioSelector(novel_exploration_cap=.01).select(
            self.state(), [novel])
        self.assertLessEqual(result.total_exposure, .01)

if __name__ == "__main__":
    unittest.main()
