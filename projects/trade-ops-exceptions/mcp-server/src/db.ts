// SQLite (node:sqlite, zero install) by default; Postgres when DATABASE_URL is a postgres URL.
// Reads use a separate read-only handle so read tools physically cannot write (SEC-03).
import { DatabaseSync } from "node:sqlite";

export type Row = Record<string, unknown>;
export interface Db {
  query(sql: string, params?: unknown[]): Promise<Row[]>;
  exec(sql: string, params?: unknown[]): Promise<void>;
  transaction(fn: () => Promise<void>): Promise<void>;
}

const isPg = (url: string) => /^postgres(ql)?:\/\//.test(url);

class SqliteDb implements Db {
  private db: DatabaseSync;
  constructor(path: string, readOnly: boolean) {
    this.db = new DatabaseSync(path, { readOnly });
  }
  async query(sql: string, params: unknown[] = []) {
    return this.db.prepare(sql).all(...(params as never[])) as Row[];
  }
  async exec(sql: string, params: unknown[] = []) {
    this.db.prepare(sql).run(...(params as never[]));
  }
  async transaction(fn: () => Promise<void>) {
    this.db.exec("BEGIN IMMEDIATE");
    try {
      await fn();
      this.db.exec("COMMIT");
    } catch (e) {
      this.db.exec("ROLLBACK");
      throw e;
    }
  }
}

class PgDb implements Db {
  private client: any;
  private ready: Promise<void>;
  constructor(url: string, readOnly: boolean) {
    this.ready = (async () => {
      const pg = (await import("pg")).default;
      // Match SQLite's representation: dates/timestamps as ISO strings, numerics as numbers.
      for (const oid of [1082, 1114, 1184]) pg.types.setTypeParser(oid, (v: string) => v);
      pg.types.setTypeParser(1700, (v: string) => parseFloat(v));
      this.client = new pg.Client({ connectionString: url });
      await this.client.connect();
      if (readOnly) await this.client.query("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY");
    })();
  }
  private conv(sql: string) {
    let i = 0;
    return sql.replace(/\?/g, () => `$${++i}`);
  }
  async query(sql: string, params: unknown[] = []) {
    await this.ready;
    return (await this.client.query(this.conv(sql), params)).rows as Row[];
  }
  async exec(sql: string, params: unknown[] = []) {
    await this.ready;
    await this.client.query(this.conv(sql), params);
  }
  async transaction(fn: () => Promise<void>) {
    await this.ready;
    await this.client.query("BEGIN");
    try {
      await fn();
      await this.client.query("COMMIT");
    } catch (e) {
      await this.client.query("ROLLBACK");
      throw e;
    }
  }
}

export function openDb(url: string, readOnly: boolean): Db {
  return isPg(url) ? new PgDb(url, readOnly) : new SqliteDb(url, readOnly);
}
