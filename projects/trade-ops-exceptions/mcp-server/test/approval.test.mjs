// node --test: approval token verification (HITL-02 / SEC-03)
import { test } from "node:test";
import assert from "node:assert/strict";
import { sign, verify } from "../dist/approval.js";

const key = "k".repeat(64);
const future = new Date(Date.now() + 60_000).toISOString();
const fields = ["EX-0001", "QUANTITY_MISMATCH", "AMEND_INTERNAL", "amend 5250 -> 5000", "", "", "", "rpowers", "abc12345", future];

test("valid token verifies", () => assert.equal(verify(key, fields, sign(key, fields), future), null));
test("tampered fix is refused", () => {
  const t = sign(key, fields);
  const changed = [...fields]; changed[3] = "amend 5250 -> 9999";
  assert.match(verify(key, changed, t, future), /does not match/);
});
test("wrong key is refused", () => assert.match(verify(key, fields, sign("other", fields), future), /does not match/));
test("expired token is refused", () => {
  const past = new Date(Date.now() - 1000).toISOString();
  const f = [...fields.slice(0, 9), past];
  assert.match(verify(key, f, sign(key, f), past), /expired/);
});
test("no signing key disables writes", () => assert.match(verify("", fields, sign(key, fields), future), /writes disabled/));
test("malformed token is refused", () => assert.match(verify(key, fields, "nope", future), /malformed/));
test("python-compatible vector", () => {
  // The same vector is asserted in tests/test_controls.py so both implementations stay in lock-step.
  assert.equal(sign("secret", ["a", "b", "c"]), "244091f6162a95a00f583c4909359922dc42cbd7637c798dd64767283841b6d3");
});
