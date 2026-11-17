use lob_engine::flow::{run_simulation, Cmd, FlowGen, FlowParams, SimConfig};
use lob_engine::{Event, OrderBook, OrderType::*, Side::*};

fn trades(ev: &[Event]) -> Vec<(u64, i64, u64)> {
    ev.iter()
        .filter_map(|e| match e {
            Event::Trade { maker, price, qty, .. } => Some((*maker, *price, *qty)),
            _ => None,
        })
        .collect()
}

fn book() -> OrderBook {
    OrderBook::new(1, 1000)
}

#[test]
fn price_then_time_priority() {
    let mut b = book();
    let mut ev = vec![];
    let a1 = b.submit(Sell, Limit, 101, 5, 1, None, &mut ev);
    let a2 = b.submit(Sell, Limit, 100, 5, 2, None, &mut ev);
    let a3 = b.submit(Sell, Limit, 100, 5, 3, None, &mut ev);
    ev.clear();
    b.submit(Buy, Limit, 101, 12, 9, None, &mut ev);
    // best price first (100), FIFO within the level (a2 before a3), then 101
    assert_eq!(trades(&ev), vec![(a2, 100, 5), (a3, 100, 5), (a1, 101, 2)]);
    assert_eq!(b.best_ask(), Some(101));
    b.check_invariants().unwrap();
}

#[test]
fn limit_rests_and_trades_at_maker_price() {
    let mut b = book();
    let mut ev = vec![];
    b.submit(Buy, Limit, 99, 10, 1, None, &mut ev);
    ev.clear();
    b.submit(Sell, Limit, 95, 4, 2, None, &mut ev);
    assert_eq!(trades(&ev)[0].1, 99, "price improvement goes to the taker");
    assert_eq!(b.best_bid(), Some(99));
    assert_eq!(b.depth(5).0[0].1, 6);
}

#[test]
fn market_ioc_fok_postonly() {
    let mut b = book();
    let mut ev = vec![];
    b.submit(Sell, Limit, 100, 5, 1, None, &mut ev);
    b.submit(Sell, Limit, 102, 5, 1, None, &mut ev);
    ev.clear();
    // FOK for 8 up to 101 can only get 5 -> killed, book untouched
    b.submit(Buy, Fok, 101, 8, 2, None, &mut ev);
    assert!(trades(&ev).is_empty());
    assert!(ev.iter().any(|e| matches!(e, Event::Cancelled { reason: "fok not fillable", .. })));
    // IOC for 8 up to 101 gets 5, rest cancelled, nothing rests
    ev.clear();
    b.submit(Buy, Ioc, 101, 8, 2, None, &mut ev);
    assert_eq!(trades(&ev).iter().map(|t| t.2).sum::<u64>(), 5);
    assert_eq!(b.best_bid(), None);
    // post-only that would cross is rejected
    ev.clear();
    b.submit(Buy, PostOnly, 102, 1, 2, None, &mut ev);
    assert!(matches!(ev.last(), Some(Event::Rejected { .. })));
    // market sweeps remaining and cancels the rest
    ev.clear();
    b.submit(Buy, Market, 0, 50, 2, None, &mut ev);
    assert_eq!(trades(&ev).iter().map(|t| t.2).sum::<u64>(), 5);
    assert_eq!(b.best_ask(), None);
    b.check_invariants().unwrap();
}

#[test]
fn cancel_and_modify_priority() {
    let mut b = book();
    let mut ev = vec![];
    let x = b.submit(Buy, Limit, 50, 10, 1, None, &mut ev);
    let y = b.submit(Buy, Limit, 50, 10, 2, None, &mut ev);
    // size-down keeps priority
    b.modify(x, 50, 4, &mut ev);
    assert_eq!(b.queue(Buy, 50)[0].id, x);
    // size-up loses priority
    b.modify(x, 50, 20, &mut ev);
    assert_eq!(b.queue(Buy, 50)[0].id, y);
    assert!(b.cancel(y, &mut ev));
    assert!(!b.cancel(y, &mut ev));
    assert_eq!(b.depth(5).0, vec![(50, 20, 1)]);
    b.check_invariants().unwrap();
}

#[test]
fn stop_orders_trigger_and_cascade() {
    let mut b = book();
    let mut ev = vec![];
    for p in 100..106 {
        b.submit(Sell, Limit, p, 5, 1, None, &mut ev);
    }
    b.submit(Buy, Limit, 99, 5, 1, None, &mut ev);
    let s1 = b.submit(Buy, StopMarket, 0, 5, 2, Some(101), &mut ev);
    let s2 = b.submit(Buy, StopMarket, 0, 5, 3, Some(102), &mut ev);
    ev.clear();
    // Lift 100 and 101 -> last=101 -> s1 fires, buys 102 -> s2 fires, buys 103
    b.submit(Buy, Market, 0, 10, 4, None, &mut ev);
    let trig: Vec<u64> = ev.iter().filter_map(|e| if let Event::Triggered { id, .. } = e { Some(*id) } else { None }).collect();
    assert_eq!(trig, vec![s1, s2]);
    assert_eq!(b.last_price(), Some(103));
    assert_eq!(b.stop_count(), 0);
    b.check_invariants().unwrap();
}

#[test]
fn self_trade_prevention() {
    let mut b = book();
    let mut ev = vec![];
    b.submit(Sell, Limit, 100, 5, 7, None, &mut ev);
    b.submit(Sell, Limit, 100, 5, 8, None, &mut ev);
    ev.clear();
    b.submit(Buy, Limit, 100, 5, 7, None, &mut ev);
    assert!(ev.iter().any(|e| matches!(e, Event::Cancelled { reason: "self-trade prevention", .. })));
    assert_eq!(trades(&ev).len(), 1);
    assert_eq!(b.best_ask(), None);
}

#[test]
fn randomized_invariants_hold() {
    let band = (5_000, 15_000);
    let mut b = OrderBook::new(band.0, band.1);
    let mut g = FlowGen::new(FlowParams { seed: 7, ..Default::default() }, band, 1);
    let mut ev = vec![];
    for _ in 0..2_000 {
        g.prefill().apply(&mut b, &mut ev);
    }
    let mut vol_from_events = 0;
    for i in 0..60_000 {
        ev.clear();
        let c: Cmd = g.next(None);
        c.apply(&mut b, &mut ev);
        vol_from_events += trades(&ev).iter().map(|t| t.2).sum::<u64>();
        if i % 5_000 == 0 {
            b.check_invariants().unwrap();
        }
    }
    b.check_invariants().unwrap();
    assert_eq!(vol_from_events, b.stats.volume);
}

#[test]
fn simulation_runs() {
    let cfg = SimConfig {
        steps: 5_000,
        snapshot_every: 50,
        depth_levels: 10,
        prefill: 300,
        band: (5_000, 15_000),
        params: FlowParams::default(),
        shock: Some((2_500, Buy, 500)),
    };
    let (r, b) = run_simulation(&cfg);
    assert_eq!(r.snap_step.len(), 101);
    assert!(!r.trades.is_empty());
    b.check_invariants().unwrap();
}
