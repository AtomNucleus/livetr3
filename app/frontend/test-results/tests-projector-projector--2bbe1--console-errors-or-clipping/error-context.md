# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: tests/projector.spec.ts >> projector mirrors finalized captions without console errors or clipping
- Location: tests/projector.spec.ts:54:1

# Error details

```
TimeoutError: page.waitForFunction: Timeout 30000ms exceeded.
```

# Page snapshot

```yaml
- generic [ref=e3]:
  - banner [ref=e4]:
    - generic [ref=e5]:
      - button "Settings" [ref=e6] [cursor=pointer]
      - generic [ref=e20]: "0.218"
      - generic [ref=e21]:
        - button "Clear" [ref=e22] [cursor=pointer]
        - button "Open Projector Window" [ref=e23] [cursor=pointer]
        - button "TXT" [ref=e24] [cursor=pointer]
        - button "SRT" [ref=e25] [cursor=pointer]
        - button "VTT" [ref=e26] [cursor=pointer]
        - button "Stop" [ref=e27] [cursor=pointer]
        - button "Pause" [ref=e28] [cursor=pointer]
    - generic [ref=e29]:
      - generic [ref=e30]:
        - text: Mic
        - combobox "Mic" [ref=e31]:
          - option "System default" [selected]
          - option "Microphone"
      - generic [ref=e32]:
        - text: Source language
        - combobox "Source language" [ref=e33]: English
      - generic [ref=e34]:
        - text: Target language
        - combobox "Target language" [ref=e35]: Spanish
      - generic [ref=e36]:
        - text: Custom vocabulary
        - textbox "Custom vocabulary" [ref=e37]: Surreal, Amy, Morgan
      - generic [ref=e38]: "VAD: Silero"
      - generic [ref=e39]:
        - checkbox "Polish final captions" [ref=e40]
        - text: Polish final captions
      - generic [ref=e41]:
        - checkbox "Code-switch aware prompting" [ref=e42]
        - text: Code-switch aware prompting
      - generic [ref=e43]:
        - text: Partial interval (s)
        - spinbutton "Partial interval (s)" [ref=e44]: "2"
      - generic [ref=e45]:
        - text: Max utterance (s)
        - spinbutton "Max utterance (s)" [ref=e46]: "25"
      - generic [ref=e47]:
        - text: Silero threshold
        - spinbutton "Silero threshold" [ref=e48]: "0.5"
      - generic [ref=e49]:
        - text: Speech pad (ms)
        - spinbutton "Speech pad (ms)" [ref=e50]: "300"
      - generic [ref=e51]:
        - text: Min silence (ms)
        - spinbutton "Min silence (ms)" [ref=e52]: "400"
      - generic [ref=e53]:
        - button "Commit Now" [ref=e54] [cursor=pointer]
        - button "Queue EN/ES Swap" [ref=e55] [cursor=pointer]
        - button "Skip Next Polish" [disabled] [ref=e56]
      - generic [ref=e57]:
        - text: Projector font size
        - generic [ref=e58]:
          - slider "Projector font size 36px" [ref=e59]: "36"
          - generic [ref=e60]: 36px
  - generic [ref=e61]: "Inference failed: AST timed out after 8.0s"
  - main [ref=e62]:
    - region "English transcript" [ref=e63]:
      - generic [ref=e64]:
        - heading "English" [level=2] [ref=e66]
        - generic [ref=e67]:
          - paragraph [ref=e68]: How can I get to the station? I am meeting Amy and Morgan near Surreal Coffee after the talk.
          - paragraph [ref=e69]: How can I get to the station? I am meeting Amy and Morgan near the surreal coffee after the talk.
          - paragraph [ref=e70]: How can I get to the station? I am meeting Amy and Morgan near Surreal Coffee after the talk.
          - paragraph [ref=e71]: How can I get to the station? I am meeting Amy and Morgan near Surreal Coffee after the talk.
          - paragraph [ref=e72]: How can I get to the station? I am meeting Amy and Morgan near Surreal Coffee after the talk.
          - paragraph [ref=e73]: How can I get to the station? I am meeting Amy and Morgan near Surreal Coffee after the talk.
          - paragraph [ref=e74]: How can I get to the station? I am meeting Amy and Morgan near Surreal Coffee after the talk.
          - paragraph [ref=e75]: How can I get to the station? I am meeting Amy and Morgan near Surreal Coffee after the talk.
          - paragraph [ref=e76]
          - paragraph [ref=e77]
          - paragraph [ref=e78]
    - region "Spanish translation" [ref=e79]:
      - generic [ref=e80]:
        - heading "Spanish" [level=2] [ref=e82]
        - generic [ref=e83]:
          - paragraph [ref=e84]: ¿Cómo puedo llegar a la estación? Me reuniré con Amy y Morgan cerca de Surreal Coffee después de la charla.
          - paragraph [ref=e85]: ¿Cómo puedo ir a la estación? Me encuentro con Amy y Morgan cerca del café surrealista después de la charla.
          - paragraph [ref=e86]: ¿Cómo puedo llegar a la estación? Me encuentro con Amy y Morgan cerca de Surreal Coffee después de la charla.
          - paragraph [ref=e87]: ¿Cómo puedo llegar a la estación? Me encuentro con Amy y Morgan cerca de Surreal Coffee después de la charla.
          - paragraph [ref=e88]: ¿Cómo puedo llegar a la estación? Me reuniré con Amy y Morgan cerca de Surreal Coffee después de la charla.
          - paragraph [ref=e89]: ¿Cómo puedo llegar a la estación? Me reuniré con Amy y Morgan cerca de Surreal Coffee después de la charla.
          - paragraph [ref=e90]: ¿Cómo puedo ir a la estación? Me encuentro con Amy y Morgan cerca de Surreal Coffee después de la charla.
          - paragraph [ref=e91]: ¿Cómo puedo llegar a la estación? Me encuentro con Amy y Morgan cerca de Surreal Coffee después de la charla.
          - paragraph [ref=e92]
          - paragraph [ref=e93]
          - paragraph [ref=e94]
```

