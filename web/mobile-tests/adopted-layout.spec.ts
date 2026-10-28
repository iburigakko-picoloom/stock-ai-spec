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
    const device = devices.find(d => d.serial() === (process.env.STOCKAI_ANDROID_SERIAL ?? "emulator-5554"));
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
    const calls: { plugin: string; method: string; operation?: string; path?: string }[] = [];
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
          calls.push({ plugin, method, operation: options?.method, path: options?.path });
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
  payloads["/api/v1/home/ledger"]=payloads["/api/v1/home"];
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

test("stock details fit narrow screens with large position values", async ({page}) => {
  if (!process.env.STOCKAI_ANDROID_UI) await page.setViewportSize({width:320,height:800});
  const payload = adoptedPayloads({})["/api/v1/stocks/1234"] as {positions: {shares:number; market_price:string}[]};
  payload.positions[0].shares = 10000;
  payload.positions[0].market_price = "12345";
  await page.route("**/api/v1/stocks/1234", route => route.fulfill({json:payload}));
  await page.goto("http://127.0.0.1:5196/#/stocks/1234");
  await expect(page.getByRole("heading", {name:"銘柄詳細",exact:true})).toBeVisible();
  await expect(page.getByText("¥123,450,000", {exact:true})).toBeVisible();
  await page.addStyleTag({content:"html{font-size:150%}"});
  expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
});

for (const width of (process.env.STOCKAI_ANDROID_UI ? [320] : [320,390])) test(`forecast lines fit ${width}px and show both horizons`, async ({page},info) => {
  if (!process.env.STOCKAI_ANDROID_UI) await page.setViewportSize({width,height:800});
  let calls=0;
  await page.route("**/api/v1/mobile/stocks/1234/forecast-history?*", route=>{
    calls++;
    return route.fulfill({json:{symbol:"1234",firstDate:"2026-02-01",lastDate:"2026-03-01",
      forecasts:Array.from({length:12},(_,i)=>({runId:`run-${i}`,kind:"daily",date:`2026-02-${String(i+1).padStart(2,"0")}`,generatedAt:`2026-02-${String(i+1).padStart(2,"0")}T02:30:00Z`,return5d:.02,return20d:-.05}))}});
  });
  await page.goto("http://127.0.0.1:5196/#/stocks/1234");
  const chart=page.getByRole("region",{name:"モデル予測の推移"});
  await expect(chart.getByRole("img",{name:"5日と20日の保存予測の折れ線グラフ"})).toBeVisible();
  expect(calls).toBe(1);
  await expect(chart.getByText("5日 +2.00% / 20日 -5.00%").first()).toBeVisible();
  expect(await chart.locator("circle[data-series='5日']").count()).toBe(12);
  expect(await chart.locator("polygon[data-series='20日']").count()).toBe(12);
  expect(await chart.locator(".forecast-line-segment").count()).toBe(22);
  expect(await chart.locator(".forecast-plot-scroll").evaluate(node=>node.scrollWidth>node.clientWidth)).toBe(true);
  for (const font of [100,150]) {
    await page.addStyleTag({content:`html{font-size:${font}%}`});
    expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
    const overflow=await chart.locator("button,.forecast-plot-scroll").evaluateAll(nodes=>nodes.filter(node=>{
      const r=node.getBoundingClientRect();return r.left < -1 || r.right > window.innerWidth+1;
    }).map(node=>node.outerHTML.slice(0,100)));
    expect(overflow).toEqual([]);
    if (!process.env.STOCKAI_ANDROID_UI && font===150) await chart.locator(".forecast-plot-frame").screenshot({path:info.outputPath(`forecast-lines-${width}.png`)});
  }
});

test("ranking initially shows 20 and finds analyzed stocks beyond the top 20",async({page})=>{
  await page.goto("http://127.0.0.1:5196/#/ranking");
  await expect(page.locator(".ranking-table-row")).toHaveCount(20);
  await expect(page.getByText("上位20件 · 20 / 24銘柄")).toBeVisible();
  await page.getByRole("searchbox").fill("画面試験24株式会社");
  const row=page.locator('.ranking-table-row[href="#/stocks/1257"]');
  await expect(row).toBeVisible();
  await expect(row.getByLabel("24位")).toBeVisible();
  await page.getByRole("searchbox").fill("");
  await expect(page.locator(".ranking-table-row")).toHaveCount(20);
});

