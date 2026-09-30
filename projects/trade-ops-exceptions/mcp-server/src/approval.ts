// Verifies approval tokens minted by the human-approval step (HITL-02, SEC-03).
// token = HMAC-SHA256(key, sha256 of the per-field sha256 digests joined by "|").
// The signing key is given only to the write-scoped server process, never to the model.
import { createHash, createHmac, timingSafeEqual } from "node:crypto";

const sha = (s: string) => createHash("sha256").update(s, "utf8").digest("hex");

export function approvalDigest(fields: string[]): string {
  return sha(fields.map(sha).join("|"));
}

export function sign(key: string, fields: string[]): string {
  return createHmac("sha256", key).update(approvalDigest(fields)).digest("hex");
}

export function verify(key: string, fields: string[], token: string, expiresAt: string, now = new Date()): string | null {
  if (!key) return "server has no APPROVAL_SIGNING_KEY; writes disabled";
  if (!/^[0-9a-f]{64}$/.test(token)) return "malformed approval token";
  if (Number.isNaN(Date.parse(expiresAt)) || Date.parse(expiresAt) < now.getTime()) return "approval expired";
  const expected = Buffer.from(sign(key, fields), "hex");
  const given = Buffer.from(token, "hex");
  return expected.length === given.length && timingSafeEqual(expected, given) ? null : "approval token does not match this resolution";
}
