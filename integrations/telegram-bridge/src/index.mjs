import process from "node:process";
import { Telegraf } from "telegraf";

import {
  activeTurnBlock,
  commandAction,
  compactRuntimeError,
  helpText,
  parseBool,
  parseCommand,
  parseList,
  splitMessage,
  ThreadStore
} from "./lib.mjs";

function requiredEnv(name) {
  const value = process.env[name];
  if (!value) {
    console.error(`${name} is required`);
    process.exit(1);
  }
  return value;
}

const config = {
  botToken: requiredEnv("TELEGRAM_BOT_TOKEN"),
  runtimeUrl: (process.env.DEEPSEEK_RUNTIME_URL || "http://127.0.0.1:7878").replace(/\/+$/, ""),
  runtimeToken: requiredEnv("DEEPSEEK_RUNTIME_TOKEN"),
  workspace: process.env.DEEPSEEK_WORKSPACE || process.cwd(),
  model: process.env.DEEPSEEK_MODEL || "auto",
  mode: process.env.DEEPSEEK_MODE || "agent",
  allowShell: parseBool(process.env.DEEPSEEK_ALLOW_SHELL, true),
  trustMode: parseBool(process.env.DEEPSEEK_TRUST_MODE, false),
  autoApprove: parseBool(process.env.DEEPSEEK_AUTO_APPROVE, false),
  allowlist: parseList(process.env.TELEGRAM_CHAT_ALLOWLIST),
  allowUnlisted: parseBool(process.env.DEEPSEEK_ALLOW_UNLISTED, false),
  threadMapPath:
    process.env.TELEGRAM_THREAD_MAP_PATH ||
    "/var/lib/deepseek-telegram-bridge/thread-map.json",
  maxReplyChars: Number(process.env.TELEGRAM_MAX_REPLY_CHARS || 4000),
  turnTimeoutMs: Number(process.env.DEEPSEEK_TURN_TIMEOUT_MS || 900000),
  ownerId: process.env.TELEGRAM_OWNER_ID || ""
};

const bot = new Telegraf(config.botToken);
const threadStore = await ThreadStore.open(config.threadMapPath);

console.log("Starting DeepSeek Telegram bridge");
console.log(`Runtime: ${config.runtimeUrl}`);
console.log(`Workspace: ${config.workspace}`);
if (!config.allowlist.length && !config.allowUnlisted) {
  console.log("No allowlist configured. Incoming chats will be logged and refused.");
}

bot.start(async (ctx) => {
  const chatId = String(ctx.chat.id);
  if (!isAllowed(chatId)) {
    return ctx.reply(`This chat (${chatId}) is not in the allowlist. Contact the bridge owner to add it.`);
  }
  await ctx.reply(helpText());
});

bot.help(async (ctx) => {
  if (!isAllowed(String(ctx.chat.id))) return;
  await ctx.reply(helpText());
});

bot.command("status", async (ctx) => {
  if (!isAllowed(String(ctx.chat.id))) return;
  await handleStatus(String(ctx.chat.id), ctx);
});

bot.command("threads", async (ctx) => {
  if (!isAllowed(String(ctx.chat.id))) return;
  await handleThreads(String(ctx.chat.id), ctx);
});

bot.command("new", async (ctx) => {
  if (!isAllowed(String(ctx.chat.id))) return;
  const state = await ensureThread(String(ctx.chat.id), { forceNew: true });
  await ctx.reply(`Created thread ${state.threadId}`);
});

bot.command("resume", async (ctx) => {
  if (!isAllowed(String(ctx.chat.id))) return;
  const threadId = ctx.message.text.split(/\s+/).slice(1).join(" ").trim();
  if (!threadId) return ctx.reply("Usage: /resume <thread_id>");
  await handleResume(String(ctx.chat.id), threadId, ctx);
});

bot.command("interrupt", async (ctx) => {
  if (!isAllowed(String(ctx.chat.id))) return;
  await handleInterrupt(String(ctx.chat.id), ctx);
});

bot.command("compact", async (ctx) => {
  if (!isAllowed(String(ctx.chat.id))) return;
  await handleCompact(String(ctx.chat.id), ctx);
});

bot.command("allow", async (ctx) => {
  if (!isAllowed(String(ctx.chat.id))) return;
  const args = ctx.message.text.split(/\s+/).slice(1).join(" ").trim();
  const action = commandAction(parseCommand(`/allow ${args}`));
  await handleApproval(String(ctx.chat.id), action, ctx);
});