test("ranking detail explains the selected snapshot even when another forecast is active",async({page})=>{
  if (!process.env.STOCKAI_ANDROID_UI) await page.setViewportSize({width:320,height:800});
  const snapshot="a".repeat(64);
  const ranking=adoptedPayloads({})["/api/v1/mobile/ranking/5d"] as Record<string,unknown>;
  await page.route("**/api/v1/mobile/ranking/5d",route=>route.fulfill({json:{...ranking,snapshotId:snapshot,metrics:{"1234":{return5d:.12,return20d:.15,rank20d:2.5}}}}));
  let explained="";
  await page.route("**/api/v1/mobile/stocks/1234/explanation?*",route=>{
    explained=new URL(route.request().url()).searchParams.get("snapshot") ?? "";
    return route.fulfill({json:{symbol:"1234",snapshotId:snapshot,asOf:"2026-10-26T11:30:00+09:00",method:"one_feature_training_median_replacement_v1",models:[
      {horizon:5,role:"return",available:true,prediction:.02,positive:[{feature:"price.return_5d",difference:.003,rankChange:null}],negative:[]},
      {horizon:20,role:"return",available:false},{horizon:20,role:"ranking",available:false}]}});
  });
  await page.goto("http://127.0.0.1:5196/#/ranking");
  await page.getByRole("searchbox").fill("画面試験1株式会社");
  await page.locator('.ranking-table-row[href="#/stocks/1234"]').click();
  const preview=page.locator("section").filter({has:page.getByRole("heading",{name:"ランキングで選んだ保存予測"})});
  await expect(preview.getByText("+12.00%")).toBeVisible();
  await expect(preview.getByText("+15.00%")).toBeVisible();
  await expect(preview.getByText("2.50")).toBeVisible();
  await expect(page.getByText("この欄はランキングで選択したものとは別の保存予測です。")).toBeVisible();
  const section=page.getByRole("region",{name:"予測に影響した特徴量"});
  await expect(section.getByText("ランキングで選択した保存予測の要因です。")).toBeVisible();
  await section.getByRole("button",{name:"予測の要因を見る"}).click();
  await expect(section.getByText("5日の騰落率")).toBeVisible();
  expect(explained).toBe(snapshot);
  await page.addStyleTag({content:"html{font-size:150%}"});
  expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
  await page.getByRole("link",{name:"← 戻る",exact:true}).click();
  await expect(page.getByRole("searchbox")).toHaveValue("画面試験1株式会社");
});

test("a ranking-only stock keeps the exact reference and explanation even without an active detail",async({page})=>{
  const snapshot="b".repeat(64);
  const ranking=adoptedPayloads({})["/api/v1/mobile/ranking/5d"] as Record<string,unknown>;
  await page.route("**/api/v1/mobile/ranking/5d",route=>route.fulfill({json:{...ranking,snapshotId:snapshot}}));
  await page.route("**/api/v1/stocks/1234",route=>route.fulfill({json:null}));
  await page.route("**/api/v1/mobile/stocks/1234/explanation?*",route=>route.fulfill({json:{
    symbol:"1234",snapshotId:snapshot,asOf:"2026-10-26T11:30:00+09:00",method:"one_feature_training_median_replacement_v1",
    models:[{horizon:5,role:"return",available:true,prediction:.02,positive:[{feature:"price.return_5d",difference:.003,rankChange:null}],negative:[]},
      {horizon:20,role:"return",available:false},{horizon:20,role:"ranking",available:false}],
  }}));
  await page.goto("http://127.0.0.1:5196/#/ranking");
  await page.locator('.ranking-table-row[href="#/stocks/1234"]').click();
  await expect(page.getByText("銘柄情報を取得できません")).toBeVisible();
  await expect(page.getByRole("heading",{name:"ランキングで選んだ保存予測"})).toBeVisible();
  const section=page.getByRole("region",{name:"予測に影響した特徴量"});
  await section.getByRole("button",{name:"予測の要因を見る"}).click();
  await expect(section.getByText("5日の騰落率")).toBeVisible();
});

test("returning to home requests daily status once for one foreground event burst", async ({page}) => {
  await page.goto("/");
  await expect(page.locator(".header-status")).toBeVisible();
  const count = () => page.evaluate(() => (window as unknown as {__settingsCalls:{method:string}[]}).__settingsCalls.filter(call => call.method === "dailyStatus").length);
  const before = await count();
  await page.evaluate(() => { document.dispatchEvent(new Event("visibilitychange")); window.dispatchEvent(new Event("focus")); });
  await expect.poll(count).toBe(before + 1);
  await page.waitForTimeout(200);
  expect(await count()).toBe(before + 1);
});

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
  await page.route(/\/api\/v1\/home(?:\/ledger)?$/,route=>route.fulfill({json:{runtimeMode:"TEST",portfolio:null,holdings:[],initialLedger:null}}));
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
  const exported={input_record_id:"synthetic-report",input_snapshot_id:"synthetic-report-input",expires_at:"2026-10-26T18:00:00+09:00",prompt:"SYNTHETIC_UI_TEST: 日本語の本文・表・出典で分析を読みます。",response_mode:"chatgpt-readable-report-v2"};
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
  // Golden values were measured from the user-provided accepted HTML. Keeping
  // only CSS properties here avoids shipping its demo data and scripts.
  const golden=JSON.parse(await readFile("mobile-tests/adopted-style-golden.json","utf8")) as {rows:{screen:string;selector:string;accepted:Record<string,string>}[]};
  expect(golden.rows.length).toBe(104);
  const properties=["fontFamily","fontSize","fontWeight","lineHeight","paddingTop","paddingRight","paddingBottom","paddingLeft","borderRadius","borderTopColor"];
  const evidence:unknown[]=[];
  const differences:unknown[]=[];
  for(const [name,path] of screens.filter(([name])=>name!=="settings")){
    await page.goto(`http://127.0.0.1:5196/#${path}`);
    await expect(page.locator(".page h1,.settings-page-header h1").filter({visible:true})).toBeVisible();
    await expect(page.getByText(/読み込んでいます|現在残高を確認しています|モデルを確認中|判断内容を準備しています|実行結果入力を準備しています|今日の状態を確認しています|保存済み入力を確認しています/).filter({visible:true})).toHaveCount(0);
    for(const item of golden.rows.filter(row=>row.screen===name)){
      const matching=name==="decision" && item.selector.startsWith(".button") ? `.subactions ${item.selector}` : item.selector;
      const actual=page.locator(".app-main").locator(matching).filter({visible:true}).first();
      if(!await actual.count())continue;
      const observed=await actual.evaluate((node,props)=>{const style=getComputedStyle(node);return Object.fromEntries(props.map(p=>[p,style[p as keyof CSSStyleDeclaration]]));},properties);
      evidence.push({screen:name,selector:item.selector,observed,accepted:item.accepted});
      if(JSON.stringify(observed)!==JSON.stringify(item.accepted))differences.push({screen:name,selector:item.selector,observed,accepted:item.accepted});
    }
  }
  await writeFile(info.outputPath("mock-style-comparison.json"),JSON.stringify(evidence,null,2));
  expect(evidence.length).toBeGreaterThan(60);
  expect(differences).toEqual([]);
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

