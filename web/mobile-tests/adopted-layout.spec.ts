import { expect, test as base, _android } from "@playwright/test";
import { adoptedPayloads } from "./adopted-fixture";
import process from "node:process";
import { readFile, writeFile } from "node:fs/promises";
import type { AndroidDevice } from "playwright";
let activeDevice: AndroidDevice | undefined;
const test = base.extend({
  page: async ({ page }, runPage) => {
    if (!process.env.STOCKAI_ANDROID_UI) { await runPage(page); return; }
    const devices = await _android.devices();
    const device = devices.find(d => d.serial() === "emulator-5554");
    if (!device) throw Error("Dedicated emulator is unavailable");
    activeDevice = device;
    await device.shell("am start -n org.chromium.webview_shell/.WebViewBrowserActivity");
    const webview = await device.webView({ pkg: "org.chromium.webview_shell" });
    const nativePage = await webview.page();
    await nativePage.goto("about:blank");
    await runPage(nativePage);
    await device.close();
  },
});
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const calls: { plugin: string; method: string; operation?: string }[] = [];
    let dailyStatus = { enabled: true, state: "waiting_cutoff", notificationsEnabled: true };
    Object.assign(window, {
      __settingsCalls: calls,
      CapacitorCustomPlatform: { name: "android" },
      Capacitor: {
        PluginHeaders: [
          { name: "StockAI", methods: ["appInfo", "compute", "keyStatus", "checkUpdate", "installUpdate", "dailyStatus", "saveApiKey", "clearApiKey", "stopDaily", "startDaily", "requestDailyNotifications", "analysisStatus", "readSavedView"].map(name => ({ name, rtype: "promise" })) },
          { name: "StockAIChatGPT", methods: [{ name: "getStatus", rtype: "promise" }] },
        ],
        nativePromise: async (plugin: string, method: string, options?: { method: string; path: string; body?: string }) => {
          calls.push({ plugin, method, operation: options?.method });
          if (method === "compute") return { status: 200, body: await (await fetch(options!.path, {
            method: options!.method, headers: { "Content-Type": "application/json" }, body: options!.method === "POST" ? options!.body : undefined,
          })).json() };
          if (method === "appInfo") return {applicationId:"jp.stockai.app",versionName:"test-build",versionCode:0};
          if (method === "analysisStatus") return {state:"idle"};
          if (method === "readSavedView") return {available:false};
          if (method === "keyStatus") return { configured: localStorage.getItem("settingsTestKey") !== "missing" };
          if (method === "checkUpdate") return localStorage.getItem("settingsTestUpdate") === "available" ? {
            available: true, versionName: "0.1.27-candidate", versionCode: 10027,
            notes: "試験用の長い変更内容です。".repeat(80), sha256: "a".repeat(64), url: "https://example.invalid/StockAI.apk", size: 123,
          } : { available: false };
          if (method === "installUpdate") return { needsPermission: true };
          if (method === "dailyStatus") return { ...dailyStatus, state: localStorage.getItem("settingsTestDailyState") ?? dailyStatus.state };
          if (method === "requestDailyNotifications") return { granted: dailyStatus.notificationsEnabled };
          if (method === "startDaily") return (dailyStatus = { ...dailyStatus, enabled: true, state: "queued" });
          if (method === "stopDaily") {
            if ((window as unknown as { __failSettingsStop?: boolean }).__failSettingsStop) throw new Error("合成停止エラー");
            return new Promise(resolve => Object.assign(window, { __finishSettingsStop: () => {
              dailyStatus = { ...dailyStatus, enabled: false, state: "paused" }; resolve(dailyStatus);
            } }));
          }
          if (method === "getStatus") return { connected: false, planEnabled: false, selection: { model: "", effort: "medium" }, models: [] };
          if (method === "saveApiKey") return new Promise<void>(resolve => Object.assign(window, { __finishSettingsSave: resolve }));
          throw new Error(`Unexpected native operation: ${plugin}.${method}`);
        },
      },
    });
  });
  const profile = { revision_id: "a".repeat(64), saved_at: "2026-10-20T09:00:00+09:00", portfolio: {
    schema_version: "manual-portfolio-v1", holdings_status: "none", investment_budget_yen: "500000",
    maximum_drawdown_percent: 10, accounts: [{ id: "synthetic-account", name: "試験用口座", account_type: "taxable_specified", withholding_mode: "withholding", available_cash_yen: "500000" }], holdings: [],
  } };
  const payloads: Record<string, unknown> = {
    "/api/v1/jobs": [],
    "/api/v1/settings": { runtimeMode: "TEST", data: {}, runtime: {} },
    "/api/v1/mobile/portfolio": profile,
    "/api/v1/mobile/personal/current": { ledger: null, profile, settings: null },
    "/api/v1/mobile/market": { latest_data_date: null, completed_dates: [] },
    "/api/v1/mobile/market/plan": { first_day: "2024-10-20", last_day: "2026-10-19" },
    "/api/v1/mobile/market/membership": { available_at_cutoff: false },
    "/api/v1/mobile/market/universe-policy": { mode: "legacy300", experimental: false },
    "/api/v1/mobile/models": { approved_bundle_count: 0, imported_bundle_count: 0, bundle_ready: false, model_adopted: false },
    "/api/v1/mobile/daily": null,
    "/api/v1/mobile/decision": null,
    "/api/v1/mobile/personal/settings": { saved: null, current_portfolio: profile },
    "/api/v1/mobile/personal/readiness": { input_gaps: ["accounts"], initial_ledger: {
      blocking_reasons: ["accounts"], prices: { date: null, prices: {} }, portfolio: null,
    }, comparison: { blocking_reasons: [{ code: "FORECAST_MISSING" }], research_only: true } },
  };
  Object.assign(payloads, adoptedPayloads(profile));
  await page.route("**/api/**", route => {
    if (route.request().method() !== "GET" && !route.request().url().endsWith("/review")) throw new Error("Unexpected write in read-only settings fixture");
    const path = new URL(route.request().url()).pathname;
    if (!(path in payloads)) throw new Error(`Unexpected fixture API: ${path}`);
    return route.fulfill({ json: payloads[path] });
  });
  await page.goto("http://127.0.0.1:5196/#/settings");
  await expect(page.getByRole("heading", { name: "設定", exact: true })).toBeVisible();
});


