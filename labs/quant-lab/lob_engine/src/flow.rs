//! Synthetic order flow, a deterministic benchmark harness and an agent-style market simulator.

use crate::book::{Event, OrderBook, OrderType, Side};
use std::time::Instant;

/// xorshift64* — tiny, fast, deterministic; good enough for synthetic flow.
#[derive(Clone)]
pub struct Rng(u64);
impl Rng {
    pub fn new(seed: u64) -> Self {
        Rng(seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) | 1)
    }
    #[inline]
    pub fn next_u64(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
    #[inline]
    pub fn uniform(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 * (1.0 / (1u64 << 53) as f64)
    }
    /// Geometric number of failures with the given mean (>= 0).
    #[inline]
    pub fn geometric(&mut self, mean: f64) -> u64 {
        if mean <= 0.0 {
            return 0;
        }
        let p = 1.0 / (1.0 + mean);
        let u = self.uniform().max(1e-12);
        (u.ln() / (1.0 - p).ln()).floor() as u64
    }
    pub fn normal(&mut self) -> f64 {
        let u1 = self.uniform().max(1e-12);
        let u2 = self.uniform();
        (-2.0 * u1.ln()).sqrt() * (2.0 * std::f64::consts::PI * u2).cos()
    }
}

/// Relative weights of each command type.
#[derive(Clone, Copy, Debug)]
pub struct FlowMix {
    pub limit: f64,
    pub market: f64,
    pub ioc: f64,
    pub fok: f64,
    pub post_only: f64,
    pub stop: f64,
    pub cancel: f64,
    pub modify: f64,
}

impl Default for FlowMix {
    fn default() -> Self {
        // Roughly shaped like a real venue: mostly passive adds and cancels.
        FlowMix { limit: 0.45, market: 0.05, ioc: 0.05, fok: 0.02, post_only: 0.05, stop: 0.01, cancel: 0.32, modify: 0.05 }
    }
}

#[derive(Clone, Debug)]
pub struct FlowParams {
    pub mix: FlowMix,
    pub mid: i64,
    pub mean_qty: f64,
    /// Mean distance (ticks) of passive limit orders from the reference price.
    pub depth_ticks: f64,
    /// Share of limit/IOC/FOK orders priced through the reference (marketable).
    pub aggressive_frac: f64,
    /// Probability an order is a buy (0.5 = balanced flow).
    pub buy_prob: f64,
    /// Std-dev of the reference price random walk per command, in ticks (benchmark mode).
    pub ref_vol: f64,
    pub traders: u32,
    pub seed: u64,
}

