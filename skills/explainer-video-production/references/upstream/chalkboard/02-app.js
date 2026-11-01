// Page: every frame is Canvas 2D (wall, slates, chalk, wet band, wipe, light), then a WebGL2 post pass
// (camera motion blur, vignette, grade). window.render(t) depends on t only.
import { clamp, lerp, ss, eio } from '/core/lib.js';
import { bake, drawStroke, n1, rng } from './chalk.js';
import { installDeposit, grainTile } from './r2d.js';
import { Post } from './post.js';
import { loadSvgFont } from './hand.js';
import { bakeWall, bakeSlate, paintGrid, WALL, PW, BH } from './stage.js';
import { drawFront } from './props.js';

const Q = new URLSearchParams(location.search), W = innerWidth, H = innerHeight;
const cv = document.getElementById('c');
cv.width = W; cv.height = H;
await loadSvgFont('fonts/' + (Q.get('font') || 'EMSDelight') + '.svg');
await loadSvgFont('fonts/EMSCasualHand.svg', 'child');
installDeposit();

if (Q.has('lab')) { await import('./lab.js').then(m => m.run(cv, W, H, Q)); }
else {
  const { build } = await import('./film.js');
  const F = build(W, H);
  for (const s of F.S) bake(s, s.o.R || 2);
  window.DUR = F.DUR; window.EV = F.EV;

  // ───────── static pictures
  const WALLI = bakeWall();
  const BACK = bakeSlate(PW + 140, BH, 61), FR = bakeSlate(PW, BH, 71, true), FL = bakeSlate(PW, BH, 81, true);
  { const c = BACK.cv.getContext('2d'); c.save(); c.translate(BACK.m, 0); for (const g of F.SMALL) paintGrid(c, g.x, g.y, g.size); c.restore(); }
  { const c = FL.cv.getContext('2d'); c.save(); c.translate(FL.m, 0); paintGrid(c, F.G1.x, F.G1.y, F.G1.size); paintGrid(c, F.G2.x, F.G2.y, F.G2.size); c.restore(); }
  const TILE = grainTile();

  const post = new Post(cv, W, H);
  const main = new OffscreenCanvas(W, H), mx = main.getContext('2d');
  const la = new OffscreenCanvas(W, H), lx = la.getContext('2d');
  const PAT = mx.createPattern(TILE, 'repeat');
  const KS = W / 1920;                                    // camera scales are given for a 1920-wide frame
  const view = c0 => { const c = { ...c0, s: c0.s * KS }; return { ...c, m: [c.s, 0, 0, c.s, W / 2 - c.cx * c.s, H / 2 - c.cy * c.s], toScreen: (x, y) => [W / 2 + (x - c.cx) * c.s, H / 2 + (y - c.cy) * c.s], W, H }; };

  // the wet band left by the cloth, drying back toward the child's corner (front-panel units).
  // A soft mask (band ∩ right of the drying line, plus a few islands still drying behind it) darkens and
  // glosses the slate; a thin bright meniscus and a darker water line mark the edge; faint cloth streaks inside.
  const wetC = new OffscreenCanvas(W, H), wx = wetC.getContext('2d');
  const WETN = (() => {                                    // uneven moisture, baked once (band units / 8)
    const o = new OffscreenCanvas(320, 60), c = o.getContext('2d'), img = c.createImageData(320, 60);
    for (let y = 0; y < 60; y++) for (let x = 0; x < 320; x++) { const v = n1(x / 9 + n1(y / 7, 2) * 3, 1) * .6 + n1(x / 3.2 + y * 1.7, 5) * .4; const q = 4 * (y * 320 + x); img.data[q] = img.data[q + 1] = img.data[q + 2] = 0; img.data[q + 3] = Math.round(clamp((v - .35) * 1.6) * 255); }
    c.putImageData(img, 0, 0); return o;
  })();
  function drawWet(ctx, t, ox, v) {
    const w = F.wet; if (t > w.t1 + .3) return;
    const u = clamp((t - w.t0) / (w.t1 - w.t0)), front = lerp(w.bx0, w.xEnd + 20, 1 - Math.pow(1 - u, 1.5));
    const mid = (w.y0 + w.y1) / 2, half = (w.y1 - w.y0) / 2;
    const bx = y => front + (n1(y / 70, 3) - .5) * 46 + (n1(y / 16, 4) - .5) * 12;
    const top = x => w.y0 + (n1(x / 160, 9) - .5) * 30, bot = x => w.y1 + (n1(x / 150, 11) - .5) * 34;
    const xe = y => w.xEnd - 70 * Math.pow(clamp(Math.abs(y - mid) / half), 3) + (n1(y / 40, 7) - .5) * 30;   // the cloth's rounded end
    const fade = 1 - ss((t - w.t1) / .3);
    const M = [v.m[0], 0, 0, v.m[3], v.m[4] + ox * v.s, v.m[5]];
    const ys = []; for (let y = w.y0 - 30; y <= w.y1 + 30; y += 2) ys.push(y);
    const region = new Path2D(); ys.forEach((y, i) => { const x = Math.max(bx(y), w.x0); i ? region.lineTo(x, y) : region.moveTo(x, y); }); ys.slice().reverse().forEach(y => region.lineTo(Math.max(bx(y), xe(y)), y)); region.closePath();
    const band = new Path2D(); band.moveTo(w.x0, top(w.x0)); for (let x = w.x0; x <= w.xEnd + 80; x += 20) band.lineTo(x, top(x)); for (let x = w.xEnd + 80; x >= w.x0; x -= 20) band.lineTo(x, bot(x)); band.closePath();
    wx.setTransform(1, 0, 0, 1, 0, 0); wx.clearRect(0, 0, W, H); wx.globalCompositeOperation = 'source-over';
    wx.setTransform(...M); wx.filter = `blur(${Math.max(2, 7 * v.s)}px)`; wx.fillStyle = '#fff';       // a soft, natural gradient at the drying edge
    wx.save(); wx.clip(band); wx.fill(region);
    const R = rng(5);                                       // small patches still drying behind the line
    for (let i = 0; i < 0; i++) {
      const x0 = w.bx0 + R() * (w.xEnd - w.bx0), y0 = w.y0 + 15 + R() * (w.y1 - w.y0 - 30), r0 = 5 + R() * 13, k = clamp(1 - (front - x0) / (90 + R() * 140));
      if (k > 0 && front > x0) { wx.globalAlpha = .8; wx.beginPath(); wx.ellipse(x0, y0, r0 * (1.5 + R()) * k, r0 * k, R() - .5, 0, 6.29); wx.fill(); }
    }
    wx.globalAlpha = 1; wx.restore(); wx.filter = 'none';
    { wx.globalCompositeOperation = 'destination-in'; const fg = wx.createLinearGradient(0, w.y0 - 25, 0, w.y1 + 25);   // damp, not cut: the band fades out at top and bottom
      fg.addColorStop(0, 'rgba(0,0,0,0)'); fg.addColorStop(.2, 'rgba(0,0,0,1)'); fg.addColorStop(.8, 'rgba(0,0,0,1)'); fg.addColorStop(1, 'rgba(0,0,0,0)');
      wx.fillStyle = fg; wx.fillRect(w.x0 - 100, w.y0 - 60, w.xEnd - w.x0 + 300, w.y1 - w.y0 + 120); wx.globalCompositeOperation = 'source-over'; }
    wx.globalCompositeOperation = 'source-in'; wx.setTransform(1, 0, 0, 1, 0, 0);
    wx.fillStyle = 'rgba(0,12,7,.36)'; wx.fillRect(0, 0, W, H);
    wx.globalCompositeOperation = 'source-atop'; wx.setTransform(...M);
    wx.globalAlpha = .22; wx.drawImage(WETN, w.x0, w.y0 - 40, w.xEnd - w.x0 + 80, w.y1 - w.y0 + 80); wx.globalAlpha = 1;
    // the window's reflection on the wet paint: a soft, slanted glow that only the wet part shows
    const sh = wx.createLinearGradient(0, w.y0 - 20, 0, w.y1 + 20);           // the wet paint's sheen: brightest near the band's top
    sh.addColorStop(0, 'rgba(185,215,200,.2)'); sh.addColorStop(.22, 'rgba(185,215,200,.08)'); sh.addColorStop(.6, 'rgba(185,215,200,0)'); sh.addColorStop(1, 'rgba(185,215,200,.04)');
    wx.fillStyle = sh; wx.fillRect(w.x0, w.y0 - 60, w.xEnd - w.x0 + 120, w.y1 - w.y0 + 120);
    ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = fade; ctx.drawImage(wetC, 0, 0); ctx.restore();
  }

  function drawWipeHaze(ctx, t, ox) {
    const w = F.wipe; if (t <= w.t0) return null;
    const P = w.path, n = Math.max(2, Math.round(P.length * clamp((t - w.t0) / (w.t1 - w.t0))));
    const p = new Path2D(); P.slice(0, n).forEach(([x, y], i) => i ? p.lineTo(x + ox, y) : p.moveTo(x + ox, y));
    return p;
  }

  function frame(t) {
    const c = F.camAt(t), v = view(c), ox = F.slideX(t);
    mx.setTransform(1, 0, 0, 1, 0, 0); mx.globalCompositeOperation = 'source-over'; mx.globalAlpha = 1; mx.filter = 'none';
    mx.fillStyle = '#000'; mx.fillRect(0, 0, W, H);
    mx.setTransform(...v.m); mx.imageSmoothingQuality = 'high';
    mx.drawImage(WALLI.cv, WALL[0], WALL[1], WALL[2], WALL[3]);
    // back board and its chalk (only ever seen once the panel has moved)
    if (ox > 1) {
      mx.drawImage(BACK.cv, -BACK.m, 0, BACK.cv.width, BH);
      for (const s of F.S) if (s.layer === 'BK' && t > s.t0) drawStroke(mx, s, t);
    }
    // FR (static), then FL on its offset with a soft occlusion shadow on what is behind its left edge
    mx.drawImage(FR.cv, PW - FR.m, 0, FR.cv.width, BH);
    for (const s of F.S) if (s.layer === 'FR' && t > s.t0) drawStroke(mx, s, t);           // the clean panel behind (end card)
    if (ox > 1) { const g = mx.createLinearGradient(ox - 60, 0, ox, 0); g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(1, 'rgba(0,0,0,.45)'); mx.fillStyle = g; mx.fillRect(ox - 60, 0, 60, BH); }
    mx.drawImage(FL.cv, ox - FL.m, 0, FL.cv.width, BH);
    drawWet(mx, t, ox, v);
    // front-panel chalk: kept strokes straight onto the frame; wiped ones on their own layer
    const focus = 0;
    lx.setTransform(1, 0, 0, 1, 0, 0); lx.clearRect(0, 0, W, H); lx.filter = 'none'; lx.globalCompositeOperation = 'source-over';
    lx.setTransform(v.m[0], 0, 0, v.m[3], v.m[4] + ox * v.s, v.m[5]);
    const hp = drawWipeHaze(mx, t, 0);
    for (const s of F.S) if (s.layer === 'FL' && s.phase === 'pre' && (!hp || s.wiped) && t > s.t0) drawStroke(lx, s, t);
    if (hp) {
      const ww = F.wipe.w;
      lx.globalCompositeOperation = 'destination-out'; lx.filter = `blur(${Math.max(1, 16 * v.s)}px)`; lx.lineCap = 'round'; lx.lineJoin = 'round'; lx.lineWidth = ww; lx.strokeStyle = '#000';
      lx.stroke(hp); lx.globalCompositeOperation = 'source-over'; lx.filter = 'none';
      for (const s of F.S) if (s.layer === 'FL' && s.phase === 'pre' && !s.wiped && t > s.t0) drawStroke(lx, s, t);   // the eraser went round what it kept
    }
    mx.setTransform(1, 0, 0, 1, 0, 0); if (focus > .2) mx.filter = `blur(${focus * KS}px)`; mx.drawImage(la, 0, 0); mx.filter = 'none';
    if (hp) {
      mx.save(); mx.setTransform(v.m[0], 0, 0, v.m[3], v.m[4] + ox * v.s, v.m[5]); mx.filter = `blur(${Math.max(1, 12 * v.s)}px)`;
      mx.strokeStyle = 'rgba(160,176,168,.024)'; mx.lineCap = 'round'; mx.lineJoin = 'round'; mx.lineWidth = F.wipe.w * .9; mx.stroke(hp); mx.restore();
    }
    mx.setTransform(v.m[0], 0, 0, v.m[3], v.m[4] + ox * v.s, v.m[5]);
    for (const s of F.S) if (s.layer === 'FL' && s.phase === 'post' && t > s.t0) drawStroke(mx, s, t);
    mx.setTransform(...v.m);
    if (t < F.T.back0) for (const s of F.S) if (s.layer === 'WORLD' && t > s.t0) drawStroke(mx, s, t);
    // slate micro grain where it can be seen
    if (v.s / KS > .6) {
      mx.save(); mx.beginPath(); mx.rect(0, 0, 6400, BH); mx.clip();
      PAT.setTransform(new DOMMatrix([.25, 0, 0, .25, 0, 0])); mx.globalCompositeOperation = 'soft-light'; mx.globalAlpha = Math.min(.2, (v.s / KS - .6) * .3);
      mx.fillStyle = PAT; mx.fillRect(0, 0, 6400, BH); mx.restore();
    }
    // morning light from the windows on the left: a soft falloff and a slanted patch low on the left
    mx.save(); mx.setTransform(...v.m);
    const lg = mx.createLinearGradient(-1500, 0, 7900, 0); lg.addColorStop(0, 'rgb(255,250,240)'); lg.addColorStop(.45, 'rgb(236,236,232)'); lg.addColorStop(1, 'rgb(196,198,200)');
    mx.globalCompositeOperation = 'multiply'; mx.fillStyle = lg; mx.fillRect(-1500, -1500, 9400, 4900);
    mx.globalCompositeOperation = 'screen'; mx.filter = `blur(${Math.max(3, 40 * v.s)}px)`;
    const pane = (x, y, w, h, a) => { mx.fillStyle = `rgba(255,212,150,${a})`; mx.beginPath(); mx.moveTo(x, y); mx.lineTo(x + w, y + w * .28); mx.lineTo(x + w, y + w * .28 + h); mx.lineTo(x, y + h); mx.closePath(); mx.fill(); };
    for (let i = 0; i < 3; i++) for (let j = 0; j < 2; j++) pane(-260 + i * 400, 1060 + j * 330 + i * 400 * .28, 360, 300, .07 - i * .018);
    mx.restore();
    // the chalk's front: a few bright grains where the writing is now
    for (const s of F.S) {
      if (t <= s.t0 || t >= s.t1) continue;
      const f = s.prog(t); const p = s.at(f * s.len), o = s.layer === 'FL' ? ox : 0;
      drawFront(mx, t, v, p[0] + o, p[1], s.color, Math.min(s.w, 9), .5);
    }
    return c;
  }

  // ───────── subtitles: the voice line in Chinese, a translation in English, on a soft dark plate above the bottom safe area
  await document.fonts.load('40px SubKai');
  const sc = document.getElementById('s'); sc.width = W; sc.height = H; const sx = sc.getContext('2d');
  const SZ = { zh: Math.round(38 * KS), en: Math.round(25 * KS), zhY: H - Math.round(100 * KS), enY: H - Math.round(62 * KS) };
  const subAt = t => F.SUBS.find(q => t >= q.t0 && t < q.t1);
  const NOSUBS = Q.has('nosubs');                          // ?nosubs: picture only (poster, gallery frame)
  function subtitle(t) {
    sx.clearRect(0, 0, W, H); if (NOSUBS) return;
    const q = subAt(t); if (!q) return;
    const a = Math.min(1, (t - q.t0) / .12, (q.t1 - t) / .12);
    sx.font = `${SZ.zh}px SubKai`; const wz = sx.measureText(q.zh).width; sx.font = `${SZ.en}px SubKai`; const we = sx.measureText(q.en).width;
    const w = Math.max(wz, we) + 56 * KS, x0 = (W - w) / 2, y0 = SZ.zhY - SZ.zh - 14 * KS, y1 = SZ.enY + 16 * KS;
    sx.globalAlpha = a * .62; sx.fillStyle = '#0a0f0c'; sx.beginPath(); sx.roundRect(x0, y0, w, y1 - y0, 10 * KS); sx.fill();
    sx.globalAlpha = a; sx.textAlign = 'center'; sx.textBaseline = 'alphabetic';
    sx.font = `${SZ.zh}px SubKai`; sx.fillStyle = '#f3efe4'; sx.fillText(q.zh, W / 2, SZ.zhY);
    sx.font = `${SZ.en}px SubKai`; sx.fillStyle = '#d9d4c6'; sx.fillText(q.en, W / 2, SZ.enY);
    sx.globalAlpha = 1;
  }
  const subBoxes = t => {
    const q = subAt(t); if (!q) return [];
    sx.font = `${SZ.zh}px SubKai`; const wz = sx.measureText(q.zh).width; sx.font = `${SZ.en}px SubKai`; const we = sx.measureText(q.en).width;
    return [{ id: 'sub-zh-' + q.id, text: q.zh, x0: (W - wz) / 2, y0: SZ.zhY - SZ.zh, x1: (W + wz) / 2, y1: SZ.zhY + SZ.zh * .25 },
            { id: 'sub-en-' + q.id, text: q.en, x0: (W - we) / 2, y0: SZ.enY - SZ.en, x1: (W + we) / 2, y1: SZ.enY + SZ.en * .3 }];
  };
  const shotOf = t => F.camAt(t).shot;
  window.render = t => {
    const c = frame(t);
    const tp = t - .5 / 30, pc = shotOf(tp) === c.shot ? F.camAt(tp) : c, k = pc.s / c.s;
    const bl = [k, 0, 0, 0, k, 0, W / 2 - k * W / 2 + pc.s * KS * (c.cx - pc.cx), H / 2 - k * H / 2 + pc.s * KS * (c.cy - pc.cy), 1];
    post.draw(main, bl, t, .3);
    subtitle(t);
  };
  window.TEXTS = t => {
    const c = F.camAt(t), v = view(c), ox = F.slideX(t), out = [];
    for (const q of F.TX) {
      if (t < q.t0 || t >= q.t1) continue;
      const o = q.layer === 'FL' ? ox : 0, [a, b] = v.toScreen(q.box[0] + o, q.box[1]), [d, e] = v.toScreen(q.box[2] + o, q.box[3]);
      out.push({ id: q.id, text: q.text, x0: a, y0: b, x1: d, y1: e });
    }
    return out;                                               // subtitles follow the voice; not part of the reading-time check
  };
  window.F = F; if (Q.has('dbg')) for (const [k, v] of Object.entries(F.T)) console.warn('T', k, JSON.stringify(v, (a, b) => typeof b === 'number' ? +b.toFixed(2) : b));
  window.render(+(Q.get('t') || 0));
}
window.READY = true;
