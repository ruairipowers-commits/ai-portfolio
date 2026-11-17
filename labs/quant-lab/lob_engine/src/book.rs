//! Limit order book with strict price-time priority.
//!
//! Design (chosen for predictable tail latency):
//! * Dense price ladder: one `Level` per tick inside a fixed price band, so finding a
//!   level is an array index, not a tree walk.
//! * Each level is an intrusive doubly-linked FIFO of nodes stored in a slab (`Vec<Node>`)
//!   with a free list, so add / cancel / fill are O(1) and allocation-free in steady state.
//! * `id -> slot` uses an open hash map with a cheap multiplicative hasher.
//! * Best bid / ask are cached and only rescanned when the best level empties.
//! * Stop orders live in ordered maps keyed by (trigger, seq) and are released after
//!   each trade print, which lets stop cascades fall out naturally.

use std::collections::{BTreeMap, HashMap};
use std::hash::{BuildHasherDefault, Hasher};

pub const NIL: u32 = u32::MAX;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Side {
    Buy,
    Sell,
}

impl Side {
    pub fn opposite(self) -> Side {
        match self {
            Side::Buy => Side::Sell,
            Side::Sell => Side::Buy,
        }
    }
    pub fn as_str(self) -> &'static str {
        match self {
            Side::Buy => "buy",
            Side::Sell => "sell",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum OrderType {
    /// Rests any unfilled remainder.
    Limit,
    /// Takes liquidity at any price; remainder cancelled.
    Market,
    /// Immediate-or-cancel limit: fills what it can up to the limit, cancels the rest.
    Ioc,
    /// Fill-or-kill limit: fills completely up to the limit or does nothing.
    Fok,
    /// Maker-only limit: rejected if it would cross the spread.
    PostOnly,
    /// Becomes a market order when the last trade touches the trigger.
    StopMarket,
    /// Becomes a limit order when the last trade touches the trigger.
    StopLimit,
}

impl OrderType {
    pub const ALL: [OrderType; 7] = [
        OrderType::Limit,
        OrderType::Market,
        OrderType::Ioc,
        OrderType::Fok,
        OrderType::PostOnly,
        OrderType::StopMarket,
        OrderType::StopLimit,
    ];
    pub fn as_str(self) -> &'static str {
        match self {
            OrderType::Limit => "limit",
            OrderType::Market => "market",
            OrderType::Ioc => "ioc",
            OrderType::Fok => "fok",
            OrderType::PostOnly => "post_only",
            OrderType::StopMarket => "stop_market",
            OrderType::StopLimit => "stop_limit",
        }
    }
    pub fn parse(s: &str) -> Option<OrderType> {
        Some(match s.to_ascii_lowercase().as_str() {
            "limit" => OrderType::Limit,
            "market" => OrderType::Market,
            "ioc" => OrderType::Ioc,
            "fok" => OrderType::Fok,
            "post_only" | "postonly" | "post" => OrderType::PostOnly,
            "stop_market" | "stop" => OrderType::StopMarket,
            "stop_limit" => OrderType::StopLimit,
            _ => return None,
        })
    }
    pub fn index(self) -> usize {
        self as usize
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum Event {
    Accepted { id: u64, side: Side, otype: OrderType, price: i64, qty: u64 },
    Rejected { id: u64, reason: &'static str },
    Trade {
        taker: u64,
        maker: u64,
        taker_trader: u32,
        maker_trader: u32,
        taker_side: Side,
        price: i64,
        qty: u64,
    },
    Rested { id: u64, side: Side, price: i64, qty: u64 },
    Cancelled { id: u64, remaining: u64, reason: &'static str },
    Triggered { id: u64, last_price: i64 },
    Modified { id: u64, price: i64, qty: u64, kept_priority: bool },
}

#[derive(Clone, Debug)]
struct Node {
    id: u64,
    trader: u32,
    side: Side,
    price: i64,
    qty: u64,
    orig_qty: u64,
    seq: u64,
    prev: u32,
    next: u32,
}

#[derive(Clone, Copy, Debug)]
struct Level {
    head: u32,
    tail: u32,
    qty: u64,
    count: u32,
}

impl Default for Level {
    fn default() -> Self {
        Level { head: NIL, tail: NIL, qty: 0, count: 0 }
    }
}

#[derive(Clone, Debug)]
pub struct StopOrder {
    pub id: u64,
    pub trader: u32,
    pub side: Side,
    pub otype: OrderType,
    pub trigger: i64,
    pub limit: i64,
    pub qty: u64,
}

/// Fast hasher for u64 order ids (Fibonacci multiplicative hashing).
#[derive(Default, Clone, Copy)]
pub struct IdHasher(u64);
impl Hasher for IdHasher {
    fn finish(&self) -> u64 {
        self.0
    }
    fn write(&mut self, bytes: &[u8]) {
        for b in bytes {
            self.0 = (self.0 ^ *b as u64).wrapping_mul(0x100000001b3);
        }
    }
    fn write_u64(&mut self, n: u64) {
        self.0 = n.wrapping_mul(0x9E37_79B9_7F4A_7C15);
    }
}
type IdMap<V> = HashMap<u64, V, BuildHasherDefault<IdHasher>>;

#[derive(Clone, Debug, Default)]
pub struct BookStats {
    pub orders_in: u64,
    pub trades: u64,
    pub volume: u64,
    pub notional: i128,
    pub cancels: u64,
    pub rejects: u64,
}

/// Public view of a resting order.
#[derive(Clone, Debug)]
pub struct RestingOrder {
    pub id: u64,
    pub trader: u32,
    pub side: Side,
    pub price: i64,
    pub qty: u64,
    pub orig_qty: u64,
    pub seq: u64,
}

pub struct OrderBook {
    min_price: i64,
    max_price: i64,
    bids: Vec<Level>,
    asks: Vec<Level>,
    best_bid: i64, // min_price - 1 when empty
    best_ask: i64, // max_price + 1 when empty
    nodes: Vec<Node>,
    free: Vec<u32>,
    index: IdMap<u32>,
    buy_stops: BTreeMap<(i64, u64), StopOrder>,  // trigger when last >= trigger
    sell_stops: BTreeMap<(i64, u64), StopOrder>, // trigger when last <= trigger
    stop_index: IdMap<(Side, i64, u64)>,
    next_id: u64,
    seq: u64,
    last_price: Option<i64>,
    /// Self-trade prevention: cancel the resting order if taker & maker share a trader id.
    pub stp: bool,
    pub stats: BookStats,
}

impl OrderBook {
    pub fn new(min_price: i64, max_price: i64) -> Self {
        assert!(max_price > min_price, "max_price must exceed min_price");
        let n = (max_price - min_price + 1) as usize;
        OrderBook {
            min_price,
            max_price,
            bids: vec![Level::default(); n],
            asks: vec![Level::default(); n],
            best_bid: min_price - 1,
            best_ask: max_price + 1,
            nodes: Vec::with_capacity(1 << 16),
            free: Vec::with_capacity(1 << 12),
            index: IdMap::with_capacity_and_hasher(1 << 16, Default::default()),
            buy_stops: BTreeMap::new(),
            sell_stops: BTreeMap::new(),
            stop_index: IdMap::default(),
            next_id: 1,
            seq: 0,
            last_price: None,
            stp: true,
            stats: BookStats::default(),
        }
    }

    // ------------------------------------------------------------------ queries
    pub fn price_band(&self) -> (i64, i64) {
        (self.min_price, self.max_price)
    }
    pub fn best_bid(&self) -> Option<i64> {
        (self.best_bid >= self.min_price).then_some(self.best_bid)
    }
    pub fn best_ask(&self) -> Option<i64> {
        (self.best_ask <= self.max_price).then_some(self.best_ask)
    }
    pub fn last_price(&self) -> Option<i64> {
        self.last_price
    }
    pub fn mid_x2(&self) -> Option<i64> {
        Some(self.best_bid()? + self.best_ask()?)
    }
    pub fn order_count(&self) -> usize {
        self.index.len()
    }
    pub fn stop_count(&self) -> usize {
        self.stop_index.len()
    }
    pub fn next_id(&self) -> u64 {
        self.next_id
    }

    #[inline]
    fn idx(&self, price: i64) -> usize {
        (price - self.min_price) as usize
    }

    /// Top `n` non-empty levels per side: (price, qty, order_count).
    pub fn depth(&self, n: usize) -> (Vec<(i64, u64, u32)>, Vec<(i64, u64, u32)>) {
        let mut bids = Vec::with_capacity(n.min(1024));
        let mut p = self.best_bid;
        while p >= self.min_price && bids.len() < n {
            let l = &self.bids[self.idx(p)];
            if l.count > 0 {
                bids.push((p, l.qty, l.count));
            }
            p -= 1;
        }
        let mut asks = Vec::with_capacity(n.min(1024));
        let mut p = self.best_ask;
        while p <= self.max_price && asks.len() < n {
            let l = &self.asks[self.idx(p)];
            if l.count > 0 {
                asks.push((p, l.qty, l.count));
            }
            p += 1;
        }
        (bids, asks)
    }

    /// Orders queued at one price level, in time priority.
    pub fn queue(&self, side: Side, price: i64) -> Vec<RestingOrder> {
        if price < self.min_price || price > self.max_price {
            return vec![];
        }
        let lvl = match side {
            Side::Buy => &self.bids[self.idx(price)],
            Side::Sell => &self.asks[self.idx(price)],
        };
        let mut out = Vec::with_capacity(lvl.count as usize);
        let mut cur = lvl.head;
        while cur != NIL {
            out.push(self.view(cur));
            cur = self.nodes[cur as usize].next;
        }
        out
    }

    fn view(&self, slot: u32) -> RestingOrder {
        let n = &self.nodes[slot as usize];
        RestingOrder {
            id: n.id,
            trader: n.trader,
            side: n.side,
            price: n.price,
            qty: n.qty,
            orig_qty: n.orig_qty,
            seq: n.seq,
        }
    }

    pub fn get_order(&self, id: u64) -> Option<RestingOrder> {
        self.index.get(&id).map(|s| self.view(*s))
    }

    pub fn open_orders(&self, trader: Option<u32>) -> Vec<RestingOrder> {
        let mut v: Vec<RestingOrder> = self
            .index
            .values()
            .map(|s| self.view(*s))
            .filter(|o| trader.map_or(true, |t| o.trader == t))
            .collect();
        v.sort_by_key(|o| o.seq);
        v
    }

    pub fn stops(&self) -> Vec<StopOrder> {
        self.buy_stops.values().chain(self.sell_stops.values()).cloned().collect()
    }

    // ------------------------------------------------------------------ commands
    /// Submit a new order. Returns the assigned id. Events are appended to `ev`.
    #[allow(clippy::too_many_arguments)]
    pub fn submit(
        &mut self,
        side: Side,
        otype: OrderType,
        price: i64,
        qty: u64,
        trader: u32,
        trigger: Option<i64>,
        ev: &mut Vec<Event>,
    ) -> u64 {
        let id = self.next_id;
        self.next_id += 1;
        self.stats.orders_in += 1;
        if qty == 0 {
            self.reject(id, "zero quantity", ev);
            return id;
        }
        let needs_price = !matches!(otype, OrderType::Market | OrderType::StopMarket);
        if needs_price && (price < self.min_price || price > self.max_price) {
            self.reject(id, "price outside band", ev);
            return id;
        }
        match otype {
            OrderType::StopMarket | OrderType::StopLimit => {
                let Some(trig) = trigger else {
                    self.reject(id, "stop order needs a trigger", ev);
                    return id;
                };
                ev.push(Event::Accepted { id, side, otype, price, qty });
                // If the market is already through the trigger, fire immediately.
                let fire_now = match (self.last_price, side) {
                    (Some(lp), Side::Buy) => lp >= trig,
                    (Some(lp), Side::Sell) => lp <= trig,
                    _ => false,
                };
                let stop = StopOrder { id, trader, side, otype, trigger: trig, limit: price, qty };
                if fire_now {
                    ev.push(Event::Triggered { id, last_price: self.last_price.unwrap() });
                    self.execute_stop(stop, ev);
                } else {
                    self.seq += 1;
                    let key = (trig, self.seq);
                    self.stop_index.insert(id, (side, trig, self.seq));
                    match side {
                        Side::Buy => self.buy_stops.insert(key, stop),
                        Side::Sell => self.sell_stops.insert(key, stop),
                    };
                }
            }
            _ => {
                ev.push(Event::Accepted { id, side, otype, price, qty });
                self.process(id, trader, side, otype, price, qty, ev);
            }
        }
        self.release_stops(ev);
        id
    }

    fn reject(&mut self, id: u64, reason: &'static str, ev: &mut Vec<Event>) {
        self.stats.rejects += 1;
        ev.push(Event::Rejected { id, reason });
    }

    #[allow(clippy::too_many_arguments)]
    fn process(
        &mut self,
        id: u64,
        trader: u32,
        side: Side,
        otype: OrderType,
        price: i64,
        qty: u64,
        ev: &mut Vec<Event>,
    ) {
        let limit = match otype {
            OrderType::Market | OrderType::StopMarket => None,
            _ => Some(price),
        };
        match otype {
            OrderType::PostOnly => {
                let crosses = match side {
                    Side::Buy => self.best_ask().is_some_and(|a| price >= a),
                    Side::Sell => self.best_bid().is_some_and(|b| price <= b),
                };
                if crosses {
                    self.reject(id, "post-only would cross", ev);
                    return;
                }
            }
            OrderType::Fok => {
                if self.available(side, price, trader) < qty {
                    self.stats.cancels += 1;
                    ev.push(Event::Cancelled { id, remaining: qty, reason: "fok not fillable" });
                    return;
                }
            }
            _ => {}
        }
        let mut remaining = qty;
        self.match_incoming(id, trader, side, limit, &mut remaining, ev);
        if remaining == 0 {
            return;
        }
        match otype {
            OrderType::Limit | OrderType::PostOnly | OrderType::StopLimit => {
                self.rest(id, trader, side, price, remaining, qty);
                ev.push(Event::Rested { id, side, price, qty: remaining });
            }
            _ => {
                self.stats.cancels += 1;
                let reason = if matches!(otype, OrderType::Market | OrderType::StopMarket) {
                    "insufficient liquidity"
                } else {
                    "ioc remainder"
                };
                ev.push(Event::Cancelled { id, remaining, reason });
            }
        }
    }

    /// Liquidity available to a taker up to `limit`, excluding the taker's own orders when STP is on.
    fn available(&self, side: Side, limit: i64, trader: u32) -> u64 {
        let mut total = 0u64;
        match side {
            Side::Buy => {
                let mut p = self.best_ask;
                while p <= limit.min(self.max_price) {
                    total += self.level_qty_excl(&self.asks[self.idx(p)], trader);
                    p += 1;
                }
            }
            Side::Sell => {
                let mut p = self.best_bid;
                while p >= limit.max(self.min_price) {
                    total += self.level_qty_excl(&self.bids[self.idx(p)], trader);
                    p -= 1;
                }
            }
        }
        total
    }

    fn level_qty_excl(&self, l: &Level, trader: u32) -> u64 {
        if !self.stp || l.count == 0 {
            return l.qty;
        }
        let mut q = l.qty;
        let mut cur = l.head;
        while cur != NIL {
            let n = &self.nodes[cur as usize];
            if n.trader == trader {
                q -= n.qty;
            }
            cur = n.next;
        }
        q
    }

    fn match_incoming(
        &mut self,
        taker: u64,
        trader: u32,
        side: Side,
        limit: Option<i64>,
        remaining: &mut u64,
        ev: &mut Vec<Event>,
    ) {
        while *remaining > 0 {
            let px = match side {
                Side::Buy => {
                    if self.best_ask > self.max_price || limit.is_some_and(|l| self.best_ask > l) {
                        break;
                    }
                    self.best_ask
                }
                Side::Sell => {
                    if self.best_bid < self.min_price || limit.is_some_and(|l| self.best_bid < l) {
                        break;
                    }
                    self.best_bid
                }
            };
            let li = self.idx(px);
            let maker_side = side.opposite();
            loop {
                if *remaining == 0 {
                    break;
                }
                let head = match maker_side {
                    Side::Buy => self.bids[li].head,
                    Side::Sell => self.asks[li].head,
                };
                if head == NIL {
                    break;
                }
                let (maker_id, maker_trader, maker_qty) = {
                    let n = &self.nodes[head as usize];
                    (n.id, n.trader, n.qty)
                };
                if self.stp && maker_trader == trader {
                    self.remove_slot(head);
                    self.stats.cancels += 1;
                    ev.push(Event::Cancelled { id: maker_id, remaining: maker_qty, reason: "self-trade prevention" });
                    continue;
                }
                let fill = maker_qty.min(*remaining);
                *remaining -= fill;
                self.stats.trades += 1;
                self.stats.volume += fill;
                self.stats.notional += (fill as i128) * (px as i128);
                ev.push(Event::Trade {
                    taker,
                    maker: maker_id,
                    taker_trader: trader,
                    maker_trader,
                    taker_side: side,
                    price: px,
                    qty: fill,
                });
                self.last_price = Some(px);
                if fill == maker_qty {
                    self.remove_slot(head);
                } else {
                    self.nodes[head as usize].qty -= fill;
                    match maker_side {
                        Side::Buy => self.bids[li].qty -= fill,
                        Side::Sell => self.asks[li].qty -= fill,
                    }
                }
            }
            // remove_slot keeps best_* up to date when a level empties
            let still_here = match maker_side {
                Side::Buy => self.bids[li].count > 0,
                Side::Sell => self.asks[li].count > 0,
            };
            if still_here && *remaining > 0 {
                // Can only happen if the level holds nothing we may trade with — unreachable
                // because STP orders are removed above; guard against infinite loops anyway.
                break;
            }
        }
    }

    fn alloc(&mut self, node: Node) -> u32 {
        if let Some(s) = self.free.pop() {
            self.nodes[s as usize] = node;
            s
        } else {
            self.nodes.push(node);
            (self.nodes.len() - 1) as u32
        }
    }

    fn rest(&mut self, id: u64, trader: u32, side: Side, price: i64, qty: u64, orig_qty: u64) {
        self.seq += 1;
        let li = self.idx(price);
        let slot = self.alloc(Node { id, trader, side, price, qty, orig_qty, seq: self.seq, prev: NIL, next: NIL });
        let lvl = match side {
            Side::Buy => &mut self.bids[li],
            Side::Sell => &mut self.asks[li],
        };
        let tail = lvl.tail;
        lvl.tail = slot;
        if tail == NIL {
            lvl.head = slot;
        }
        lvl.qty += qty;
        lvl.count += 1;
        if tail != NIL {
            self.nodes[tail as usize].next = slot;
            self.nodes[slot as usize].prev = tail;
        }
        self.index.insert(id, slot);
        match side {
            Side::Buy if price > self.best_bid => self.best_bid = price,
            Side::Sell if price < self.best_ask => self.best_ask = price,
            _ => {}
        }
    }

    /// Unlink a resting node, free its slot and fix the best price if its level emptied.
    fn remove_slot(&mut self, slot: u32) {
        let (id, side, price, qty, prev, next) = {
            let n = &self.nodes[slot as usize];
            (n.id, n.side, n.price, n.qty, n.prev, n.next)
        };
        if prev != NIL {
            self.nodes[prev as usize].next = next;
        }
        if next != NIL {
            self.nodes[next as usize].prev = prev;
        }
        let li = self.idx(price);
        let lvl = match side {
            Side::Buy => &mut self.bids[li],
            Side::Sell => &mut self.asks[li],
        };
        if lvl.head == slot {
            lvl.head = next;
        }
        if lvl.tail == slot {
            lvl.tail = prev;
        }
        lvl.qty -= qty;
        lvl.count -= 1;
        let emptied = lvl.count == 0;
        self.index.remove(&id);
        self.free.push(slot);
        if emptied {
            match side {
                Side::Buy if price == self.best_bid => {
                    while self.best_bid >= self.min_price && self.bids[self.idx(self.best_bid)].count == 0 {
                        self.best_bid -= 1;
                    }
                }
                Side::Sell if price == self.best_ask => {
                    while self.best_ask <= self.max_price && self.asks[self.idx(self.best_ask)].count == 0 {
                        self.best_ask += 1;
                    }
                }
                _ => {}
            }
        }
    }

    pub fn cancel(&mut self, id: u64, ev: &mut Vec<Event>) -> bool {
        if let Some(slot) = self.index.get(&id).copied() {
            let remaining = self.nodes[slot as usize].qty;
            self.remove_slot(slot);
            self.stats.cancels += 1;
            ev.push(Event::Cancelled { id, remaining, reason: "user cancel" });
            return true;
        }
        if let Some((side, trig, seq)) = self.stop_index.remove(&id) {
            let s = match side {
                Side::Buy => self.buy_stops.remove(&(trig, seq)),
                Side::Sell => self.sell_stops.remove(&(trig, seq)),
            };
            self.stats.cancels += 1;
            ev.push(Event::Cancelled { id, remaining: s.map_or(0, |s| s.qty), reason: "user cancel" });
            return true;
        }
        ev.push(Event::Rejected { id, reason: "unknown order id" });
        false
    }

    /// Modify a resting order. Reducing quantity at the same price keeps queue priority;
    /// a price change or quantity increase is cancel/replace and goes to the back of the queue
    /// (and may trade immediately if the new price crosses).
    pub fn modify(&mut self, id: u64, new_price: i64, new_qty: u64, ev: &mut Vec<Event>) -> bool {
        let Some(slot) = self.index.get(&id).copied() else {
            ev.push(Event::Rejected { id, reason: "unknown order id" });
            return false;
        };
        if new_qty == 0 {
            return self.cancel(id, ev);
        }
        if new_price < self.min_price || new_price > self.max_price {
            ev.push(Event::Rejected { id, reason: "price outside band" });
            return false;
        }
        let (side, price, qty, trader, orig) = {
            let n = &self.nodes[slot as usize];
            (n.side, n.price, n.qty, n.trader, n.orig_qty)
        };
        if new_price == price && new_qty <= qty {
            let delta = qty - new_qty;
            self.nodes[slot as usize].qty = new_qty;
            let li = self.idx(price);
            match side {
                Side::Buy => self.bids[li].qty -= delta,
                Side::Sell => self.asks[li].qty -= delta,
            }
            ev.push(Event::Modified { id, price, qty: new_qty, kept_priority: true });
            return true;
        }
        self.remove_slot(slot);
        ev.push(Event::Modified { id, price: new_price, qty: new_qty, kept_priority: false });
        let mut remaining = new_qty;
        self.match_incoming(id, trader, side, Some(new_price), &mut remaining, ev);
        if remaining > 0 {
            self.rest(id, trader, side, new_price, remaining, orig.max(new_qty));
            ev.push(Event::Rested { id, side, price: new_price, qty: remaining });
        }
        self.release_stops(ev);
        true
    }

    fn execute_stop(&mut self, s: StopOrder, ev: &mut Vec<Event>) {
        let ot = if s.otype == OrderType::StopMarket { OrderType::StopMarket } else { OrderType::StopLimit };
        self.process(s.id, s.trader, s.side, ot, s.limit, s.qty, ev);
    }

    /// Release stops whose trigger has been touched by the last trade; repeat until stable.
    fn release_stops(&mut self, ev: &mut Vec<Event>) {
        if self.stop_index.is_empty() {
            return;
        }
        loop {
            let Some(lp) = self.last_price else { return };
            let next = if let Some((&k, _)) = self.buy_stops.iter().next().filter(|(k, _)| k.0 <= lp) {
                self.buy_stops.remove(&k)
            } else if let Some((&k, _)) = self.sell_stops.iter().next_back().filter(|(k, _)| k.0 >= lp) {
                self.sell_stops.remove(&k)
            } else {
                None
            };
            let Some(stop) = next else { return };
            self.stop_index.remove(&stop.id);
            ev.push(Event::Triggered { id: stop.id, last_price: lp });
            self.execute_stop(stop, ev);
        }
    }

    /// Internal consistency check used by tests: level aggregates match their queues,
    /// cached best prices are correct and the book is not crossed.
    pub fn check_invariants(&self) -> Result<(), String> {
        for (side, levels) in [(Side::Buy, &self.bids), (Side::Sell, &self.asks)] {
            for (i, l) in levels.iter().enumerate() {
                let mut q = 0;
                let mut c = 0;
                let mut cur = l.head;
                let mut last_seq = 0;
                while cur != NIL {
                    let n = &self.nodes[cur as usize];
                    if n.seq < last_seq {
                        return Err(format!("time priority broken at {:?} {}", side, i));
                    }
                    last_seq = n.seq;
                    q += n.qty;
                    c += 1;
                    cur = n.next;
                }
                if q != l.qty || c != l.count {
                    return Err(format!("level aggregate mismatch {:?} idx {}", side, i));
                }
            }
        }
        let true_bb = (self.min_price..=self.max_price).rev().find(|p| self.bids[self.idx(*p)].count > 0);
        let true_ba = (self.min_price..=self.max_price).find(|p| self.asks[self.idx(*p)].count > 0);
        if true_bb != self.best_bid() || true_ba != self.best_ask() {
            return Err(format!("cached best wrong: {:?}/{:?} vs {:?}/{:?}", self.best_bid(), self.best_ask(), true_bb, true_ba));
        }
        if let (Some(b), Some(a)) = (true_bb, true_ba) {
            if b >= a {
                return Err(format!("crossed book {} >= {}", b, a));
            }
        }
        Ok(())
    }
}
