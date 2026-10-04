"""Puzzle kinds: what each one is, how the offline mock writes one, and how code checks it.

Every kind has
  - `make(rng, difficulty, scenario)`: a procedural draft — this is what the mock "generator model" returns, and how
    the reserve puzzles are built. A real model writes drafts in the same JSON shape (prompts/generator.v1.md).
  - `check(draft)` (formal kinds): an independent proof of the answer from the machine-readable `spec` — counts the
    solutions by brute force and returns them. A puzzle is publishable only with exactly one.
  - `solve(spec, draft_public)`: what the mock "solver model" does. It sees only the public part of the puzzle.
    For sandbox kinds it returns *code* (written differently from the generator's reference code) that is run in the
    sandbox, the same as a real solver's code would be.

`scenario` lets evals and the operator demo force known-bad drafts: two_answers, wrong_key, nondeterministic,
bad_license, pickle, sandbox_escape, offensive, copyrighted.
"""
from __future__ import annotations

import inspect
import itertools
import math
import random
from functools import lru_cache
from pathlib import Path
from textwrap import dedent

DATA = Path(__file__).resolve().parent / "data"
NAMES = ["Ava", "Ben", "Cal", "Dee", "Eli", "Fay", "Gus"]
LEVELS = {"easy": 0, "medium": 1, "hard": 2}


