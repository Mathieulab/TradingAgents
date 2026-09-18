"""Vendor router must respect the configured chain and never silently hide a
broken primary.

Regressions for #988 (explicit single-vendor config still fell back to others),
#289 (fallback ran for unchosen vendors), and #989 (serious primary failures
were swallowed without a trace).
"""
import copy
import sys
import types
import unittest
from unittest import mock

import pytest

try:
    import yfinance  # noqa: F401
except ModuleNotFoundError:
    yfinance_module = types.ModuleType("yfinance")
    yfinance_exceptions = types.ModuleType("yfinance.exceptions")
    yfinance_exceptions.YFRateLimitError = type("YFRateLimitError", (Exception,), {})
    sys.modules["yfinance"] = yfinance_module
    sys.modules["yfinance.exceptions"] = yfinance_exceptions

try:
    import stockstats  # noqa: F401
except ModuleNotFoundError:
    stockstats_module = types.ModuleType("stockstats")
    stockstats_module.wrap = lambda frame: frame
    sys.modules["stockstats"] = stockstats_module

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import interface
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.symbol_utils import NoMarketDataError


def _reset_config():
    # Hard reset: set_config() merges, so empty DEFAULT dicts (e.g. tool_vendors)
    # don't clear keys leaked by other tests. Replace the global outright.
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def _no_data(symbol, *a, **k):
    raise NoMarketDataError(symbol, symbol, "no rows")


def _returns(value):
    def impl(symbol, *a, **k):
        return value
    return impl


def _raises(exc):
    def impl(symbol, *a, **k):
        raise exc
    return impl


@pytest.mark.unit
class VendorRoutingTests(unittest.TestCase):
    def setUp(self):
        _reset_config()

    def tearDown(self):
        _reset_config()

    def _route(self, vendors_for_get_stock_data):
        return mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_stock_data": vendors_for_get_stock_data},
            clear=False,
        )

    def test_explicit_single_vendor_does_not_fall_back(self):
        # #988: with yfinance pinned, a healthy alpha_vantage must NOT be used.
        set_config({"data_vendors": {"core_stock_apis": "yfinance"}})
        av = mock.Mock(side_effect=_returns("AV_DATA"))
        with self._route({"yfinance": _no_data, "alpha_vantage": av}):
            result = interface.route_to_vendor("get_stock_data", "FAKE", "2026-01-01", "2026-01-10")
        self.assertIn("NO_DATA_AVAILABLE", result)
        av.assert_not_called()  # the unchosen vendor was never tried

    def test_explicit_multi_vendor_falls_back_within_chain(self):
        # Listing both vendors opts in to ordered fallback.
        set_config({"data_vendors": {"core_stock_apis": "yfinance,alpha_vantage"}})
        with self._route({"yfinance": _no_data, "alpha_vantage": _returns("AV_DATA")}):
            result = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertEqual(result, "AV_DATA")

    def test_primary_error_is_logged_not_masked(self):
        # #989: primary errors + fallback no-data -> NO_DATA, but the failure
        # must be visible in logs (broken primary not hidden).
        set_config({"data_vendors": {"core_stock_apis": "yfinance,alpha_vantage"}})
        with self._route({"yfinance": _raises(ValueError("boom")), "alpha_vantage": _no_data}), \
                self.assertLogs("tradingagents.dataflows.interface", level="WARNING") as cm:
            result = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertIn("NO_DATA_AVAILABLE", result)
        joined = "\n".join(cm.output)
        self.assertIn("boom", joined)            # the real error surfaced in logs
        self.assertIn("yfinance", joined)

    def test_unknown_configured_vendor_raises(self):
        set_config({"data_vendors": {"core_stock_apis": "bogus_vendor"}})
        with self.assertRaises(ValueError) as ctx:
            interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertIn("bogus_vendor", str(ctx.exception))

    def test_default_sentinel_uses_all_vendors(self):
        # No explicit choice ("default") keeps the resilient full-chain behavior.
        set_config({"data_vendors": {"core_stock_apis": "default"}})
        with self._route({"yfinance": _no_data, "alpha_vantage": _returns("AV_DATA")}):
            result = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertEqual(result, "AV_DATA")

    def test_as_of_guard_clamps_future_end_date(self):
        set_config({
            "analysis_as_of_date": "2026-01-05",
            "data_vendors": {"core_stock_apis": "yfinance"},
        })
        vendor = mock.Mock(return_value="AS_OF_DATA")
        with self._route({"yfinance": vendor}):
            result = interface.route_to_vendor(
                "get_stock_data",
                "AAPL",
                "2026-01-01",
                "2026-01-10",
            )

        self.assertEqual(result, "AS_OF_DATA")
        vendor.assert_called_once_with("AAPL", "2026-01-01", "2026-01-05")

    def test_as_of_guard_rejects_future_start_date(self):
        set_config({
            "analysis_as_of_date": "2026-01-05",
            "data_vendors": {"core_stock_apis": "yfinance"},
        })
        vendor = mock.Mock(return_value="SHOULD_NOT_CALL")
        with self._route({"yfinance": vendor}):
            result = interface.route_to_vendor(
                "get_stock_data",
                "AAPL",
                "2026-01-06",
                "2026-01-10",
            )

        self.assertIn("AS_OF_DATE_VIOLATION", result)
        vendor.assert_not_called()

    def test_as_of_guard_blocks_live_only_tools_for_historical_runs(self):
        set_config({"analysis_as_of_date": "2000-01-01"})

        result = interface.route_to_vendor("get_prediction_markets", "Fed rate cut", 3)

        self.assertIn("AS_OF_DATE_UNAVAILABLE", result)


if __name__ == "__main__":
    unittest.main()