const screens = [
  ["home", "/", "ホーム"], ["today", "/today", "今日"], ["ranking", "/ranking", "ランキング"], ["review", "/validation", "検証"], ["settings", "/settings", "設定"],
  ["detail", "/stocks/1234", "銘柄詳細"], ["asset-manage", "/assets", "資産管理"], ["asset-register", "/holdings?initial=1", "初回資産登録"],
  ["cash-change", "/assets/cash", "現金残高の変更"], ["holding-correction", "/holdings", "保有の訂正"], ["correction-history", "/assets/history", "残高・修正履歴"],
  ["trade", "/today/executions", "取引記録"], ["trade-history", "/transactions", "取引履歴"], ["decision", "/today/review", "判断を確認"],
  ["consultation", "/today/chatgpt", "ChatGPTと相談"], ["consultation-history", "/today/chatgpt/history", "相談履歴"],
  ["conditions-settings", "/settings?edit=conditions", "運用条件"], ["account-settings", "/settings?edit=taxes", "口座・税・手数料"],
  ["data-update", "/settings?edit=daily", "データ更新"], ["chatgpt-settings", "/settings?edit=chatgpt", "ChatGPT"],
  ["backup", "/settings?edit=backup", "バックアップ・復元"], ["app-info", "/settings?edit=about", "アプリ情報・詳細"],
  ["model-management", "/settings?edit=model", "モデル管理"], ["data-repair", "/settings?edit=repair", "市場データの修復"],
  ["calculation-method", "/settings?edit=method", "計算方式"], ["csv-import", "/settings/csv", "CSV取り込み"], ["process-log", "/settings/logs", "処理状況・実行記録"],
  ["performance-analysis", "/validation/details", "詳細分析"], ["research-history", "/stocks/1234/research", "調査履歴"],
];