@lru_cache(maxsize=1)
def words() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in (DATA / "words.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            cat, ws = line.split(":", 1)
            out[cat.strip()] = ws.split()
    return out


def all_words() -> set[str]:
    return {w for ws in words().values() for w in ws}


def base(track, kind, difficulty, title, statement, answer, answer_type="text", **kw) -> dict:
    d = {"track": track, "kind": kind, "difficulty": difficulty, "title": title, "statement": inspect.cleandoc(statement),
         "answer": str(answer), "answer_type": answer_type, "decimals": None, "accepted_forms": [str(answer)],
         "answer_format": "", "learning_objective": "", "skill_tags": [], "starter": "", "solution": "",
         "reference_code": "", "assets": [], "spec": {}}
    d.update(kw)
    return d


def _wrong_key(d: dict, rng: random.Random) -> dict:
    """A plausible but wrong key (what a careless generator produces)."""
    a = d["answer"]
    if d["answer_type"] == "int":
        a = str(int(a) + rng.choice([-2, -1, 1, 3]))
    elif d["answer_type"] == "float":
        a = f"{float(a) * 1.07 + 0.013:.{d.get('decimals') or 3}f}"
    elif d["kind"] in ("cipher", "anagram"):
        a = rng.choice([w for w in all_words() if len(w) == len(a) and w != a] or ["wrong"])
    else:
        parts = [p.strip() for p in a.split(",")]
        a = ", ".join(reversed(parts)) if len(parts) > 1 else (NAMES[0] if a != NAMES[0] else NAMES[1])
    d = dict(d, answer=a, accepted_forms=[a])
    return d


# ================================================================ logic: knights and knaves
def _kk_truth(st: dict, assign: dict) -> bool:
    t = st["type"]
    if t == "is":
        return assign[st["a"]] == (st["role"] == "knight")
    if t == "same":
        return assign[st["a"]] == assign[st["b"]]
    if t == "count":
        return sum(assign.values()) == st["k"]
    if t == "or":                       # "A is a knave or B is a knight"
        return (not assign[st["a"]]) or assign[st["b"]]
    raise ValueError(t)


def _kk_text(st: dict) -> str:
    t = st["type"]
    if t == "is":
        return f"{st['a']} is a {st['role']}."
    if t == "same":
        return f"{st['a']} and {st['b']} are the same type."
    if t == "count":
        return f"Exactly {st['k']} of us {'is a knight' if st['k'] == 1 else 'are knights'}."
    return f"{st['a']} is a knave or {st['b']} is a knight."


def kk_solutions(spec: dict) -> list[str]:
    people = spec["people"]
    sols = []
    for bits in itertools.product([True, False], repeat=len(people)):
        assign = dict(zip(people, bits))
        if all(_kk_truth(s, assign) == assign[s["speaker"]] for s in spec["statements"]):
            knights = sorted(p for p in people if assign[p])
            sols.append(", ".join(knights) if knights else "none")
    return sols


def make_knights_knaves(rng, difficulty, scenario=None):
    n = 3 + LEVELS[difficulty]
    people = NAMES[:n]
    want = 2 if scenario == "two_answers" else 1
    for _ in range(2000):
        assign = {p: rng.random() < 0.5 for p in people}
        stmts = []
        for sp in people:
            for _ in range(50):
                others = [p for p in people if p != sp]
                t = rng.choice(["is", "is", "same", "count", "or"])
                a, b = rng.sample(others, 2) if len(others) >= 2 else (others[0], sp)
                st = {"speaker": sp, "type": t, "a": a, "b": b, "role": rng.choice(["knight", "knave"]),
                      "k": rng.randint(0, n)}
                if _kk_truth(st, assign) == assign[sp]:
                    stmts.append({k: v for k, v in st.items() if k in {"is": ("speaker", "type", "a", "role"),
                                  "same": ("speaker", "type", "a", "b"), "count": ("speaker", "type", "k"),
                                  "or": ("speaker", "type", "a", "b")}[t]})
                    break
        spec = {"people": people, "statements": stmts}
        sols = kk_solutions(spec)
        if len(sols) == want:
            break
    knights = sorted(p for p in people if assign[p])
    answer = ", ".join(knights) if knights else "none"
    quotes = ("\n" + " " * 16).join(f"- **{s['speaker']}** says: “{_kk_text(s)}”" for s in stmts)
    forms = [answer] + ([" and ".join(knights)] if len(knights) > 1 else [])
    if 1 < len(knights) <= 3:
        forms += [", ".join(p) for p in itertools.permutations(knights)] + [" and ".join(p) for p in itertools.permutations(knights)]
    return base("logic", "knights-knaves", difficulty, f"Knights and knaves: {n} islanders",
                f"""On this island knights always tell the truth and knaves always lie. You meet {', '.join(people[:-1])}
                and {people[-1]}.

                {quotes}

                Who are the knights?""",
                answer, accepted_forms=sorted(set(forms)), spec=spec,
                answer_format="the knights' names, separated by commas (or 'none')",
                solution="Try every knight/knave assignment and keep the ones where each knight's statement is true "
                         "and each knave's is false; exactly one assignment survives.")


# ================================================================ logic: ordering
def _ord_ok(c: dict, order: list[str]) -> bool:
    pos = {p: i for i, p in enumerate(order)}
    t = c["type"]
    if t == "before":
        return pos[c["a"]] < pos[c["b"]]
    if t == "right_after":
        return pos[c["a"]] == pos[c["b"]] + 1
    if t == "at":
        return pos[c["a"]] == c["i"] - 1
    if t == "not_at":
        return pos[c["a"]] != c["i"] - 1
    raise ValueError(t)


def _ord_text(c: dict, n: int) -> str:
    t = c["type"]
    if t == "before":
        return f"{c['a']} finished before {c['b']}."
    if t == "right_after":
        return f"{c['a']} finished immediately after {c['b']}."
    place = {1: "first", n: "last"}.get(c["i"], f"in position {c['i']}")
    return f"{c['a']} finished {place}." if t == "at" else f"{c['a']} did not finish {place}."


def ordering_solutions(spec: dict) -> list[str]:
    return [", ".join(o) for o in itertools.permutations(spec["people"])
            if all(_ord_ok(c, list(o)) for c in spec["clues"])]


def make_ordering(rng, difficulty, scenario=None):
    n = 4 + LEVELS[difficulty]
    people = NAMES[:n]
    order = people[:]
    rng.shuffle(order)
    clues: list[dict] = []
    want = 2 if scenario == "two_answers" else 1
    for _ in range(400):
        sols = ordering_solutions({"people": people, "clues": clues})
        if len(sols) == want or (want == 2 and len(sols) < 2):
            break
        a, b = rng.sample(people, 2)
        t = rng.choice(["before", "before", "right_after", "not_at", "at"] if difficulty != "easy" else ["before", "at", "not_at"])
        c = {"type": t, "a": a, "b": b, "i": rng.randint(1, n)}
        c = {k: v for k, v in c.items() if k in {"before": ("type", "a", "b"), "right_after": ("type", "a", "b"),
                                                  "at": ("type", "a", "i"), "not_at": ("type", "a", "i")}[t]}
        if _ord_ok(c, order) and c not in clues and len(ordering_solutions({"people": people, "clues": clues + [c]})) >= want:
            clues.append(c)
    spec = {"people": people, "clues": clues}
    answer = ", ".join(order)
    lines = ("\n" + " " * 16).join(f"- {_ord_text(c, n)}" for c in clues)
    return base("logic", "ordering", difficulty, f"Who finished where? ({n} runners)",
                f"""{', '.join(people[:-1])} and {people[-1]} ran a race. There were no ties.

                {lines}

                What was the finishing order, first to last?""",
                answer, spec=spec, answer_format="names first to last, separated by commas",
                solution="Fix the absolute clues first, then place the before/after pairs; only one order fits every clue.")


# ================================================================ word: Caesar cipher
def shift(word: str, k: int) -> str:
    return "".join(chr((ord(c) - 97 + k) % 26 + 97) if c.isalpha() else c for c in word.lower())


def cipher_solutions(spec: dict) -> list[str]:
    vocab = all_words()
    out = []
    for k in range(1, 26):
        plain = shift(spec["ciphertext"], -k)
        if all(w in vocab for w in plain.split()):
            out.append(plain)
    return out


def make_cipher(rng, difficulty, scenario=None):
    cat = rng.choice(["markets", "data", "ai", "animals"] if difficulty != "easy" else ["animals", "fruits"])
    for _ in range(200):
        ws = rng.sample(words()[cat], 1 if difficulty != "hard" else 2)
        plain = " ".join(ws)
        k = rng.randint(1, 25)
        spec = {"ciphertext": shift(plain, k).upper(), "category": cat, "words": len(ws)}
        if len(cipher_solutions({"ciphertext": spec["ciphertext"]})) == 1:
            break
    hint = f"Each letter was shifted the same number of places along the alphabet (wrapping Z → A)."
    if difficulty == "easy":
        hint += f" The shift is between 1 and 25."
    return base("word", "cipher", difficulty, "Shifted message",
                f"""This message was encrypted with a Caesar cipher. {hint} The plain text is
                {'a word' if spec['words'] == 1 else 'two words'} from the category **{cat}**.

                `{spec['ciphertext']}`

                What is the plain text?""",
                plain, spec=spec, answer_format="the plain-text word(s), lower or upper case",
                solution=f"Try all 25 shifts; shifting back by {k} gives English: {plain}.",
                skill_tags=["ciphers"])


# ================================================================ word: anagram
def anagram_solutions(spec: dict) -> list[str]:
    key = "".join(sorted(spec["letters"].lower()))
    return sorted(w for w in all_words() if "".join(sorted(w)) == key)


def make_anagram(rng, difficulty, scenario=None):
    if scenario == "two_answers":
        word = rng.choice(["listen", "earth", "night", "stale", "below", "dusty", "cider", "angel", "lemon"])
        cat = "general"
    else:
        cat = rng.choice(["fruits", "animals"] if difficulty == "easy" else ["markets", "data", "ai", "animals"])
        pool = [w for w in words()[cat] if (len(w) <= 6) == (difficulty == "easy")] or words()[cat]
        for _ in range(100):
            word = rng.choice(pool)
            if anagram_solutions({"letters": word}) == [word]:
                break
    letters = list(word)
    while "".join(letters) == word:
        rng.shuffle(letters)
    spec = {"letters": "".join(letters).upper(), "category": cat}
    return base("word", "anagram", difficulty, "Unscramble",
                f"""Rearrange **{spec['letters']}** into a single word{'' if cat == 'general' else f' from the category **{cat}**'}.""",
                word, spec=spec, answer_format="one word",
                solution=f"The letters {spec['letters']} rearrange to {word}.")


# ================================================================ numbers: sequences
def seq_predictions(terms: list[int]) -> dict[str, int]:
    """Next term according to every rule family that fits all the shown terms exactly."""
    out: dict[str, int] = {}
    d = [b - a for a, b in zip(terms, terms[1:])]
    if len(set(d)) == 1:
        out["arithmetic"] = terms[-1] + d[0]
    if all(t != 0 for t in terms) and len(terms) >= 3:
        r = terms[1] / terms[0]
        if all(math.isclose(b, a * r) for a, b in zip(terms, terms[1:])) and float(terms[-1] * r).is_integer():
            out["geometric"] = int(terms[-1] * r)
    if len(terms) >= 3:
        dd = [b - a for a, b in zip(d, d[1:])]
        if len(set(dd)) == 1:
            out["quadratic"] = terms[-1] + d[-1] + dd[0]
        if all(terms[i] == terms[i - 1] + terms[i - 2] for i in range(2, len(terms))):
            out["fibonacci"] = terms[-1] + terms[-2]
        x0, x1, x2 = terms[:3]
        if x1 != x0:                                  # x_{n+1} = a·x_n + b fitted on the first three terms
            a = (x2 - x1) / (x1 - x0)
            b = x1 - a * x0
            if a.is_integer() and b.is_integer() and all(terms[i + 1] == a * terms[i] + b for i in range(len(terms) - 1)):
                out["linear-recurrence"] = int(a * terms[-1] + b)
    return out


def sequence_solutions(spec: dict) -> list[str]:
    return sorted({str(v) for v in seq_predictions(spec["terms"]).values()})


def make_sequence(rng, difficulty, scenario=None):
    if scenario == "two_answers":
        terms, fam = [1, 2, 4], "ambiguous"
    else:
        fam = rng.choice({"easy": ["arithmetic", "geometric"], "medium": ["quadratic", "fibonacci"],
                          "hard": ["linear-recurrence", "quadratic"]}[difficulty])
        for _ in range(200):
            a = rng.randint(1, 9)
            if fam == "arithmetic":
                dlt = rng.randint(2, 12)
                terms = [a + i * dlt for i in range(7)]
            elif fam == "geometric":
                r = rng.choice([2, 3, -2])
                terms = [a * r ** i for i in range(6)]
            elif fam == "quadratic":
                p, q = rng.randint(1, 4), rng.randint(-5, 6)
                terms = [p * i * i + q * i + a for i in range(1, 7)]
            elif fam == "fibonacci":
                terms = [a, rng.randint(1, 9)]
                while len(terms) < 7:
                    terms.append(terms[-1] + terms[-2])
            else:
                m, c = rng.choice([2, 3]), rng.randint(-4, 5)
                terms = [a]
                while len(terms) < 6:
                    terms.append(m * terms[-1] + c)
            preds = seq_predictions(terms)
            if len(set(preds.values())) == 1:
                break
    preds = seq_predictions(terms)
    answer = preds.get(fam, next(iter(preds.values()), 0))
    shown = ", ".join(map(str, terms))
    return base("numbers", "sequence", difficulty, "What comes next?",
                f"""What is the next number in the sequence?

                **{shown}, …**""",
                answer, "int", spec={"terms": terms}, answer_format="an integer",
                solution=f"The sequence follows a {fam} rule; the next term is {answer}.",
                skill_tags=["pattern recognition"])


# ================================================================ numbers: combinatorics
def _div_count(n, a, b, c):
    return sum(1 for x in range(1, n + 1) if (x % a == 0 or x % b == 0) and x % c != 0)


def _no_two_ones(n):
    return sum(1 for bits in itertools.product("01", repeat=n) if "11" not in "".join(bits))


def _coin_ways(amount, coins):
    ways = [1] + [0] * amount
    for c in coins:
        for v in range(c, amount + 1):
            ways[v] += ways[v - c]
    return ways[amount]


def combinatorics_solutions(spec: dict) -> list[str]:
    t, p = spec["type"], spec["params"]
    if t == "divisible":
        return [str(_div_count(**p))]
    if t == "binary":
        return [str(_no_two_ones(**p))]
    return [str(_coin_ways(p["amount"], p["coins"]))]


def make_combinatorics(rng, difficulty, scenario=None):
    t = rng.choice(["divisible", "binary", "coins"])
    if t == "divisible":
        a, b = rng.sample([2, 3, 5, 7], 2)
        c = rng.choice([x for x in [4, 6, 9, 10, 11] if x not in (a, b)])
        p = {"n": [100, 500, 2000][LEVELS[difficulty]], "a": a, "b": b, "c": c}
        text = (f"How many whole numbers from 1 to {p['n']} are divisible by {a} or {b}, but not by {c}?")
        sol = "Count with inclusion–exclusion, or loop over the range and test each number."
    elif t == "binary":
        p = {"n": [6, 10, 16][LEVELS[difficulty]]}
        text = f"How many strings of {p['n']} binary digits (0s and 1s) contain no two 1s next to each other?"
        sol = "The counts follow the Fibonacci numbers: strings of length n end in 0 (any valid n−1 string) or in 01."
    else:
        coins = sorted(rng.sample([1, 2, 5, 10, 20, 25, 50], 3 + LEVELS[difficulty] // 2))
        if 1 not in coins:
            coins = [1] + coins[1:]
        p = {"amount": [20, 60, 150][LEVELS[difficulty]], "coins": coins}
        text = (f"Using coins worth {', '.join(map(str, coins))} cents (as many of each as you like), how many "
                f"different ways can you make {p['amount']} cents? Order doesn't matter.")
        sol = "Dynamic programming over coin values: ways[v] += ways[v − coin], one coin type at a time."
    spec = {"type": t, "params": p}
    ans = combinatorics_solutions(spec)[0]
    return base("numbers", "combinatorics", difficulty, "Count them", text, ans, "int", spec=spec,
                answer_format="an integer", solution=sol, skill_tags=["counting"])


# ================================================================ coding: what does it print?
def make_python_output(rng, difficulty, scenario=None):
    t = rng.choice(["mutable_default", "late_binding", "floor_mod", "slicing", "generator", "set_comp"])
    if t == "mutable_default":
        a, b, c = rng.sample(range(1, 9), 3)
        code = f"""\
            def collect(x, seen=[]):
                seen.append(x)
                return seen

            first = collect({a})
            second = collect({b})
            third = collect({c}, [])
            print(len(first) + len(second) * 10 + len(third) * 100)"""
        obj = "A default argument is evaluated once, when the function is defined, so a mutable default is shared between calls."
        tags = ["python", "functions", "mutable defaults"]
    elif t == "late_binding":
        n, k = rng.randint(3, 6), rng.randint(2, 5)
        code = f"""\
            funcs = [lambda: i * {k} for i in range({n})]
            print(sum(f() for f in funcs))"""
        obj = "Closures look up variables when they run, not when they are made (late binding)."
        tags = ["python", "closures"]
    elif t == "floor_mod":
        a, b = rng.randint(7, 40), rng.randint(3, 9)
        code = f"""\
            a, b = -{a}, {b}
            print(a // b, a % b, int(a / b))"""
        obj = "Python's // rounds towards minus infinity and % takes the divisor's sign; int() truncates towards zero."
        tags = ["python", "integer arithmetic"]
    elif t == "slicing":
        s = rng.choice(["portfolio", "transformer", "arbitrage", "embedding", "dividends"])
        i, j, k = rng.randint(0, 2), rng.randint(5, len(s)), rng.choice([2, -1, 3])
        code = f"""\
            s = "{s}"
            print(s[{i}:{j}:{k}] + "|" + s[::-2])"""
        obj = "Slices are start:stop:step; a negative step walks backwards and swaps the default ends."
        tags = ["python", "strings", "slicing"]
    elif t == "generator":
        n = rng.randint(4, 9)
        code = f"""\
            squares = (x * x for x in range({n}))
            total = sum(squares)
            again = sum(squares)
            print(total, again)"""
        obj = "A generator can be consumed only once; the second pass sees nothing."
        tags = ["python", "generators", "iteration"]
    else:
        a, b, m = rng.randint(0, 10), rng.randint(30, 80), rng.randint(4, 12)
        code = f"""\
            residues = {{x % {m} for x in range({a}, {b}) if x % 3}}
            print(len(residues), max(residues))"""
        obj = "Set comprehensions de-duplicate; the filter `if x % 3` drops multiples of 3 first."
        tags = ["python", "comprehensions", "sets"]
    code = dedent(code)
    out = run_trusted(code).strip()
    atype = "int" if out.lstrip("-").isdigit() else "text"
    return base("coding", "python-output", difficulty, "What does this print?",
                f"""What does this Python 3 program print? Work it out first, then check by running it.

                ```python
{indent(code, 16)}
                ```""",
                out, atype, reference_code=code, learning_objective=obj, skill_tags=tags,
                answer_format="exactly what is printed (one line)" if atype == "text" else "an integer",
                starter="# Predict the output, then run the program to check.\n",
                solution=f"{obj} The program prints {out}.")


def indent(code: str, n: int) -> str:
    return "\n".join(" " * n + line if line else "" for line in code.splitlines())


def run_trusted(code: str) -> str:
    """Run one of *our own* template programs (never model-written code) to compute its output."""
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(compile(code, "<template>", "exec"), {"__name__": "__main__"})
    return buf.getvalue()


# ================================================================ sandbox kinds on bundled / public data
FLOWERS = {"id": "fixture/flowers", "files": ["flowers.csv"]}
MLP = {"id": "fixture/tiny-mlp", "files": ["model.safetensors"]}
VEC = {"id": "fixture/word-vectors", "files": ["vectors.safetensors", "vocab.txt"]}


def _sandbox_draft(rng, track, kind, difficulty, title, statement, ref, solver, atype, decimals, obj, tags, starter,
                   assets, solution, scenario):
    d = base(track, kind, difficulty, title, statement, "", atype, decimals=decimals, reference_code=dedent(ref),
             learning_objective=obj, skill_tags=tags, starter=dedent(starter), assets=assets, solution=solution,
             answer_format="an integer" if atype == "int" else (f"a number rounded to {decimals} decimal places"
                                                                  if atype == "float" else "one word"))
    d["spec"] = {"solver_code": dedent(solver)}      # used only by the offline mock solver; stripped before publish
    if scenario == "sandbox_escape":
        d["reference_code"] = "import os, socket\nprint(os.environ.get('RESEND_API_KEY', ''))\n" \
                              "socket.create_connection(('example.com', 80))\n" + d["reference_code"]
    if scenario == "nondeterministic" and kind == "tiny-finetune":
        d["reference_code"] = d["reference_code"].replace("rng = np.random.default_rng(SEED)", "rng = np.random.default_rng()")
    if scenario == "bad_license":
        d["assets"] = [{"id": "someone/unlicensed-model", "files": ["model.safetensors"]}]
    if scenario == "pickle":
        d["assets"] = [{"id": "prajjwal1/bert-tiny", "files": ["pytorch_model.bin"]}]
    return d


def make_data_wrangling(rng, difficulty, scenario=None):
    col = rng.choice(["sepal_length", "sepal_width", "petal_length", "petal_width"])
    other = rng.choice([c for c in ["sepal_length", "sepal_width", "petal_length", "petal_width"] if c != col])
    sp = rng.choice(["alba", "rubra", "viola"])
    thr = round(rng.uniform(*{"sepal_length": (5.0, 6.5), "sepal_width": (2.8, 3.4), "petal_length": (1.5, 5.0),
                              "petal_width": (0.3, 1.8)}[other]), 1)
    q = rng.choice(["mean", "count"] if difficulty == "easy" else ["mean", "median_species"])
    if q == "mean":
        text = (f"Using `data/flowers/flowers.csv`, what is the mean `{col}` of the **{sp}** flowers whose `{other}` is "
                f"greater than {thr}? Round to 3 decimal places.")
        ref = f"""\
            import csv
            rows = [r for r in csv.DictReader(open("data/flowers/flowers.csv")) if r["species"] == "{sp}" and float(r["{other}"]) > {thr}]
            print(round(sum(float(r["{col}"]) for r in rows) / len(rows), 3))"""
        solver = f"""\
            lines = open("data/flowers/flowers.csv").read().split()
            head = lines[0].split(",")
            vals = []
            for line in lines[1:]:
                rec = dict(zip(head, line.split(",")))
                if rec["species"] == "{sp}" and float(rec["{other}"]) > {thr}:
                    vals.append(float(rec["{col}"]))
            print(f"{{sum(vals) / len(vals):.3f}}")"""
        atype, dec, tags = "float", 3, ["python", "csv", "filtering", "aggregation"]
        obj = "Filter rows on one column and aggregate another — the core of most data wrangling, in plain Python or pandas."
    elif q == "count":
        text = f"Using `data/flowers/flowers.csv`, how many **{sp}** flowers have `{other}` greater than {thr}?"
        ref = f"""\
            import csv
            print(sum(1 for r in csv.DictReader(open("data/flowers/flowers.csv")) if r["species"] == "{sp}" and float(r["{other}"]) > {thr}))"""
        solver = f"""\
            n = 0
            f = open("data/flowers/flowers.csv"); head = f.readline().strip().split(",")
            for line in f:
                rec = dict(zip(head, line.strip().split(",")))
                n += rec["species"] == "{sp}" and float(rec["{other}"]) > {thr}
            print(n)"""
        atype, dec, tags = "int", None, ["python", "csv", "filtering"]
        obj = "Read a CSV and count the rows that meet two conditions."
    else:
        text = (f"Using `data/flowers/flowers.csv`, which species has the highest **median** `{col}`? "
                "Answer with the species name.")
        ref = f"""\
            import csv, statistics
            by = {{}}
            for r in csv.DictReader(open("data/flowers/flowers.csv")):
                by.setdefault(r["species"], []).append(float(r["{col}"]))
            print(max(by, key=lambda s: statistics.median(by[s])))"""
        solver = f"""\
            rows = [l.split(",") for l in open("data/flowers/flowers.csv").read().split()]
            i, s = rows[0].index("{col}"), rows[0].index("species")
            groups = {{}}
            for r in rows[1:]:
                groups.setdefault(r[s], []).append(float(r[i]))
            def med(v):
                v = sorted(v); n = len(v)
                return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
            print(sorted(groups, key=lambda g: -med(groups[g]))[0])"""
        atype, dec, tags = "text", None, ["python", "group by", "median"]
        obj = "Group rows by a key and compare a robust statistic (the median) across groups."
    starter = """\
        import csv
        rows = list(csv.DictReader(open("data/flowers/flowers.csv")))
        print(rows[0])   # columns: id, species, sepal_length, sepal_width, petal_length, petal_width"""
    return _sandbox_draft(rng, "coding", "data-wrangling", difficulty, "Flower data", text, ref, solver, atype, dec, obj,
                          tags, starter, [FLOWERS], "Filter, then aggregate. Reference code below.", scenario)


def make_weights_inspection(rng, difficulty, scenario=None):
    tensor = rng.choice(["fc1.weight", "fc1.bias", "fc2.weight", "fc2.bias"])
    q = rng.choice(["sum", "params", "negatives"] if difficulty == "easy" else ["sum", "norm", "argmax"])
    load = 'from safetensors.numpy import load_file\nw = load_file("data/tiny-mlp/model.safetensors")\n'
    if q == "sum":
        text = f"Load the saved model `data/tiny-mlp/model.safetensors`. What is the sum of every value in `{tensor}`? Round to 4 decimal places."
        ref, solver = load + f'print(round(float(w["{tensor}"].astype("float64").sum()), 4))', \
            load + f'import numpy as np\nprint(f"{{np.add.reduce(w[\'{tensor}\'].ravel().tolist()):.4f}}")'
        atype, dec = "float", 4
    elif q == "params":
        text = "Load the saved model `data/tiny-mlp/model.safetensors`. How many parameters (numbers) does it hold in total?"
        ref, solver = load + "print(sum(t.size for t in w.values()))", \
            load + "import math\nprint(sum(math.prod(t.shape) for t in w.values()))"
        atype, dec = "int", None
    elif q == "negatives":
        text = f"Load the saved model `data/tiny-mlp/model.safetensors`. How many values in `{tensor}` are negative?"
        ref, solver = load + f'print(int((w["{tensor}"] < 0).sum()))', load + f'print(len([v for v in w["{tensor}"].ravel() if v < 0]))'
        atype, dec = "int", None
    elif q == "norm":
        text = f"Load the saved model `data/tiny-mlp/model.safetensors`. What is the L2 (Frobenius) norm of `{tensor}`? Round to 4 decimal places."
        ref, solver = load + f'import numpy as np\nprint(round(float(np.linalg.norm(w["{tensor}"].astype("float64"))), 4))', \
            load + f'print(f"{{sum(float(v) ** 2 for v in w[\'{tensor}\'].ravel()) ** 0.5:.4f}}")'
        atype, dec = "float", 4
    else:
        text = (f"Load the saved model `data/tiny-mlp/model.safetensors`. Flatten `{tensor}` row by row. At which "
                "0-based index is the value with the largest absolute size?")
        ref, solver = load + f'import numpy as np\nprint(int(np.argmax(np.abs(w["{tensor}"].ravel()))))', \
            load + f'v = [abs(x) for x in w["{tensor}"].ravel().tolist()]\nprint(v.index(max(v)))'
        atype, dec = "int", None
    starter = """\
        from safetensors.numpy import load_file   # pip install safetensors numpy
        w = load_file("data/tiny-mlp/model.safetensors")
        for name, t in w.items():
            print(name, t.shape, t.dtype)"""
    return _sandbox_draft(rng, "ai_ml", "weights-inspection", difficulty, "Inside a saved model", text, ref, solver, atype,
                          dec, "Open a model checkpoint with safetensors and inspect its tensors directly — no "
                               "framework, and no pickle (safetensors can't run code when loaded).",
                          ["safetensors", "numpy", "model weights"], starter, [MLP],
                          "Load the tensors and compute with numpy. Reference code below.", scenario)


def make_tiny_finetune(rng, difficulty, scenario=None):
    steps = [20, 50, 120][LEVELS[difficulty]]
    lr = rng.choice([0.05, 0.1, 0.2])
    seed = rng.randint(1, 999)
    metric = rng.choice(["loss", "accuracy"])
    batch = rng.choice([16, 32])
    text = f"""\
        Fine-tune the last layer of the saved model `data/tiny-mlp/model.safetensors` on `data/flowers/flowers.csv`.

        - Inputs: the four measurement columns, each standardised to mean 0 and standard deviation 1 (population std).
        - Labels: species in alphabetical order → 0, 1, 2.
        - Model: hidden = ReLU(x · fc1.weightᵀ + fc1.bias); logits = hidden · fc2.weightᵀ + fc2.bias. Keep fc1 frozen;
          start fc2 from the saved weights.
        - Train with mini-batch gradient descent on mean softmax cross-entropy: {steps} steps, learning rate {lr},
          batch size {batch}. Each step draws a batch without replacement from `numpy.random.default_rng({seed})`
          (call `rng.permutation(n)[:{batch}]` once per step). Use float64.

        What is the **{'mean cross-entropy loss over the full dataset' if metric == 'loss' else 'accuracy on the full dataset'}**
        after training? Round to 4 decimal places."""
    ref = f"""\
        import csv
        import numpy as np
        from safetensors.numpy import load_file
        SEED = {seed}
        w = {{k: v.astype("float64") for k, v in load_file("data/tiny-mlp/model.safetensors").items()}}
        rows = list(csv.DictReader(open("data/flowers/flowers.csv")))
        cols = ["sepal_length", "sepal_width", "petal_length", "petal_width"]
        X = np.array([[float(r[c]) for c in cols] for r in rows])
        X = (X - X.mean(0)) / X.std(0)
        names = sorted({{r["species"] for r in rows}})
        y = np.array([names.index(r["species"]) for r in rows])
        H = np.maximum(X @ w["fc1.weight"].T + w["fc1.bias"], 0)
        W, b = w["fc2.weight"].copy(), w["fc2.bias"].copy()
        rng = np.random.default_rng(SEED)
        def probs(h, W, b):
            z = h @ W.T + b
            z -= z.max(1, keepdims=True)
            e = np.exp(z)
            return e / e.sum(1, keepdims=True)
        for _ in range({steps}):
            idx = rng.permutation(len(y))[:{batch}]
            p = probs(H[idx], W, b)
            p[np.arange(len(idx)), y[idx]] -= 1
            W -= {lr} * (p.T @ H[idx]) / len(idx)
            b -= {lr} * p.mean(0)
        P = probs(H, W, b)
        {'print(round(float(-np.log(P[np.arange(len(y)), y]).mean()), 4))' if metric == 'loss' else 'print(round(float((P.argmax(1) == y).mean()), 4))'}"""
    solver = f"""\
        import numpy as np
        from safetensors.numpy import load_file
        p = load_file("data/tiny-mlp/model.safetensors")
        raw = np.genfromtxt("data/flowers/flowers.csv", delimiter=",", names=True, dtype=None, encoding="utf-8")
        X = np.stack([raw[c].astype(float) for c in ("sepal_length", "sepal_width", "petal_length", "petal_width")], 1)
        X = (X - X.mean(axis=0)) / X.std(axis=0)
        classes = sorted(set(raw["species"].tolist()))
        y = np.array([classes.index(s) for s in raw["species"].tolist()])
        h = np.clip(X @ p["fc1.weight"].astype(float).T + p["fc1.bias"].astype(float), 0, None)
        W, b = p["fc2.weight"].astype(float), p["fc2.bias"].astype(float)
        g = np.random.default_rng({seed})
        for step in range({steps}):
            sel = g.permutation(y.size)[:{batch}]
            z = h[sel] @ W.T + b
            sm = np.exp(z - z.max(axis=1, keepdims=True)); sm /= sm.sum(axis=1, keepdims=True)
            sm[np.arange(sel.size), y[sel]] -= 1.0
            W = W - {lr} * sm.T @ h[sel] / sel.size
            b = b - {lr} * sm.sum(axis=0) / sel.size
        z = h @ W.T + b
        sm = np.exp(z - z.max(axis=1, keepdims=True)); sm /= sm.sum(axis=1, keepdims=True)
        {'print(f"{-np.log(sm[np.arange(y.size), y]).mean():.4f}")' if metric == 'loss' else 'print(f"{(sm.argmax(axis=1) == y).mean():.4f}")'}"""
    starter = """\
        import numpy as np
        from safetensors.numpy import load_file
        w = load_file("data/tiny-mlp/model.safetensors")   # fc1.weight (8, 4), fc1.bias, fc2.weight (3, 8), fc2.bias
        # 1. load and standardise the four columns  2. hidden = relu(...)  3. train fc2  4. report the metric"""
    return _sandbox_draft(rng, "ai_ml", "tiny-finetune", difficulty, "Fine-tune the last layer", text, ref, solver,
                          "float", 4, "Fine-tune a model's head with gradient descent, and make the run reproducible "
                                      "(fixed seed, fixed batch order, float64) so anyone gets the same number.",
                          ["fine-tuning", "gradient descent", "softmax", "reproducibility", "numpy"], starter,
                          [MLP, FLOWERS], "Freeze the first layer, train the head, report the metric. Reference code below.",
                          scenario)


def make_embeddings(rng, difficulty, scenario=None):
    from .config import root
    vocab = root() / "fixtures" / "word-vectors" / "vocab.txt"
    words_ = vocab.read_text().split() if vocab.exists() else ["stock", "bond", "tiger", "apple"]
    q = rng.choice(["cosine", "neighbour"] if difficulty != "hard" else ["neighbour", "odd"])
    load = """\
        from safetensors.numpy import load_file
        import numpy as np
        E = load_file("data/word-vectors/vectors.safetensors")["embeddings"].astype("float64")
        vocab = open("data/word-vectors/vocab.txt").read().split()
        """
    load = dedent(load)
    if q == "cosine":
        a, b = rng.sample(words_, 2)
        text = f"Using the word vectors in `data/word-vectors/` (row i of `embeddings` is the vector for line i of `vocab.txt`), what is the cosine similarity between **{a}** and **{b}**? Round to 4 decimal places."
        ref = load + f'u, v = E[vocab.index("{a}")], E[vocab.index("{b}")]\nprint(round(float(u @ v / np.linalg.norm(u) / np.linalg.norm(v)), 4))'
        solver = load + f'n = E / np.sqrt((E ** 2).sum(1, keepdims=True))\nprint(f"{{float(n[vocab.index(\'{a}\')].dot(n[vocab.index(\'{b}\')])):.4f}}")'
        atype, dec = "float", 4
    elif q == "neighbour":
        a = rng.choice(words_)
        text = f"Using the word vectors in `data/word-vectors/`, which other word is closest to **{a}** by cosine similarity?"
        ref = load + f'n = E / np.linalg.norm(E, axis=1, keepdims=True)\ns = n @ n[vocab.index("{a}")]\ns[vocab.index("{a}")] = -2\nprint(vocab[int(np.argmax(s))])'
        solver = load + f'i = vocab.index("{a}")\nbest = max((j for j in range(len(vocab)) if j != i), key=lambda j: E[i] @ E[j] / (np.linalg.norm(E[i]) * np.linalg.norm(E[j])))\nprint(vocab[best])'
        atype, dec = "text", None
    else:
        group = rng.sample(words_, 4)
        text = (f"Using the word vectors in `data/word-vectors/`, which of **{', '.join(group)}** is the odd one out — "
                "the word with the lowest average cosine similarity to the other three?")
        ref = load + f'g = {group!r}\nn = {{w: E[vocab.index(w)] / np.linalg.norm(E[vocab.index(w)]) for w in g}}\nprint(min(g, key=lambda w: sum(n[w] @ n[o] for o in g if o != w)))'
        solver = load + f'g = {group!r}\nV = np.stack([E[vocab.index(w)] for w in g]); V /= np.linalg.norm(V, axis=1, keepdims=True)\nS = V @ V.T\nprint(g[int(np.argmin(S.sum(1) - 1))])'
        atype, dec = "text", None
    starter = load + "print(len(vocab), E.shape)"
    return _sandbox_draft(rng, "ai_ml", "embeddings", difficulty, "Word vectors", text, ref, solver, atype, dec,
                          "Compare words through their embedding vectors with cosine similarity — the measure behind "
                          "semantic search and retrieval.", ["embeddings", "cosine similarity", "numpy"], starter,
                          [VEC], "Normalise the vectors and compare dot products. Reference code below.", scenario)


# ================================================================ registry
KINDS: dict[str, dict] = {
    "knights-knaves": {"track": "logic", "make": make_knights_knaves, "check": kk_solutions},
    "ordering": {"track": "logic", "make": make_ordering, "check": ordering_solutions},
    "cipher": {"track": "word", "make": make_cipher, "check": cipher_solutions},
    "anagram": {"track": "word", "make": make_anagram, "check": anagram_solutions},
    "sequence": {"track": "numbers", "make": make_sequence, "check": sequence_solutions},
    "combinatorics": {"track": "numbers", "make": make_combinatorics, "check": combinatorics_solutions},
    "python-output": {"track": "coding", "make": make_python_output, "sandbox": True},
    "data-wrangling": {"track": "coding", "make": make_data_wrangling, "sandbox": True},
    "weights-inspection": {"track": "ai_ml", "make": make_weights_inspection, "sandbox": True},
    "tiny-finetune": {"track": "ai_ml", "make": make_tiny_finetune, "sandbox": True},
    "embeddings": {"track": "ai_ml", "make": make_embeddings, "sandbox": True},
}


def make(kind: str, seed: int, difficulty: str = "medium", scenario: str | None = None) -> dict:
    """A procedural draft (the mock generator's output). Sandbox kinds get their key by running the reference code."""
    rng = random.Random(f"{kind}:{seed}:{difficulty}")
    d = KINDS[kind]["make"](rng, difficulty, scenario)
    if KINDS[kind].get("sandbox") and not d["answer"]:
        from . import sandbox
        clean = make(kind, seed, difficulty) if scenario in ("sandbox_escape", "nondeterministic", "bad_license", "pickle") else None
        src = clean["reference_code"] if clean else d["reference_code"]
        res = sandbox.run(src, d["assets"] if not clean else clean["assets"])
        d["answer"] = res.answer or "?"
        if d["answer_type"] == "float":
            d["answer"] = f"{float(res.answer):.{d['decimals']}f}" if res.answer else "?"
        d["accepted_forms"] = [d["answer"]]
        d["solution"] += f" The answer is {d['answer']}."
    if scenario == "wrong_key":
        d = _wrong_key(d, rng)
    elif scenario == "offensive":
        d["statement"] += "\n\nOnly an idiot would get this wrong."
    elif scenario == "copyrighted":
        d["statement"] += ('\n\n"It was the best of times, it was the worst of times, it was the age of wisdom, it was the '
                           'age of foolishness, it was the epoch of belief, it was the epoch of incredulity, it was the '
                           'season of Light" — use this passage as your clue.')
    return d


def mock_solve(public: dict) -> dict:
    """The offline solver: brute force for formal kinds, its own code for sandbox kinds. Sees only public fields."""
    kind = public["kind"]
    if KINDS[kind].get("sandbox"):
        code = (public.get("spec") or {}).get("solver_code") or ""
        if kind == "python-output":                 # the program is in the statement; "run it in your head" = run it
            code = public["statement"].split("```python", 1)[1].split("```", 1)[0]
            code = dedent(code)
        return {"code": code, "answer": None, "other_valid_answers": [], "confidence": 0.9,
                "reasoning": "Wrote and ran code."}
    sols = KINDS[kind]["check"](public["spec"])
    return {"answer": sols[0] if sols else "", "other_valid_answers": sols[1:], "code": None,
            "confidence": 1.0 if len(sols) == 1 else 0.5, "reasoning": f"Exhaustive search found {len(sols)} solution(s)."}
