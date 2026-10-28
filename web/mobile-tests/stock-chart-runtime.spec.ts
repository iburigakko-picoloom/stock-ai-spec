import { expect, test } from "@playwright/test";

test("offline runtime exposes an empty chart without inventing prices or predictions", async ({page,context})=>{
  await context.route("https://**", route=>route.abort());
  await page.route("**/chart-runtime-test",route=>route.fulfill({contentType:"text/html",body:"<!doctype html><title>Offline chart test</title>"}));
  await page.goto("/chart-runtime-test");
  const result=await page.evaluate(async()=>{
    const worker=new Worker("/src/mobile/compute-worker.ts",{type:"module"});
    let id=0;
    const send=(value:Record<string,unknown>)=>new Promise<Record<string,unknown>>((resolve,reject)=>{
      const current=++id;
      worker.onmessage=event=>{if(event.data.id===current){if(event.data.error)reject(new Error(event.data.error));else resolve(event.data);}};
      worker.onerror=event=>reject(new Error(event.message));
      worker.postMessage({...value,id:current});
    });
    try {
      await send({command:"initialize",state:""});
      return await send({command:"request",method:"GET",path:"/api/v1/mobile/stocks/7203/chart?days=90"});
    } finally { worker.terminate(); }
  });
  expect(result.result).toMatchObject({status:200,body:{symbol:"7203",prices:[],forecasts:[]}});
});
