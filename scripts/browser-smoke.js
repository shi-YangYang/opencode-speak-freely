#!/usr/bin/env node
/*
 * 浏览器冒烟测试（只读）：用无头 Chrome 验证 Web UI 的关键交互。
 *
 * 依赖：本机 Chrome + Node.js（有全局 WebSocket）。
 * 用法：
 *   ./scripts/speakfreely-web --no-browser &        # 先启动服务
 *   node scripts/browser-smoke.js [URL] [PROJECT_DIR]
 * 默认 URL: http://127.0.0.1:8788/；PROJECT_DIR 用于指定要扫描的项目
 * （省略时用列表第一个；该项目没有拒绝时会跳过深层检查）
 *
 * 检查项：
 *   1. 页面加载、两个页签存在
 *   2. 点击「清理拒绝」后视图切换（计算样式，而非 hidden 属性）
 *   3. 扫描拒绝并列出会话（该项目需至少有一个含拒绝的会话）
 *   4. 点击会话后列出拒绝条目
 *   5. 替换文案下拉出现在按钮正下方
 *   6. 预览（dry-run，不修改数据库）
 *   7. 收集控制台错误（应为 0）
 */
const { spawn } = require("child_process");
const http = require("http");

const CHROME_CANDIDATES = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
];
const fs = require("fs");
const CHROME = CHROME_CANDIDATES.find((p) => fs.existsSync(p));
const URL = process.argv[2] || "http://127.0.0.1:8788/";
const PROJECT = process.argv[3] || "";
const DEBUG_PORT = 9432;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const failures = [];
function check(name, ok, detail) {
  console.log(`${ok ? "✓" : "✗"} ${name}${detail ? " — " + detail : ""}`);
  if (!ok) failures.push(name);
}

function getJson(path) {
  return new Promise((resolve, reject) => {
    http.get({ host: "127.0.0.1", port: DEBUG_PORT, path }, (res) => {
      let body = "";
      res.on("data", (c) => (body += c));
      res.on("end", () => { try { resolve(JSON.parse(body)); } catch (e) { reject(e); } });
    }).on("error", reject);
  });
}