bot.command("deny", async (ctx) => {
  if (!isAllowed(String(ctx.chat.id))) return;
  const args = ctx.message.text.split(/\s+/).slice(1).join(" ").trim();
  const action = commandAction(parseCommand(`/deny ${args}`));
  await handleApproval(String(ctx.chat.id), action, ctx);
});

// Handle non-command text as prompt
bot.on("text", async (ctx) => {
  if (!isAllowed(String(ctx.chat.id))) return;
  const text = ctx.message.text.trim();
  if (!text || text.startsWith("/")) return;
  await runPrompt(String(ctx.chat.id), text, ctx);
});

bot.launch({ dropPendingUpdates: true });
console.log("Telegram bot started (long polling)");

// --- Security ---

function isAllowed(chatId) {
  if (config.allowUnlisted) return true;
  if (config.allowlist.includes(chatId)) return true;
  if (config.ownerId && chatId === config.ownerId) return true;
  console.log(`Refused chat ${chatId} — not in allowlist`);
  return false;
}

// --- Thread Management ---

async function ensureThread(chatId, { forceNew = false } = {}) {
  const existing = await threadStore.getChat(chatId);
  if (existing?.threadId && !forceNew) return existing;

  const thread = await runtimeJson("/v1/threads", {
    method: "POST",
    body: {
      model: config.model,
      workspace: config.workspace,
      mode: config.mode,
      allow_shell: config.allowShell,
      trust_mode: config.trustMode,
      auto_approve: config.autoApprove,
      archived: false,
      system_prompt:
        "You are being controlled from a Telegram chat. Keep status updates concise. Ask for tool approvals when needed."
    }
  });

  const state = {
    threadId: thread.id,
    lastSeq: 0,
    activeTurnId: null,
    updatedAt: new Date().toISOString()
  };
  await threadStore.setChat(chatId, state);
  return state;
}

async function runtimeJson(path, options = {}) {
  const url = `${config.runtimeUrl}${path}`;
  const headers = {
    "Authorization": `Bearer ${config.runtimeToken}`,
    "Content-Type": "application/json"
  };
  const fetchOptions = {
    method: options.method || "GET",
    headers
  };
  if (options.body) fetchOptions.body = JSON.stringify(options.body);

  const response = await fetch(url, fetchOptions);
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(compactRuntimeError(response.status, body));
  }
  return body;
}

// --- Command Handlers ---

async function handleStatus(chatId, ctx) {
  try {
    const threads = await runtimeJson("/v1/threads?limit=5");
    const state = await threadStore.getChat(chatId);
    const lines = [
      `Runtime: ${config.runtimeUrl}`,
      `Workspace: ${config.workspace}`,
      `Model: ${config.model}`,
      `Mode: ${config.mode}`,
      `Active thread: ${state?.threadId || "none"}`,
      `Total threads: ${threads?.length || "unknown"}`
    ];
    await ctx.reply(lines.join("\n"));
  } catch (err) {
    await ctx.reply(`Status error: ${err.message}`);
  }
}

async function handleThreads(chatId, ctx) {
  try {
    const threads = await runtimeJson("/v1/threads");
    const list = Array.isArray(threads) ? threads.slice(0, 10) : [];
    if (!list.length) return ctx.reply("No threads found.");
    const lines = list.map((t, i) => `${i + 1}. ${t.id} ${t.title || ""} [${t.status || "unknown"}]`);
    await ctx.reply(lines.join("\n"));
  } catch (err) {
    await ctx.reply(`Threads error: ${err.message}`);
  }
}

async function handleResume(chatId, targetThreadId, ctx) {
  try {
    await runtimeJson(`/v1/threads/${encodeURIComponent(targetThreadId)}`);
    await threadStore.setChat(chatId, {
      threadId: targetThreadId,
      lastSeq: 0,
      activeTurnId: null,
      updatedAt: new Date().toISOString()
    });
    await ctx.reply(`Resumed thread ${targetThreadId}`);
  } catch (err) {
    await ctx.reply(`Resume error: ${err.message}`);
  }
}