test("settings keeps its content while all five tabs share adopted navigation",async({page},info)=>{
  test.setTimeout(90_000);
  const properties=["fontFamily","fontSize","lineHeight","paddingTop","paddingRight","paddingBottom","paddingLeft","borderRadius","backgroundColor"];
  for(const width of (process.env.STOCKAI_ANDROID_UI ? [320] : [320,390])){
    if(!process.env.STOCKAI_ANDROID_UI)await page.setViewportSize({width,height:800});
    for(const font of [100,150]){
      let expected:unknown;
      for(const [name,path,title] of screens.slice(0,5)){
        await page.goto(`http://127.0.0.1:5196/#${path}`);
        await page.addStyleTag({content:`html{font-size:${font}%}`});
        await expect(page.getByRole("heading",{name:title,exact:true,level:1})).toBeVisible();
        const nav=page.getByRole("navigation",{name:"メインナビゲーション"});
        await expect(nav.getByRole("link")).toHaveText(["ホーム","今日","ランキング","検証","設定"]);
        await expect(nav.getByRole("link",{name:title,exact:true})).toHaveAttribute("aria-current","page");
        const actual=await nav.evaluate((node,props)=>{
          const style=(element:Element)=>{const css=getComputedStyle(element);return Object.fromEntries(props.map(key=>[key,css[key as keyof CSSStyleDeclaration]]));};
          const rect=node.getBoundingClientRect();
          return {style:style(node),width:rect.width,height:rect.height,bottom:rect.bottom,
            links:[...node.querySelectorAll("a")].map(link=>({style:style(link),icon:link.querySelector("path")?.getAttribute("d")})),
            active:style(node.querySelector("a.active")!),
            activeLabelWeight:getComputedStyle(node.querySelector("a.active strong")!).fontWeight};
        },properties);
        if(expected)expect(actual,`${name} ${width}px ${font}%`).toEqual(expected);else expected=actual;
        // WebView's visual height can contain a fractional CSS pixel; innerHeight is integer-rounded.
        expect(actual.bottom).toBeCloseTo(await page.evaluate(()=>visualViewport?.height ?? innerHeight),3);
        if(name==="settings"){
          await expect(page.locator(".app-shell--adopted")).toHaveCount(0);
          expect(await page.locator(".settings-menu-row").count()).toBeGreaterThan(0);
          if(process.env.STOCKAI_ANDROID_UI)await writeFile(info.outputPath(`settings-nav-${width}-${font}.png`),await activeDevice!.screenshot());
          else await page.screenshot({path:info.outputPath(`settings-nav-${width}-${font}.png`),fullPage:true});
          expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
        }
      }
    }
  }
});

for (const width of (process.env.STOCKAI_ANDROID_UI ? [320] : [320,390])) test(`29 adopted screens ${width}px`, async ({page}, info) => {
  test.setTimeout(180_000);
  if(process.env.STOCKAI_ANDROID_UI)expect(await page.evaluate(()=>window.innerWidth)).toBe(width);
  else await page.setViewportSize({width,height:800});
  const errors: string[]=[]; page.on("pageerror", e=>errors.push(e.message));
  for (const [name,path,title] of screens) {
    await page.goto(`http://127.0.0.1:5196/#${path}`);
    await expect(page.getByRole("heading",{name:title,exact:true,level:1})).toBeVisible();
    await expect(page.getByText(/読み込んでいます|現在残高を確認しています|モデルを確認中|判断内容を準備しています|実行結果入力を準備しています|今日の状態を確認しています|保存済み入力を確認しています/).filter({visible:true})).toHaveCount(0);
    await expect(page.getByRole("navigation",{name:"メインナビゲーション"}).getByRole("link")).toHaveCount(5);
    for (const font of [100,150]) {
      await page.addStyleTag({content:`html{font-size:${font}%}`});
      await page.evaluate(()=>document.querySelector(".app-main")!.scrollTo(0,0));
      expect(await page.evaluate(()=>document.documentElement.scrollWidth), `${name} at ${font}%`).toBeLessThanOrEqual(width);
      expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth),`${name} main horizontal scroll`).toBeLessThanOrEqual(1);
      const overflow = await page.locator('input:visible,select:visible,textarea:visible,button:visible,a.button:visible').evaluateAll(nodes=>nodes.filter(n=>{const r=n.getBoundingClientRect();return r.left < -1 || r.right > window.innerWidth+1}).map(n=>n.outerHTML.slice(0,150)));
      expect(overflow, `${name} controls`).toEqual([]);
      const overlaps=await page.locator('input:visible,select:visible,textarea:visible,button:visible,a.button:visible').evaluateAll(nodes=>{
        const controls=nodes.map(node=>({node,r:node.getBoundingClientRect()})).filter(({r})=>r.width>0 && r.height>0);
        const result:string[]=[];
        for(let i=0;i<controls.length;i++)for(let j=i+1;j<controls.length;j++){
          const a=controls[i],b=controls[j];if(a.node.contains(b.node)||b.node.contains(a.node))continue;
          if(Math.min(a.r.right,b.r.right)-Math.max(a.r.left,b.r.left)>2 && Math.min(a.r.bottom,b.r.bottom)-Math.max(a.r.top,b.r.top)>2)result.push(`${a.node.outerHTML.slice(0,80)} / ${b.node.outerHTML.slice(0,80)}`);
        }return result;
      });
      expect(overlaps,`${name} overlapping controls`).toEqual([]);
      if (process.env.STOCKAI_ANDROID_UI) {
        for (const position of [0,0.5,1]) {
          await page.evaluate(p=>{const main=document.querySelector(".app-main")!;main.scrollTo(0,(main.scrollHeight-main.clientHeight)*p);},position);
          await writeFile(info.outputPath(`${name}-${font}-${position}.png`), await activeDevice!.screenshot());
        }
      } else await page.screenshot({path:info.outputPath(`${name}-${font}.png`),fullPage:true});
    }
  }
  expect(errors).toEqual([]);
});