# Test source

```ts
  35  |   backend = spawn("uv", ["run", "python", "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8765"], {
  36  |     cwd: backendDir,
  37  |     env: { ...process.env, PYTHONUNBUFFERED: "1" },
  38  |     stdio: ["ignore", backendLog, backendLog],
  39  |   });
  40  |   frontend = spawn("yarn", ["dev"], {
  41  |     cwd: frontendDir,
  42  |     env: { ...process.env },
  43  |     stdio: ["ignore", frontendLog, frontendLog],
  44  |   });
  45  |   await waitForHttp(backendHealthUrl, 240_000);
  46  |   await waitForHttp(frontendUrl, 60_000);
  47  | });
  48  | 
  49  | test.afterAll(async () => {
  50  |   await stopProcess(frontend);
  51  |   await stopProcess(backend);
  52  | });
  53  | 
  54  | test("projector mirrors finalized captions without console errors or clipping", async ({ browser }) => {
  55  |   const consoleErrors: string[] = [];
  56  |   const operatorContext = await newContext(browser);
  57  |   const projectorContext = await newContext(browser);
  58  |   await operatorContext.route("**/*", async (route) => {
  59  |     if (new URL(route.request().url()).pathname !== "/__livetr3-test-audio.wav") {
  60  |       await route.continue();
  61  |       return;
  62  |     }
  63  |     await route.fulfill({ contentType: "audio/wav", body: fs.readFileSync(sampleWav) });
  64  |   });
  65  |   const operator = await operatorContext.newPage();
  66  |   const projector = await projectorContext.newPage();
  67  |   collectConsoleErrors(operator, consoleErrors);
  68  |   collectConsoleErrors(projector, consoleErrors);
  69  | 
  70  |   await operator.goto(`${frontendUrl}?test_audio_url=/__livetr3-test-audio.wav`);
  71  |   await operator.getByTestId("polish-toggle").setChecked(false);
  72  |   await operator.getByTestId("start-stop-button").click();
  73  |   await expect(operator.getByTestId("start-stop-button")).toHaveText("Stop", { timeout: 30_000 });
  74  |   await expect(operator.getByTestId("error-banner")).toHaveCount(0);
  75  | 
  76  |   const sessionId = await operator.getByTestId("app-shell").getAttribute("data-session-id");
  77  |   expect(sessionId).toBeTruthy();
  78  |   await projector.goto(`${frontendUrl}/projector?session=${sessionId}`);
  79  | 
  80  |   const samples: Array<{ id: number; text: string; delayMs: number }> = [];
  81  |   let lastId = 0;
  82  |   for (let index = 0; index < 5; index += 1) {
  83  |     const operatorFinal = await waitForOperatorFinal(operator, lastId);
  84  |     const projectorFinal = await waitForProjectorFinal(projector, operatorFinal.id);
  85  |     expect(projectorFinal.text).toBe(operatorFinal.text);
  86  |     samples.push({
  87  |       id: operatorFinal.id,
  88  |       text: operatorFinal.text,
  89  |       delayMs: projectorFinal.at - operatorFinal.at,
  90  |     });
  91  |     lastId = operatorFinal.id;
  92  |   }
  93  | 
  94  |   const p95DelayMs = percentile(samples.map((sample) => sample.delayMs), 0.95);
  95  |   expect(p95DelayMs).toBeLessThanOrEqual(300);
  96  | 
  97  |   const lastSample = samples.at(-1);
  98  |   expect(lastSample).toBeTruthy();
  99  |   const operatorText = await operator.getByTestId(`caption-translation-${lastSample!.id}`).innerText();
  100 |   const projectorText = await projector.getByTestId(`projector-caption-${lastSample!.id}`).innerText();
  101 |   expect(projectorText.trim()).toBe(operatorText.trim());
  102 | 
  103 |   await expectNoProjectorClipping(projector, { width: 1280, height: 720 });
  104 |   await projector.screenshot({ path: path.join(evidenceDir, "projector-1280x720.png"), fullPage: true });
  105 |   await expectNoProjectorClipping(projector, { width: 1920, height: 1080 });
  106 |   await projector.screenshot({ path: path.join(evidenceDir, "projector-1920x1080.png"), fullPage: true });
  107 |   await operator.screenshot({ path: path.join(evidenceDir, "operator-projector-smoke.png"), fullPage: true });
  108 | 
  109 |   expect(consoleErrors).toEqual([]);
  110 |   await operator.getByTestId("start-stop-button").click();
  111 | });
  112 | 
  113 | async function newContext(browser: Browser): Promise<BrowserContext> {
  114 |   const context = await browser.newContext({
  115 |     permissions: ["microphone"],
  116 |     viewport: { width: 1280, height: 720 },
  117 |   });
  118 |   await context.grantPermissions(["microphone"], { origin: frontendUrl });
  119 |   return context;
  120 | }
  121 | 
  122 | async function waitForOperatorFinal(page: Page, lastId: number): Promise<FinalRender> {
  123 |   const handle = await page.waitForFunction(
  124 |     (id) => {
  125 |       const event = window.__livetr3LastOperatorFinalRender;
  126 |       return event && event.id > id ? event : null;
  127 |     },
  128 |     lastId,
  129 |     { timeout: 180_000 },
  130 |   );
  131 |   return handle.jsonValue() as Promise<FinalRender>;
  132 | }
  133 | 
  134 | async function waitForProjectorFinal(page: Page, id: number): Promise<FinalRender> {
> 135 |   const handle = await page.waitForFunction(
      |                             ^ TimeoutError: page.waitForFunction: Timeout 30000ms exceeded.
  136 |     (expectedId) => {
  137 |       const event = window.__livetr3LastProjectorFinalRender;
  138 |       return event && event.id === expectedId ? event : null;
  139 |     },
  140 |     id,
  141 |     { timeout: 30_000 },
  142 |   );
  143 |   return handle.jsonValue() as Promise<FinalRender>;
  144 | }
  145 | 
  146 | async function expectNoProjectorClipping(
  147 |   page: Page,
  148 |   viewport: { width: number; height: number },
  149 | ): Promise<void> {
  150 |   await page.setViewportSize(viewport);
  151 |   await page.waitForTimeout(250);
  152 |   const clipped = await page.locator("[data-testid='projector-shell'] > div > div").evaluate((node) => {
  153 |     return node.scrollHeight > node.clientHeight || node.scrollWidth > node.clientWidth;
  154 |   });
  155 |   expect(clipped).toBe(false);
  156 | }
  157 | 
  158 | function collectConsoleErrors(page: Page, errors: string[]): void {
  159 |   page.on("console", (message) => {
  160 |     if (message.type() === "error") {
  161 |       errors.push(message.text());
  162 |     }
  163 |   });
  164 |   page.on("pageerror", (error) => errors.push(error.message));
  165 | }
  166 | 
  167 | async function waitForHttp(url: string, timeoutMs: number): Promise<void> {
  168 |   const deadline = Date.now() + timeoutMs;
  169 |   let lastError: unknown;
  170 |   while (Date.now() < deadline) {
  171 |     try {
  172 |       const response = await fetch(url, { signal: AbortSignal.timeout(2_000) });
  173 |       if (response.ok) return;
  174 |     } catch (error) {
  175 |       lastError = error;
  176 |     }
  177 |     await new Promise((resolve) => setTimeout(resolve, 1000));
  178 |   }
  179 |   throw new Error(`Timed out waiting for ${url}: ${String(lastError)}`);
  180 | }
  181 | 
  182 | async function stopProcess(process: ChildProcess | undefined): Promise<void> {
  183 |   if (!process || process.killed || process.exitCode !== null) return;
  184 |   process.kill("SIGTERM");
  185 |   await new Promise<void>((resolve) => {
  186 |     const timer = setTimeout(() => {
  187 |       process.kill("SIGKILL");
  188 |       resolve();
  189 |     }, 10_000);
  190 |     process.once("exit", () => {
  191 |       clearTimeout(timer);
  192 |       resolve();
  193 |     });
  194 |   });
  195 | }
  196 | 
  197 | function percentile(values: number[], pct: number): number {
  198 |   const sorted = [...values].sort((a, b) => a - b);
  199 |   const index = (sorted.length - 1) * pct;
  200 |   const lower = Math.floor(index);
  201 |   const upper = Math.min(lower + 1, sorted.length - 1);
  202 |   const fraction = index - lower;
  203 |   return sorted[lower] + (sorted[upper] - sorted[lower]) * fraction;
  204 | }
  205 | 
```