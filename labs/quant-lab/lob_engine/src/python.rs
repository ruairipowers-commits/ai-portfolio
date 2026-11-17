//! Python bindings (pyo3). Prices are integer ticks on the Rust side.

use crate::book::{Event, OrderBook, OrderType, RestingOrder, Side};
use crate::flow::{run_benchmark, run_simulation, BenchConfig, FlowMix, FlowParams, SimConfig};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

fn parse_side(s: &str) -> PyResult<Side> {
    match s.to_ascii_lowercase().as_str() {
        "buy" | "b" | "bid" => Ok(Side::Buy),
        "sell" | "s" | "ask" => Ok(Side::Sell),
        _ => Err(PyValueError::new_err(format!("bad side {s:?}"))),
    }
}

fn parse_type(s: &str) -> PyResult<OrderType> {
    OrderType::parse(s).ok_or_else(|| PyValueError::new_err(format!("bad order type {s:?}")))
}

fn event_dict<'py>(py: Python<'py>, e: &Event) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    match e {
        Event::Accepted { id, side, otype, price, qty } => {
            d.set_item("event", "accepted")?;
            d.set_item("id", id)?;
            d.set_item("side", side.as_str())?;
            d.set_item("type", otype.as_str())?;
            d.set_item("price", price)?;
            d.set_item("qty", qty)?;
        }
        Event::Rejected { id, reason } => {
            d.set_item("event", "rejected")?;
            d.set_item("id", id)?;
            d.set_item("reason", reason)?;
        }
        Event::Trade { taker, maker, taker_trader, maker_trader, taker_side, price, qty } => {
            d.set_item("event", "trade")?;
            d.set_item("taker", taker)?;
            d.set_item("maker", maker)?;
            d.set_item("taker_trader", taker_trader)?;
            d.set_item("maker_trader", maker_trader)?;
            d.set_item("aggressor", taker_side.as_str())?;
            d.set_item("price", price)?;
            d.set_item("qty", qty)?;
        }
        Event::Rested { id, side, price, qty } => {
            d.set_item("event", "rested")?;
            d.set_item("id", id)?;
            d.set_item("side", side.as_str())?;
            d.set_item("price", price)?;
            d.set_item("qty", qty)?;
        }
        Event::Cancelled { id, remaining, reason } => {
            d.set_item("event", "cancelled")?;
            d.set_item("id", id)?;
            d.set_item("qty", remaining)?;
            d.set_item("reason", reason)?;
        }
        Event::Triggered { id, last_price } => {
            d.set_item("event", "triggered")?;
            d.set_item("id", id)?;
            d.set_item("price", last_price)?;
        }
        Event::Modified { id, price, qty, kept_priority } => {
            d.set_item("event", "modified")?;
            d.set_item("id", id)?;
            d.set_item("price", price)?;
            d.set_item("qty", qty)?;
            d.set_item("kept_priority", kept_priority)?;
        }
    }
    Ok(d)
}

fn events_list<'py>(py: Python<'py>, ev: &[Event]) -> PyResult<Bound<'py, PyList>> {
    let l = PyList::empty(py);
    for e in ev {
        l.append(event_dict(py, e)?)?;
    }
    Ok(l)
}

fn order_dict<'py>(py: Python<'py>, o: &RestingOrder) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("id", o.id)?;
    d.set_item("trader", o.trader)?;
    d.set_item("side", o.side.as_str())?;
    d.set_item("price", o.price)?;
    d.set_item("qty", o.qty)?;
    d.set_item("orig_qty", o.orig_qty)?;
    d.set_item("seq", o.seq)?;
    Ok(d)
}

#[pyclass(name = "OrderBook", module = "lob_engine")]
pub struct PyOrderBook {
    inner: OrderBook,
    ev: Vec<Event>,
}

