import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  parseBool,
  parseList,
  parseCommand,
  commandAction,
  splitMessage,
  parseApprovalDecisionArgs,
  helpText,
  compactRuntimeError,
  activeTurnBlock,
  validateBridgeConfig
} from "../src/lib.mjs";

describe("parseBool", () => {
  it("returns fallback for null/empty", () => {
    assert.equal(parseBool(null, true), true);
    assert.equal(parseBool("", false), false);
  });
  it("returns true for truthy values", () => {
    assert.equal(parseBool("1"), true);
    assert.equal(parseBool("true"), true);
    assert.equal(parseBool("yes"), true);
    assert.equal(parseBool("on"), true);
  });
  it("returns false otherwise", () => {
    assert.equal(parseBool("0"), false);
    assert.equal(parseBool("false"), false);
    assert.equal(parseBool("no"), false);
  });
});

describe("parseList", () => {
  it("splits comma-separated values", () => {
    assert.deepEqual(parseList("a,b,c"), ["a", "b", "c"]);
  });
  it("trims whitespace", () => {
    assert.deepEqual(parseList(" a , b "), ["a", "b"]);
  });
  it("returns empty array for empty input", () => {
    assert.deepEqual(parseList(""), []);
    assert.deepEqual(parseList(null), []);
  });
});

describe("parseCommand", () => {
  it("parses slash commands", () => {
    assert.deepEqual(parseCommand("/help"), { name: "help", args: "" });
    assert.deepEqual(parseCommand("/new thread"), { name: "new", args: "thread" });
  });
  it("treats non-slash as prompt", () => {
    assert.deepEqual(parseCommand("hello world"), { name: "prompt", args: "hello world" });
  });
});

describe("commandAction", () => {
  it("maps known commands", () => {
    assert.deepEqual(commandAction({ name: "help", args: "" }), { kind: "help" });
    assert.deepEqual(commandAction({ name: "status", args: "" }), { kind: "status" });
    assert.deepEqual(commandAction({ name: "new", args: "" }), { kind: "new_thread" });
    assert.deepEqual(commandAction({ name: "interrupt", args: "" }), { kind: "interrupt" });
    assert.deepEqual(commandAction({ name: "compact", args: "" }), { kind: "compact" });
  });
  it("passes threadId for resume", () => {
    assert.deepEqual(commandAction({ name: "resume", args: "thr_123" }), { kind: "resume", threadId: "thr_123" });
  });
  it("parses approval commands", () => {
    const allow = commandAction({ name: "allow", args: "app_1 remember" });
    assert.equal(allow.kind, "approval");
    assert.equal(allow.decision, "allow");
    assert.equal(allow.approvalId, "app_1");
    assert.equal(allow.remember, true);
  });
  it("falls through unknown commands as prompt", () => {
    const r = commandAction({ name: "foo", args: "bar" });
    assert.equal(r.kind, "prompt");
    assert.equal(r.prompt, "/foo bar");
  });
});

describe("parseApprovalDecisionArgs", () => {
  it("extracts approvalId and remember flag", () => {
    assert.deepEqual(parseApprovalDecisionArgs("app_1 remember"), { approvalId: "app_1", remember: true });
    assert.deepEqual(parseApprovalDecisionArgs("app_1"), { approvalId: "app_1", remember: false });
  });
});

describe("splitMessage", () => {
  it("returns single chunk for short text", () => {
    assert.deepEqual(splitMessage("hello", 100), ["hello"]);
  });
  it("splits long text into chunks", () => {
    const text = "x".repeat(500);
    const chunks = splitMessage(text, 200);
    assert.equal(chunks.length, 3);
    assert.equal(chunks[0].length, 200);
    assert.equal(chunks[1].length, 200);
    assert.equal(chunks[2].length, 100);
  });
  it("returns empty array for empty string", () => {
    assert.deepEqual(splitMessage(""), []);
  });
});

describe("activeTurnBlock", () => {
  it("returns null when no active turn", () => {
    const detail = { turns: [{ id: "t1", status: "completed" }] };
    assert.equal(activeTurnBlock(detail), null);
  });
  it("returns block for queued/in_progress turns", () => {
    const detail = { turns: [{ id: "t_123", status: "in_progress" }] };
    const block = activeTurnBlock(detail);
    assert.equal(block.turnId, "t_123");
    assert(block.message.includes("t_123"));
  });
});

describe("compactRuntimeError", () => {
  it("formats error message from response body", () => {
    assert(compactRuntimeError(500, { error: { message: "boom" } }).includes("boom"));
  });
  it("falls back to raw body", () => {
    assert(compactRuntimeError(502, "bad gateway").includes("bad gateway"));
  });
});

describe("validateBridgeConfig", () => {
  it("reports missing required fields", () => {
    const result = validateBridgeConfig({});
    assert.equal(result.valid, false);
    assert(result.errors.some(e => e.code === "missing_required"));
  });
  it("warns on empty allowlist", () => {
    const env = {
      TELEGRAM_BOT_TOKEN: "real:token",
      DEEPSEEK_RUNTIME_URL: "http://127.0.0.1:7878",
      DEEPSEEK_RUNTIME_TOKEN: "real-secret-token"
    };
    const result = validateBridgeConfig(env);
    assert(result.warnings.some(w => w.code === "not_paired"));
  });
  it("validates URL format", () => {
    const env = {
      TELEGRAM_BOT_TOKEN: "real:token",
      DEEPSEEK_RUNTIME_URL: "not-a-url",
      DEEPSEEK_RUNTIME_TOKEN: "real-secret-token"
    };
    const result = validateBridgeConfig(env);
    assert(result.errors.some(e => e.code === "invalid_runtime_url"));
  });
});
