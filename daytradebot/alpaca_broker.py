from __future__ import annotations

import logging
import socket
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from daytradebot.account_status import normalize_account_status

log = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")
_TRANSIENT_HTTP_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_TRANSIENT_ERROR_MARKERS = (
    "temporary failure in name resolution",
    "name resolution",
    "max retries exceeded",
    "temporarily unavailable",
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "connection refused",
    "server disconnected",
    "bad gateway",
    "service unavailable",
    "too many requests",
)


def _daily_bars_start(limit: int) -> datetime:
    days_back = max(30, int(limit) * 2)
    return datetime.now(timezone.utc) - timedelta(days=days_back)


def _session_start_et(now: datetime | None = None) -> datetime:
    clock = (now or datetime.now(NY)).astimezone(NY)
    start = clock.replace(hour=9, minute=30, second=0, microsecond=0)
    if clock.time().hour < 9 or (clock.time().hour == 9 and clock.time().minute < 30):
        start -= timedelta(days=1)
    while start.weekday() >= 5:
        start -= timedelta(days=1)
    return start.astimezone(timezone.utc)


def _iter_exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        chain.append(cur)
        seen.add(id(cur))
        nxt = cur.__cause__ or cur.__context__
        cur = nxt if isinstance(nxt, BaseException) else None
    return chain


def _is_transient_alpaca_error(exc: BaseException) -> bool:
    for item in _iter_exception_chain(exc):
        if isinstance(item, (TimeoutError, socket.timeout, socket.gaierror)):
            return True
        if isinstance(item, requests.exceptions.Timeout):
            return True
        if isinstance(item, requests.exceptions.ConnectionError):
            return True
        if isinstance(item, requests.exceptions.HTTPError):
            response = getattr(item, "response", None)
            status_code = getattr(response, "status_code", None)
            if status_code in _TRANSIENT_HTTP_CODES:
                return True
        text = str(item).strip().lower()
        if any(marker in text for marker in _TRANSIENT_ERROR_MARKERS):
            return True
    return False


def _is_wash_trade_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "wash trade" in text or "opposite side market" in text


