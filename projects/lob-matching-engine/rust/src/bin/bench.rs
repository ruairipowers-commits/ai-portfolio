//! Native benchmark: `cargo run --release --bin lob-bench -- [n_orders] [prefill] [--json]`

use lob_engine::flow::{run_benchmark, BenchConfig};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let json = args.iter().any(|a| a == "--json");
    let nums: Vec<usize> = args.iter().filter_map(|a| a.replace('_', "").parse().ok()).collect();
    let mut cfg = BenchConfig::default();
    if let Some(n) = nums.first() {
        cfg.n_orders = *n;
    }
    if let Some(p) = nums.get(1) {
        cfg.prefill = *p;
    }
    let r = run_benchmark(&cfg);
    if json {
        let pcts: Vec<String> = r.percentiles.iter().map(|(q, v)| format!("\"p{}\":{}", q * 100.0, v)).collect();
        println!(
            "{{\"n_ops\":{},\"throughput_ops\":{:.0},\"mean_ns\":{:.1},{},\"trades\":{},\"timer_overhead_ns\":{}}}",
            r.n_ops,
            r.throughput_ops,
            r.mean_ns,
            pcts.join(","),
            r.trades,
            r.timer_overhead_ns
        );
        return;
    }
    println!("ops            : {}", r.n_ops);
    println!("throughput     : {:.2} M ops/s (untimed loop)", r.throughput_ops / 1e6);
    println!("mean latency   : {:.0} ns (incl. ~{:.0} ns timer overhead)", r.mean_ns, r.timer_overhead_ns);
    for (q, v) in &r.percentiles {
        let label = if *q >= 1.0 { "max".to_string() } else { format!("p{}", q * 100.0) };
        println!("{:<15}: {} ns", label, v);
    }
    println!("trades         : {}  volume: {}", r.trades, r.volume);
    println!("resting orders : {}  levels bid/ask: {}/{}", r.resting_orders, r.levels_bid, r.levels_ask);
    println!("\nper command kind:");
    println!("{:<10} {:>9} {:>8} {:>8} {:>8} {:>9} {:>9}", "kind", "count", "mean", "p50", "p99", "p99.9", "max");
    for k in &r.per_kind {
        println!("{:<10} {:>9} {:>8.0} {:>8} {:>8} {:>9} {:>9}", k.kind, k.count, k.mean_ns, k.p50, k.p99, k.p999, k.max);
    }
}