test("unregistered home keeps the adopted layout and real registration route",async({page},info)=>{
  await page.route("**/api/v1/home",route=>route.fulfill({json:{runtimeMode:"TEST",portfolio:null,holdings:[],initialLedger:null}}));
  if(!process.env.STOCKAI_ANDROID_UI)await page.setViewportSize({width:320,height:800});
  await page.goto("http://127.0.0.1:5196/#/");
  await expect(page.locator(".screen-home")).toBeVisible();
  await expect(page.getByRole("region",{name:"資産残高"})).toContainText("資産はまだ登録されていません");
  await expect(page.getByRole("heading",{name:"毎日の自動処理"})).toHaveCount(0);
  await expect(page.getByRole("link",{name:"初回資産登録",exact:true})).toHaveAttribute("href","#/holdings?initial=1");
  for(const font of [100,150]){
    await page.addStyleTag({content:`html{font-size:${font}%}`});
    expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
    if(process.env.STOCKAI_ANDROID_UI)await writeFile(info.outputPath(`unregistered-home-${font}.png`),await activeDevice!.screenshot());
    else await page.screenshot({path:info.outputPath(`unregistered-home-${font}.png`),fullPage:true});
  }
  await page.getByRole("link",{name:"初回資産登録",exact:true}).click();
  await expect(page.getByRole("heading",{name:"初回資産登録",exact:true})).toBeVisible();
});

