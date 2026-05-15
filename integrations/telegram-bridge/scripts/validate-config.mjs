#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { parseBool, parseList, cleanEnvValue, isPlaceholderValue } from "../src/lib.mjs";

function parseEnv(text) {
  const env = {};
  for (const line of String(text || "").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const normalized = trimmed.startsWith("export ") ? trimmed.slice(7).trim() : trimmed;
    const index = normalized.indexOf("=");
    if (index <= 0) continue;
    const key = normalized.slice(0, index).trim();
    let value = normalized.slice(index + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    env[key] = value;
  }
  return env;
}

function validate() {
  const errors = [];
  const warnings = [];

  const envPath = process.argv.find(a => a.startsWith("--env="))?.slice(6) || ".env";
  let env;
  try {
    env = parseEnv(readFileSync(envPath, "utf8"));
  } catch {
    errors.push({ code: "env_not_found", message: `Cannot read ${envPath}` });
    print(errors, warnings);
    process.exit(1);
  }

  const add = (list, code, msg) => list.push({ code, message: msg });

  for (const key of ["TELEGRAM_BOT_TOKEN", "DEEPSEEK_RUNTIME_TOKEN"]) {
    const val = cleanEnvValue(env[key]);
    if (!val) add(errors, "missing_required", `${key} is required`);
    else if (isPlaceholderValue(val)) add(errors, "placeholder", `${key} is still a placeholder`);
  }

  const url = cleanEnvValue(env.DEEPSEEK_RUNTIME_URL || "http://127.0.0.1:7878");
  try {
    const p = new URL(url);
    if (!["http:", "https:"].includes(p.protocol)) add(errors, "bad_url", "DEEPSEEK_RUNTIME_URL must be http/https");
  } catch {
    add(errors, "bad_url", "DEEPSEEK_RUNTIME_URL is not a valid URL");
  }

  const allowlist = parseList(env.TELEGRAM_CHAT_ALLOWLIST);
  const allowUnlisted = parseBool(env.DEEPSEEK_ALLOW_UNLISTED, false);
  if (!allowlist.length && !allowUnlisted) add(warnings, "no_allowlist", "TELEGRAM_CHAT_ALLOWLIST is empty");
  if (allowUnlisted) add(warnings, "unlisted", "DEEPSEEK_ALLOW_UNLISTED=true — anyone can use this bot");

  print(errors, warnings);
  process.exit(errors.length ? 1 : 0);
}

function print(errors, warnings) {
  if (!errors.length && !warnings.length) {
    console.log("✅ Configuration valid");
    return;
  }
  for (const e of errors) console.log(`❌ ${e.code}: ${e.message}`);
  for (const w of warnings) console.log(`⚠️  ${w.code}: ${w.message}`);
}

validate();