#[pymethods]
impl PyOrderBook {
    #[new]
    #[pyo3(signature = (min_price=1, max_price=100_000, stp=true))]
    fn new(min_price: i64, max_price: i64, stp: bool) -> PyResult<Self> {
        if max_price <= min_price || max_price - min_price > 50_000_000 {
            return Err(PyValueError::new_err("invalid price band"));
        }
        let mut inner = OrderBook::new(min_price, max_price);
        inner.stp = stp;
        Ok(PyOrderBook { inner, ev: Vec::new() })
    }

    /// Submit an order. Returns (order_id, [event dicts]).
    #[pyo3(signature = (side, order_type, price=0, qty=1, trader=0, trigger=None))]
    fn submit<'py>(
        &mut self,
        py: Python<'py>,
        side: &str,
        order_type: &str,
        price: i64,
        qty: u64,
        trader: u32,
        trigger: Option<i64>,
    ) -> PyResult<(u64, Bound<'py, PyList>)> {
        let s = parse_side(side)?;
        let t = parse_type(order_type)?;
        self.ev.clear();
        let id = self.inner.submit(s, t, price, qty, trader, trigger, &mut self.ev);
        Ok((id, events_list(py, &self.ev)?))
    }

    fn cancel<'py>(&mut self, py: Python<'py>, order_id: u64) -> PyResult<(bool, Bound<'py, PyList>)> {
        self.ev.clear();
        let ok = self.inner.cancel(order_id, &mut self.ev);
        Ok((ok, events_list(py, &self.ev)?))
    }

    fn modify<'py>(&mut self, py: Python<'py>, order_id: u64, price: i64, qty: u64) -> PyResult<(bool, Bound<'py, PyList>)> {
        self.ev.clear();
        let ok = self.inner.modify(order_id, price, qty, &mut self.ev);
        Ok((ok, events_list(py, &self.ev)?))
    }

    /// Top-n levels per side: {"bids": [(price, qty, count)], "asks": [...]}
    #[pyo3(signature = (levels=10))]
    fn depth<'py>(&self, py: Python<'py>, levels: usize) -> PyResult<Bound<'py, PyDict>> {
        let (b, a) = self.inner.depth(levels);
        let d = PyDict::new(py);
        d.set_item("bids", b)?;
        d.set_item("asks", a)?;
        Ok(d)
    }

    fn queue<'py>(&self, py: Python<'py>, side: &str, price: i64) -> PyResult<Bound<'py, PyList>> {
        let l = PyList::empty(py);
        for o in self.inner.queue(parse_side(side)?, price) {
            l.append(order_dict(py, &o)?)?;
        }
        Ok(l)
    }

    #[pyo3(signature = (trader=None))]
    fn open_orders<'py>(&self, py: Python<'py>, trader: Option<u32>) -> PyResult<Bound<'py, PyList>> {
        let l = PyList::empty(py);
        for o in self.inner.open_orders(trader) {
            l.append(order_dict(py, &o)?)?;
        }
        Ok(l)
    }

    fn stop_orders<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let l = PyList::empty(py);
        for s in self.inner.stops() {
            let d = PyDict::new(py);
            d.set_item("id", s.id)?;
            d.set_item("trader", s.trader)?;
            d.set_item("side", s.side.as_str())?;
            d.set_item("type", s.otype.as_str())?;
            d.set_item("trigger", s.trigger)?;
            d.set_item("limit", s.limit)?;
            d.set_item("qty", s.qty)?;
            l.append(d)?;
        }
        Ok(l)
    }

    fn get_order<'py>(&self, py: Python<'py>, order_id: u64) -> PyResult<Option<Bound<'py, PyDict>>> {
        self.inner.get_order(order_id).map(|o| order_dict(py, &o)).transpose()
    }

    #[getter]
    fn best_bid(&self) -> Option<i64> {
        self.inner.best_bid()
    }
    #[getter]
    fn best_ask(&self) -> Option<i64> {
        self.inner.best_ask()
    }
    #[getter]
    fn last_price(&self) -> Option<i64> {
        self.inner.last_price()
    }
    #[getter]
    fn order_count(&self) -> usize {
        self.inner.order_count()
    }
    #[getter]
    fn price_band(&self) -> (i64, i64) {
        self.inner.price_band()
    }
    #[getter]
    fn stp(&self) -> bool {
        self.inner.stp
    }
    #[setter]
    fn set_stp(&mut self, v: bool) {
        self.inner.stp = v;
    }

    fn stats<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let s = &self.inner.stats;
        let d = PyDict::new(py);
        d.set_item("orders_in", s.orders_in)?;
        d.set_item("trades", s.trades)?;
        d.set_item("volume", s.volume)?;
        d.set_item("vwap", if s.volume > 0 { s.notional as f64 / s.volume as f64 } else { f64::NAN })?;
        d.set_item("cancels", s.cancels)?;
        d.set_item("rejects", s.rejects)?;
        d.set_item("resting", self.inner.order_count())?;
        d.set_item("stops", self.inner.stop_count())?;
        Ok(d)
    }

    fn check_invariants(&self) -> PyResult<()> {
        self.inner.check_invariants().map_err(PyValueError::new_err)
    }
}

