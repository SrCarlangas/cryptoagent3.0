"""Pixel Agents-style top-down Agent Office, driven by BTC agent activity.

Uses the official Pixel Agents MIT-licensed character, furniture, floor and wall
assets, served locally by the dashboard. The browser renderer builds a real tiled
office (not cards), animates 16x32 sprites with walk/typing/reading frames, moves
agents between desks and a central collaboration space, shows speech bubbles, and
renders real pipeline activity from /api/state.

Upstream assets: https://github.com/pixel-agents-hq/pixel-agents (MIT).
License is preserved in observability/static/pixel-office/LICENSE.txt.
"""

from __future__ import annotations

FLOOR_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Agent Office · BTC Decision Lab</title>
<style>
 @font-face{font-family:pixel;src:local('Monaco')}
 :root{color-scheme:dark;--ink:#e8edf8;--muted:#9da9bd;--panel:#111827;--cyan:#3de1d0}
 *{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#060913;color:var(--ink);font-family:pixel,'SFMono-Regular',Consolas,monospace}
 canvas{position:fixed;inset:0;width:100%;height:100%;image-rendering:pixelated;cursor:grab}
 canvas.drag{cursor:grabbing}
 #hud{position:fixed;z-index:5;left:16px;right:16px;top:12px;display:flex;align-items:center;gap:10px;pointer-events:none}
 .brand,.chip,.panel,.hint{background:rgba(8,13,26,.93);border:2px solid #263751;box-shadow:3px 3px 0 #02040a}
 .brand{padding:9px 13px;font-weight:800;letter-spacing:.06em}.brand a{color:#5eead4;text-decoration:none}.brand em{font-style:normal;color:#ffcc66}
 .chip{padding:7px 10px;font-size:11px;color:var(--muted)}.chip b{color:var(--ink)}.spacer{flex:1}
 #side{position:fixed;z-index:6;right:16px;top:66px;width:278px;display:none;padding:14px;pointer-events:auto}.panel h2{font-size:13px;margin:0 0 8px;color:#fff}.panel .role{font-size:10px;color:#5eead4;letter-spacing:.12em}.panel .note{font-size:11px;line-height:1.55;color:#b9c8db;margin-top:10px}.panel .status{display:inline-block;margin-top:10px;padding:3px 7px;border:1px solid currentColor;font-size:10px}
 #hint{position:fixed;z-index:5;left:16px;bottom:12px;padding:7px 10px;font-size:10px;color:#8392a8;pointer-events:none}
 #load{position:fixed;inset:0;z-index:10;display:grid;place-items:center;background:#060913;color:#8392a8;font-size:12px}
</style></head><body>
<div id="load">LOADING AGENT OFFICE…</div>
<div id="hud"><div class="brand"><a href="/">← DASHBOARD</a> · <em>AGENT OFFICE // GEEK OPS V12</em></div><div class="chip">DEMO · LIVE</div><div class="spacer"></div><div class="chip">POS <b id="pos">—</b></div><div class="chip">BTC <b id="price">—</b></div><div class="chip">EQUITY <b id="eq">—</b></div><div class="chip">VS HOLD <b id="ex">—</b></div></div>
<div id="side" class="panel"><div class="role" id="srole"></div><h2 id="sname"></h2><div class="note" id="snote"></div><span class="status" id="sstatus"></span></div>
<div id="hint" class="hint">CLICK AGENT · DRAG TO PAN · WHEEL TO ZOOM · REAL ACTIVITY FROM JOURNAL</div>
<canvas id="office"></canvas>
<script>
const A='/static/pixel-office/';
const PATH={
 floor1:A+'assets/floors/floor_1.png',floor2:A+'assets/floors/floor_2.png',floor3:A+'assets/floors/floor_3.png',floor7:A+'assets/floors/floor_7.png',floor8:A+'assets/floors/floor_8.png',carpet:A+'assets/carpets/carpet_1.png',office:A+'office.png',
 desk:A+'assets/furniture/DESK/DESK_FRONT.png',pc1:A+'assets/furniture/PC/PC_FRONT_ON_1.png',pc2:A+'assets/furniture/PC/PC_FRONT_ON_2.png',pc3:A+'assets/furniture/PC/PC_FRONT_ON_3.png',chair:A+'assets/furniture/WOODEN_CHAIR/WOODEN_CHAIR_FRONT.png',shelf:A+'assets/furniture/DOUBLE_BOOKSHELF/DOUBLE_BOOKSHELF.png',plant:A+'assets/furniture/LARGE_PLANT/LARGE_PLANT.png',plant2:A+'assets/furniture/PLANT_2/PLANT_2.png',sofa:A+'assets/furniture/SOFA/SOFA_FRONT.png',sofaSide:A+'assets/furniture/SOFA/SOFA_SIDE.png',coffeeTable:A+'assets/furniture/COFFEE_TABLE/COFFEE_TABLE.png',coffee:A+'assets/furniture/COFFEE/COFFEE.png',whiteboard:A+'assets/furniture/WHITEBOARD/WHITEBOARD.png',painting:A+'assets/furniture/LARGE_PAINTING/LARGE_PAINTING.png',clock:A+'assets/furniture/CLOCK/CLOCK.png',bin:A+'assets/furniture/BIN/BIN.png',
 ch0:A+'assets/characters/char_0.png',ch1:A+'assets/characters/char_1.png',ch2:A+'assets/characters/char_2.png',ch3:A+'assets/characters/char_3.png',ch4:A+'assets/characters/char_4.png',ch5:A+'assets/characters/char_5.png'
};
const cv=document.getElementById('office'),ctx=cv.getContext('2d');ctx.imageSmoothingEnabled=false;
const TILE=16,COLS=60,ROWS=40,W=960,H=640;
let DPR=1,scale=2,camX=0,camY=0,drag=false,dragAt=null,lastOrders=null,state={floor:[],recent:[]},selected=null,t=0;
const IMG={};
function loadImg(k,url){return new Promise((ok,bad)=>{const i=new Image();i.onload=()=>{IMG[k]=i;ok(i)};i.onerror=bad;i.src=url})}
const AGENTS=[
 {id:'sensor',name:'Market Scout',role:'LIVE MARKET DATA',sheet:'ch0',home:[190,260],desk:[190,260],door:[164,284],meet:[420,320]},
 {id:'research',name:'Research Analyst',role:'RESEARCH LAB',sheet:'ch1',home:[480,260],desk:[480,260],door:[480,284],meet:[455,320]},
 {id:'policy',name:'Strategy Engineer',role:'POLICY DEVELOPMENT',sheet:'ch2',home:[790,260],desk:[790,260],door:[796,284],meet:[440,318]},
 {id:'risk',name:'Risk Governor',role:'RISK & COMPLIANCE',sheet:'ch3',home:[170,570],desk:[170,570],door:[164,356],meet:[480,318]},
 {id:'execution',name:'Execution Trader',role:'DEMO EXECUTION',sheet:'ch4',home:[480,570],desk:[480,570],door:[480,356],meet:[520,318]},
 {id:'ledger',name:'Memory Keeper',role:'LEDGER & MEMORY',sheet:'ch5',home:[790,570],desk:[790,570],door:[796,356],meet:[555,320]},
].map((a,i)=>({...a,x:a.home[0],y:a.home[1],tx:a.home[0],ty:a.home[1],path:[],inMeeting:false,dir:0,frame:0,status:'idle',note:'awaiting activity',bubble:0,phase:i*.9,wandering:0}));
const ROOMS=[
 {x:1,y:1,w:13,h:12,label:'MARKET DATA',floor:'floor7',color:'#ffb454',base:'#925b37'},
 {x:15,y:1,w:14,h:12,label:'RESEARCH LAB',floor:'floor7',color:'#8fd3ff',base:'#77513b'},
 {x:30,y:1,w:15,h:12,label:'STRATEGY DEV',floor:'floor7',color:'#e0b0ff',base:'#695040'},
 {x:1,y:17,w:13,h:12,label:'RISK & QA',floor:'floor1',color:'#ffd178',base:'#486a89'},
 {x:15,y:17,w:14,h:12,label:'TRADING DESK',floor:'floor1',color:'#67f2dd',base:'#3f7188'},
 {x:30,y:17,w:15,h:12,label:'MEMORY / LEDGER',floor:'floor1',color:'#8fc3ff',base:'#526f92'},
];
const FURN=[
 // top desks and electronics
 ...[[4,4],[17,4],[34,4],[4,19],[19,19],[34,19]].flatMap((p,i)=>[
  {k:'desk',x:p[0]*TILE,y:p[1]*TILE,z:p[1]*TILE+32},{k:'pc'+((i%3)+1),x:(p[0]+1)*TILE,y:(p[1]-1)*TILE,z:p[1]*TILE+20},{k:'chair',x:(p[0]+1)*TILE,y:(p[1]+2)*TILE,z:(p[1]+3)*TILE}
 ]),
 // shelves / boards / decor
 {k:'shelf',x:2*TILE,y:2*TILE,z:3*TILE},{k:'plant',x:11*TILE,y:2*TILE,z:4*TILE},{k:'clock',x:9*TILE,y:1*TILE,z:2*TILE},
 {k:'whiteboard',x:16*TILE,y:1*TILE,z:3*TILE},{k:'shelf',x:25*TILE,y:2*TILE,z:3*TILE},{k:'plant2',x:27*TILE,y:3*TILE,z:4*TILE},
 {k:'whiteboard',x:31*TILE,y:1*TILE,z:3*TILE},{k:'painting',x:39*TILE,y:1*TILE,z:3*TILE},{k:'plant',x:42*TILE,y:2*TILE,z:4*TILE},
 {k:'shelf',x:2*TILE,y:18*TILE,z:19*TILE},{k:'whiteboard',x:9*TILE,y:17*TILE,z:19*TILE},{k:'plant2',x:12*TILE,y:24*TILE,z:26*TILE},
 {k:'whiteboard',x:16*TILE,y:17*TILE,z:19*TILE},{k:'plant',x:27*TILE,y:25*TILE,z:27*TILE},{k:'bin',x:17*TILE,y:26*TILE,z:27*TILE},
 {k:'shelf',x:31*TILE,y:18*TILE,z:19*TILE},{k:'shelf',x:39*TILE,y:18*TILE,z:19*TILE},{k:'clock',x:42*TILE,y:17*TILE,z:18*TILE},
 // collaboration lounge in central corridor
 {k:'sofa',x:17*TILE,y:13*TILE,z:14*TILE},{k:'sofa',x:25*TILE,y:15*TILE,z:16*TILE},{k:'sofaSide',x:16*TILE,y:14*TILE,z:16*TILE},{k:'sofaSide',x:28*TILE,y:14*TILE,z:16*TILE},{k:'coffeeTable',x:21*TILE,y:14*TILE,z:16*TILE},{k:'coffee',x:22*TILE,y:14*TILE,z:17*TILE},
 // secondary workstations make each functional area feel occupied and extensible
 ...[[9,8],[24,8],[39,8],[9,24],[24,24],[39,24]].flatMap((p,i)=>[
  {k:'desk',x:p[0]*TILE,y:p[1]*TILE,z:p[1]*TILE+32},{k:'pc'+(((i+1)%3)+1),x:(p[0]+1)*TILE,y:(p[1]-1)*TILE,z:p[1]*TILE+20},{k:'chair',x:(p[0]+1)*TILE,y:(p[1]+2)*TILE,z:(p[1]+3)*TILE}
 ]),
 // additional office texture: reading corners, plants, bins and wall decor
 {k:'plant2',x:2*TILE,y:10*TILE,z:12*TILE},{k:'bin',x:12*TILE,y:10*TILE,z:12*TILE},
 {k:'painting',x:21*TILE,y:1*TILE,z:3*TILE},{k:'bin',x:28*TILE,y:10*TILE,z:12*TILE},
 {k:'shelf',x:31*TILE,y:2*TILE,z:3*TILE},{k:'plant2',x:43*TILE,y:10*TILE,z:12*TILE},
 {k:'plant',x:2*TILE,y:25*TILE,z:27*TILE},{k:'bin',x:12*TILE,y:26*TILE,z:28*TILE},
 {k:'painting',x:22*TILE,y:17*TILE,z:19*TILE},{k:'bin',x:28*TILE,y:26*TILE,z:28*TILE},
 {k:'whiteboard',x:36*TILE,y:17*TILE,z:19*TILE},{k:'plant',x:43*TILE,y:25*TILE,z:27*TILE},
];
function resize(){DPR=Math.min(2,devicePixelRatio||1);cv.width=innerWidth*DPR;cv.height=innerHeight*DPR;cv.style.width=innerWidth+'px';cv.style.height=innerHeight+'px';ctx.setTransform(DPR,0,0,DPR,0,0);ctx.imageSmoothingEnabled=false;if(camX===0&&camY===0){scale=Math.min((innerWidth-30)/W,(innerHeight-82)/H);camX=(innerWidth-W*scale)/2;camY=(innerHeight-H*scale)/2+18}}
addEventListener('resize',resize);
function stat(id){return(state.floor||[]).find(x=>x.id===id)||{status:'idle',note:'waiting'}}
function pattern(k){return ctx.createPattern(IMG[k],'repeat')}
function rect(x,y,w,h,fill,stroke='#0c1422'){ctx.fillStyle=fill;ctx.fillRect(x,y,w,h);ctx.strokeStyle=stroke;ctx.lineWidth=1;ctx.strokeRect(x+.5,y+.5,w-1,h-1)}
function drawRoom(r){const x=r.x*TILE,y=r.y*TILE,w=r.w*TILE,h=r.h*TILE;ctx.fillStyle=r.base;ctx.fillRect(x,y,w,h);ctx.save();ctx.globalCompositeOperation='multiply';ctx.globalAlpha=.72;ctx.fillStyle=pattern(r.floor);ctx.fillRect(x,y,w,h);ctx.restore();ctx.fillStyle='#121d2c';ctx.fillRect(x-5,y-8,w+10,8);ctx.fillRect(x-5,y+h,w+10,5);ctx.fillRect(x-5,y-8,5,h+13);ctx.fillRect(x+w,y-8,5,h+13);ctx.fillStyle='#2c415c';ctx.fillRect(x-3,y-6,w+6,2);ctx.fillStyle='#07101c';ctx.fillRect(x+5,y-17,Math.max(72,r.label.length*5+12),12);ctx.font='bold 7px monospace';ctx.fillStyle=r.color;ctx.fillText(r.label,x+9,y-9)}
function drawFurniture(o){const im=IMG[o.k];if(!im)return;ctx.save();if(o.flip){ctx.translate(o.x+im.width,o.y);ctx.scale(-1,1);ctx.drawImage(im,0,0)}else ctx.drawImage(im,o.x,o.y);ctx.restore()}
function sprite(a,now){const im=IMG[a.sheet];if(!im)return;const moving=Math.hypot(a.tx-a.x,a.ty-a.y)>2;let col=0,row=0,flip=false;if(moving){col=[0,1,2,1][Math.floor(now*7+a.phase)%4];if(Math.abs(a.tx-a.x)>Math.abs(a.ty-a.y)){row=2;flip=a.tx<a.x}else row=a.ty<a.y?1:0}else if(a.status==='working'||a.status==='success'){col=3+Math.floor(now*3+a.phase)%2;row=1}else if(a.id==='research'||a.id==='ledger'){col=5+Math.floor(now*2+a.phase)%2;row=0}const sw=48,sh=96,dx=Math.round(a.x-sw/2),dy=Math.round(a.y-sh+10);ctx.save();if(flip){ctx.translate(dx+sw,dy);ctx.scale(-1,1);ctx.drawImage(im,col*16,row*32,16,32,0,0,sw,sh)}else ctx.drawImage(im,col*16,row*32,16,32,dx,dy,sw,sh);ctx.restore();
 const w=Math.max(104,a.name.length*8+18);ctx.fillStyle='rgba(3,6,12,.94)';ctx.fillRect(a.x-w/2,a.y+8,w,20);ctx.strokeStyle=a.status==='alert'?'#ff6b6b':a.status==='success'?'#4de8ff':'#415776';ctx.strokeRect(a.x-w/2+.5,a.y+8.5,w-1,19);ctx.fillStyle=a.status==='alert'?'#ff8b8b':a.status==='success'?'#66efff':'#f4f7ff';ctx.font='bold 11px monospace';ctx.textAlign='center';ctx.fillText(a.name.toUpperCase(),a.x,a.y+22);ctx.textAlign='left';
 if(a.bubble>0||selected===a.id)bubble(a,a.note)}
function bubble(a,text){if(!text)return;const lines=[];let s=text;while(s.length>32){let n=s.lastIndexOf(' ',32);if(n<12)n=32;lines.push(s.slice(0,n));s=s.slice(n).trim()}lines.push(s);const bw=236,bh=24+lines.length*15,bx=a.x-bw/2,by=a.y-118-bh;ctx.fillStyle='#f8f7ec';ctx.fillRect(bx,by,bw,bh);ctx.strokeStyle='#111827';ctx.lineWidth=2;ctx.strokeRect(bx+1,by+1,bw-2,bh-2);ctx.fillStyle='#182033';ctx.font='12px monospace';lines.forEach((l,i)=>ctx.fillText(l,bx+10,by+20+i*15));ctx.fillStyle='#f8f7ec';ctx.beginPath();ctx.moveTo(a.x-8,by+bh);ctx.lineTo(a.x+8,by+bh);ctx.lineTo(a.x,by+bh+12);ctx.fill()}
function arrow(ax,ay,bx,by,phase){ctx.save();ctx.strokeStyle='rgba(49,220,255,.75)';ctx.lineWidth=2;ctx.setLineDash([7,4]);ctx.lineDashOffset=-phase*20;ctx.beginPath();ctx.moveTo(ax,ay);ctx.lineTo(bx,by);ctx.stroke();ctx.setLineDash([]);const ang=Math.atan2(by-ay,bx-ax);ctx.fillStyle='#31dcff';ctx.beginPath();ctx.moveTo(bx,by);ctx.lineTo(bx-8*Math.cos(ang-.5),by-8*Math.sin(ang-.5));ctx.lineTo(bx-8*Math.cos(ang+.5),by-8*Math.sin(ang+.5));ctx.fill();ctx.restore()}
let collaborationSeq=0,lastInteractionKey=null;
function setRoute(a,points,meeting){a.path=points.map(p=>[p[0],p[1]]);a.inMeeting=meeting;if(a.path.length){a.tx=a.path[0][0];a.ty=a.path[0][1]}}
function routeToHub(a,note){a.note=note;a.bubble=3;setRoute(a,[[a.door[0],a.door[1]],[a.door[0],325],[a.meet[0],325],[a.meet[0],a.meet[1]]],true)}
function routeHome(a){a.bubble=0;setRoute(a,[[a.door[0],325],[a.door[0],a.door[1]],[a.desk[0],a.desk[1]]],false)}
function beginCollaboration(snapshot){const token=++collaborationSeq,p=AGENTS.find(a=>a.id==='policy'),r=AGENTS.find(a=>a.id==='risk'),e=AGENTS.find(a=>a.id==='execution');routeToHub(p,`Proposal: ${snapshot.last_action||'HOLD'}`);setTimeout(()=>{if(token!==collaborationSeq)return;routeToHub(r,`Reviewing risk · ${snapshot.position||'—'}`)},1300);setTimeout(()=>{if(token!==collaborationSeq)return;routeToHub(e,`Execution plan · ${snapshot.last_reason||'waiting'}`)},2600);setTimeout(()=>{if(token!==collaborationSeq)return;p.note='Decision approved';r.note='Risk checked';e.note=snapshot.order_count?'Fill reconciled':'No order';p.bubble=r.bubble=e.bubble=2.5},4700);setTimeout(()=>{if(token!==collaborationSeq)return;[p,r,e].forEach(routeHome)},7600)}
function updateAgents(dt){for(const a of AGENTS){const s=stat(a.id),changed=s.status!==a.status||s.note!==a.note;if(changed){a.status=s.status;if(!a.inMeeting)a.note=s.note;if(s.status==='alert'&&!a.inMeeting){routeToHub(a,`Alert: ${s.note}`);setTimeout(()=>{if(a.inMeeting)routeHome(a)},6000)}else if(!a.inMeeting&&a.path.length===0){a.tx=a.desk[0];a.ty=a.desk[1]}}a.bubble=Math.max(0,a.bubble-dt);let dx=a.tx-a.x,dy=a.ty-a.y,d=Math.hypot(dx,dy);if(d<=1&&a.path.length){a.x=a.tx;a.y=a.ty;a.path.shift();if(a.path.length){a.tx=a.path[0][0];a.ty=a.path[0][1];dx=a.tx-a.x;dy=a.ty-a.y;d=Math.hypot(dx,dy)}}if(d>1){const sp=72*dt;a.x+=dx/d*Math.min(sp,d);a.y+=dy/d*Math.min(sp,d)}}}
function zoneLabel(text,x,y,color){ctx.fillStyle='rgba(4,8,16,.88)';ctx.fillRect(x,y,Math.max(150,text.length*9+24),24);ctx.strokeStyle=color;ctx.lineWidth=2;ctx.strokeRect(x+1,y+1,Math.max(150,text.length*9+24)-2,22);ctx.fillStyle=color;ctx.font='bold 12px monospace';ctx.fillText(text,x+10,y+17)}
function neonBox(x,y,w,h,title,color){ctx.save();ctx.fillStyle='rgba(2,12,24,.82)';ctx.fillRect(x,y,w,h);ctx.shadowColor=color;ctx.shadowBlur=10;ctx.strokeStyle=color;ctx.lineWidth=2;ctx.strokeRect(x+.5,y+.5,w-1,h-1);ctx.shadowBlur=0;ctx.fillStyle=color;ctx.font='bold 10px monospace';ctx.fillText(title,x+8,y+15);ctx.restore()}
function seriesValues(key){return(state.recent||[]).slice().reverse().map(e=>Number(e[key])).filter(Number.isFinite)}
function miniChart(x,y,w,h,values,color){if(values.length<2)return;let lo=Math.min(...values),hi=Math.max(...values);if(lo===hi){lo-=1;hi+=1}ctx.save();ctx.strokeStyle='rgba(61,225,208,.16)';ctx.lineWidth=1;for(let i=1;i<4;i++){ctx.beginPath();ctx.moveTo(x,y+h*i/4);ctx.lineTo(x+w,y+h*i/4);ctx.stroke()}ctx.shadowColor=color;ctx.shadowBlur=7;ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();values.forEach((v,i)=>{const px=x+w*i/(values.length-1),py=y+h-(v-lo)/(hi-lo)*h;i?ctx.lineTo(px,py):ctx.moveTo(px,py)});ctx.stroke();ctx.restore()}
function serverRack(x,y,status,phase){const col=status==='alert'?'#ff5d71':'#43e8cf';neonBox(x,y,76,132,'DATA RACK',col);ctx.fillStyle='#0a1627';ctx.fillRect(x+9,y+23,58,100);for(let r=0;r<7;r++){ctx.fillStyle='#132840';ctx.fillRect(x+13,y+28+r*13,50,9);for(let l=0;l<4;l++){const on=(Math.floor(phase*5+r+l)%3)!==0;ctx.fillStyle=on?(r%3===0?'#ffcc66':col):'#233348';ctx.fillRect(x+18+l*10,y+31+r*13,4,3)}}ctx.fillStyle='#7091ad';ctx.font='8px monospace';ctx.fillText('ws://live',x+16,y+119)}
function riskRadar(x,y,phase,status){const col=status==='alert'?'#ff5d71':'#53f0d0';neonBox(x,y,148,112,'RISK RADAR',col);const cx=x+74,cy=y+68,r=35;ctx.save();ctx.strokeStyle='rgba(83,240,208,.32)';ctx.lineWidth=1;[12,24,35].forEach(rr=>{ctx.beginPath();ctx.arc(cx,cy,rr,0,Math.PI*2);ctx.stroke()});ctx.beginPath();ctx.moveTo(cx-r,cy);ctx.lineTo(cx+r,cy);ctx.moveTo(cx,cy-r);ctx.lineTo(cx,cy+r);ctx.stroke();const a=phase*1.8;ctx.fillStyle='rgba(83,240,208,.14)';ctx.beginPath();ctx.moveTo(cx,cy);ctx.arc(cx,cy,r,a-.55,a);ctx.closePath();ctx.fill();ctx.strokeStyle=col;ctx.beginPath();ctx.moveTo(cx,cy);ctx.lineTo(cx+Math.cos(a)*r,cy+Math.sin(a)*r);ctx.stroke();ctx.fillStyle=col;ctx.fillRect(cx+Math.cos(a-.2)*23-2,cy+Math.sin(a-.2)*23-2,4,4);ctx.restore()}
function aiCore(x,y,phase){const active=state.last_action==='ENTER_LONG'||state.last_action==='EXIT_LONG',col=active?'#ffcc66':'#4de8ff',pulse=1+Math.sin(phase*3)*.12;ctx.save();ctx.translate(x,y);ctx.shadowColor=col;ctx.shadowBlur=18;ctx.strokeStyle=col;ctx.lineWidth=3;ctx.beginPath();ctx.arc(0,0,30*pulse,0,Math.PI*2);ctx.stroke();ctx.shadowBlur=5;ctx.strokeStyle='rgba(77,232,255,.55)';ctx.beginPath();ctx.arc(0,0,42,phase,phase+Math.PI*1.4);ctx.stroke();ctx.beginPath();ctx.arc(0,0,50,-phase*.7,-phase*.7+Math.PI);ctx.stroke();ctx.fillStyle='rgba(4,24,42,.9)';ctx.beginPath();ctx.arc(0,0,22,0,Math.PI*2);ctx.fill();ctx.fillStyle=col;ctx.font='bold 14px monospace';ctx.textAlign='center';ctx.fillText('AI',0,5);ctx.textAlign='left';ctx.shadowBlur=0;ctx.fillStyle='#87a9c0';ctx.font='8px monospace';ctx.fillText('DECISION CORE',-36,65);ctx.restore()}
function memoryGraph(x,y,phase){neonBox(x,y,176,92,'MEMORY GRAPH','#b88cff');const n=6,pts=[];for(let i=0;i<n;i++){const a=i/n*Math.PI*2+phase*.08;pts.push([x+88+Math.cos(a)*50,y+54+Math.sin(a)*24])}ctx.strokeStyle='rgba(184,140,255,.42)';ctx.lineWidth=1;for(let i=0;i<n;i++){for(let j=i+1;j<n;j++){if((i+j+Math.floor(phase))%3===0){ctx.beginPath();ctx.moveTo(...pts[i]);ctx.lineTo(...pts[j]);ctx.stroke()}}}pts.forEach((p,i)=>{ctx.fillStyle=i<(state.order_count||0)%n?'#ffcc66':'#b88cff';ctx.fillRect(p[0]-3,p[1]-3,6,6)});ctx.fillStyle='#9db0c8';ctx.font='8px monospace';ctx.fillText(`eval:${state.eval_count||0}  orders:${state.order_count||0}`,x+10,y+84)}
function execConsole(x,y){const col=state.last_action==='ENTER_LONG'?'#53f0a8':state.last_action==='EXIT_LONG'?'#ff9b66':'#4de8ff';neonBox(x,y,184,76,'EXECUTION CONSOLE',col);ctx.fillStyle='#abc0d4';ctx.font='9px monospace';ctx.fillText(`> action ${state.last_action||'HOLD'}`,x+10,y+31);ctx.fillText(`> pos    ${state.position||'—'}`,x+10,y+45);ctx.fillStyle=col;ctx.fillText(`> ${state.last_reason||'waiting'}`.slice(0,31),x+10,y+61)}
function compiler(x,y){neonBox(x,y,190,80,'STRATEGY COMPILER','#ffcc66');ctx.font='9px monospace';ctx.fillStyle='#b9c9dc';ctx.fillText(`fast = ${state.fast_sma?Number(state.fast_sma).toFixed(2):'—'}`,x+10,y+31);ctx.fillText(`slow = ${state.slow_sma?Number(state.slow_sma).toFixed(2):'—'}`,x+10,y+45);ctx.fillStyle=state.last_action==='ENTER_LONG'?'#53f0a8':'#7da2bd';ctx.fillText(`emit ${state.last_action||'HOLD'}`,x+10,y+62)}
function circuit(x1,y1,x2,y2,phase,color='#34dbea'){ctx.save();ctx.strokeStyle='rgba(52,219,234,.25)';ctx.lineWidth=2;ctx.setLineDash([4,5]);ctx.lineDashOffset=-phase*12;ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo((x1+x2)/2,y1);ctx.lineTo((x1+x2)/2,y2);ctx.lineTo(x2,y2);ctx.stroke();ctx.setLineDash([]);const f=(phase*.3)%1,px=x1+(x2-x1)*f,py=y1+(y2-y1)*f;ctx.fillStyle=color;ctx.fillRect(px-2,py-2,5,5);ctx.restore()}
function techLayer(phase){ctx.save();ctx.fillStyle='rgba(2,8,22,.20)';ctx.fillRect(0,0,W,H);serverRack(48,145,stat('sensor').status,phase);compiler(290,112);const prices=seriesValues('price');neonBox(650,92,260,112,'MARKET HOLOGRAM','#4de8ff');miniChart(664,120,232,68,prices,'#4de8ff');if(state.price){ctx.fillStyle='#d9f9ff';ctx.font='bold 11px monospace';ctx.fillText(`BTC ${Number(state.price).toLocaleString()}`,666,105)}riskRadar(62,452,phase,stat('risk').status);execConsole(598,430);memoryGraph(798,474,phase);aiCore(930,575,phase);circuit(122,276,650,148,phase);circuit(386,276,690,468,phase+.4,'#ffcc66');circuit(690,468,886,520,phase+.8,'#b88cff');ctx.restore()}
function labRoom(x,y,w,h,label,accent,base,doorBottom){
 ctx.fillStyle=base;ctx.fillRect(x,y,w,h);
 // metallic floor panels with bolts and alternating plates
 for(let yy=y;yy<y+h;yy+=16)for(let xx=x;xx<x+w;xx+=16){ctx.fillStyle=((xx+yy)/16)%2===0?'rgba(255,255,255,.012)':'rgba(0,0,0,.035)';ctx.fillRect(xx,yy,16,16);ctx.strokeStyle='#172b40';ctx.lineWidth=1;ctx.strokeRect(xx+.5,yy+.5,15,15);ctx.fillStyle='rgba(94,234,212,.20)';ctx.fillRect(xx+2,yy+2,1,1)}
 const wt=14,top=22,bottom=14;
 // wall volume: top cap, front face, side columns and bottom sill
 ctx.fillStyle='#0a1422';ctx.fillRect(x-wt,y-top,w+wt*2,top);ctx.fillRect(x-wt,y+h,w+wt*2,bottom);ctx.fillRect(x-wt,y-top,wt,h+top+bottom);ctx.fillRect(x+w,y-top,wt,h+top+bottom);
 ctx.fillStyle='#203753';ctx.fillRect(x-wt+3,y-top+3,w+wt*2-6,5);ctx.fillRect(x-wt+3,y+h+3,w+wt*2-6,5);ctx.fillRect(x-wt+3,y-top+3,4,h+top+bottom-6);ctx.fillRect(x+w+7,y-top+3,4,h+top+bottom-6);
 ctx.fillStyle='#344d6a';ctx.fillRect(x-wt+5,y-top+5,w+wt*2-10,2);ctx.fillStyle=accent;ctx.fillRect(x,y-3,w,2);
 // structural columns every 72px
 for(let px=x+70;px<x+w;px+=72){ctx.fillStyle='#16283d';ctx.fillRect(px,y-top,7,top);ctx.fillStyle='#3a526d';ctx.fillRect(px+1,y-top+2,2,top-4)}
 // physical door cutout facing corridor, with jambs and threshold lights
 const dx=x+w/2-32;
 if(doorBottom){ctx.fillStyle='#030711';ctx.fillRect(dx,y+h,64,bottom);ctx.fillStyle='#344d6a';ctx.fillRect(dx-4,y+h,4,bottom);ctx.fillRect(dx+64,y+h,4,bottom);ctx.fillStyle=accent;ctx.fillRect(dx,y+h+bottom-2,64,2)}
 else {ctx.fillStyle='#030711';ctx.fillRect(dx,y-top,64,top);ctx.fillStyle='#344d6a';ctx.fillRect(dx-4,y-top,4,top);ctx.fillRect(dx+64,y-top,4,top);ctx.fillStyle=accent;ctx.fillRect(dx,y-2,64,2)}
 // wall-mounted room sign (inside its own wall, never over the floor)
 const signW=Math.max(112,label.length*8+20);ctx.fillStyle='#050b15';ctx.fillRect(x+12,y-top+4,signW,15);ctx.strokeStyle=accent;ctx.strokeRect(x+12.5,y-top+4.5,signW-1,14);ctx.fillStyle=accent;ctx.font='bold 9px monospace';ctx.fillText(label,x+20,y-top+15)
}
function meetingHub(phase){const x=399,y=298,w=162,h=54;ctx.fillStyle='rgba(8,22,36,.96)';ctx.fillRect(x,y,w,h);ctx.strokeStyle='#3adfd4';ctx.lineWidth=2;ctx.strokeRect(x+.5,y+.5,w-1,h-1);ctx.fillStyle='#172b40';ctx.fillRect(x+25,y+13,w-50,27);ctx.strokeStyle='#55718a';ctx.strokeRect(x+25.5,y+13.5,w-51,26);const pulse=.45+.3*Math.sin(phase*3);ctx.fillStyle=`rgba(58,223,212,${pulse})`;ctx.fillRect(x+40,y+20,w-80,3);ctx.fillStyle='#3adfd4';ctx.font='bold 8px monospace';ctx.fillText('COLLAB HUB',x+50,y+10);for(const sx of [x+10,x+w-18])for(const sy of [y+10,y+34]){ctx.fillStyle='#243a50';ctx.fillRect(sx,sy,8,10);ctx.fillStyle='#425f78';ctx.fillRect(sx+1,sy+1,6,3)}}
function labMonitor(x,y,w,h,accent,title,values){ctx.fillStyle='#050b14';ctx.fillRect(x,y,w,h);ctx.strokeStyle='#334963';ctx.lineWidth=3;ctx.strokeRect(x-2,y-2,w+4,h+4);ctx.fillStyle=accent;ctx.fillRect(x,y,w,3);ctx.font='bold 7px monospace';ctx.fillText(title,x+5,y+12);if(values&&values.length>1)miniChart(x+6,y+17,w-12,h-23,values,accent);else{ctx.fillStyle='rgba(78,219,208,.5)';for(let i=0;i<5;i++)ctx.fillRect(x+7,y+18+i*7,Math.max(8,(w-16)*(0.3+((i*17)%50)/100)),2)}}
function labDesk(x,y,w,accent,title,values,mode){ctx.fillStyle='#162538';ctx.fillRect(x,y+55,w,23);ctx.fillStyle='#263b53';ctx.fillRect(x,y+55,w,5);ctx.fillStyle='#0b1421';ctx.fillRect(x+9,y+78,8,20);ctx.fillRect(x+w-17,y+78,8,20);const monitors=mode==='triple'?3:2,mw=Math.floor((w-16-(monitors-1)*6)/monitors);for(let i=0;i<monitors;i++){const vals=i===0?values:(i===1?seriesValues('fast_sma'):seriesValues('slow_sma'));labMonitor(x+8+i*(mw+6),y,mw,48,accent,i===0?title:(i===1?'FAST SMA':'SLOW SMA'),vals)}ctx.fillStyle='#51677e';ctx.fillRect(x+w/2-8,y+48,16,7);ctx.fillStyle=accent;ctx.fillRect(x+w/2-12,y+82,24,3)}
function labRack(x,y,w,h,accent,status,phase){ctx.fillStyle='#0a1320';ctx.fillRect(x,y,w,h);ctx.strokeStyle='#354b62';ctx.lineWidth=3;ctx.strokeRect(x-2,y-2,w+4,h+4);ctx.fillStyle=accent;ctx.fillRect(x,y,w,3);for(let r=0;r<8;r++){ctx.fillStyle='#14263b';ctx.fillRect(x+7,y+12+r*13,w-14,9);for(let l=0;l<4;l++){const on=(Math.floor(phase*6+r+l)%3)!==0;ctx.fillStyle=on?(status==='alert'?'#ff5f6d':l===3?'#ffcc66':accent):'#26374a';ctx.fillRect(x+13+l*9,y+15+r*13,4,3)}}ctx.fillStyle='#8299ad';ctx.font='7px monospace';ctx.fillText('NODE '+String(state.eval_count||0).padStart(4,'0'),x+8,y+h-6)}
function physicalCore(x,y,phase){const active=state.last_action==='ENTER_LONG'||state.last_action==='EXIT_LONG',col=active?'#ffcc66':'#44dfef';ctx.fillStyle='#111e30';ctx.fillRect(x-45,y-18,90,60);ctx.strokeStyle='#354c66';ctx.lineWidth=3;ctx.strokeRect(x-47,y-20,94,64);ctx.fillStyle='#1d3248';ctx.fillRect(x-32,y-43,64,28);ctx.strokeStyle=col;ctx.strokeRect(x-30,y-41,60,24);const p=1+Math.sin(phase*3)*.12;ctx.save();ctx.shadowColor=col;ctx.shadowBlur=12;ctx.strokeStyle=col;ctx.lineWidth=3;ctx.beginPath();ctx.arc(x,y-29,15*p,0,Math.PI*2);ctx.stroke();ctx.fillStyle='rgba(6,26,45,.94)';ctx.fillRect(x-12,y-39,24,20);ctx.fillStyle=col;ctx.font='bold 10px monospace';ctx.fillText('AI',x-7,y-25);ctx.restore();ctx.fillStyle='#8ca2b8';ctx.font='7px monospace';ctx.fillText('DECISION CORE',x-28,y+32)}
function deskRadar(x,y,w,accent,phase){labDesk(x,y,w,accent,'RISK',null,'double');const cx=x+w/2,cy=y+24,r=16;ctx.strokeStyle='rgba(83,240,208,.55)';[6,11,16].forEach(rr=>{ctx.beginPath();ctx.arc(cx,cy,rr,0,Math.PI*2);ctx.stroke()});const a=phase*1.7;ctx.strokeStyle=accent;ctx.beginPath();ctx.moveTo(cx,cy);ctx.lineTo(cx+Math.cos(a)*r,cy+Math.sin(a)*r);ctx.stroke()}
function orderBookDesk(x,y,w,accent){labDesk(x,y,w,accent,'ORDERS',null,'triple');for(let i=0;i<7;i++){const bw=12+(i*13)%40;ctx.fillStyle=i<3?'#47df9a':'#ff7b72';ctx.fillRect(x+12,y+18+i*4,bw,2);ctx.fillRect(x+w-12-bw,y+18+i*4,bw,2)}}
function labArchitecture(phase){
 ctx.fillStyle='#030711';ctx.fillRect(0,0,W,H);
 // central corridor is drawn first so it can never cover room walls or labels
 ctx.fillStyle='#07101c';ctx.fillRect(14,292,932,66);for(let x=20;x<940;x+=24){ctx.fillStyle=(x/24)%2?'#10243a':'#0c1d30';ctx.fillRect(x,297,18,56);ctx.fillStyle='#1f4860';ctx.fillRect(x+3,324,12,2)}
 circuit(110,325,850,325,phase,'#36ddeb');
 // six physically separated offices, each with a door into the corridor
 labRoom(24,42,280,240,'MARKET DATA','#41e5d1','#081524',true);
 labRoom(340,42,280,240,'RESEARCH LAB','#54bfff','#091727',true);
 labRoom(656,42,280,240,'STRATEGY DEV','#d28bff','#101326',true);
 labRoom(24,374,280,242,'RISK & QA','#ffbd5c','#121523',false);
 labRoom(340,374,280,242,'EXECUTION OPS','#45e2a0','#081923',false);
 labRoom(656,374,280,242,'MEMORY CORE','#9d84ff','#0d1326',false);
 meetingHub(phase);
 // Market data: physical racks + dual monitor desk
 labRack(42,92,54,128,'#41e5d1',stat('sensor').status,phase);labRack(104,92,54,128,'#41e5d1',stat('sensor').status,phase+.5);
 labDesk(172,126,112,'#41e5d1','BTC/USD',seriesValues('price'),'double');
 // Research: three-monitor quantitative workstation
 labDesk(372,126,216,'#54bfff','PRICE',seriesValues('price'),'triple');
 // Strategy development: compiler workstation embedded in monitors
 labDesk(687,126,218,'#d28bff','POLICY',seriesValues('fast_sma'),'triple');
 // Risk: radar console and shield indicator
 deskRadar(60,444,214,'#ffbd5c',phase);ctx.strokeStyle=stat('risk').status==='alert'?'#ff596a':'#ffbd5c';ctx.lineWidth=2;ctx.beginPath();ctx.arc(263,411,18,0,Math.PI*2);ctx.stroke();ctx.fillStyle='#ffbd5c';ctx.font='7px monospace';ctx.fillText('SHIELD',243,414);
 // Execution: integrated orderbook and fill console
 orderBookDesk(372,444,216,'#45e2a0');
 // Memory: two racks and a physical AI core
 labRack(672,397,48,126,'#9d84ff',stat('ledger').status,phase);labRack(728,397,48,126,'#9d84ff',stat('ledger').status,phase+.7);physicalCore(854,466,phase);
}
function render(now){t=now/1000;ctx.save();ctx.setTransform(scale*DPR,0,0,scale*DPR,camX*DPR,camY*DPR);ctx.imageSmoothingEnabled=false;labArchitecture(t);
 const entities=AGENTS.map(a=>({z:a.y,fn:()=>sprite(a,t)})).sort((a,b)=>a.z-b.z);entities.forEach(e=>e.fn());
 ctx.restore();requestAnimationFrame(render)}
function screenToWorld(x,y){return{x:(x-camX)/scale,y:(y-camY)/scale}}
cv.addEventListener('pointerdown',e=>{drag=true;dragAt={x:e.clientX,y:e.clientY,cx:camX,cy:camY};cv.classList.add('drag');const p=screenToWorld(e.clientX,e.clientY);selected=null;for(const a of AGENTS)if(Math.hypot(p.x-a.x,p.y-a.y)<18){selected=a.id;showPanel(a);break}});
addEventListener('pointermove',e=>{if(drag&&dragAt){camX=dragAt.cx+e.clientX-dragAt.x;camY=dragAt.cy+e.clientY-dragAt.y}});addEventListener('pointerup',()=>{drag=false;dragAt=null;cv.classList.remove('drag')});
cv.addEventListener('wheel',e=>{e.preventDefault();const p=screenToWorld(e.clientX,e.clientY),old=scale;scale=Math.max(1,Math.min(6,scale+(e.deltaY<0?1:-1)));camX=e.clientX-p.x*scale;camY=e.clientY-p.y*scale},{passive:false});
function showPanel(a){const s=stat(a.id),p=document.getElementById('side');p.style.display='block';document.getElementById('srole').textContent=a.role;document.getElementById('sname').textContent=a.name;document.getElementById('snote').textContent=s.note;const ss=document.getElementById('sstatus');ss.textContent=s.status.toUpperCase();ss.style.color=s.status==='alert'?'#ff6b6b':s.status==='success'?'#66e3ff':'#5eead4'}
async function poll(){try{
 const r=await fetch('/api/state');const n=await r.json();const previousOrders=state.order_count||0;
 if(n.order_count>previousOrders){const ex=AGENTS.find(a=>a.id==='execution');ex.bubble=5;ex.note='ORDER FILLED · '+n.last_action}
 state=n;
 document.getElementById('pos').textContent=state.position||'—';document.getElementById('price').textContent=state.price?Number(state.price).toLocaleString(undefined,{maximumFractionDigits:2}):'—';document.getElementById('eq').textContent=state.equity_usdt?Number(state.equity_usdt).toLocaleString(undefined,{maximumFractionDigits:2}):'—';
 const sv=state.strategy_vs_hold,ex=document.getElementById('ex');if(sv){const v=Number(sv.excess_pct);ex.textContent=(v>=0?'+':'')+v.toFixed(3)+'%';ex.style.color=v>=0?'#5eead4':'#ff6b6b'}
 const interactionKey=`${n.generated_at||''}|${n.last_action||''}|${n.order_count||0}`;
 if(interactionKey!==lastInteractionKey&&(n.last_action==='ENTER_LONG'||n.last_action==='EXIT_LONG'))beginCollaboration(n);
 lastInteractionKey=interactionKey;updateAgents(0)
 }catch(e){}}
let last=performance.now();function loop(now){const dt=Math.min(.05,(now-last)/1000);last=now;updateAgents(dt);requestAnimationFrame(loop)}
Promise.all(Object.entries(PATH).map(([k,u])=>loadImg(k,u))).then(()=>{document.getElementById('load').remove();resize();poll();setInterval(poll,2500);requestAnimationFrame(render);requestAnimationFrame(loop)}).catch(e=>{document.getElementById('load').textContent='ASSET LOAD FAILED · '+e});
</script></body></html>
"""

__all__ = ["FLOOR_PAGE"]
