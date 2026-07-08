#!/usr/bin/env node
/**
 * 图片生成工具 - 五后端智能降级 + 调用追踪
 *
 * 降级链：
 *   🥇 Seedream 直连 (火山引擎 Ark) ¥0.15/张 - 字节·国漫最强·原生2K
 *   🥈 seedream     (Pollinations代理) ~$0.03 - 同上走代理
 *   🥉 grok-imagine (Pollinations代理) ~$0.02 - xAI·综合强
 *   🏅 z-image-turbo (Pollinations免费) - 1088×1920 原生
 *   🟢 旧API          (永远免费)   - ~768px + Lanczos放大
 *
 * 用法:
 *   export VOLCENGINE_API_KEY="volc_xxx"   # 火山引擎 Ark API Key
 *   export POLLINATIONS_KEY="sk_xxx"       # Pollinations Key
 *   node tools/generate_image.js --prompt "描述" --output 路径 --width 1080 --height 1920
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');
const { execSync } = require('child_process');

const PYTHON3 = '/usr/bin/python3';

// ==================== 配置 ====================
const CONFIG = {
  // 火山引擎 图片模型列表（按优先级排列，自动尝试）
  VOLCENGINE_MODELS: [
    'doubao-seedance-4.5-250115',    // 200张免费
    'doubao-seedance-4.0-250115',    // 173/200张
    'doubao-seedance-3.0-0i-250115', // 199/200张
    'doubao-seedance-3.0-pro-250115',// 200/200张
    'doubao-seedance-5.0-lite-250115',// 50/50张
    'doubao-seedance-1.0-pro-250115',// tokens
  ],

  // Pollinations 代理（🥈🥉🏅备用）
  POLLINATIONS_KEY: process.env.POLLINATIONS_KEY || '',
  NEW_API: 'https://gen.pollinations.ai/image',
  OLD_API: 'https://image.pollinations.ai/prompt',

  // Pollinations 付费模型
  PAID_MODELS: [
    { name: 'seedream', label: '🥈 Seedream(代理)', cost: 0.030, desc: '走Pollinations代理' },
    { name: 'grok-imagine', label: '🥉 Grok', cost: 0.020, desc: 'xAI·综合质量强' },
  ],

  FREE_MODEL: 'z-image-turbo',

  REQUEST_TIMEOUT: 120000,
};

// ==================== 调用追踪 ====================
class Tracker {
  constructor(projectDir) {
    this.logPath = projectDir ? path.join(projectDir, '图片生成追踪.json') : null;
    this.records = this._load();
  }
  _load() {
    if (this.logPath && fs.existsSync(this.logPath)) {
      return JSON.parse(fs.readFileSync(this.logPath, 'utf8'));
    }
    return { generations: [], summary: '' };
  }
  record(shotId, backend, status, extra = {}) {
    const entry = { shot: shotId, backend, status, timestamp: new Date().toISOString(), ...extra };
    this.records.generations.push(entry);
    this._updateSummary();
    this._save();
  }
  _updateSummary() {
    const gens = this.records.generations;
    if (!gens.length) { this.records.summary = ''; return; }
    const success = gens.filter(g => g.status === 'success').length;
    const backends = {};
    let totalCost = 0;
    gens.forEach(g => {
      backends[g.backend] = (backends[g.backend] || 0) + 1;
      totalCost += (g.cost || 0);
    });
    this.records.summary = `共${gens.length}张 | 成功${success} | 后端:${JSON.stringify(backends)} | 💰$${totalCost.toFixed(3)}`;
  }
  _save() {
    if (this.logPath) {
      const dir = path.dirname(this.logPath);
      if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(this.logPath, JSON.stringify(this.records, null, 2));
    }
  }
  summary() { return this.records.summary || '无记录'; }
}

// ==================== 参数解析 ====================
function parseArgs() {
  const args = process.argv.slice(2);
  const params = {};
  for (let i = 0; i < args.length; i++) {
    if (args[i].startsWith('--')) {
      const key = args[i].slice(2);
      const val = args[i + 1] && !args[i + 1].startsWith('--') ? args[++i] : 'true';
      params[key] = val;
    }
  }
  return params;
}

// ==================== 网络请求 ====================
function downloadTo(url, outputPath) {
  const dir = path.dirname(outputPath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(outputPath);
    const proto = url.startsWith('https') ? https : http;
    const req = proto.get(url, {
      timeout: CONFIG.REQUEST_TIMEOUT,
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ManjuCLI/1.0',
        'Accept': 'image/*',
      },
    }, (resp) => {
      if (resp.statusCode === 402) { file.close(); reject(new Error('INSUFFICIENT_BALANCE')); return; }
      if (resp.statusCode === 401 || resp.statusCode === 403) { file.close(); reject(new Error('AUTH_FAILED')); return; }
      if (resp.statusCode !== 200) { file.close(); reject(new Error(`HTTP_${resp.statusCode}`)); return; }
      resp.pipe(file);
      file.on('finish', () => { file.close(); resolve(outputPath); });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('TIMEOUT')); });
  });
}

function jsonPost(url, body, apiKey) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify(body);
    const u = new URL(url);
    const options = {
      hostname: u.hostname,
      port: u.port || 443,
      path: u.pathname + u.search,
      method: 'POST',
      timeout: CONFIG.REQUEST_TIMEOUT,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`,
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ManjuCLI/2.0',
        'Accept': 'application/json',
      },
    };
    const req = https.request(options, (resp) => {
      let data = '';
      resp.on('data', chunk => data += chunk);
      resp.on('end', () => {
        try {
          const json = JSON.parse(data);
          resolve({ status: resp.statusCode, body: json });
        } catch {
          reject(new Error(`PARSE_FAILED: ${data.substring(0, 200)}`));
        }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('TIMEOUT')); });
    req.write(payload);
    req.end();
  });
}

async function downloadFromUrl(imageUrl, outputPath) {
  return downloadTo(imageUrl, outputPath);
}

// ==================== 图片分析 ====================
function escapePath(p) {
  // 安全转义文件路径中的特殊字符，防止命令注入
  return p.replace(/'/g, "'\\''");
}

function getResolution(filePath) {
  try {
    const safePath = escapePath(filePath);
    const info = execSync(
      `${PYTHON3} -c "import cv2;img=cv2.imread('${safePath}');print(img.shape[1],img.shape[0])"`,
      { timeout: 5000, encoding: 'utf8' }
    ).trim();
    const [w, h] = info.split(' ').map(Number);
    return { width: w, height: h };
  } catch { return null; }
}

function getFileSizeKB(filePath) {
  return (fs.statSync(filePath).size / 1024).toFixed(1);
}

// ==================== 放大工具 ====================
function upscaleImage(outputPath, targetW, targetH) {
  const res = getResolution(outputPath);
  if (res && res.width >= targetW && res.height >= targetH) {
    console.log(`  ✓ 分辨率已达标 ${res.width}×${res.height}`);
    return;
  }
  const upscaleScript = path.join(__dirname, 'upscale_image.py');
  if (!fs.existsSync(upscaleScript)) {
    console.log(`  ⚠️ 放大脚本不存在，保持原分辨率`);
    return;
  }
  const from = res ? `${res.width}×${res.height}` : '?';
  console.log(`  🔧 放大 ${from} → ${targetW}×${targetH}...`);
  try {
    const safeScript = escapePath(upscaleScript);
    const safeOutput = escapePath(outputPath);
    execSync(`${PYTHON3} "${safeScript}" --input "${safeOutput}" --output "${safeOutput}" --width ${targetW} --height ${targetH}`,
      { stdio: 'pipe', timeout: 30000 });
  } catch { console.log(`  ⚠️ 放大失败，保持原分辨率`); }
}

// ==================== 生成后端 ====================

async function generateSeedreamDirect(prompt, outputPath, width, height) {
  /** 🥇 火山引擎 多模型尝试 */
  const apiKey = CONFIG.VOLCENGINE_KEY;
  if (!apiKey) return null;

  // 计算 size
  const totalPixels = width * height;
  let size = '2K';
  if (totalPixels > 4000000) size = '4K';
  if (totalPixels < 1500000) size = '1K';

  for (const model of CONFIG.VOLCENGINE_MODELS) {
    const body = {
      model: model,
      prompt: prompt,
      size: size,
      output_format: 'png',
      watermark: false,
      response_format: 'url',
      force_single: true,
    };

    console.log(`  🥇 火山引擎 ${model} | ${size}`);
    try {
      const resp = await jsonPost(CONFIG.VOLCENGINE_ARK_URL, body, apiKey);

      if (resp.status === 401 || resp.status === 403) {
        throw new Error('AUTH_FAILED');
      }
      if (resp.status === 402) {
        console.log(`    ⚠️ ${model} 余额不足，试下一模型`);
        continue;
      }
      if (resp.status !== 200) {
        const msg = resp.body?.error?.message || resp.body?.message || `HTTP_${resp.status}`;
        console.log(`    ⚠️ ${model} ${msg.substring(0, 60)}`);
        continue;
      }

      const imageUrl = resp.body?.data?.[0]?.url;
      if (!imageUrl) {
        console.log(`    ⚠️ ${model} 无图片URL`);
        continue;
      }
      await downloadFromUrl(imageUrl, outputPath);
      console.log(`    ✅ ${model} 成功`);
      return outputPath;
    } catch (err) {
      const msg = err.message || String(err);
      console.log(`    ⚠️ ${model} ${msg.substring(0, 60)}`);
    }
  }

  throw new Error('ALL_VOLC_MODELS_FAILED');
}