test("new ChatGPT consultation copies and opens a report without answer import",async({page},info)=>{
  const exported={input_record_id:"synthetic-report",input_snapshot_id:"synthetic-report-input",expires_at:"2026-10-26T18:00:00+09:00",prompt:"SYNTHETIC_UI_TEST: 日本語の本文・表・出典で分析を読みます。",response_mode:"chatgpt-readable-report-v1"};
  let saved:typeof exported|null=null;
  let writes=0;
  const clipboardMock=()=>Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:async(value:string)=>{Object.assign(window,{__reportCopied:value});}}});
  await page.addInitScript(clipboardMock);
  // This app uses hash routes, so the already loaded document also needs the boundary mock.
  await page.evaluate(clipboardMock);
  await page.route("**/api/v1/mobile/chatgpt-manual/status",route=>route.fulfill({json:{ready:true,reason:null,saved_input:saved,selected_input:saved?.input_record_id ?? null,answers:[]}}));
  await page.route("**/api/v1/mobile/chatgpt-manual/export",route=>{
    expect(route.request().postDataJSON()).toMatchObject({personal_analysis_only:true,training_disabled:true,data_entitlement_confirmed:true});
    writes++;saved=exported;return route.fulfill({json:exported});
  });
  if(!process.env.STOCKAI_ANDROID_UI)await page.setViewportSize({width:320,height:800});
  await page.goto("http://127.0.0.1:5196/#/today/chatgpt");
  const create=page.getByRole("button",{name:"作成・コピー",exact:true});
  await expect(create).toBeDisabled();
  await page.getByRole("checkbox").check();
  await create.click();
  await expect(page.getByRole("textbox",{name:"ChatGPTへ渡す入力"})).toHaveValue(exported.prompt);
  expect(await page.evaluate(()=>(window as unknown as {__reportCopied:string}).__reportCopied)).toBe(exported.prompt);
  await expect(page.getByRole("textbox",{name:"ChatGPTの回答JSON"})).toHaveCount(0);
  await expect(page.getByRole("button",{name:"検証・保存"})).toHaveCount(0);
  await expect(page.getByRole("link",{name:"ChatGPTを開く",exact:true})).toHaveAttribute("href","https://chatgpt.com/");
  expect(writes).toBe(1);
  for(const font of [100,150]){
    await page.addStyleTag({content:`html{font-size:${font}%}`});
    expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
    await page.getByRole("link",{name:"ChatGPTを開く",exact:true}).scrollIntoViewIfNeeded();
    if(process.env.STOCKAI_ANDROID_UI)await writeFile(info.outputPath(`external-report-${font}.png`),await activeDevice!.screenshot());
    else await page.screenshot({path:info.outputPath(`external-report-${font}.png`),fullPage:true});
  }
});

test("adopted HTML typography and controls match the implementation",async({page},info)=>{
  test.skip(!!process.env.STOCKAI_ANDROID_UI,"Reference CSS comparison runs in Edge; Android runs all route and overlap checks.");
  test.setTimeout(180_000);
  await page.setViewportSize({width:390,height:844});
  const source=await readFile("../../.codex-remote-attachments/01a175f6-f76f-70a1-a798-51257e37d7de/e3e392c4-ea41-48cd-b708-9a30cd048fd1/1-stock-ui-mock-offline.html","utf8");
  const reference=await page.context().newPage();
  await reference.setViewportSize({width:390,height:844});
  await reference.route("**/adopted-reference*",route=>route.fulfill({contentType:"text/html",body:source}));
  const selectors=[".card",".section-title","input.input","select.input","textarea.input",".button:not(.secondary):not(.button--secondary):not(.ghost)",".button.secondary,.button--secondary",".button.ghost",".home-balance-line",".ranking-table-row",".ss-group"];
  const properties=["fontFamily","fontSize","fontWeight","lineHeight","paddingTop","paddingRight","paddingBottom","paddingLeft","borderRadius","borderTopColor"];
  const evidence:unknown[]=[];
  const differences:unknown[]=[];
  for(const [name,path] of screens.filter(([name])=>name!=="settings")){
    await page.goto(`http://127.0.0.1:5196/#${path}`);
    await expect(page.locator(".page h1,.settings-page-header h1").filter({visible:true})).toBeVisible();
    await expect(page.getByText(/読み込んでいます|現在残高を確認しています|モデルを確認中|判断内容を準備しています|実行結果入力を準備しています|今日の状態を確認しています|保存済み入力を確認しています/).filter({visible:true})).toHaveCount(0);
    await reference.goto(`http://127.0.0.1:5196/adopted-reference?screen=${name}#${name}`);
    await reference.locator(".app-screen").waitFor();
    for(const selector of selectors){
      const actual=page.locator(".app-main").locator(selector).filter({visible:true}).first();
      const expected=reference.locator(".app-screen").locator(selector).filter({visible:true}).first();
      if(!await actual.count() || !await expected.count())continue;
      const read=(node:Element,props:string[])=>{const style=getComputedStyle(node);return Object.fromEntries(props.map(p=>[p,style[p as keyof CSSStyleDeclaration]]));};
      const observed=await actual.evaluate(read,properties), accepted=await expected.evaluate(read,properties);
      evidence.push({screen:name,selector,observed,accepted});
      if(JSON.stringify(observed)!==JSON.stringify(accepted))differences.push({screen:name,selector,observed,accepted});
    }
  }
  await writeFile(info.outputPath("mock-style-comparison.json"),JSON.stringify(evidence,null,2));
  expect(evidence.length).toBeGreaterThan(60);
  expect(differences).toEqual([]);
  await reference.close();
});

