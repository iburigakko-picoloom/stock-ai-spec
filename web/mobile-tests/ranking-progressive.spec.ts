import { expect, test } from "@playwright/test";

test("ranking completes and restores model, search and scroll after stock details", async ({ page }) => {
  await page.setViewportSize({width:320,height:720});
  await page.addInitScript(() => {
    const rows=Array.from({length:150},(_,index)=>({symbol:String(1000+index),companyName:index===149 ? "1149" : `合成企業${index}`,modelRank:index+1,score:150-index,expectedReturn:(150-index)/10000}));
    const metrics=Object.fromEntries(rows.map((row,index)=>[row.symbol,{return5d:row.expectedReturn,return20d:row.expectedReturn,rank20d:150-index}]));
    const ranking={id:"synthetic",snapshotId:"snapshot-synthetic",generatedAt:"2026-10-26T09:00:00Z",asOf:"2026-10-26T09:00:00Z",priceDate:"2026-10-26",rows,metrics,total:150,answer:null,holdingSymbols:["1149"]};
    Object.assign(window,{CapacitorCustomPlatform:{name:"android"},Capacitor:{
      PluginHeaders:[{name:"StockAI",methods:["compute","readSavedView","analysisStatus","dailyStatus","appInfo","checkUpdate"].map(name=>({name,rtype:"promise"}))}],
      nativePromise:async(_plugin:string,method:string,options?:{path:string})=>{
        if(method==="compute") {
          const path=options?.path ?? "";
          const body=path.startsWith("/api/v1/mobile/ranking/") && path.endsWith("/names") ? {snapshotId:"snapshot-synthetic",names:{"1149":"合成企業149"}} : path.startsWith("/api/v1/mobile/ranking/") ? ranking : path.endsWith("/note") ? {symbol:"1149",text:"",revision:null,updatedAt:null} : path.startsWith("/api/v1/stocks/") ? {symbol:"1149",positions:[],proposalLines:[],proposal:null,forecast:null,researchRuns:[],chatgptResearch:[]} : null;
          return {status:200,body};
        }
        if(method==="readSavedView")return {available:false};
        if(method==="analysisStatus")return {state:"idle"};
        if(method==="dailyStatus")return {enabled:false,state:"idle",notificationsEnabled:false};
        if(method==="appInfo")return {applicationId:"jp.stockai.app",versionName:"test",versionCode:0};
        return {available:false};
      },
    }});
  });
  await page.goto("/#/ranking");
  const rows=page.locator(".ranking-table-row");
  await expect(rows).toHaveCount(20);
  await page.getByRole("button",{name:"20日・ランキング"}).click();
  await expect(rows).toHaveCount(20);
  const saved=await page.evaluate(()=>{
    const main=document.querySelector<HTMLElement>(".app-shell--adopted .app-main")!;
    main.scrollTo(0,Math.floor((main.scrollHeight-main.clientHeight)*0.7));return main.scrollTop;
  });
  expect(saved).toBeGreaterThan(0);
  await page.waitForTimeout(100);
  await rows.last().evaluate(link=>(link as HTMLAnchorElement).click());
  await expect(page).toHaveURL(/#\/stocks\/1019$/);
  await page.goBack();
  await expect(page).toHaveURL(/#\/ranking$/);
  await expect(rows).toHaveCount(20);
  await expect(page.getByRole("button",{name:"20日・ランキング"})).toHaveAttribute("aria-pressed","true");
  await expect.poll(()=>page.evaluate(()=>document.querySelector<HTMLElement>(".app-shell--adopted .app-main")!.scrollTop)).toBe(saved);
  await page.getByRole("searchbox").fill("合成企業149");
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("1149");
  await expect(page.getByLabel("150位")).toBeVisible();
  await rows.first().click();
  await page.goBack();
  await expect(page.getByRole("searchbox")).toHaveValue("合成企業149");
  await expect(rows).toHaveCount(1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});
