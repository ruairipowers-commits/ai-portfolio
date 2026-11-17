import lob_engine as L


def test_roundtrip_and_queries():
    b = L.OrderBook(1, 10_000)
    a, _ = b.submit("sell", "limit", 101, 10, 1)
    _, ev = b.submit("buy", "market", 0, 4, 2)
    assert [e["event"] for e in ev] == ["accepted", "trade"]
    assert b.depth(5)["asks"] == [(101, 6, 1)]
    ok, _ = b.modify(a, 101, 3)
    assert ok and b.queue("sell", 101)[0]["qty"] == 3
    ok, _ = b.cancel(a)
    assert ok and b.best_ask is None
    b.check_invariants()
    assert b.stats()["volume"] == 4


def test_benchmark_and_simulation():
    r = L.benchmark(n_orders=50_000, prefill=1_000)
    assert r["n_ops"] == 50_000 and r["throughput_ops"] > 0
    assert sum(r["hist_counts"]) == 50_000
    d, book = L.simulate(steps=2_000, snapshot_every=100)
    assert len(d["step"]) == 21
    book.check_invariants()
