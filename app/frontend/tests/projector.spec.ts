import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(testDir, "../../..");
const appRoot = path.join(repoRoot, "app");
const backendDir = path.join(appRoot, "backend");
const frontendDir = path.join(appRoot, "frontend");
const evidenceDir = path.join(appRoot, "docs", "evidence");
const frontendUrl = "http://127.0.0.1:5173";
const backendHealthUrl = "http://127.0.0.1:8765/health";
const sampleWav = path.join(backendDir, "sample.wav");

type FinalRender = { id: number; text: string; at: number };

declare global {
  interface Window {
    __livetr3LastOperatorFinalRender?: FinalRender;
    __livetr3LastProjectorFinalRender?: FinalRender;
  }
}

let backend: ChildProcess | undefined;
let frontend: ChildProcess | undefined;

test.setTimeout(10 * 60 * 1000);

test.beforeAll(async () => {
  fs.mkdirSync(evidenceDir, { recursive: true });
  const backendLog = fs.openSync(path.join(evidenceDir, "projector-backend.log"), "w");
  const frontendLog = fs.openSync(path.join(evidenceDir, "projector-frontend.log"), "w");
  backend = spawn("uv", ["run", "python", "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8765"], {
    cwd: backendDir,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
    stdio: ["ignore", backendLog, backendLog],
  });
  frontend = spawn("yarn", ["dev"], {
    cwd: frontendDir,
    env: { ...process.env },
    stdio: ["ignore", frontendLog, frontendLog],
  });
  await waitForHttp(backendHealthUrl, 240_000);
  await waitForHttp(frontendUrl, 60_000);
});

test.afterAll(async () => {
  await stopProcess(frontend);
  await stopProcess(backend);
});

test("projector mirrors finalized captions without console errors or clipping", async ({ browser }) => {
  const consoleErrors: string[] = [];
  const operatorContext = await newContext(browser);
  const projectorContext = await newContext(browser);
  await operatorContext.route("**/*", async (route) => {
    if (new URL(route.request().url()).pathname !== "/__livetr3-test-audio.wav") {
      await route.continue();
      return;
    }
    await route.fulfill({ contentType: "audio/wav", body: fs.readFileSync(sampleWav) });
  });
  const operator = await operatorContext.newPage();
  const projector = await projectorContext.newPage();
  collectConsoleErrors(operator, consoleErrors);
  collectConsoleErrors(projector, consoleErrors);

  await operator.goto(`${frontendUrl}?test_audio_url=/__livetr3-test-audio.wav`);
  await operator.getByTestId("polish-toggle").setChecked(false);
  await operator.getByTestId("start-stop-button").click();
  await expect(operator.getByTestId("start-stop-button")).toHaveText("Stop", { timeout: 30_000 });
  await expect(operator.getByTestId("error-banner")).toHaveCount(0);

  const sessionId = await operator.getByTestId("app-shell").getAttribute("data-session-id");
  expect(sessionId).toBeTruthy();
  await projector.goto(`${frontendUrl}/projector?session=${sessionId}`);

  const samples: Array<{ id: number; text: string; delayMs: number }> = [];
  let lastId = 0;
  for (let index = 0; index < 5; index += 1) {
    const operatorFinal = await waitForOperatorFinal(operator, lastId);
    const projectorFinal = await waitForProjectorFinal(projector, operatorFinal.id);
    expect(projectorFinal.text).toBe(operatorFinal.text);
    samples.push({
      id: operatorFinal.id,
      text: operatorFinal.text,
      delayMs: projectorFinal.at - operatorFinal.at,
    });
    lastId = operatorFinal.id;
  }

  const p95DelayMs = percentile(samples.map((sample) => sample.delayMs), 0.95);
  expect(p95DelayMs).toBeLessThanOrEqual(300);

  const lastSample = samples.at(-1);
  expect(lastSample).toBeTruthy();
  const operatorText = await operator.getByTestId(`caption-translation-${lastSample!.id}`).innerText();
  const projectorText = await projector.getByTestId(`projector-caption-${lastSample!.id}`).innerText();
  expect(projectorText.trim()).toBe(operatorText.trim());

  await expectNoProjectorClipping(projector, { width: 1280, height: 720 });
  await projector.screenshot({ path: path.join(evidenceDir, "projector-1280x720.png"), fullPage: true });
  await expectNoProjectorClipping(projector, { width: 1920, height: 1080 });
  await projector.screenshot({ path: path.join(evidenceDir, "projector-1920x1080.png"), fullPage: true });
  await operator.screenshot({ path: path.join(evidenceDir, "operator-projector-smoke.png"), fullPage: true });

  expect(consoleErrors).toEqual([]);
  await operator.getByTestId("start-stop-button").click();
});

async function newContext(browser: Browser): Promise<BrowserContext> {
  const context = await browser.newContext({
    permissions: ["microphone"],
    viewport: { width: 1280, height: 720 },
  });
  await context.grantPermissions(["microphone"], { origin: frontendUrl });
  return context;
}

async function waitForOperatorFinal(page: Page, lastId: number): Promise<FinalRender> {
  const handle = await page.waitForFunction(
    (id) => {
      const event = window.__livetr3LastOperatorFinalRender;
      return event && event.id > id ? event : null;
    },
    lastId,
    { timeout: 180_000 },
  );
  return handle.jsonValue() as Promise<FinalRender>;
}

async function waitForProjectorFinal(page: Page, id: number): Promise<FinalRender> {
  const handle = await page.waitForFunction(
    (expectedId) => {
      const event = window.__livetr3LastProjectorFinalRender;
      return event && event.id === expectedId ? event : null;
    },
    id,
    { timeout: 30_000 },
  );
  return handle.jsonValue() as Promise<FinalRender>;
}

async function expectNoProjectorClipping(
  page: Page,
  viewport: { width: number; height: number },
): Promise<void> {
  await page.setViewportSize(viewport);
  await page.waitForTimeout(250);
  const clipped = await page.locator("[data-testid='projector-shell'] > div > div").evaluate((node) => {
    return node.scrollHeight > node.clientHeight || node.scrollWidth > node.clientWidth;
  });
  expect(clipped).toBe(false);
}

function collectConsoleErrors(page: Page, errors: string[]): void {
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  page.on("pageerror", (error) => errors.push(error.message));
}

async function waitForHttp(url: string, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(2_000) });
      if (response.ok) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`Timed out waiting for ${url}: ${String(lastError)}`);
}

async function stopProcess(process: ChildProcess | undefined): Promise<void> {
  if (!process || process.killed || process.exitCode !== null) return;
  process.kill("SIGTERM");
  await new Promise<void>((resolve) => {
    const timer = setTimeout(() => {
      process.kill("SIGKILL");
      resolve();
    }, 10_000);
    process.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

function percentile(values: number[], pct: number): number {
  const sorted = [...values].sort((a, b) => a - b);
  const index = (sorted.length - 1) * pct;
  const lower = Math.floor(index);
  const upper = Math.min(lower + 1, sorted.length - 1);
  const fraction = index - lower;
  return sorted[lower] + (sorted[upper] - sorted[lower]) * fraction;
}