test("numeric judgment and unsaved adoption survive stock detail and return",async({page})=>{
  await page.goto("http://127.0.0.1:5196/#/today/review?source=model");
  const choice=page.getByRole("button",{name:"画面試験株式会社の提案を採用",exact:true});
  await expect(choice).toHaveAttribute("aria-pressed","true");
  await choice.click();
  await expect(choice).toHaveAttribute("aria-pressed","false");
  await page.getByRole("link",{name:"画面試験株式会社",exact:true}).click();
  await page.getByRole("link",{name:"← 戻る",exact:true}).click();
  await expect(choice).toHaveAttribute("aria-pressed","false");
  await expect(page.getByRole("button",{name:"ChatGPT",exact:true})).toHaveCount(0);
  await expect(page).toHaveURL(/#\/today\/review$/);
});

test("stock memo persists across detail navigation and fits narrow screens",async({page},info)=>{
  let saved={symbol:"1234",text:"",revision:null as string|null,updatedAt:null as string|null};
  let writes=0;
  await page.route("**/api/v1/stocks/1234/note",route=>{
    if(route.request().method()==="POST"){
      expect(route.request().postDataJSON()).toEqual({text:"決算発表後に確認\n自分の判断を記録",expectedRevision:saved.revision});
      saved={...saved,text:route.request().postDataJSON().text,revision:"c".repeat(64),updatedAt:"2026-10-26T19:00:00+09:00"};writes++;
    }
    return route.fulfill({json:saved});
  });
  if(!process.env.STOCKAI_ANDROID_UI)await page.setViewportSize({width:320,height:800});
  await page.goto("http://127.0.0.1:5196/#/stocks/1234");
  const memo=page.getByRole("region",{name:"銘柄メモ"});
  await expect(memo.getByRole("textbox",{name:"メモ",exact:true})).toBeEnabled();
  await memo.getByRole("textbox",{name:"メモ",exact:true}).fill("決算発表後に確認\n自分の判断を記録");
  await memo.getByRole("button",{name:"メモを保存",exact:true}).click();
  await expect(memo.getByRole("status")).toHaveText("メモを保存しました。");
  for(const font of [100,150]){
    await page.addStyleTag({content:`html{font-size:${font}%}`});
    await memo.getByRole("button",{name:"メモを保存",exact:true}).scrollIntoViewIfNeeded();
    expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
    const input=await memo.getByRole("textbox").boundingBox(),button=await memo.getByRole("button").boundingBox();
    expect(input!.y+input!.height).toBeLessThanOrEqual(button!.y);
    if(process.env.STOCKAI_ANDROID_UI)await writeFile(info.outputPath(`stock-memo-${font}.png`),await activeDevice!.screenshot());
    else await page.screenshot({path:info.outputPath(`stock-memo-${font}.png`),fullPage:true});
  }
  await page.getByRole("navigation",{name:"メインナビゲーション"}).getByRole("link",{name:"ランキング",exact:true}).click();
  await page.locator('.ranking-table-row[href="#/stocks/1234"]').click();
  await expect(memo.getByRole("textbox",{name:"メモ",exact:true})).toHaveValue(saved.text);
  expect(writes).toBe(1);
});

test("execution entry uses one saved context without waiting for today recalculation",async({page},info)=>{
  const reads:string[]=[];
  page.on("request",request=>{if(request.method()==="GET" && request.url().includes("/api/"))reads.push(new URL(request.url()).pathname);});
  if(!process.env.STOCKAI_ANDROID_UI)await page.setViewportSize({width:320,height:800});
  await page.goto("http://127.0.0.1:5196/#/today/executions");
  await expect(page.getByRole("heading",{name:"取引記録",exact:true})).toBeVisible();
  await page.getByRole("combobox",{name:"実行状態",exact:true}).selectOption("filled");
  await expect(page.getByLabel("約定株数",{exact:true})).toBeVisible();
  expect(reads.filter(path=>path==="/api/v1/execution-context")).toHaveLength(1);
  expect(reads.filter(path=>path==="/api/v1/today" || path.endsWith("/decision"))).toEqual([]);
  for(const font of [100,150]){
    await page.addStyleTag({content:`html{font-size:${font}%}`});
    expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
    if(process.env.STOCKAI_ANDROID_UI)await writeFile(info.outputPath(`execution-context-${font}.png`),await activeDevice!.screenshot());
    else await page.screenshot({path:info.outputPath(`execution-context-${font}.png`),fullPage:true});
  }
});

test("home and assets show saved balances with no forecast read and no duplicate balance request",async({page})=>{
  const reads:string[]=[];page.on("request",request=>{if(request.method()==="GET" && request.url().includes("/api/"))reads.push(new URL(request.url()).pathname);});
  await page.goto("http://127.0.0.1:5196/#/");
  await expect(page.getByRole("region",{name:"資産残高"})).toContainText("600,000");
  expect(reads.filter(path=>path==="/api/v1/home/ledger")).toHaveLength(1);
  expect(reads.filter(path=>path==="/api/v1/home" || path==="/api/v1/today")).toEqual([]);
  reads.length=0;
  await page.getByRole("link",{name:"資産を管理 ›",exact:true}).click();
  await expect(page.getByRole("region",{name:"保有一覧"})).toContainText("100株");
  expect(reads.filter(path=>path==="/api/v1/home/ledger")).toHaveLength(1);
});

test("home and assets label a saved balance until the current ledger is verified",async({page},info)=>{
  if(!process.env.STOCKAI_ANDROID_UI)await page.setViewportSize({width:320,height:800});
  const fresh=adoptedPayloads(null)["/api/v1/home"] as {portfolio:Record<string,unknown>};
  const saved={...fresh,portfolio:{...fresh.portfolio,totalAssets:"610000"}};
  await page.evaluate(({saved})=>{
    const surface=window as unknown as {Capacitor:{nativePromise:(plugin:string,method:string,options?:{path?:string})=>Promise<unknown>}};
    const original=surface.Capacitor.nativePromise;
    surface.Capacitor.nativePromise=async(plugin,method,options)=>{
      if(method==="readSavedView" && options?.path==="/api/v1/home/ledger")return {available:true,readOnly:true,savedAt:"2026-10-26T10:00:00Z",body:saved};
      return original(plugin,method,options);
    };
  },{saved});
  const finishes:(()=>Promise<void>)[]=[];
  await page.route("**/api/v1/home/ledger",route=>{finishes.push(()=>route.fulfill({json:fresh}));});
  await page.goto("http://127.0.0.1:5196/#/");
  await expect(page.getByRole("region",{name:"資産残高"})).toContainText("610,000");
  await expect(page.getByText(/保存済み表示・閲覧用/)).toBeVisible();
  await expect.poll(()=>finishes.length).toBe(1);
  if(process.env.STOCKAI_ANDROID_UI)await writeFile(info.outputPath("home-saved-ledger.png"),await activeDevice!.screenshot());
  else await page.screenshot({path:info.outputPath("home-saved-ledger.png")});
  await finishes.shift()!();
  await expect(page.getByRole("region",{name:"資産残高"})).toContainText("600,000");
  await expect(page.getByText(/保存済み表示・閲覧用/)).toHaveCount(0);
  await page.getByRole("link",{name:"資産を管理 ›",exact:true}).click();
  await expect(page.getByText(/保存済み表示・閲覧用/)).toBeVisible();
  await expect(page.locator(".subscreen")).toContainText("610,000");
  await expect.poll(()=>finishes.length).toBe(1);
  expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
  await finishes.shift()!();
  await expect(page.locator(".subscreen")).toContainText("600,000");
  await expect(page.getByText(/保存済み表示・閲覧用/)).toHaveCount(0);
  await page.goto("http://127.0.0.1:5196/#/settings?edit=conditions");
  await expect(page.getByText(/保存済み表示・閲覧用/)).toBeVisible();
  await expect.poll(()=>finishes.length).toBe(1);
  expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
  await finishes.shift()!();
  await expect(page.getByText(/保存済み表示・閲覧用/)).toHaveCount(0);
});

test("saved trade and balance histories display read-only while current records are verified",async({page})=>{
  await page.setViewportSize({width:320,height:800});
  const data=adoptedPayloads(null);
  const trade=data["/api/v1/executions"] as {records:{symbol:string}[];appliedIds:string[]};
  const ledger=data["/api/v1/portfolio/history"] as {positions:{shares:number}[]}[];
  const savedTrade={...trade,records:trade.records.map(row=>({...row,symbol:"1111"}))};
  const savedLedger=ledger.map(row=>({...row,positions:row.positions.map(position=>({...position,shares:300}))}));
  await page.evaluate(({savedTrade,savedLedger})=>{
    const surface=window as unknown as {Capacitor:{nativePromise:(plugin:string,method:string,options?:{path?:string})=>Promise<unknown>}};
    const original=surface.Capacitor.nativePromise;
    surface.Capacitor.nativePromise=async(plugin,method,options)=>{
      if(method==="readSavedView" && options?.path==="/api/v1/executions")return {available:true,readOnly:true,savedAt:"2026-10-26T10:00:00Z",body:savedTrade};
      if(method==="readSavedView" && options?.path==="/api/v1/portfolio/history")return {available:true,readOnly:true,savedAt:"2026-10-26T10:00:00Z",body:savedLedger};
      return original(plugin,method,options);
    };
  },{savedTrade,savedLedger});
  let finishTrade!:()=>Promise<void>,finishLedger!:()=>Promise<void>;
  await page.route("**/api/v1/executions",route=>{finishTrade=()=>route.fulfill({json:trade});});
  await page.route("**/api/v1/portfolio/history",route=>{finishLedger=()=>route.fulfill({json:ledger});});
  await page.goto("http://127.0.0.1:5196/#/transactions");
  await expect(page.getByText("1111 / synthetic-account")).toBeVisible();
  await expect(page.getByText(/保存済み履歴・閲覧用/)).toBeVisible();
  await expect.poll(()=>typeof finishTrade).toBe("function");
  await finishTrade();
  await expect(page.getByText("1234 / synthetic-account")).toBeVisible();
  await expect(page.getByText(/保存済み履歴・閲覧用/)).toHaveCount(0);
  await page.goto("http://127.0.0.1:5196/#/assets/history");
  await expect(page.getByText(/→ 300株/)).toBeVisible();
  await expect(page.getByText(/保存済み履歴・閲覧用/)).toBeVisible();
  await expect.poll(()=>typeof finishLedger).toBe("function");
  await finishLedger();
  await expect(page.getByText(/→ 100株/)).toBeVisible();
  await expect(page.getByText(/保存済み履歴・閲覧用/)).toHaveCount(0);
  expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
});

test("saved ranking is visible while the expensive current read is still pending",async({page},info)=>{
  const ranking=adoptedPayloads(null)["/api/v1/mobile/ranking/5d"];
  await page.evaluate(({ranking})=>{
    const surface=window as unknown as {Capacitor:{nativePromise:(plugin:string,method:string,options?:{path?:string})=>Promise<unknown>}};
    const original=surface.Capacitor.nativePromise;
    surface.Capacitor.nativePromise=async(plugin,method,options)=>{
      if(method==="readSavedView" && options?.path==="/api/v1/mobile/ranking/5d")return {available:true,readOnly:true,savedAt:"2026-10-26T10:00:00Z",body:ranking};
      return original(plugin,method,options);
    };
  },{ranking});
  let finish!:()=>Promise<void>;
  await page.route("**/api/v1/mobile/ranking/5d",route=>{finish=()=>route.fulfill({json:ranking});});
  await page.goto("http://127.0.0.1:5196/#/ranking");
  await expect(page.locator(".ranking-table-row").first()).toContainText("画面試験1株式会社");
  await expect(page.getByRole("status")).toContainText("保存済みの順位を表示中");
  await expect.poll(()=>typeof finish).toBe("function");
  if(process.env.STOCKAI_ANDROID_UI)await writeFile(info.outputPath("saved-ranking-before-validation.png"),await activeDevice!.screenshot());
  else await page.screenshot({path:info.outputPath("saved-ranking-before-validation.png")});
  await finish();
  await expect(page.getByText("保存済みの順位を表示中・更新を確認しています…")).toHaveCount(0);
});


test("manual trade is available without a saved judgment and fits narrow Android", async ({page},info)=>{
  if(!process.env.STOCKAI_ANDROID_UI)await page.setViewportSize({width:320,height:800});
  await page.route("**/api/v1/execution-context?*",route=>route.fulfill({json:{proposal:null,decision:null,accountLabels:{}}}));
  await page.route("**/api/v1/execution-entry-context",route=>route.fulfill({json:{portfolioId:"synthetic",asOf:"2026-10-01T09:00:00+09:00",accountLabels:{bucket:"試験口座"},holdings:[]}}));
  await page.route("**/api/v1/executions/manual",route=>route.fulfill({json:{applied:true}}));
  await page.goto("http://127.0.0.1:5196/#/today/executions");
  await expect(page.getByLabel("銘柄コード")).toBeVisible();
  await expect(page.getByText("実行待ちの保存済み判断がありません")).toHaveCount(0);
  for(const font of [100,150]){
    await page.addStyleTag({content:`html{font-size:${font}%}`});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
    expect(await page.locator(".app-main").evaluate(n=>n.scrollWidth-n.clientWidth)).toBeLessThanOrEqual(1);
    const outside=await page.locator("input:visible,select:visible,button:visible").evaluateAll(nodes=>nodes.filter(n=>{const r=n.getBoundingClientRect();return r.left < -1 || r.right > innerWidth+1}).map(n=>n.outerHTML));
    expect(outside).toEqual([]);
    if(process.env.STOCKAI_ANDROID_UI)await writeFile(info.outputPath(`manual-trade-${font}.png`),await activeDevice!.screenshot());
    else await page.screenshot({path:info.outputPath(`manual-trade-${font}.png`),fullPage:true});
  }
  await page.getByLabel("銘柄コード").fill("7203");
  await page.getByLabel("約定株数").fill("100");
  await page.getByLabel("平均約定単価").fill("1000.25");
  await page.getByRole("button",{name:"取引を記録",exact:true}).click();
  await expect(page.getByRole("status")).toContainText("約定した株数と金額だけ");
  await expect(page.getByRole("button",{name:"記録済み"})).toBeDisabled();
});

test("trade entry is reachable while today remains blocked on its first read", async ({page})=>{
  let release!:()=>void;
  const gate=new Promise<void>(resolve=>{release=resolve;});
  let requested=false;
  await page.route("**/api/v1/today",async route=>{
    requested=true;
    await gate;
    await route.fulfill({json:adoptedPayloads({})["/api/v1/today"]});
  });
  await page.route("**/api/v1/execution-entry-context",route=>route.fulfill({json:{portfolioId:"synthetic",asOf:"2026-10-01T09:00:00+09:00",accountLabels:{bucket:"試験口座"},holdings:[]}}));
  try {
    await page.goto("http://127.0.0.1:5196/#/today");
    await expect.poll(()=>requested).toBe(true);
    await expect(page.getByText("今日の状態を確認しています")).toBeVisible();
    await page.getByRole("link",{name:/取引を記録/}).click();
    await expect(page.getByLabel("銘柄コード")).toBeVisible();
    expect(requested).toBe(true);
  } finally {release();}
});

test("market status appears before slow membership without permitting acquisition", async ({page})=>{
  let release!:()=>void;
  const gate=new Promise<void>(resolve=>{release=resolve;});
  let requested=false;
  await page.route("**/api/v1/mobile/market",route=>route.fulfill({json:{latest_data_date:"2026-01-05",completed_dates:[]}}));
  await page.route("**/api/v1/mobile/market/plan",async route=>{requested=true;await gate;await route.fulfill({json:{first_day:"2024-10-20",last_day:"2026-10-19"}});});
  await page.route("**/api/v1/mobile/market/membership",async route=>{await route.fulfill({json:{available_at_cutoff:false}});});
  try {
    await page.goto("http://127.0.0.1:5196/#/settings?edit=market");
    await expect.poll(()=>requested).toBe(true);
    await expect(page.getByText("2026-01-05")).toBeVisible();
    await expect(page.getByLabel("取得開始日")).toHaveValue("");
    await expect(page.getByLabel("取得開始日")).toBeDisabled();
    await expect(page.getByRole("button",{name:"履歴を取得"})).toBeDisabled();
    await expect(page.getByRole("button",{name:"候補と全保有の対象を確認"})).toBeDisabled();
  } finally {
    await page.goto("http://127.0.0.1:5196/#/");
    await expect(page.getByRole("heading",{name:"ホーム",exact:true})).toBeVisible();
    release();
  }
});

test("model information appears before a slow judgment read", async ({page})=>{
  let release!:()=>void;
  const gate=new Promise<void>(resolve=>{release=resolve;});
  let requested=false;
  await page.route("**/api/v1/mobile/models",route=>route.fulfill({json:{approved_bundle_count:1,imported_bundle_count:1,bundle_ready:true,model_adopted:false}}));
  await page.route("**/api/v1/mobile/decision",async route=>{requested=true;await gate;await route.fulfill({json:null});});
  try {
    await page.goto("http://127.0.0.1:5196/#/settings?edit=model");
    await expect.poll(()=>requested).toBe(true);
    await expect(page.getByText("1件取込済み")).toBeVisible();
    await expect(page.getByRole("button",{name:"当日の予測・株数を計算・保存"})).toBeDisabled();
  } finally {
    await page.goto("http://127.0.0.1:5196/#/");
    await expect(page.getByRole("heading",{name:"ホーム",exact:true})).toBeVisible();
    release();
  }
});

test("proposal details and calculation method fit narrow screens", async ({page})=>{
  if (!process.env.STOCKAI_ANDROID_UI) await page.setViewportSize({width:320,height:800});
  await page.goto("http://127.0.0.1:5196/#/today/details");
  await expect(page.getByRole("heading",{name:"費用と現状維持との差"})).toBeVisible();
  await expect(page.getByRole("heading",{name:"計算に使った情報"})).toBeVisible();
  await page.addStyleTag({content:"html{font-size:150%}"});
  expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
  await page.goto("http://127.0.0.1:5196/#/settings?edit=method");
  await expect(page.getByRole("heading",{name:"何を計算するか"})).toBeVisible();
  await expect(page.getByRole("heading",{name:"比較に使う条件"})).toBeVisible();
  await page.addStyleTag({content:"html{font-size:150%}"});
  expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
});

test("proposal details show progress and failure while today read is stalled", async ({page})=>{
  if (!process.env.STOCKAI_ANDROID_UI) await page.setViewportSize({width:320,height:800});
  let release!:()=>void;
  const gate=new Promise<void>(resolve=>{release=resolve;});
  let requested=false;
  await page.route("**/api/v1/today",async route=>{requested=true;await gate;await route.fulfill({json:adoptedPayloads({})["/api/v1/today"]});});
  await page.evaluate(() => {
    const native=window as unknown as {Capacitor:{nativePromise:(plugin:string,method:string,options?:unknown)=>Promise<unknown>}};
    const previous=native.Capacitor.nativePromise;
    native.Capacitor.nativePromise=async(plugin,method,options)=>{
      if(method==="dailyStatus")return {enabled:true,state:"retry",notificationsEnabled:true,retryAt:"2026-10-28T03:30:00Z"};
      if(method==="analysisStatus")return {state:"blocked",blockingReasons:["NO_USABLE_FORECAST"]};
      return previous(plugin,method,options);
    };
  });
  try {
    await page.goto("http://127.0.0.1:5196/#/today/details");
    await expect.poll(()=>requested).toBe(true);
    await expect(page.getByText("今日の状態を確認しています")).toBeVisible();
    await expect(page.getByText(/予測に必要な株価履歴が不足/)).toBeVisible();
    await expect(page.getByText(/再試行予定/)).toBeVisible();
    await page.addStyleTag({content:"html{font-size:150%}"});
    expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
  } finally {release();}
});

for (const panel of ["market", "model"]) test(`leaving ${panel} skips its not-yet-started reads`, async ({page})=>{
  let release!:()=>void;
  const gate=new Promise<void>(resolve=>{release=resolve;});
  let requested=false, finished=false;
  const first=panel === "market" ? "/api/v1/mobile/market" : "/api/v1/mobile/daily";
  const later=panel === "market" ? ["/api/v1/mobile/market/plan","/api/v1/mobile/market/membership","/api/v1/mobile/market/universe-policy"] : ["/api/v1/mobile/models","/api/v1/mobile/decision"];
  await page.route(`**${first}`,async route=>{
    requested=true; await gate;
    await route.fulfill({json:panel === "market" ? {latest_data_date:null,completed_dates:[]} : null});
    finished=true;
  });
  try {
    await page.goto(`http://127.0.0.1:5196/#/settings?edit=${panel}`);
    await expect.poll(()=>requested).toBe(true);
    await page.getByRole("navigation",{name:"メインナビゲーション"}).getByRole("link",{name:"ホーム"}).click();
    await expect(page.getByRole("heading",{name:"ホーム",exact:true})).toBeVisible();
    release(); await expect.poll(()=>finished).toBe(true);
    await page.waitForTimeout(200);
    const calls=await page.evaluate(()=>(window as unknown as {__settingsCalls:{operation?:string;path?:string}[]}).__settingsCalls);
    expect(calls.filter(call=>call.operation === "GET" && later.includes(call.path ?? ""))).toEqual([]);
  } finally {release();}
});


test("daily evidence opens on request and fits a narrow screen",async({page})=>{
  let requests=0;
  await page.route("**/api/v1/mobile/forward-evidence",route=>{
    requests++;
    return route.fulfill({json:{runs:[{run_id:"synthetic-daily",as_of:"2026-10-26T11:30:00+09:00",generated_at:"2026-10-26T11:32:00+09:00",prediction_count:489,excluded_candidates:[{}],has_5d_return:true,has_20d_return:true,has_20d_rank:true}]}});
  });
  await page.setViewportSize({width:320,height:800});
  await page.goto("http://127.0.0.1:5196/#/validation");
  const panel=page.getByRole("region",{name:"日次予測の記録"});
  await expect(panel).toBeVisible();
  expect(requests).toBe(0);
  await panel.getByRole("button",{name:"記録を確認"}).click();
  await expect(panel.getByText(/489銘柄 · 予測対象外 1銘柄/)).toBeVisible();
  expect(requests).toBe(1);
  await expect(panel.getByText(/正式な採用評価は行っていません/)).toBeVisible();
  for(const font of [100,150]){
    await page.addStyleTag({content:`html{font-size:${font}%}`});
    expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
  }
});

test("forward evidence registers and records outcomes at 320px",async({page})=>{
  const registration={registration_id:"a".repeat(64),model_version:"mobile-bundle:test",registered_at:"2026-10-25T09:00:00Z",eligible_from:"2026-10-25T15:00:00Z"};
  const run={run_id:"b".repeat(64),model_version:registration.model_version,as_of:"2026-10-26T11:30:00+09:00",generated_at:"2026-10-26T11:32:00+09:00",prediction_count:2,excluded_candidates:[],has_5d_return:true,has_20d_return:true,has_20d_rank:true};
  let registered=false,observed=false;
  await page.route("**/api/v1/mobile/forward-evidence**",async route=>{
    const url=route.request().url();
    if(url.endsWith("/observations/c"))return route.fulfill({json:{observation_id:"c",evidence:{horizon:5,results:[{symbol:"7203",expected_return:.02,actual_return:.05,rank_score:null,status:"available"},{symbol:"1000",expected_return:.01,actual_return:null,rank_score:null,status:"price_missing"}]}}});
    if(url.endsWith("/register")){registered=true;return route.fulfill({json:registration});}
    if(url.endsWith("/observe")){
      const body=route.request().postDataJSON();
      expect(body).toEqual({registration_id:registration.registration_id,run_id:run.run_id,horizon:5});
      observed=true;return route.fulfill({json:{evidence:{count:2,scored_count:1,mean_absolute_error:.03}}});
    }
    return route.fulfill({json:{runs:[run],registrations:registered?[registration]:[],observations:observed?[{observation_id:"c",run_id:run.run_id,horizon:5,count:2,scored_count:1,mean_absolute_error:.03,observed_at:"2026-10-28T00:00:00Z"}]:[]}});
  });
  await page.setViewportSize({width:320,height:800});
  await page.goto("http://127.0.0.1:5196/#/validation");
  const panel=page.getByRole("region",{name:"日次予測の記録"});
  await panel.getByRole("button",{name:"記録を確認"}).click();
  await panel.getByRole("button",{name:"現在のモデルで検証を開始"}).click();
  await expect(panel.getByText(/検証記録を開始しました/)).toBeVisible();
  await panel.getByRole("button",{name:"5日結果を記録"}).click();
  await expect(panel.getByText(/5日の結果を記録しました/)).toContainText("比較可能 1 / 2銘柄");
  await expect(panel.getByText(/記録した参考結果/)).toBeVisible();
  await panel.getByRole("button",{name:"銘柄別を見る"}).click();
  const detail=panel.getByRole("region",{name:"銘柄別の参考結果"});
  await expect(detail.getByText(/7203/)).toContainText("値予測 2.00% · 実績 5.00%");
  await expect(detail.getByText(/1000/)).toContainText("株価不足");
  for(const font of [100,150]){
    await page.addStyleTag({content:`html{font-size:${font}%}`});
    expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
  }
});

test("older forecasts can be reached after twenty sessions",async({page})=>{
  const runs=Array.from({length:25},(_,i)=>({run_id:String(i),as_of:`2026-10-${String(i+1).padStart(2,"0")}T11:30:00+09:00`,generated_at:`2026-10-${String(i+1).padStart(2,"0")}T11:31:00+09:00`,prediction_count:1,excluded_candidates:[],has_5d_return:true,has_20d_return:true,has_20d_rank:true}));
  await page.route("**/api/v1/mobile/forward-evidence",route=>route.fulfill({json:{runs}}));
  await page.setViewportSize({width:320,height:800});await page.goto("http://127.0.0.1:5196/#/validation");
  const panel=page.getByRole("region",{name:"日次予測の記録"});
  await panel.getByRole("button",{name:"記録を確認"}).click();
  await expect(panel.locator("li")).toHaveCount(10);
  await panel.getByRole("button",{name:"過去の記録をさらに表示"}).click();
  await expect(panel.locator("li")).toHaveCount(20);
  await panel.getByRole("button",{name:"過去の記録をさらに表示"}).click();
  await expect(panel.locator("li")).toHaveCount(25);
});

for(const width of [320,390])test(`model comparison opens from validation at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:800});
  await page.goto("http://127.0.0.1:5196/#/validation");
  await page.getByRole("link",{name:"モデル比較"}).click();
  await expect(page.getByRole("heading",{name:"Champion / Challenger"})).toBeVisible();
  await expect(page.getByRole("button",{name:"モデル比較"})).toHaveAttribute("aria-pressed","true");
  await page.addStyleTag({content:"html{font-size:150%}"});
  expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
});

for(const width of [320,390])test(`home shows holding name and gains without waiting for names at ${width}px`,async({page},info)=>{
  const source=adoptedPayloads(null)["/api/v1/home"] as {holdings:Record<string,unknown>[]};
  const first={...source.holdings[0],symbol:"7203",companyName:"7203",accountBucketId:"tax",shares:200,averageAcquisitionPrice:"900",currentPrice:"1000",marketValue:"200000"};
  const second={...first,accountBucketId:"nisa",shares:100,averageAcquisitionPrice:"800",marketValue:"100000"};
  await page.route("**/api/v1/home/ledger",route=>route.fulfill({json:{...source,portfolioId:"ledger-a",holdings:[first,second],accountLabels:{tax:"特定口座",nisa:"NISA"}}}));
  let release!:()=>void;
  const waiting=new Promise<void>(resolve=>{release=resolve;});
  await page.route("**/api/v1/mobile/holdings/market",async route=>{await waiting;return route.fulfill({json:{portfolioId:"ledger-a",names:{"7203":"トヨタ自動車"},prices:{"7203":"1100"},priceDate:"2026-10-27"}});});
  try{
    await page.setViewportSize({width,height:800});
    await page.goto("http://127.0.0.1:5196/#/");
    const holdings=page.getByRole("region",{name:"実保有"});
    await expect(holdings.getByRole("link",{name:/銘柄名未確認/})).toBeVisible();
    await expect(holdings.getByText("+¥40,000",{exact:true})).toBeVisible();
    await expect(holdings.getByText("+15.38%",{exact:true})).toBeVisible();
    await expect(holdings.getByText("¥866.67",{exact:true})).toBeVisible();
    release();
    await expect(holdings.getByRole("link",{name:/トヨタ自動車/})).toBeVisible();
    await expect(holdings.getByText("+¥70,000",{exact:true})).toBeVisible();
    await expect(holdings.getByText("2026-10-27 終値",{exact:true})).toBeVisible();
    await expect(holdings.getByText("7203",{exact:true})).toBeVisible();
    await page.addStyleTag({content:"html{font-size:150%}"});
    expect(await page.locator(".app-main").evaluate(node=>node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
    const boxes=await holdings.locator(".home-held-head > *").evaluateAll(nodes=>nodes.map(node=>{const box=node.getBoundingClientRect();return {left:box.left,right:box.right};}));
    expect(boxes[0].right).toBeLessThanOrEqual(boxes[1].left+1);
    await holdings.scrollIntoViewIfNeeded();
    if(process.env.STOCKAI_ANDROID_UI)await writeFile(info.outputPath(`holding-${width}.png`),await activeDevice!.screenshot());
    else await page.screenshot({path:info.outputPath(`holding-${width}.png`)});
  }finally{release();}
});
