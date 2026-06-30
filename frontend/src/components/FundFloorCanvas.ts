/**
 * FundFloorCanvas — BMG Capital Fund Floor pixel-art game engine.
 *
 * Ported from Fund Floor.dc.html IIFE. Exposes window.BMGFloor public surface.
 * Call initFundFloor(canvas) from a useEffect; call cleanup() on unmount.
 */

export function initFundFloor(canvas: HTMLCanvasElement): () => void {
  const ctx = canvas.getContext('2d')!;
  ctx.imageSmoothingEnabled = false;
  const T = 16, MAPW = 30, MAPH = 28, VW = 320, VH = 208;

  const PAL: Record<string, Record<string, string>> = {
    brock:   { hair:'#3a2a18', skin:'#e8b890', shirt:'#1f8a5b', pants:'#161a16', cap:'#eafbe9' },
    brick:   { hair:'#4a3420', skin:'#e8b890', shirt:'#2ea36b', pants:'#1a241a' },
    dick:    { hair:'#6b4422', skin:'#f0c8a0', shirt:'#f87171', pants:'#2a1414' },
    patrick: { hair:'#1a1a1a', skin:'#d8a878', shirt:'#38bdf8', pants:'#1a2430' },
    nick:    { hair:'#c98a34', skin:'#f0c8a0', shirt:'#9fb0cf', pants:'#22303a' },
    mick:    { hair:'#14110f', skin:'#d8a878', shirt:'#a78bfa', pants:'#201828' },
    rick:    { hair:'#241712', skin:'#c89868', shirt:'#f0b35a', pants:'#2a2010' },
    vick:    { hair:'#2a2a2a', skin:'#e0b088', shirt:'#5ec5d8', pants:'#16282c' },
    slick:   { hair:'#3a2a18', skin:'#f0c8a0', shirt:'#e0a0c0', pants:'#2a1c26' },
    wick:    { hair:'#46264f', skin:'#f0c8a0', shirt:'#8a9a8a', pants:'#1c241c' },
  };

  const M: Record<string, {
    name: string; role: string; pal: Record<string, string>; status: string;
    cost: string; dept: string; line: string; briefing: string; decision: string;
  }> = {
    brick:   { name:'BRICK',   role:'PORTFOLIO MANAGER',    pal:PAL.brick,   status:'active',   cost:'0.00', dept:'lead',
               line:"Capital flows the way I tell it to.",
               briefing:"Awaiting first morning meeting.",
               decision:"No decisions yet." },
    dick:    { name:'DICK',    role:'CHIEF RISK OFFICER',   pal:PAL.dick,    status:'active',   cost:'0.00', dept:'lead',
               line:"I veto first, apologize never.",
               briefing:"Risk monitors armed.",
               decision:"No vetoes issued yet." },
    nick:    { name:'NICK',    role:'EQUITY RESEARCHER',    pal:PAL.nick,    status:'active',   cost:'0.00', dept:'research',
               line:"AAPL up, NVDA crowded, MSFT boring.",
               briefing:"Equity read pending.",
               decision:"No recommendations yet." },
    mick:    { name:'MICK',    role:'QUANT RESEARCHER',     pal:PAL.mick,    status:'active',   cost:'0.00', dept:'research',
               line:"Alpha decays. Numbers don't.",
               briefing:"Quant signals pending.",
               decision:"No decisions yet." },
    rick:    { name:'RICK',    role:'MACRO STRATEGIST',     pal:PAL.rick,    status:'active',   cost:'0.00', dept:'research',
               line:"Regime: chop. Get used to it.",
               briefing:"Macro read pending.",
               decision:"No regime calls yet." },
    vick:    { name:'VICK',    role:'DATA QUALITY WATCHER', pal:PAL.vick,    status:'active',   cost:'0.00', dept:'ops',
               line:"If the feed lies, I tell.",
               briefing:"Feed integrity pending.",
               decision:"No flags yet." },
    slick:   { name:'SLICK',   role:'EXECUTION AUDITOR',    pal:PAL.slick,   status:'active',   cost:'0.00', dept:'ops',
               line:"Slippage is the silent killer.",
               briefing:"Execution audit pending.",
               decision:"No exceptions logged." },
    wick:    { name:'WICK',    role:'OPERATIONS',           pal:PAL.wick,    status:'active',   cost:'0.00', dept:'ops',
               line:"Back office, front-line eyes.",
               briefing:"Ops status pending.",
               decision:"No ops tickets open." },
    patrick: { name:'PATRICK', role:'SENTINEL DEVOPS',      pal:PAL.patrick, status:'active',   cost:'0.00', dept:'ops',
               line:"Infra holds. For now.",
               briefing:"Infra status pending.",
               decision:"No escalations." },
  };

  const DATA = {
    budgetSpent: 0,
    budgetCap: 3,
    stale: [] as string[],
    night: false,
    vetoFlash: -999,
    cioBriefing: "# CIO BRIEFING\n\nNo morning meeting has run yet.\nPress MEETING to start one.",
  };

  // Build map
  const solid: number[][] = Array.from({ length: MAPH }, () => Array(MAPW).fill(0));
  const tile: number[][] = Array.from({ length: MAPH }, () => Array(MAPW).fill(0));
  for (let x = 0; x < MAPW; x++) {
    for (const y of [0, 1]) { solid[y][x] = 1; tile[y][x] = 1; }
    solid[MAPH-1][x] = 1; tile[MAPH-1][x] = 1;
  }
  for (let y = 0; y < MAPH; y++) {
    solid[y][0] = 1; tile[y][0] = 1;
    solid[y][MAPW-1] = 1; tile[y][MAPW-1] = 1;
  }
  solid[MAPH-1][14] = 0; solid[MAPH-1][15] = 0;
  tile[MAPH-1][14] = 0; tile[MAPH-1][15] = 0;

  const set = (tx: number, ty: number, code: number, isSolid?: number) => {
    if (ty<0||tx<0||ty>=MAPH||tx>=MAPW) return;
    tile[ty][tx] = code;
    if (isSolid != null) solid[ty][tx] = isSolid;
  };
  for (let y = 3; y <= MAPH-2; y++) {
    if (tile[y][14]===0) set(14,y,11);
    if (tile[y][15]===0) set(15,y,11);
  }
  set(14,10,13); set(15,10,13); set(14,11,13); set(15,11,13);

  const cubicles = [
    { dx:7,  dy:6,  who:'brick' }, { dx:19, dy:6,  who:'dick' },
    { dx:4,  dy:14, who:'nick' },  { dx:13, dy:14, who:'mick' }, { dx:22, dy:14, who:'rick' },
    { dx:2,  dy:22, who:'vick' },  { dx:9,  dy:22, who:'slick' }, { dx:16, dy:22, who:'wick' }, { dx:23, dy:22, who:'patrick' },
  ];

  interface NPC { tx: number; ty: number; who: string; facing: string; px: number; py: number; hx: number; hy: number; walking: boolean; seat?: { x: number; y: number }; }
  const npcs: NPC[] = [];
  cubicles.forEach(c => {
    const { dx, dy } = c;
    set(dx, dy, 14, 1); set(dx+1, dy, 15, 1);
    for (let x = dx-1; x <= dx+2; x++) set(x, dy-1, 4, 1);
    set(dx-1, dy, 4, 1); set(dx+2, dy, 4, 1);
    set(dx-1, dy+1, 4, 1); set(dx+2, dy+1, 4, 1);
    set(dx, dy+1, 10, 0);
    const px = dx*T+8, py = (dy+1)*T+15;
    npcs.push({ tx: dx, ty: dy+1, who: c.who, facing: 'down', px, py, hx: px, hy: py, walking: false });
    solid[dy+1][dx] = 1;
  });

  for (let x = 10; x <= 17; x++) { solid[7][x] = 1; tile[7][x] = 18; }
  for (let x = 12; x <= 17; x++) for (let y = 18; y <= 19; y++) set(x, y, 9, 1);

  const seats = [ [12,17],[16,17],[12,20],[14,20],[16,20],[11,18],[11,19],[18,18],[18,19] ];
  npcs.forEach((n, i) => { const s = seats[i % seats.length]; n.seat = { x: s[0]*T+8, y: s[1]*T+15 }; });
  const tableCx = 14.5*T, tableCy = 18.5*T;

  set(14,3,17,1); set(15,3,17,1);
  const cioChair = { tx:14, ty:4 };
  const board = { tx:17, ty:3 }; set(17,3,19,1);
  set(24,2,5,1); set(25,2,5,1); set(26,2,5,1); set(26,3,6,1);
  set(1,2,7,1); set(28,2,7,1); set(1,MAPH-2,7,1); set(28,MAPH-2,7,1);
  set(10,MAPH-3,7,1); set(19,MAPH-3,7,1); set(9,MAPH-3,8,1);

  // DOM elements (created inline since we're in a canvas React page)
  let elDialog: HTMLElement | null = document.getElementById('ff-dialog');
  let elHint: HTMLElement | null = document.getElementById('ff-hint');
  let elBudgetVal: HTMLElement | null = document.getElementById('ff-budget-val');
  let elBudgetFill: HTMLElement | null = document.getElementById('ff-budget-fill');

  const updateBudget = () => {
    if (!elBudgetVal || !elBudgetFill) return;
    elBudgetVal.textContent = '$' + Number(DATA.budgetSpent).toFixed(2) + ' / $' + Number(DATA.budgetCap).toFixed(2);
    const pc = Math.max(0, Math.min(1, DATA.budgetSpent / DATA.budgetCap));
    elBudgetFill.style.width = (pc*100).toFixed(0) + '%';
    elBudgetFill.style.background = pc > 0.85
      ? 'linear-gradient(90deg,#f87171,#fbbf24)'
      : (pc > 0.6 ? 'linear-gradient(90deg,#fbbf24,#9cffc4)' : 'linear-gradient(90deg,#4ade80,#9cffc4)');
  };
  updateBudget();

  const player = { x: 14*T+8, y: 11*T+12, facing: 'down', moving: false };
  const keys: Record<string, boolean> = {};
  const cam = { x: 0, y: 0 };
  let dialogOpen = false, hintTarget: string | null = null, tick = 0, raf: number | null = null;
  const coins: Array<{ px: number; py: number; t: number }> = [];
  let meetState = 'idle', meetTimer = 0;

  const KEYMAP: Record<string, string> = {
    ArrowUp:'up', ArrowDown:'down', ArrowLeft:'left', ArrowRight:'right',
    w:'up', s:'down', a:'left', d:'right', W:'up', S:'down', A:'left', D:'right',
  };

  const solidPx = (x: number, y: number) => {
    if (x<0||y<0||x>=MAPW*T||y>=MAPH*T) return true;
    return solid[Math.floor(y/T)][Math.floor(x/T)] === 1;
  };
  const boxHits = (cx: number, cy: number) => {
    const L=cx-5, Rr=cx+5, TP=cy-9, BT=cy-1;
    return solidPx(L,TP)||solidPx(Rr,TP)||solidPx(L,BT)||solidPx(Rr,BT)||solidPx(cx,BT);
  };
  const dirVec: Record<string, [number,number]> = { up:[0,-1], down:[0,1], left:[-1,0], right:[1,0] };

  const facingTarget = () => {
    const ptx = Math.floor(player.x / T), pty = Math.floor((player.y - 7) / T);
    const [vx, vy] = dirVec[player.facing] || [0,0];
    const fx = ptx+vx, fy = pty+vy;
    if (board.tx === fx && board.ty === fy) return { board: true } as const;
    const n = npcs.find(n => n.tx === fx && n.ty === fy && meetState === 'idle');
    if (n) return { npc: n } as const;
    if (meetState === 'meeting' && Math.hypot(player.x - tableCx, player.y - tableCy) < 30) return { meeting: true } as const;
    return null;
  };

  const closeDialog = () => {
    dialogOpen = false;
    if (elDialog) elDialog.style.display = 'none';
  };

  const lockMove = () => { keys.up = false; keys.down = false; keys.left = false; keys.right = false; };

  const dotColor = (s: string) => s === 'down' ? '#f87171' : (s === 'degraded' ? '#fbbf24' : '#4ade80');
  const statusLabel = (s: string) => s === 'down' ? 'DOWN' : (s === 'degraded' ? 'DEGRADED' : 'ACTIVE');

  const openMember = (n: NPC) => {
    const m = M[n.who]; if (!m || !elDialog) return;
    dialogOpen = true; lockMove();
    const dc = dotColor(m.status);
    elDialog.style.borderColor = dc;
    elDialog.innerHTML =
      '<div style="display:flex;align-items:center;gap:9px;flex-wrap:wrap;">'
      + '<span style="font-family:Silkscreen,monospace;font-size:13px;color:#eafbe9;">' + m.name + '</span>'
      + '<span style="font-family:Silkscreen,monospace;font-size:8px;color:#9fb0a0;letter-spacing:0.04em;">' + m.role + '</span>'
      + '<span style="margin-left:auto;display:flex;align-items:center;gap:5px;font-family:Silkscreen,monospace;font-size:8px;color:' + dc + ';"><span style="width:6px;height:6px;border-radius:50%;background:' + dc + ';box-shadow:0 0 6px ' + dc + ';"></span>' + statusLabel(m.status) + '</span></div>'
      + '<div style="font-family:Pixelify Sans,sans-serif;font-size:15px;line-height:1.4;color:#eafbe9;margin-top:9px;">' + m.line + '</div>'
      + '<div style="display:flex;gap:8px;margin-top:11px;flex-wrap:wrap;">'
      + '<div style="flex:1;min-width:180px;background:rgba(6,17,11,0.6);border-left:2px solid ' + dc + ';border-radius:3px;padding:7px 9px;"><div style="font-family:Silkscreen,monospace;font-size:7px;color:#7e8e7e;">LAST BRIEFING READ</div><div style="font-family:Pixelify Sans,sans-serif;font-size:13px;color:#cdd8cd;margin-top:3px;line-height:1.35;">' + m.briefing + '</div></div>'
      + '<div style="flex:1;min-width:180px;background:rgba(6,17,11,0.6);border-left:2px solid #38bdf8;border-radius:3px;padding:7px 9px;"><div style="font-family:Silkscreen,monospace;font-size:7px;color:#7e8e7e;">LAST DECISION</div><div style="font-family:Pixelify Sans,sans-serif;font-size:13px;color:#cdd8cd;margin-top:3px;line-height:1.35;">' + m.decision + '</div></div></div>'
      + '<div style="display:flex;align-items:center;justify-content:space-between;margin-top:10px;"><span style="font-family:Silkscreen,monospace;font-size:8px;color:#7e8e7e;">DAILY COST <span style="color:#fbbf24;">$' + m.cost + '</span></span><span style="font-family:Silkscreen,monospace;font-size:9px;color:#4ade80;animation:ff-blink 0.9s steps(1) infinite;">▼ CLOSE</span></div>';
    elDialog.style.display = 'block';
    if (elHint) elHint.style.display = 'none';
  };

  const openBoard = () => {
    if (!elDialog) return;
    dialogOpen = true; lockMove(); elDialog.style.borderColor = '#fbbf24';
    const html = String(DATA.cioBriefing).split('\n').map(l => {
      if (l.startsWith('# ')) return '<div style="font-family:Silkscreen,monospace;font-size:12px;color:#fbbf24;margin-bottom:4px;">' + l.slice(2) + '</div>';
      if (!l.trim()) return '<div style="height:6px;"></div>';
      return '<div style="font-family:Pixelify Sans,sans-serif;font-size:14px;line-height:1.4;color:#eafbe9;">' + l + '</div>';
    }).join('');
    elDialog.innerHTML = '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;"><span style="font-family:Silkscreen,monospace;font-size:11px;color:#fbbf24;">CIO BRIEFING BOARD</span><span style="margin-left:auto;font-family:Silkscreen,monospace;font-size:9px;color:#fbbf24;animation:ff-blink 0.9s steps(1) infinite;">▼ CLOSE</span></div>' + html;
    elDialog.style.display = 'block';
    if (elHint) elHint.style.display = 'none';
  };

  const openTranscript = () => {
    if (!elDialog) return;
    dialogOpen = true; lockMove(); elDialog.style.borderColor = '#a78bfa';
    elDialog.innerHTML = '<div style="display:flex;align-items:center;gap:8px;margin-bottom:9px;"><span style="width:7px;height:7px;border-radius:50%;background:#a78bfa;box-shadow:0 0 6px #a78bfa;"></span><span style="font-family:Silkscreen,monospace;font-size:11px;color:#a78bfa;">CIO MEETING</span><span style="margin-left:auto;font-family:Silkscreen,monospace;font-size:9px;color:#a78bfa;animation:ff-blink 0.9s steps(1) infinite;">▼ CLOSE</span></div>'
      + '<div style="font-family:Pixelify Sans,sans-serif;font-size:14px;line-height:1.5;color:#eafbe9;">Meeting in progress…</div>';
    elDialog.style.display = 'block';
    if (elHint) elHint.style.display = 'none';
  };

  const interact = () => {
    if (dialogOpen) { closeDialog(); return; }
    const t = facingTarget(); if (!t) return;
    if ('board' in t) openBoard();
    else if ('meeting' in t) openTranscript();
    else if ('npc' in t) openMember(t.npc);
  };

  const startMeeting = () => { if (meetState !== 'idle') return; meetState = 'gathering'; };
  const endMeeting = () => { if (meetState === 'idle') return; meetState = 'returning'; };

  const onKeyDown = (e: KeyboardEvent) => {
    if (['ArrowUp','ArrowDown','ArrowLeft','ArrowRight',' '].includes(e.key)) e.preventDefault();
    if (e.key === ' ' || e.key === 'Enter' || e.key === 'e' || e.key === 'E') { interact(); return; }
    const d = KEYMAP[e.key]; if (d) keys[d] = true;
  };
  const onKeyUp = (e: KeyboardEvent) => { const d = KEYMAP[e.key]; if (d) keys[d] = false; };
  window.addEventListener('keydown', onKeyDown);
  window.addEventListener('keyup', onKeyUp);

  const R = (x: number, y: number, w: number, h: number, c: string) => {
    ctx.fillStyle = c; ctx.fillRect(x|0, y|0, w, h);
  };

  const chartSeed: Record<number, number[]> = {};
  const miniChart = (sx: number, sy: number, seed: number) => {
    if (!chartSeed[seed]) {
      let s = (seed*2654435761) >>> 0; const pts: number[] = []; let yv = 4;
      for (let i = 0; i < 9; i++) {
        s = (s*1664525+1013904223) >>> 0;
        yv += ((s/4294967296)-0.5)*2.2; yv = Math.max(1,Math.min(6,yv)); pts.push(yv);
      }
      chartSeed[seed] = pts;
    }
    const pts = chartSeed[seed]; R(sx,sy,11,8,'#06150c');
    const col = ((Math.floor(tick/10)+seed)%7===0) ? '#9cffc4' : '#4ade80';
    for (let i = 0; i < pts.length-1; i++) R(sx+1+i*1.1, sy+7-pts[i], 1, 1, col);
  };

  const drawTile = (code: number, sx: number, sy: number, tx: number, ty: number) => {
    if (code === 1) { R(sx,sy,T,T,'#16241a'); R(sx,sy,T,4,'#22382a'); R(sx,sy+T-2,T,2,'#0c160f'); R(sx,sy,1,T,'#0c160f'); R(sx+T-1,sy,1,T,'#0c160f'); return; }
    if (code === 4) { R(sx+1,sy+3,T-2,T-3,'#243a32'); R(sx+1,sy+3,T-2,3,'#3a5a4c'); R(sx+1,sy+1,T-2,2,'#1a2c24'); return; }
    if (code === 14 || code === 15) {
      R(sx,sy+6,T,T-6,'#3a2a1c'); R(sx,sy+6,T,2,'#523c28'); R(sx,sy+T-1,T,1,'#241810');
      if (code===14) { R(sx+1,sy+1,14,8,'#15151a'); miniChart(sx+2,sy+1,tx*31+ty*7); R(sx+7,sy+9,2,2,'#15151a'); }
      else { R(sx+2,sy+8,9,3,'#1a1a1f'); R(sx+11,sy+8,3,4,'#cdd8cd'); }
      return;
    }
    if (code === 17) { R(sx,sy+6,T,T-6,'#173a26'); R(sx,sy+6,T,2,'#2ea36b'); R(sx+1,sy+1,14,8,'#0a1f14'); R(sx+3,sy+3,8,4,'#4ade80'); R(sx,sy+T-1,T,1,'#0c2a1a'); return; }
    if (code === 10) { R(sx+4,sy+5,8,7,'#15151a'); R(sx+3,sy+3,10,4,'#22222a'); R(sx+5,sy+12,6,3,'#101015'); return; }
    if (code === 5) {
      R(sx+2,sy,12,T,'#0e1612'); R(sx+3,sy+1,10,T-2,'#16241c');
      for (let i = 0; i < 5; i++) {
        const on = (Math.floor(tick/14)+i+tx)%3===0;
        R(sx+4,sy+2+i*3,2,1,on?'#4ade80':'#173824');
        R(sx+9,sy+2+i*3,3,1,((tick/9|0)+i)%4===0?'#fbbf24':'#2a2410');
      }
      return;
    }
    if (code === 6) {
      R(sx+1,sy+T-3,T-2,3,'#2a2a30'); R(sx+1,sy-2,T-2,T,'#0a0a0c'); R(sx+2,sy-1,T-4,T-2,'#06160d');
      R(sx+3,sy+1,8,1,'#38bdf8'); R(sx+3,sy+3,6,1,'#4ade80'); R(sx+3,sy+5,9,1,'#4ade80');
      if (Math.floor(tick/16)%2===0) R(sx+8,sy+7,2,1,'#9cffc4');
      return;
    }
    if (code === 7) { R(sx+5,sy+10,6,5,'#5a3a22'); R(sx+5,sy+10,6,1,'#714a2c'); R(sx+3,sy+3,10,8,'#1f8a5b'); R(sx+5,sy+1,6,5,'#27a86e'); R(sx+2,sy+6,4,4,'#176844'); R(sx+10,sy+5,4,4,'#176844'); return; }
    if (code === 8) { R(sx+4,sy+6,8,9,'#e8f0f6'); R(sx+5,sy+1,6,6,'#38bdf8'); R(sx+6,sy+2,4,4,'#7dd3fc'); R(sx+6,sy+10,4,2,'#9fb0cf'); return; }
    if (code === 9) { R(sx,sy,T,T,'#3a2a1c'); R(sx,sy,T,3,'#4c3826'); R(sx+1,sy+4,T-2,1,'#241810'); return; }
    if (code === 18) {
      const flash = (tick - DATA.vetoFlash) < 30 && Math.floor(tick/4)%2===0;
      R(sx,sy+6,T,4,flash?'#fbbf24':'#7a5a12'); R(sx,sy+6,T,1,flash?'#ffe08a':'#a8801c');
      R(sx+2,sy+10,2,4,'#3a2c10'); R(sx+12,sy+10,2,4,'#3a2c10'); return;
    }
    if (code === 19) { R(sx+1,sy+1,T-2,T-3,'#2a1f0c'); R(sx+1,sy+1,T-2,2,'#4a3818'); R(sx+3,sy+4,4,1,'#fbbf24'); R(sx+3,sy+6,8,1,'#cdd8cd'); R(sx+3,sy+8,6,1,'#cdd8cd'); R(sx+3,sy+10,9,1,'#cdd8cd'); return; }
  };

  const drawFloor = (sx: number, sy: number, tx: number, ty: number, code: number) => {
    const a = (tx+ty)%2===0; R(sx,sy,T,T,a?'#0e1d13':'#0c1a10');
    if ((tx*7+ty*3)%5===0) R(sx+(tx%3)*4+2,sy+(ty%3)*4+2,1,1,'#13261a');
    if (code === 11) { R(sx+1,sy,T-2,T,'#103a24'); R(sx+1,sy,T-2,1,'#175a36'); R(sx+2,sy+(ty%2?0:8),T-4,1,'#0c2a1a'); }
    if (code === 13) R(sx,sy,T,T,'#0a1810');
  };

  const drawLogoOverlay = () => {
    const cx=15*T-cam.x, cy=11*T-cam.y;
    ctx.save(); ctx.globalAlpha=0.85; ctx.translate(cx,cy); ctx.rotate(Math.PI/4);
    R(-7,-7,14,14,'#0f2a1c'); ctx.fillStyle='#1f8a5b'; ctx.fillRect(-5,-5,10,10);
    ctx.fillStyle='#4ade80'; ctx.fillRect(-2,-2,4,4); ctx.restore();
  };

  const drawPerson = (cx: number, cy: number, pal: Record<string,string>, facing: string, frame: number, isPlayer: boolean) => {
    const sx=Math.round(cx-cam.x), sy=Math.round(cy-cam.y); const ox=sx-6, oy=sy-16;
    ctx.fillStyle='rgba(0,0,0,0.28)'; ctx.fillRect(ox+1,sy-2,10,3);
    R(ox+2,oy+13,3,3+(frame?1:0),pal.pants); R(ox+7,oy+13,3,3+(frame?0:1),pal.pants);
    R(ox+1,oy+8,10,6,pal.shirt); R(ox+1,oy+8,10,1,'#ffffff22');
    R(ox+0,oy+8,2,5,pal.skin); R(ox+10,oy+8,2,5,pal.skin);
    if (facing==='up') R(ox+1,oy+0,10,8,pal.hair);
    else if (facing==='down') { R(ox+1,oy+0,10,4,pal.hair); R(ox+1,oy+4,1,3,pal.hair); R(ox+10,oy+4,1,3,pal.hair); R(ox+2,oy+4,8,4,pal.skin); R(ox+3,oy+5,2,2,'#1a1410'); R(ox+7,oy+5,2,2,'#1a1410'); }
    else if (facing==='left') { R(ox+1,oy+0,10,4,pal.hair); R(ox+8,oy+4,3,4,pal.hair); R(ox+2,oy+4,6,4,pal.skin); R(ox+3,oy+5,2,2,'#1a1410'); }
    else { R(ox+1,oy+0,10,4,pal.hair); R(ox+1,oy+4,3,4,pal.hair); R(ox+4,oy+4,6,4,pal.skin); R(ox+7,oy+5,2,2,'#1a1410'); }
    if (isPlayer) {
      R(ox+1,oy-1,10,3,pal.cap||'#eafbe9'); R(ox+1,oy-1,10,1,'#ffffff');
    }
  };

  const drawCharOverlay = (px: number, py: number, who: string) => {
    const sx=Math.round(px-cam.x), sy=Math.round(py-cam.y);
    const m = M[who]; if (!m) return;
    const dc = dotColor(m.status);
    R(sx-1,sy-26,3,3,dc);
    if (m.status !== 'active') { ctx.fillStyle=dc; ctx.globalAlpha=0.4; ctx.fillRect(sx-2,sy-27,5,5); ctx.globalAlpha=1; }
    if (DATA.stale.includes(who) && Math.floor(tick/12)%2===0) {
      ctx.fillStyle='#f87171'; ctx.font='9px Silkscreen,monospace'; ctx.textAlign='center';
      ctx.fillText('!',sx,sy-30); ctx.textAlign='left';
    }
  };

  const update = () => {
    tick++;
    if (!dialogOpen) {
      let vx=0, vy=0;
      if (keys.up) vy-=1; if (keys.down) vy+=1; if (keys.left) vx-=1; if (keys.right) vx+=1;
      player.moving = (vx!==0||vy!==0);
      if (vx!==0) player.facing=vx<0?'left':'right'; else if (vy!==0) player.facing=vy<0?'up':'down';
      if (player.moving) {
        const sp=1.15, len=Math.hypot(vx,vy)||1, mx=vx/len*sp, my=vy/len*sp;
        if (!boxHits(player.x+mx,player.y)) player.x+=mx;
        if (!boxHits(player.x,player.y+my)) player.y+=my;
      }
    }
    if (meetState !== 'idle') {
      let allArrived = true;
      npcs.forEach(n => {
        const tgt = (meetState==='gathering'||meetState==='meeting') ? n.seat! : { x:n.hx, y:n.hy };
        const dx=tgt.x-n.px, dy=tgt.y-n.py, d=Math.hypot(dx,dy);
        if (d > 1.4) {
          n.px+=dx/d*1.0; n.py+=dy/d*1.0; n.walking=true; allArrived=false;
          n.facing=Math.abs(dx)>Math.abs(dy)?(dx<0?'left':'right'):(dy<0?'up':'down');
        } else {
          n.px=tgt.x; n.py=tgt.y; n.walking=false;
          if (meetState==='meeting') {
            n.facing=n.py<tableCy?'down':(n.py>tableCy+8?'up':(n.px<tableCx?'right':'left'));
          }
        }
      });
      if (meetState==='gathering'&&allArrived) { meetState='meeting'; meetTimer=tick; }
      else if (meetState==='meeting') {
        DATA.budgetSpent=Math.min(DATA.budgetCap,DATA.budgetSpent+0.0008);
        updateBudget();
        if (tick-meetTimer > 60*16) endMeeting();
      }
      else if (meetState==='returning'&&allArrived) meetState='idle';
    }
    for (let i=coins.length-1;i>=0;i--) { coins[i].t++; if (coins[i].t>52) coins.splice(i,1); }
    cam.x=Math.round(Math.max(0,Math.min(player.x-VW/2,MAPW*T-VW)));
    cam.y=Math.round(Math.max(0,Math.min(player.y-VH/2-4,MAPH*T-VH)));
    if (!dialogOpen) {
      const t=facingTarget(); const key=t?('board' in t?'board':('meeting' in t?'meeting':t.npc.who)):null;
      if (key!==hintTarget) {
        hintTarget=key;
        if (elHint) {
          if (t && 'board' in t) { elHint.textContent='SPACE — CIO BRIEFING BOARD'; elHint.style.display='flex'; }
          else if (t && 'meeting' in t) { elHint.textContent='SPACE — JOIN MEETING'; elHint.style.display='flex'; }
          else if (t && 'npc' in t) { elHint.textContent='SPACE — '+M[t.npc.who]?.name+' · '+M[t.npc.who]?.role; elHint.style.display='flex'; }
          else elHint.style.display='none';
        }
      }
    }
  };

  const render = () => {
    ctx.clearRect(0,0,VW,VH);
    const x0=Math.floor(cam.x/T), y0=Math.floor(cam.y/T);
    const x1=Math.min(MAPW-1,x0+Math.ceil(VW/T)+1), y1=Math.min(MAPH-1,y0+Math.ceil(VH/T)+1);
    for (let ty2=y0;ty2<=y1;ty2++) for (let tx2=x0;tx2<=x1;tx2++) drawFloor(tx2*T-cam.x,ty2*T-cam.y,tx2,ty2,tile[ty2][tx2]);
    drawLogoOverlay();
    { const vy=7*T+8-cam.y, vx0=10*T-cam.x, vx1=18*T-cam.x;
      ctx.font='7px Silkscreen,monospace'; ctx.textAlign='center';
      ctx.fillStyle=(tick-DATA.vetoFlash)<30?'#ffe08a':'#fbbf24';
      ctx.fillText('VETO',(vx0+vx1)/2,vy-6); ctx.textAlign='left'; }
    for (let ty2=y0;ty2<=y1;ty2++) for (let tx2=x0;tx2<=x1;tx2++) {
      const code=tile[ty2][tx2]; if (code===0||code===11||code===13) continue;
      drawTile(code,tx2*T-cam.x,ty2*T-cam.y,tx2,ty2);
    }
    { const cx2=cioChair.tx*T-cam.x, cy2=cioChair.ty*T-cam.y;
      R(cx2+3,cy2+4,10,7,'#1f8a5b'); R(cx2+3,cy2+2,10,4,'#27a86e');
      R(cx2+6,cy2+11,4,3,'#15151a'); R(cx2+4,cy2+13,2,2,'#0c1a10'); R(cx2+10,cy2+13,2,2,'#0c1a10'); }
    const draws: Array<{ y: number; fn: () => void }> = [];
    npcs.forEach(n => draws.push({ y:n.py, fn:()=>{ drawPerson(n.px,n.py,M[n.who].pal,n.facing,n.walking?(Math.floor(tick/8)%2):0,false); drawCharOverlay(n.px,n.py,n.who); } }));
    draws.push({ y:player.y, fn:()=>drawPerson(player.x,player.y,PAL.brock,player.facing,player.moving?(Math.floor(tick/8)%2):0,true) });
    draws.sort((a,b)=>a.y-b.y).forEach(d=>d.fn());
    coins.forEach(c => {
      const sx=Math.round(c.px-cam.x), sy=Math.round(c.py-cam.y-c.t*0.6);
      const al=Math.max(0,1-c.t/52); ctx.globalAlpha=al; R(sx-2,sy,4,4,'#fbbf24'); ctx.globalAlpha=1;
    });
    ctx.textBaseline='alphabetic';
    npcs.forEach(n => {
      if (meetState!=='idle') return;
      const m=M[n.who]; const nx2=n.px-cam.x, ny2=n.ty*T-12-cam.y; if (nx2<-30||nx2>VW+30) return;
      const w=Math.max(m.name.length*5+6,m.role.length*3.4+6);
      ctx.fillStyle='rgba(6,17,11,0.9)'; ctx.fillRect(nx2-w/2,ny2-13,w,17);
      ctx.fillStyle=M[n.who].pal.shirt; ctx.fillRect(nx2-w/2,ny2-13,w,1);
      ctx.font='7px Silkscreen,monospace'; ctx.textAlign='center'; ctx.fillStyle='#eafbe9'; ctx.fillText(m.name,nx2,ny2-5);
      ctx.font='5px Silkscreen,monospace'; ctx.fillStyle='#7e8e7e'; ctx.fillText(m.role,nx2,ny2+2);
    });
    ctx.textAlign='left';
    if (DATA.night) { ctx.fillStyle='rgba(10,20,48,0.32)'; ctx.fillRect(0,0,VW,VH); }
  };

  const spawnCoin = (who: string) => { const n=npcs.find(x=>x.who===who); if (n) coins.push({ px:n.px, py:n.py-18, t:0 }); };

  const loop = () => { update(); render(); raf=requestAnimationFrame(loop); };
  raf = requestAnimationFrame(loop);

  // Expose window.BMGFloor
  window.BMGFloor = {
    setCost: (w, c) => { if (M[w]) M[w].cost = String(c); },
    setBriefing: (w, t) => {
      if (w === 'board') { DATA.cioBriefing = t; return; }
      if (M[w]) M[w].briefing = t;
    },
    setDecision: (w, t) => { if (M[w]) M[w].decision = t; },
    setStale: (list) => { DATA.stale = Array.isArray(list) ? list : []; },
    setBudget: (spent, cap) => {
      if (spent != null) DATA.budgetSpent = +spent;
      if (cap != null) DATA.budgetCap = +cap;
      updateBudget();
    },
    vetoFlash: () => { DATA.vetoFlash = tick; },
  };

  // Cleanup
  return () => {
    if (raf) cancelAnimationFrame(raf);
    window.removeEventListener('keydown', onKeyDown);
    window.removeEventListener('keyup', onKeyUp);
    try { delete window.BMGFloor; } catch (_) { /* ok */ }
  };
}