async function tryGenerate(modelName, prompt, outputPath, width, height, label) {
  const key = CONFIG.POLLINATIONS_KEY;
  const url = `${CONFIG.NEW_API}/${encodeURIComponent(prompt)}`;
  const params = new URLSearchParams({ width: String(width), height: String(height), model: modelName, key });
  console.log(`  ${label} | ${width}×${height}`);
  await downloadTo(`${url}?${params}`, outputPath);
  return outputPath;
}

// ==================== 主流程 ====================
async function main() {
  const params = parseArgs();

  if (!params.prompt) {
    console.log('图片生成工具 - 五后端智能降级');
    console.log('');
    console.log('用法: node tools/generate_image.js --prompt "描述" --output 路径 [选项]');
    console.log('');
    console.log('选项:');
    console.log('  --width  目标宽度 (默认1080)');
    console.log('  --height 目标高度 (默认1920)');
    console.log('  --project-dir 项目目录 (追踪日志)');
    console.log('');
    console.log('降级链: Seedream直连(¥0.15)→Seedream代理($0.03)→Grok($0.02)→z-image-turbo(免费)→旧API(免费)');
    console.log('');
    console.log('需要: export VOLCENGINE_API_KEY="volc_xxx"  或  export POLLINATIONS_KEY="sk_xxx"');
    process.exit(1);
  }

  const prompt = params.prompt;
  const outputPath = path.resolve(params.output);
  const width = parseInt(params.width) || 1080;
  const height = parseInt(params.height) || 1920;
  const projectDir = params['project-dir'] || path.dirname(outputPath);
  const tracker = new Tracker(projectDir);
  const shotId = path.basename(outputPath, path.extname(outputPath));
  const key = CONFIG.POLLINATIONS_KEY;

  console.log(`[Artist] ══════════════════════════`);
  console.log(`[Artist] 目标: ${width}×${height}`);
  console.log(`[Artist] ${prompt.substring(0, 70)}...`);
  console.log(`[Artist] ══════════════════════════`);

  let result = null;
  let backendUsed = 'unknown';

  // === Tier 🥇: 火山引擎 Seedream 直连 ===
  if (CONFIG.VOLCENGINE_KEY) {
    try {
      await generateSeedreamDirect(prompt, outputPath, width, height);
      result = outputPath;
      backendUsed = 'seedream-direct';
      tracker.record(shotId, 'seedream-direct', 'success', { cost: 0.15, resolution: `${width}×${height}(目标)` });
    } catch (err) {
      const msg = err.message || String(err);
      console.log(`  ⚠️ Seedream直连: ${msg.substring(0, 50)}`);
      tracker.record(shotId, 'seedream-direct(skipped)', 'skip', { reason: msg.substring(0, 80), cost: 0 });
    }
  }

  // === Tier 1-3: Pollinations 付费模型 + 免费 ===
  if (!result && key) {
    for (const model of CONFIG.PAID_MODELS) {
      try {
        console.log(`[Artist] ${model.label} (${model.desc})`);
        await tryGenerate(model.name, prompt, outputPath, width, height, model.label);
        result = outputPath;
        backendUsed = model.name;
        tracker.record(shotId, model.name, 'success', { cost: model.cost, resolution: `${width}×${height}(目标)` });
        break;
      } catch (err) {
        if (err.message === 'INSUFFICIENT_BALANCE') {
          console.log(`  ⚠️ 余额不足，跳过`);
          tracker.record(shotId, `${model.name}(skipped)`, 'skip', { reason: '余额不足', cost: 0 });
        } else {
          console.log(`  ❌ ${err.message}`);
          tracker.record(shotId, `${model.name}(failed)`, 'fail', { reason: err.message, cost: 0 });
        }
      }
    }

    // === Tier 4: z-image-turbo 免费 ===
    if (!result) {
      console.log(`[Artist] 🥉 z-image-turbo (免费·1080p原生)`);
      try {
        await tryGenerate(CONFIG.FREE_MODEL, prompt, outputPath, width, height, 'z-image-turbo');
        result = outputPath;
        backendUsed = 'z-image-turbo';
        tracker.record(shotId, 'z-image-turbo', 'success', { cost: 0 });
      } catch (err) {
        console.log(`  ⚠️ ${err.message}`);
      }
    }
  }

  // === Tier 4: 旧API兜底 ===
  if (!result) {
    console.log(`[Artist] 🟢 旧API兜底 (~768px→放大)`);
    const seed = Math.floor(Math.random() * 1000000);
    const url = `${CONFIG.OLD_API}/${encodeURIComponent(prompt)}?width=${width}&height=${height}&nologo=true&seed=${seed}`;
    try {
      await downloadTo(url, outputPath);
      upscaleImage(outputPath, width, height);
      result = outputPath;
      backendUsed = 'old-api';
      tracker.record(shotId, 'old-api', 'success', { cost: 0 });
    } catch (err) {
      tracker.record(shotId, 'ALL_FAILED', 'fail', { reason: err.message, cost: 0 });
      console.error(`[Artist] ❌ 全部后端失败: ${err.message}`);
      process.exit(1);
    }
  }

  // === 输出结果 ===
  const res = getResolution(result);
  console.log(`[Artist] ✅ ${path.basename(result)} (${getFileSizeKB(result)}KB, ${res ? res.width+'×'+res.height : '?'})`);
  console.log(`[Artist] 📊 ${tracker.summary()}`);
  console.log(`[Artist] 📝 日志: ${tracker.logPath}`);
}

main().catch(err => {
  console.error(`[Artist] ❌ ${err.message}`);
  process.exit(1);
});