test("ranking detail returns with model, filter and scroll intact", async ({page})=>{
  await page.goto("http://127.0.0.1:5196/#/ranking");
  await page.getByRole("button",{name:"20日・値予測",exact:true}).click();
  await page.getByRole("searchbox").fill("画面試験");
  const stock=page.locator(".ranking-table-row").nth(12);
  // Use the shared detail route with a fixture for this selected symbol.
  await page.route("**/api/v1/stocks/1246", route=>route.fulfill({json:{positions:[],proposalLines:[],forecast:null,researchRuns:[],chatgptResearch:[]}}));
  await stock.scrollIntoViewIfNeeded();
  const y=await page.evaluate(()=>document.querySelector(".app-main")!.scrollTop);
  await stock.click(); await page.getByRole("link",{name:"← 戻る",exact:true}).click();
  await expect(page.getByRole("searchbox")).toHaveValue("画面試験");
  await expect(page.getByRole("button",{name:"20日・値予測",exact:true})).toHaveAttribute("aria-pressed","true");
  await expect.poll(()=>page.evaluate(()=>document.querySelector(".app-main")!.scrollTop)).toBeGreaterThan(y-5);
});

test("returning to a settings editor preserves an unsaved draft", async ({page})=>{
  await page.goto("http://127.0.0.1:5196/#/settings?edit=capital");
  const input=page.getByLabel("投資上限（円・未定は空欄）");
  await expect(input).toBeEnabled();
  await input.fill("730000");
  await page.getByRole("navigation",{name:"メインナビゲーション"}).getByRole("link",{name:"ホーム",exact:true}).click();
  await expect(page.getByRole("heading",{name:"ホーム",exact:true,level:1})).toBeVisible();
  await page.goBack();
  await expect(input).toHaveValue("730000");
});

test("unregistered assets show the real initial cash and holding form", async ({page},info)=>{
  await page.route("**/api/v1/mobile/personal/current",route=>route.fulfill({json:{ledger:null,profile:null,settings:null}}));
  await page.goto("http://127.0.0.1:5196/#/holdings?initial=1");
  await expect(page.getByLabel("現金残高（円）")).toBeVisible();
  await page.getByRole("button",{name:"保有株を追加",exact:true}).click();
  await expect(page.getByLabel("銘柄コード",{exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(await page.evaluate(()=>window.innerWidth));
  if(process.env.STOCKAI_ANDROID_UI)await writeFile(info.outputPath("initial-unregistered.png"),await activeDevice!.screenshot());
  else await page.screenshot({path:info.outputPath("initial-unregistered.png")});
});

test("execution history retains the selected record when returning from stock detail",async({page})=>{
  await page.goto("http://127.0.0.1:5196/#/transactions");
  await page.getByRole("button",{name:"記録を確認",exact:true}).first().click();
  const selected=page.url();
  await page.getByRole("link",{name:"銘柄詳細",exact:true}).click();
  await page.getByRole("link",{name:"← 戻る",exact:true}).click();
  await expect(page).toHaveURL(selected);
  await expect(page.getByRole("button",{name:"記録を確認",exact:true}).first()).toHaveAttribute("aria-pressed","true");
});

test("judgment source and unsaved adoption survive stock detail and return",async({page})=>{
  await page.goto("http://127.0.0.1:5196/#/today/review?source=model");
  const choice=page.getByRole("button",{name:"画面試験株式会社の提案を採用",exact:true});
  await expect(choice).toHaveAttribute("aria-pressed","true");
  await choice.click();
  await expect(choice).toHaveAttribute("aria-pressed","false");
  await page.getByRole("link",{name:"画面試験株式会社",exact:true}).click();
  await page.getByRole("link",{name:"← 戻る",exact:true}).click();
  await expect(choice).toHaveAttribute("aria-pressed","false");
  await expect(page.getByRole("button",{name:"数値モデル",exact:true})).toHaveAttribute("aria-pressed","true");
});