async function handleInterrupt(chatId, ctx) {
  const state = await threadStore.getChat(chatId);
  if (!state?.threadId) return ctx.reply("No active thread to interrupt.");
  try {
    // Find active turn
    const detail = await runtimeJson(`/v1/threads/${encodeURIComponent(state.threadId)}`);
    const block = activeTurnBlock(detail, state);
    if (block) {
      await runtimeJson(`/v1/threads/${encodeURIComponent(state.threadId)}/turns/${encodeURIComponent(block.turnId)}/interrupt`, { method: "POST" });
      await ctx.reply("Interrupted active turn.");
    } else {
      await ctx.reply("No active turn to interrupt.");
    }
  } catch (err) {
    await ctx.reply(`Interrupt error: ${err.message}`);
  }
}

async function handleCompact(chatId, ctx) {
  const state = await threadStore.getChat(chatId);
  if (!state?.threadId) return ctx.reply("No active thread to compact.");
  try {
    await runtimeJson(`/v1/threads/${encodeURIComponent(state.threadId)}/compact`, { method: "POST" });
    await ctx.reply("Compacted thread context.");
  } catch (err) {
    await ctx.reply(`Compact error: ${err.message}`);
  }
}

async function handleApproval(chatId, action, ctx) {
  const state = await threadStore.getChat(chatId);
  if (!state?.threadId) return ctx.reply("No active thread. Start one with /new or send a prompt.");
  try {
    const endpoint = action.decision === "allow"
      ? `/v1/threads/${encodeURIComponent(state.threadId)}/approvals/${encodeURIComponent(action.approvalId)}/approve`
      : `/v1/threads/${encodeURIComponent(state.threadId)}/approvals/${encodeURIComponent(action.approvalId)}/reject`;
    await runtimeJson(endpoint, { method: "POST" });
    await ctx.reply(`${action.decision === "allow" ? "Approved" : "Rejected"} approval ${action.approvalId}`);
  } catch (err) {
    await ctx.reply(`Approval error: ${err.message}`);
  }
}

async function runPrompt(chatId, prompt, ctx) {
  if (!prompt.trim()) return;
  const state = await ensureThread(chatId);

  // Check for active turn
  try {
    const detail = await runtimeJson(`/v1/threads/${encodeURIComponent(state.threadId)}`);
    const block = activeTurnBlock(detail, state);
    if (block) {
      await threadStore.patchChat(chatId, { activeTurnId: block.turnId });
      await ctx.reply(block.message);
      return;
    }
    if (state.activeTurnId) {
      await threadStore.patchChat(chatId, { activeTurnId: null });
    }
  } catch {
    // Ignore errors checking active turns
  }

  await ctx.reply("🤔 Processing...");

  try {
    await runtimeJson(`/v1/threads/${encodeURIComponent(state.threadId)}/turns`, {
      method: "POST",
      body: { content: prompt }
    });

    // Poll for turn completion via events
    const result = await pollForTurnCompletion(state.threadId, state.lastSeq, chatId, ctx);
    if (result.lastSeq > state.lastSeq) {
      await threadStore.patchChat(chatId, { lastSeq: result.lastSeq });
    }
    if (result.response) {
      const chunks = splitMessage(result.response, config.maxReplyChars);
      for (const chunk of chunks) {
        await ctx.reply(chunk);
      }
    } else {
      await ctx.reply("🤖 Done (no text response)");
    }
  } catch (err) {
    await ctx.reply(`Error: ${err.message}`);
  }
}

async function pollForTurnCompletion(threadId, sinceSeq, chatId, ctx) {
  const timeoutAt = Date.now() + config.turnTimeoutMs;
  let lastSeq = sinceSeq;
  let response = "";
  const seenEvents = new Set();

  while (Date.now() < timeoutAt) {
    try {
      const events = await runtimeJson(`/v1/threads/${encodeURIComponent(threadId)}/events?since_seq=${lastSeq}`);
      if (!Array.isArray(events)) {
        await new Promise(r => setTimeout(r, 1000));
        continue;
      }
      for (const event of events) {
        if (seenEvents.has(event.seq)) continue;
        seenEvents.add(event.seq);
        lastSeq = Math.max(lastSeq, event.seq);
        if (event.event === "item.delta" && event.payload?.delta) {
          response += event.payload.delta;
        }
        if (event.event === "turn.completed") {
          return { lastSeq, response };
        }
      }
      await new Promise(r => setTimeout(r, 1000));
    } catch {
      await new Promise(r => setTimeout(r, 2000));
    }
  }
  return { lastSeq, response };
}

// Graceful shutdown
process.once("SIGINT", () => bot.stop("SIGINT"));
process.once("SIGTERM", () => bot.stop("SIGTERM"));
