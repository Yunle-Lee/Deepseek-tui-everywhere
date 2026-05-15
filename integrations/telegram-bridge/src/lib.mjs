import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";

export function parseBool(raw, fallback = false) {
  if (raw == null || raw === "") return fallback;
  return ["1", "true", "yes", "on"].includes(String(raw).trim().toLowerCase());
}

export function parseList(raw) {
  return String(raw || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function cleanEnvValue(value) {
  return String(value ?? "").trim();
}

export function isPlaceholderValue(value) {
  const normalized = cleanEnvValue(value).toLowerCase();
  return (
    !normalized ||
    normalized.includes("replace-with") ||
    normalized.includes("xxxxxxxx") ||
    normalized === "changeme"
  );
}

export function splitMessage(text, maxChars = 4000) {
  const value = String(text || "");
  if (value.length <= maxChars) return value ? [value] : [];
  const chunks = [];
  let cursor = 0;
  while (cursor < value.length) {
    chunks.push(value.slice(cursor, cursor + maxChars));
    cursor += maxChars;
  }
  return chunks;
}

export function parseCommand(text) {
  const trimmed = String(text || "").trim();
  if (!trimmed.startsWith("/")) return { name: "prompt", args: trimmed };
  const parts = trimmed.split(/\s+/);
  return {
    name: parts[0].slice(1).toLowerCase(),
    args: parts.slice(1).join(" ").trim()
  };
}

export function parseApprovalDecisionArgs(args) {
  const parts = String(args || "").split(/\s+/).filter(Boolean);
  return {
    approvalId: parts[0] || "",
    remember: parts.slice(1).includes("remember")
  };
}

export function commandAction(command) {
  switch (command.name) {
    case "help":     return { kind: "help" };
    case "status":   return { kind: "status" };
    case "threads":  return { kind: "threads" };
    case "new":      return { kind: "new_thread" };
    case "resume":   return { kind: "resume", threadId: command.args };
    case "interrupt":return { kind: "interrupt" };
    case "compact":  return { kind: "compact" };
    case "allow":    return { kind: "approval", decision: "allow", ...parseApprovalDecisionArgs(command.args) };
    case "deny":     return { kind: "approval", decision: "deny", ...parseApprovalDecisionArgs(command.args) };
    default:
      return { kind: "prompt", prompt: `/${command.name}${command.args ? ` ${command.args}` : ""}` };
  }
}

export function helpText() {
  return [
    "DeepSeek Telegram Bridge Commands:",
    "",
    "/help          — Show this help",
    "/status        — Show runtime status and active thread info",
    "/threads       — List your threads",
    "/new           — Start a new thread",
    "/resume <id>   — Resume an existing thread",
    "/interrupt     — Interrupt the active turn",
    "/compact       — Compact the active thread's context",
    "/allow <id>    — Approve a pending tool call",
    "/deny <id>     — Reject a pending tool call",
    "",
    "Any other text is sent as a prompt to the AI."
  ].join("\n");
}

export function compactRuntimeError(status, body) {
  const message =
    body?.error?.message ||
    body?.message ||
    (typeof body === "string" ? body : JSON.stringify(body));
  return `Runtime API request failed (${status}): ${message}`;
}

export function activeTurnBlock(detail, state = {}) {
  const turns = Array.isArray(detail?.turns) ? detail.turns : [];
  for (let i = turns.length - 1; i >= 0; i--) {
    const turn = turns[i];
    if (["queued", "in_progress"].includes(turn?.status)) {
      return {
        turnId: turn.id || state.activeTurnId || "",
        message: `Thread already has active turn ${turn.id || state.activeTurnId || "(unknown)"}. Wait for it to finish or send /interrupt.`
      };
    }
  }
  return null;
}

export { ThreadStore };

class ThreadStore {
  #path;
  #data;
  #dirty;

  constructor(path, data) {
    this.#path = path;
    this.#data = data;
    this.#dirty = false;
  }

  static async open(filePath) {
    const dir = path.dirname(filePath);
    try { await mkdir(dir, { recursive: true }); } catch { /* ok */ }
    try {
      const raw = await readFile(filePath, "utf8");
      return new ThreadStore(filePath, JSON.parse(raw));
    } catch {
      return new ThreadStore(filePath, { chats: {} });
    }
  }

  async #save() {
    if (!this.#dirty) return;
    const dir = path.dirname(this.#path);
    await mkdir(dir, { recursive: true });
    await writeFile(this.#path, JSON.stringify(this.#data, null, 2));
    this.#dirty = false;
  }

  #mark() { this.#dirty = true; }

  getChat(chatId) {
    return this.#data.chats[String(chatId)] || null;
  }

  async setChat(chatId, state) {
    this.#data.chats[String(chatId)] = state;
    this.#mark();
    await this.#save();
  }

  async patchChat(chatId, patch) {
    const key = String(chatId);
    if (!this.#data.chats[key]) this.#data.chats[key] = {};
    Object.assign(this.#data.chats[key], patch);
    this.#mark();
    await this.#save();
  }

  allChats() {
    return Object.entries(this.#data.chats).map(([chatId, state]) => ({ chatId, ...state }));
  }

  async recordMessage(msgId) {
    const seen = this.#data.seenMessages || {};
    if (seen[msgId]) return true;
    seen[msgId] = 1;
    this.#data.seenMessages = seen;
    // Prune old entries
    const keys = Object.keys(seen);
    if (keys.length > 1000) {
      const sorted = keys.sort();
      const toRemove = sorted.slice(0, sorted.length - 500);
      for (const k of toRemove) delete seen[k];
    }
    this.#mark();
    await this.#save();
    return false;
  }
}

export function validateBridgeConfig(env) {
  const errors = [];
  const warnings = [];
  const add = (list, code, message) => list.push({ code, message });

  for (const key of ["TELEGRAM_BOT_TOKEN", "DEEPSEEK_RUNTIME_URL", "DEEPSEEK_RUNTIME_TOKEN"]) {
    const value = cleanEnvValue(env[key]);
    if (!value) add(errors, "missing_required", `${key} is required`);
    else if (isPlaceholderValue(value)) add(errors, "placeholder_value", `${key} still contains a placeholder value`);
  }

  const url = cleanEnvValue(env.DEEPSEEK_RUNTIME_URL || "http://127.0.0.1:7878");
  try {
    const parsed = new URL(url);
    if (!["http:", "https:"].includes(parsed.protocol))
      add(errors, "invalid_runtime_url", "DEEPSEEK_RUNTIME_URL must use http or https");
  } catch {
    add(errors, "invalid_runtime_url", "DEEPSEEK_RUNTIME_URL is not a valid URL");
  }

  const maxReply = Number(env.TELEGRAM_MAX_REPLY_CHARS || 4000);
  if (!Number.isFinite(maxReply) || maxReply < 100)
    add(errors, "invalid_max_reply_chars", "TELEGRAM_MAX_REPLY_CHARS must be at least 100");

  const timeout = Number(env.DEEPSEEK_TURN_TIMEOUT_MS || 900000);
  if (!Number.isFinite(timeout) || timeout < 1000)
    add(errors, "invalid_turn_timeout", "DEEPSEEK_TURN_TIMEOUT_MS must be at least 1000");

  const allowlist = parseList(env.TELEGRAM_CHAT_ALLOWLIST);
  const allowUnlisted = parseBool(env.DEEPSEEK_ALLOW_UNLISTED, false);
  if (!allowlist.length && allowUnlisted)
    add(warnings, "pairing_mode_open", "DEEPSEEK_ALLOW_UNLISTED=true leaves pairing mode open");
  else if (!allowlist.length)
    add(warnings, "not_paired", "TELEGRAM_CHAT_ALLOWLIST is empty; all chats will be refused");

  return { valid: errors.length === 0, errors, warnings };
}
