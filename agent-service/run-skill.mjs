import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { InMemoryCredentialStore } from "@earendil-works/pi-ai";
import {
  createAgentSession,
  DefaultResourceLoader,
  ModelRuntime,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";

const serviceDir = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(serviceDir, "..");
const agentDir = resolve(serviceDir, ".pi-agent");
const provider = (process.env.LLM_PROVIDER || "ollama").trim().toLowerCase();
const modelId = provider === "openai"
  ? (process.env.OPENAI_MODEL || "gpt-4o-mini")
  : (process.env.PI_OLLAMA_MODEL || process.env.OLLAMA_MODEL || "qwen2.5:3b");

async function main() {
  let input = "";
  for await (const part of process.stdin) input += part;
  const request = JSON.parse(input);
  if (typeof request.skill !== "string" || typeof request.task !== "string") {
    throw new Error("Expected JSON fields 'skill' and 'task'.");
  }

  const modelsPath = resolve(serviceDir, "models.json");
  const modelRuntime = await ModelRuntime.create({
    credentials: new InMemoryCredentialStore(),
    modelsPath,
    allowModelNetwork: false,
    refreshOnCreate: false,
  });
  if (provider !== "ollama" && provider !== "openai") {
    throw new Error("LLM_PROVIDER must be either 'ollama' or 'openai'.");
  }
  if (provider === "openai" && !process.env.OPENAI_API_KEY) {
    throw new Error("OpenAI is selected but OPENAI_API_KEY is not configured.");
  }
  const model = modelRuntime.getModel(provider, modelId);
  if (!model) throw new Error(`Pi could not load the ${provider} model configuration for ${modelId}.`);

  const skillPath = resolve(projectRoot, ".pi", "skills", request.skill, "SKILL.md");
  await readFile(skillPath, "utf8");
  const settingsManager = SettingsManager.inMemory();
  const resourceLoader = new DefaultResourceLoader({ cwd: projectRoot, agentDir, settingsManager });
  await resourceLoader.reload();
  const { session } = await createAgentSession({
    cwd: projectRoot,
    agentDir,
    model,
    modelRuntime,
    settingsManager,
    resourceLoader,
    noTools: true,
    sessionManager: SessionManager.inMemory(projectRoot),
  });
  try {
    await session.prompt(`/skill:${request.skill} ${request.task}`);
    const reply = session.getLastAssistantText();
    process.stdout.write(JSON.stringify({ reply }));
  } finally {
    session.dispose();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
});