impl Default for FlowParams {
    fn default() -> Self {
        FlowParams {
            mix: FlowMix::default(),
            mid: 10_000,
            mean_qty: 20.0,
            depth_ticks: 8.0,
            aggressive_frac: 0.1,
            buy_prob: 0.5,
            ref_vol: 0.05,
            traders: 50,
            seed: 42,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum CmdKind {
    Limit,
    Market,
    Ioc,
    Fok,
    PostOnly,
    Stop,
    Cancel,
    Modify,
}
impl CmdKind {
    pub const ALL: [CmdKind; 8] = [
        CmdKind::Limit,
        CmdKind::Market,
        CmdKind::Ioc,
        CmdKind::Fok,
        CmdKind::PostOnly,
        CmdKind::Stop,
        CmdKind::Cancel,
        CmdKind::Modify,
    ];
    pub fn as_str(self) -> &'static str {
        match self {
            CmdKind::Limit => "limit",
            CmdKind::Market => "market",
            CmdKind::Ioc => "ioc",
            CmdKind::Fok => "fok",
            CmdKind::PostOnly => "post_only",
            CmdKind::Stop => "stop",
            CmdKind::Cancel => "cancel",
            CmdKind::Modify => "modify",
        }
    }
}

#[derive(Clone, Debug)]
pub enum Cmd {
    New { side: Side, otype: OrderType, price: i64, qty: u64, trader: u32, trigger: Option<i64> },
    Cancel { id: u64 },
    Modify { id: u64, price: i64, qty: u64 },
}

impl Cmd {
    pub fn kind(&self) -> CmdKind {
        match self {
            Cmd::New { otype, .. } => match otype {
                OrderType::Limit => CmdKind::Limit,
                OrderType::Market => CmdKind::Market,
                OrderType::Ioc => CmdKind::Ioc,
                OrderType::Fok => CmdKind::Fok,
                OrderType::PostOnly => CmdKind::PostOnly,
                OrderType::StopMarket | OrderType::StopLimit => CmdKind::Stop,
            },
            Cmd::Cancel { .. } => CmdKind::Cancel,
            Cmd::Modify { .. } => CmdKind::Modify,
        }
    }

    #[inline]
    pub fn apply(&self, book: &mut OrderBook, ev: &mut Vec<Event>) {
        match *self {
            Cmd::New { side, otype, price, qty, trader, trigger } => {
                book.submit(side, otype, price, qty, trader, trigger, ev);
            }
            Cmd::Cancel { id } => {
                book.cancel(id, ev);
            }
            Cmd::Modify { id, price, qty } => {
                book.modify(id, price, qty, ev);
            }
        }
    }
}

/// Generates commands. Order ids are predicted (the book assigns ids sequentially), so
/// cancels/modifies can be pre-generated without touching the book — keeping RNG cost
/// out of the timed loop.
pub struct FlowGen {
    pub p: FlowParams,
    rng: Rng,
    ref_px: f64,
    live: Vec<(u64, i64, u64)>, // (id, price, qty) of recently submitted resting-capable orders
    next_id: u64,
    band: (i64, i64),
    cum: [f64; 8],
}

impl FlowGen {
    pub fn new(p: FlowParams, band: (i64, i64), first_id: u64) -> Self {
        let m = p.mix;
        let w = [m.limit, m.market, m.ioc, m.fok, m.post_only, m.stop, m.cancel, m.modify];
        let tot: f64 = w.iter().map(|x| x.max(0.0)).sum::<f64>().max(1e-12);
        let mut cum = [0.0; 8];
        let mut acc = 0.0;
        for i in 0..8 {
            acc += w[i].max(0.0) / tot;
            cum[i] = acc;
        }
        FlowGen { rng: Rng::new(p.seed), ref_px: p.mid as f64, live: Vec::with_capacity(1 << 15), next_id: first_id, band, cum, p }
    }

    fn clamp(&self, px: i64) -> i64 {
        px.clamp(self.band.0, self.band.1)
    }

    fn qty(&mut self) -> u64 {
        1 + self.rng.geometric(self.p.mean_qty - 1.0)
    }

    fn side(&mut self) -> Side {
        if self.rng.uniform() < self.p.buy_prob {
            Side::Buy
        } else {
            Side::Sell
        }
    }

    fn passive_price(&mut self, side: Side) -> i64 {
        let off = 1 + self.rng.geometric(self.p.depth_ticks - 1.0) as i64;
        let r = self.ref_px.round() as i64;
        self.clamp(match side {
            Side::Buy => r - off,
            Side::Sell => r + off,
        })
    }

    fn priced(&mut self, side: Side) -> i64 {
        if self.rng.uniform() < self.p.aggressive_frac {
            let through = self.rng.geometric(2.0) as i64;
            let r = self.ref_px.round() as i64;
            self.clamp(match side {
                Side::Buy => r + through,
                Side::Sell => r - through,
            })
        } else {
            self.passive_price(side)
        }
    }

    /// Passive limit orders only — used to pre-fill a book.
    pub fn prefill(&mut self) -> Cmd {
        let side = self.side();
        let price = self.passive_price(side);
        let qty = self.qty();
        let trader = (self.rng.next_u64() % self.p.traders as u64) as u32;
        self.track_new(price, qty);
        Cmd::New { side, otype: OrderType::Limit, price, qty, trader, trigger: None }
    }

    fn track_new(&mut self, price: i64, qty: u64) {
        let id = self.next_id;
        self.next_id += 1;
        if self.live.len() < 200_000 {
            self.live.push((id, price, qty));
        } else {
            let i = (self.rng.next_u64() % self.live.len() as u64) as usize;
            self.live[i] = (id, price, qty);
        }
    }

    /// Next command. `book_mid` (if given) anchors the reference price to the live book,
    /// which is what the simulator uses; the benchmark passes `None` and uses a random walk.
    pub fn next(&mut self, book_mid: Option<f64>) -> Cmd {
        match book_mid {
            Some(m) => self.ref_px = m + self.rng.normal() * 0.5,
            None => self.ref_px += self.rng.normal() * self.p.ref_vol,
        }
        self.ref_px = self.ref_px.clamp(self.band.0 as f64 + 50.0, self.band.1 as f64 - 50.0);
        let u = self.rng.uniform();
        let k = self.cum.iter().position(|c| u <= *c).unwrap_or(7);
        let trader = (self.rng.next_u64() % self.p.traders as u64) as u32;
        let side = self.side();
        let (otype, price, trigger) = match k {
            0 => (OrderType::Limit, self.priced(side), None),
            1 => (OrderType::Market, 0, None),
            2 => (OrderType::Ioc, self.priced(side), None),
            3 => (OrderType::Fok, self.priced(side), None),
            4 => (OrderType::PostOnly, self.passive_price(side), None),
            5 => {
                let gap = 3 + self.rng.geometric(6.0) as i64;
                let r = self.ref_px.round() as i64;
                let trig = self.clamp(if side == Side::Buy { r + gap } else { r - gap });
                (OrderType::StopMarket, 0, Some(trig))
            }
            6 => {
                if self.live.is_empty() {
                    return self.prefill();
                }
                let i = (self.rng.next_u64() % self.live.len() as u64) as usize;
                let (id, _, _) = self.live.swap_remove(i);
                return Cmd::Cancel { id };
            }
            _ => {
                if self.live.is_empty() {
                    return self.prefill();
                }
                let i = (self.rng.next_u64() % self.live.len() as u64) as usize;
                let (id, price, qty) = self.live[i];
                // Half the time a size-down (keeps priority), otherwise re-price by a tick or two.
                let (np, nq) = if self.rng.uniform() < 0.5 && qty > 1 {
                    (price, (qty / 2).max(1))
                } else {
                    let d = 1 + (self.rng.next_u64() % 2) as i64;
                    let d = if self.rng.uniform() < 0.5 { -d } else { d };
                    (self.clamp(price + d), qty)
                };
                self.live[i] = (id, np, nq);
                return Cmd::Modify { id, price: np, qty: nq };
            }
        };
        let qty = self.qty();
        if matches!(otype, OrderType::Limit | OrderType::PostOnly) {
            self.track_new(price, qty);
        } else {
            self.next_id += 1;
        }
        Cmd::New { side, otype, price, qty, trader, trigger }
    }
}

// ---------------------------------------------------------------------------- benchmark

#[derive(Clone, Debug)]
pub struct BenchConfig {
    pub n_orders: usize,
    pub prefill: usize,
    pub band: (i64, i64),
    pub params: FlowParams,
    pub stp: bool,
}

impl Default for BenchConfig {
    fn default() -> Self {
        BenchConfig { n_orders: 1_000_000, prefill: 10_000, band: (5_000, 15_000), params: FlowParams::default(), stp: false }
    }
}

#[derive(Clone, Debug, Default)]
pub struct KindStats {
    pub kind: &'static str,
    pub count: usize,
    pub mean_ns: f64,
    pub p50: u64,
    pub p99: u64,
    pub p999: u64,
    pub max: u64,
}

#[derive(Clone, Debug, Default)]
pub struct BenchResult {
    pub n_ops: usize,
    pub throughput_ops: f64,
    pub untimed_wall_ns: u64,
    pub timed_wall_ns: u64,
    pub timer_overhead_ns: f64,
    pub percentiles: Vec<(f64, u64)>,
    pub mean_ns: f64,
    pub hist_edges: Vec<f64>,
    pub hist_counts: Vec<u64>,
    pub per_kind: Vec<KindStats>,
    pub trades: u64,
    pub volume: u64,
    pub events: u64,
    pub resting_orders: usize,
    pub levels_bid: usize,
    pub levels_ask: usize,
}

fn pct(sorted: &[u64], q: f64) -> u64 {
    if sorted.is_empty() {
        return 0;
    }
    let i = ((q * sorted.len() as f64).ceil() as usize).clamp(1, sorted.len()) - 1;
    sorted[i]
}

pub fn run_benchmark(cfg: &BenchConfig) -> BenchResult {
    // 1) Pre-generate all commands so RNG work is not measured.
    let mut gen = FlowGen::new(cfg.params.clone(), cfg.band, 1);
    let pre: Vec<Cmd> = (0..cfg.prefill).map(|_| gen.prefill()).collect();
    let cmds: Vec<Cmd> = (0..cfg.n_orders).map(|_| gen.next(None)).collect();
    let mut ev: Vec<Event> = Vec::with_capacity(4096);

    let fresh = || {
        let mut b = OrderBook::new(cfg.band.0, cfg.band.1);
        b.stp = cfg.stp;
        b
    };

    // 2) Throughput: untimed tight loop on a fresh book.
    let mut book = fresh();
    for c in &pre {
        c.apply(&mut book, &mut ev);
        ev.clear();
    }
    let mut events = 0u64;
    let t0 = Instant::now();
    for c in &cmds {
        c.apply(&mut book, &mut ev);
        events += ev.len() as u64;
        ev.clear();
    }
    let untimed = t0.elapsed().as_nanos() as u64;

    // 3) Latency: same command stream, each op individually timed, on a fresh book.
    let mut book2 = fresh();
    for c in &pre {
        c.apply(&mut book2, &mut ev);
        ev.clear();
    }
    // timer overhead estimate
    let mut oh = Vec::with_capacity(10_000);
    for _ in 0..10_000 {
        let a = Instant::now();
        oh.push(a.elapsed().as_nanos() as u64);
    }
    oh.sort_unstable();
    let timer_oh = pct(&oh, 0.5) as f64;

    let mut lat: Vec<u64> = Vec::with_capacity(cmds.len());
    let t1 = Instant::now();
    for c in &cmds {
        let a = Instant::now();
        c.apply(&mut book2, &mut ev);
        lat.push(a.elapsed().as_nanos() as u64);
        ev.clear();
    }
    let timed = t1.elapsed().as_nanos() as u64;

    // per-kind breakdown
    let mut per: Vec<Vec<u64>> = vec![Vec::new(); CmdKind::ALL.len()];
    for (c, l) in cmds.iter().zip(&lat) {
        per[c.kind() as usize].push(*l);
    }
    let per_kind = CmdKind::ALL
        .iter()
        .zip(per.iter_mut())
        .filter(|(_, v)| !v.is_empty())
        .map(|(k, v)| {
            v.sort_unstable();
            KindStats {
                kind: k.as_str(),
                count: v.len(),
                mean_ns: v.iter().sum::<u64>() as f64 / v.len() as f64,
                p50: pct(v, 0.5),
                p99: pct(v, 0.99),
                p999: pct(v, 0.999),
                max: *v.last().unwrap(),
            }
        })
        .collect();

    let mean = lat.iter().sum::<u64>() as f64 / lat.len().max(1) as f64;
    lat.sort_unstable();
    let qs = [0.5, 0.9, 0.99, 0.999, 0.9999, 1.0];
    let percentiles = qs.iter().map(|q| (*q, pct(&lat, *q))).collect();

    // log-spaced histogram 10ns .. 1ms
    let nb = 64usize;
    let (lo, hi) = (10f64.ln(), 1e6f64.ln());
    let edges: Vec<f64> = (0..=nb).map(|i| (lo + (hi - lo) * i as f64 / nb as f64).exp()).collect();
    let mut counts = vec![0u64; nb];
    for &l in &lat {
        let x = (l.max(1) as f64).ln();
        let b = (((x - lo) / (hi - lo)) * nb as f64).floor() as isize;
        counts[b.clamp(0, nb as isize - 1) as usize] += 1;
    }
    let (bd, ad) = book.depth(usize::MAX);
    BenchResult {
        n_ops: cmds.len(),
        throughput_ops: cmds.len() as f64 / (untimed as f64 / 1e9),
        untimed_wall_ns: untimed,
        timed_wall_ns: timed,
        timer_overhead_ns: timer_oh,
        percentiles,
        mean_ns: mean,
        hist_edges: edges,
        hist_counts: counts,
        per_kind,
        trades: book.stats.trades,
        volume: book.stats.volume,
        events,
        resting_orders: book.order_count(),
        levels_bid: bd.len(),
        levels_ask: ad.len(),
    }
}

// ---------------------------------------------------------------------------- simulator

#[derive(Clone, Debug)]
pub struct SimConfig {
    pub steps: usize,
    pub snapshot_every: usize,
    pub depth_levels: usize,
    pub prefill: usize,
    pub band: (i64, i64),
    pub params: FlowParams,
    /// Optional liquidity shock: (step, side, qty) market order.
    pub shock: Option<(usize, Side, u64)>,
}

#[derive(Clone, Debug, Default)]
pub struct SimResult {
    pub snap_step: Vec<u64>,
    pub best_bid: Vec<Option<i64>>,
    pub best_ask: Vec<Option<i64>>,
    pub last: Vec<Option<i64>>,
    pub bid_depth: Vec<u64>,
    pub ask_depth: Vec<u64>,
    pub resting: Vec<usize>,
    /// (snapshot index, price, signed qty: +bid / -ask)
    pub depth_cells: Vec<(usize, i64, i64)>,
    /// (step, price, qty, aggressor side)
    pub trades: Vec<(u64, i64, u64, Side)>,
    pub kind_counts: Vec<(&'static str, u64)>,
    pub rejects: u64,
    pub cancels_by_reason: Vec<(&'static str, u64)>,
}

pub fn run_simulation(cfg: &SimConfig) -> (SimResult, OrderBook) {
    let mut book = OrderBook::new(cfg.band.0, cfg.band.1);
    let mut gen = FlowGen::new(cfg.params.clone(), cfg.band, book.next_id());
    let mut ev = Vec::with_capacity(256);
    for _ in 0..cfg.prefill {
        gen.prefill().apply(&mut book, &mut ev);
        ev.clear();
    }
    let mut r = SimResult::default();
    let mut kc = [0u64; 8];
    let mut cancel_reasons: std::collections::BTreeMap<&'static str, u64> = Default::default();
    let every = cfg.snapshot_every.max(1);
    for step in 0..cfg.steps {
        if let Some((s, side, q)) = cfg.shock {
            if s == step {
                book.submit(side, OrderType::Market, 0, q, u32::MAX - 1, None, &mut ev);
                collect(&ev, step as u64, &mut r, &mut cancel_reasons);
                ev.clear();
            }
        }
        let mid = book.mid_x2().map(|m| m as f64 / 2.0).or(book.last_price().map(|p| p as f64));
        let cmd = gen.next(mid);
        kc[cmd.kind() as usize] += 1;
        cmd.apply(&mut book, &mut ev);
        collect(&ev, step as u64, &mut r, &mut cancel_reasons);
        ev.clear();
        if step % every == 0 || step + 1 == cfg.steps {
            let si = r.snap_step.len();
            r.snap_step.push(step as u64);
            r.best_bid.push(book.best_bid());
            r.best_ask.push(book.best_ask());
            r.last.push(book.last_price());
            r.resting.push(book.order_count());
            let (b, a) = book.depth(cfg.depth_levels);
            r.bid_depth.push(b.iter().map(|x| x.1).sum());
            r.ask_depth.push(a.iter().map(|x| x.1).sum());
            for (p, q, _) in b {
                r.depth_cells.push((si, p, q as i64));
            }
            for (p, q, _) in a {
                r.depth_cells.push((si, p, -(q as i64)));
            }
        }
    }
    r.kind_counts = CmdKind::ALL.iter().map(|k| (k.as_str(), kc[*k as usize])).collect();
    r.cancels_by_reason = cancel_reasons.into_iter().collect();
    (r, book)
}

fn collect(ev: &[Event], step: u64, r: &mut SimResult, reasons: &mut std::collections::BTreeMap<&'static str, u64>) {
    for e in ev {
        match e {
            Event::Trade { price, qty, taker_side, .. } => r.trades.push((step, *price, *qty, *taker_side)),
            Event::Rejected { .. } => r.rejects += 1,
            Event::Cancelled { reason, .. } => *reasons.entry(reason).or_default() += 1,
            _ => {}
        }
    }
}