(async () => {
  if (!CHROME) {
    console.error("未找到 Chrome/Chromium/Edge，跳过浏览器冒烟测试");
    process.exit(0);
  }

  const chrome = spawn(CHROME, [
    "--headless=new", `--remote-debugging-port=${DEBUG_PORT}`,
    "--no-first-run", "--no-default-browser-check",
    `--user-data-dir=/tmp/sf-browser-smoke`, "about:blank",
  ], { stdio: "ignore" });

  try {
    let targets = null;
    for (let i = 0; i < 30; i++) {
      try { targets = await getJson("/json"); break; } catch { await sleep(300); }
    }
    if (!targets) throw new Error("Chrome 未就绪");
    const page = targets.find((t) => t.type === "page");
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((r) => (ws.onopen = r));

    let id = 0;
    const pending = new Map();
    const errors = [];
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); return; }
      if (msg.method === "Page.javascriptDialogOpening") {
        ws.send(JSON.stringify({ id: ++id, method: "Page.handleJavaScriptDialog", params: { accept: false } }));
      } else if (msg.method === "Log.entryAdded" && msg.params.entry.level === "error") {
        errors.push(msg.params.entry.text);
      } else if (msg.method === "Runtime.exceptionThrown") {
        errors.push(msg.params.exceptionDetails.text);
      }
    };
    const send = (method, params = {}) => new Promise((resolve) => {
      const msgId = ++id; pending.set(msgId, resolve);
      ws.send(JSON.stringify({ id: msgId, method, params }));
    });
    const evaluate = async (expression) => {
      const res = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
      if (res.result?.exceptionDetails) throw new Error(res.result.exceptionDetails.text);
      return res.result?.result?.value;
    };

    await send("Runtime.enable");
    await send("Log.enable");
    await send("Page.enable");
    await send("Page.navigate", { url: URL });
    await sleep(3000);

    check("页面标题", (await evaluate("document.title")) === "speakfreely");
    check("三个页签", (await evaluate("document.querySelectorAll('.tab').length")) === 3);

    await evaluate("document.querySelector('.tab[data-view=clean]').click()");
    await sleep(400);
    await evaluate("document.querySelector('.tab[data-view=settings]').click()");
    await sleep(400);
    check("切换到设置页",
      (await evaluate("getComputedStyle(document.getElementById('view-settings')).display")) !== "none" &&
      (await evaluate("getComputedStyle(document.getElementById('view-clean')).display")) === "none");
    await evaluate("document.querySelector('.tab[data-view=clean]').click()");
    await sleep(400);

    check(
      "切换到清理拒绝页",
      (await evaluate("getComputedStyle(document.getElementById('view-run')).display")) === "none" &&
      (await evaluate("getComputedStyle(document.getElementById('view-clean')).display")) !== "none",
    );

    if (PROJECT) {
      await evaluate("document.querySelector('#dd-clean-project .dd-btn').click()");
      await sleep(300);
      const found = await evaluate(
        `!!document.querySelector('#dd-clean-project .dd-item[data-value="${PROJECT}"]')`);
      if (found) {
        await evaluate(
          `document.querySelector('#dd-clean-project .dd-item[data-value="${PROJECT}"]').click()`);
        await sleep(500);
      } else {
        console.log(`（未在列表中找到 ${PROJECT}，用默认项目）`);
      }
    }

    await evaluate("document.getElementById('btn-scan').click()");
    let items = 0;
    for (let i = 0; i < 24; i++) {           // 最多等 12 秒（扫描是异步的）
      await sleep(500);
      items = await evaluate("document.querySelectorAll('#clean-sessions .list-item').length");
      const busy = await evaluate("document.getElementById('clean-sessions').textContent.includes('扫描中')");
      if (items >= 1 || !busy) break;
    }
    if (items === 0) {
      console.log("（该项目当前没有含拒绝的会话，跳过深层检查；" +
        "可用 node scripts/browser-smoke.js <URL> <项目目录> 指定项目）");
    } else {
      check("扫描出含拒绝的会话", true, `找到 ${items} 个`);
    }

    if (items >= 1) {
      await evaluate("document.querySelector('#clean-sessions .list-item').click()");
      let refusals = 0;
      for (let i = 0; i < 20; i++) {          // 最多等 10 秒
        await sleep(500);
        refusals = await evaluate("document.querySelectorAll('#clean-list .refusal-item').length");
        const loading = await evaluate("document.getElementById('clean-list').textContent.includes('加载中')");
        if (refusals >= 1 || !loading) break;
      }
      check("列出拒绝条目", refusals >= 1, `${refusals} 条`);

      await evaluate("document.querySelector('#dd-clean-mode .dd-btn').click()");
      await sleep(200);
      const pos = await evaluate(`(() => {
        const btn = document.querySelector('#dd-clean-mode .dd-btn').getBoundingClientRect();
        const menu = document.querySelector('#dd-clean-mode .dd-menu').getBoundingClientRect();
        return { top: Math.round(menu.top), bottom: Math.round(btn.bottom) };
      })()`);
      check("下拉菜单在按钮正下方", pos.top >= pos.bottom - 2, `menu.top=${pos.top} btn.bottom=${pos.bottom}`);

      await evaluate("document.getElementById('btn-clean-preview').click()");
      await sleep(2000);
      const status = await evaluate("document.getElementById('clean-status').textContent");
      check("预览给出提示", /预览/.test(status || ""), status);
    }

    check("控制台无错误", errors.length === 0, errors.join(" | ") || "0");

    console.log(failures.length ? `\n失败 ${failures.length} 项: ${failures.join(", ")}` : "\n全部通过");
    process.exitCode = failures.length ? 1 : 0;
  } catch (e) {
    console.error("冒烟测试异常:", e.message);
    process.exitCode = 1;
  } finally {
    chrome.kill();
  }
})();