def _bars_to_df(bars: Any) -> pd.DataFrame:
    rows = []
    for bar in bars:
        rows.append(
            {
                "ts": bar.timestamp,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    return pd.DataFrame(rows).set_index("ts").sort_index()


class AlpacaBroker:
    """Alpaca trading + intraday/daily bars for DayTradeBot."""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        paper: bool,
        *,
        retry_attempts: int = 3,
        retry_base_delay_sec: float = 2.0,
    ) -> None:
        self._trading = TradingClient(api_key, secret_key, paper=paper)
        self._data = StockHistoricalDataClient(api_key, secret_key)
        self._on_trade: Callable[[str, float, str, str], None] | None = None
        self._retry_attempts = max(1, int(retry_attempts))
        self._retry_base_delay_sec = max(0.0, float(retry_base_delay_sec))

    def set_trade_callback(
        self, cb: Callable[[str, float, str, str], None] | None
    ) -> None:
        self._on_trade = cb

    def _call_with_retries(self, op_name: str, func: Callable[[], Any]) -> Any:
        for attempt in range(1, self._retry_attempts + 1):
            try:
                return func()
            except Exception as exc:
                if attempt >= self._retry_attempts or not _is_transient_alpaca_error(exc):
                    raise
                delay = self._retry_base_delay_sec * (2 ** (attempt - 1))
                log.warning(
                    "Transient Alpaca error during %s (attempt %d/%d): %s; retrying in %.1fs",
                    op_name,
                    attempt,
                    self._retry_attempts,
                    exc,
                    delay,
                )
                time.sleep(delay)

    def get_account(self) -> dict[str, Any]:
        a = self._call_with_retries("get_account", lambda: self._trading.get_account())
        return {
            "status": normalize_account_status(a.status),
            "equity": float(a.equity),
            "cash": float(a.cash),
            "buying_power": float(a.buying_power),
        }

    def get_position_qty(self, symbol: str) -> float:
        pos = self.get_position(symbol)
        return float(pos["qty"]) if pos else 0.0

    def get_position(self, symbol: str) -> dict[str, Any] | None:
        sym = symbol.strip().upper()
        try:
            pos = self._call_with_retries(
                f"get_open_position({sym})",
                lambda: self._trading.get_open_position(sym),
            )
            return {
                "symbol": sym,
                "qty": float(pos.qty),
                "avg_entry_price": float(pos.avg_entry_price),
                "market_value": float(pos.market_value),
                "unrealized_pl": float(pos.unrealized_pl),
            }
        except Exception:
            return None

    def get_open_positions(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        positions = self._call_with_retries(
            "get_all_positions",
            lambda: self._trading.get_all_positions(),
        )
        for pos in positions:
            rows.append(
                {
                    "symbol": str(pos.symbol),
                    "qty": float(pos.qty),
                    "avg_entry_price": float(pos.avg_entry_price),
                    "market_value": float(pos.market_value),
                    "unrealized_pl": float(pos.unrealized_pl),
                }
            )
        return rows

    def _find_open_order(self, symbol: str, side: str) -> Any | None:
        sym = symbol.strip().upper()
        wanted_side = side.strip().upper()
        try:
            orders = self._call_with_retries(
                f"get_orders(dedupe:{sym}:{wanted_side})",
                lambda: self._trading.get_orders(),
            )
        except Exception:
            log.exception("Failed to fetch open orders for %s", sym)
            return None
        for order in orders:
            order_sym = str(getattr(order, "symbol", "")).strip().upper()
            order_side = str(getattr(order, "side", "")).strip().upper()
            if "." in order_side:
                order_side = order_side.rsplit(".", 1)[-1]
            if order_sym == sym and order_side == wanted_side:
                return order
        return None

    def submit_market_order(
        self, symbol: str, qty: float, side: str, client_order_id: str | None = None
    ) -> str:
        sym = symbol.strip().upper()
        side_text = side.strip().upper()
        pos = self.get_position_qty(sym)
        if side_text == "BUY" and pos > 0:
            log.debug("Skip BUY %s %s; already long qty=%g", sym, qty, pos)
            return ""
        if side_text == "SELL" and pos <= 0 and qty > 0:
            pass  # allow short entry or flat skip below
        if side_text == "SELL" and pos > 0 and qty > pos:
            qty = pos

        existing = self._find_open_order(sym, side_text)
        if existing is not None:
            order_id = str(getattr(existing, "id", ""))
            log.debug(
                "Skip duplicate %s %s %s; existing open order_id=%s",
                side_text,
                qty,
                sym,
                order_id,
            )
            return order_id

        opp_side = "SELL" if side_text == "BUY" else "BUY"
        opposite = self._find_open_order(sym, opp_side)
        if opposite is not None:
            log.warning(
                "Skip %s %s %s: opposite-side open order_id=%s",
                side_text,
                qty,
                sym,
                getattr(opposite, "id", ""),
            )
            return ""

        side_enum = OrderSide.BUY if side_text == "BUY" else OrderSide.SELL
        req = MarketOrderRequest(
            symbol=sym,
            qty=qty,
            side=side_enum,
            time_in_force=TimeInForce.DAY,
            client_order_id=client_order_id,
        )
        try:
            order = self._trading.submit_order(req)
        except Exception as exc:
            if _is_wash_trade_error(exc):
                log.warning(
                    "Skip %s %s %s: Alpaca rejected as wash trade (%s)",
                    side_text,
                    qty,
                    sym,
                    exc,
                )
                return ""
            raise
        order_id = str(order.id)
        log.info("Submitted %s %s %s -> order_id=%s", side_text, qty, sym, order_id)
        if self._on_trade is not None:
            try:
                self._on_trade(side_text, float(qty), sym, order_id)
            except Exception:
                log.exception("Trade callback failed for %s", sym)
        return order_id

    def get_intraday_bars(self, symbol: str, timeframe_min: int) -> pd.DataFrame:
        sym = symbol.strip().upper()
        unit = TimeFrame(amount=int(timeframe_min), unit=TimeFrameUnit.Minute)
        start = _session_start_et()
        req = StockBarsRequest(
            symbol_or_symbols=sym,
            timeframe=unit,
            start=start,
            feed=DataFeed.IEX,
        )
        bars = self._call_with_retries(
            f"get_intraday_bars({sym},{timeframe_min}m)",
            lambda: self._data.get_stock_bars(req),
        )
        sym_bars = bars.data.get(sym)
        if not sym_bars:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return _bars_to_df(sym_bars)

    def get_daily_bars(self, symbol: str, limit: int) -> pd.DataFrame:
        sym = symbol.strip().upper()
        req = StockBarsRequest(
            symbol_or_symbols=sym,
            timeframe=TimeFrame.Day,
            start=_daily_bars_start(limit),
            feed=DataFeed.IEX,
        )
        bars = self._call_with_retries(
            f"get_daily_bars({sym})",
            lambda: self._data.get_stock_bars(req),
        )
        sym_bars = bars.data.get(sym)
        if not sym_bars:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return _bars_to_df(sym_bars).tail(limit)