fn flow_params(d: Option<&Bound<'_, PyDict>>) -> PyResult<FlowParams> {
    let mut p = FlowParams::default();
    let Some(d) = d else { return Ok(p) };
    macro_rules! get {
        ($k:literal, $t:ty) => {
            d.get_item($k)?.map(|v| v.extract::<$t>()).transpose()?
        };
    }
    if let Some(v) = get!("mid", i64) { p.mid = v }
    if let Some(v) = get!("mean_qty", f64) { p.mean_qty = v.max(1.0) }
    if let Some(v) = get!("depth_ticks", f64) { p.depth_ticks = v.max(1.0) }
    if let Some(v) = get!("aggressive_frac", f64) { p.aggressive_frac = v.clamp(0.0, 1.0) }
    if let Some(v) = get!("buy_prob", f64) { p.buy_prob = v.clamp(0.0, 1.0) }
    if let Some(v) = get!("ref_vol", f64) { p.ref_vol = v.max(0.0) }
    if let Some(v) = get!("traders", u32) { p.traders = v.max(1) }
    if let Some(v) = get!("seed", u64) { p.seed = v }
    if let Some(m) = d.get_item("mix")? {
        let m = m.downcast::<PyDict>()?;
        let g = |k: &str, dflt: f64| -> PyResult<f64> { Ok(m.get_item(k)?.map(|v| v.extract()).transpose()?.unwrap_or(dflt)) };
        let x = FlowMix::default();
        p.mix = FlowMix {
            limit: g("limit", x.limit)?,
            market: g("market", x.market)?,
            ioc: g("ioc", x.ioc)?,
            fok: g("fok", x.fok)?,
            post_only: g("post_only", x.post_only)?,
            stop: g("stop", x.stop)?,
            cancel: g("cancel", x.cancel)?,
            modify: g("modify", x.modify)?,
        };
    }
    Ok(p)
}

/// Run the native benchmark (GIL released). Returns a dict of results.
#[pyfunction]
#[pyo3(signature = (n_orders=1_000_000, prefill=10_000, band=(5_000, 15_000), params=None, stp=false))]
fn benchmark<'py>(
    py: Python<'py>,
    n_orders: usize,
    prefill: usize,
    band: (i64, i64),
    params: Option<&Bound<'py, PyDict>>,
    stp: bool,
) -> PyResult<Bound<'py, PyDict>> {
    let mut p = flow_params(params)?;
    p.mid = p.mid.clamp(band.0 + 100, band.1 - 100);
    let cfg = BenchConfig { n_orders, prefill, band, params: p, stp };
    let r = py.allow_threads(|| run_benchmark(&cfg));
    let d = PyDict::new(py);
    d.set_item("n_ops", r.n_ops)?;
    d.set_item("throughput_ops", r.throughput_ops)?;
    d.set_item("untimed_wall_ms", r.untimed_wall_ns as f64 / 1e6)?;
    d.set_item("timed_wall_ms", r.timed_wall_ns as f64 / 1e6)?;
    d.set_item("timer_overhead_ns", r.timer_overhead_ns)?;
    d.set_item("mean_ns", r.mean_ns)?;
    d.set_item("percentiles", r.percentiles)?;
    d.set_item("hist_edges", r.hist_edges)?;
    d.set_item("hist_counts", r.hist_counts)?;
    let pk = PyList::empty(py);
    for k in &r.per_kind {
        let kd = PyDict::new(py);
        kd.set_item("kind", k.kind)?;
        kd.set_item("count", k.count)?;
        kd.set_item("mean_ns", k.mean_ns)?;
        kd.set_item("p50_ns", k.p50)?;
        kd.set_item("p99_ns", k.p99)?;
        kd.set_item("p999_ns", k.p999)?;
        kd.set_item("max_ns", k.max)?;
        pk.append(kd)?;
    }
    d.set_item("per_kind", pk)?;
    d.set_item("trades", r.trades)?;
    d.set_item("volume", r.volume)?;
    d.set_item("events", r.events)?;
    d.set_item("resting_orders", r.resting_orders)?;
    d.set_item("levels_bid", r.levels_bid)?;
    d.set_item("levels_ask", r.levels_ask)?;
    Ok(d)
}

/// Agent-style market simulation. Returns (result dict, final OrderBook).
#[pyfunction]
#[pyo3(signature = (steps=20_000, snapshot_every=100, depth_levels=15, prefill=400, band=(5_000, 15_000), params=None, shock=None))]
#[allow(clippy::too_many_arguments)]
fn simulate<'py>(
    py: Python<'py>,
    steps: usize,
    snapshot_every: usize,
    depth_levels: usize,
    prefill: usize,
    band: (i64, i64),
    params: Option<&Bound<'py, PyDict>>,
    shock: Option<(usize, String, u64)>,
) -> PyResult<(Bound<'py, PyDict>, PyOrderBook)> {
    let mut p = flow_params(params)?;
    p.mid = p.mid.clamp(band.0 + 100, band.1 - 100);
    let shock = match shock {
        Some((s, side, q)) => Some((s, parse_side(&side)?, q)),
        None => None,
    };
    let cfg = SimConfig { steps, snapshot_every, depth_levels, prefill, band, params: p, shock };
    let (r, book) = py.allow_threads(|| run_simulation(&cfg));
    let d = PyDict::new(py);
    d.set_item("step", r.snap_step)?;
    d.set_item("best_bid", r.best_bid)?;
    d.set_item("best_ask", r.best_ask)?;
    d.set_item("last", r.last)?;
    d.set_item("bid_depth", r.bid_depth)?;
    d.set_item("ask_depth", r.ask_depth)?;
    d.set_item("resting", r.resting)?;
    d.set_item("depth_cells", r.depth_cells)?;
    let trades: Vec<(u64, i64, u64, &str)> = r.trades.iter().map(|(s, p, q, sd)| (*s, *p, *q, sd.as_str())).collect();
    d.set_item("trades", trades)?;
    d.set_item("kind_counts", r.kind_counts)?;
    d.set_item("rejects", r.rejects)?;
    d.set_item("cancels_by_reason", r.cancels_by_reason)?;
    Ok((d, PyOrderBook { inner: book, ev: Vec::new() }))
}

#[pymodule]
fn lob_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyOrderBook>()?;
    m.add_function(wrap_pyfunction!(benchmark, m)?)?;
    m.add_function(wrap_pyfunction!(simulate, m)?)?;
    m.add("ORDER_TYPES", vec!["limit", "market", "ioc", "fok", "post_only", "stop_market", "stop_limit"])?;
    Ok(())
}
