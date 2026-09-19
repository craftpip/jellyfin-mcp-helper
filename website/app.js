// Tabs (REST / MCP)
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
  });
});

// Show the header logo once the hero logo scrolls out of view
const nav = document.querySelector(".nav");
const heroMark = document.querySelector(".hero-logo");
if (nav && heroMark && "IntersectionObserver" in window) {
  new IntersectionObserver(
    ([entry]) => nav.classList.toggle("scrolled", !entry.isIntersecting),
    { threshold: 0 }
  ).observe(heroMark);
} else if (nav) {
  nav.classList.add("scrolled");
}

// Copy buttons on code blocks
document.querySelectorAll("pre").forEach((block) => {
  const btn = document.createElement("button");
  btn.className = "copy-btn";
  btn.textContent = "Copy";
  btn.addEventListener("click", async () => {
    const code = block.querySelector("code").innerText;
    try {
      await navigator.clipboard.writeText(code);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = code;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    btn.textContent = "Copied";
    setTimeout(() => { btn.textContent = "Copy"; }, 1500);
  });
  block.appendChild(btn);
});

// Mobile nav
const toggle = document.querySelector(".nav-toggle");
const links = document.querySelector(".nav-links");
toggle.addEventListener("click", () => {
  const open = links.classList.toggle("open");
  toggle.setAttribute("aria-expanded", String(open));
});
links.querySelectorAll("a").forEach((a) => {
  a.addEventListener("click", () => links.classList.remove("open"));
});

// ——— Sorting demo ———
const FILE_QUEUE = [
  { name: "Example.Show.S01E04.1080p.mkv", kind: "series" },
  { name: "An.Example.Movie.2024.2160p.mkv", kind: "movie" },
  { name: "Example.Show.S01E05.part", kind: "skip" },
  { name: "Example.Classic.1995.REMUX.mkv", kind: "movie" },
  { name: "Example.Show.S02E01.v2.mkv", kind: "series" },
  { name: "Example.Show.Trailer.mkv", kind: "skip" },
  { name: "Another.Example.Movie.2021.x265.mkv", kind: "movie" },
  { name: "Example.Show.S01E06.WEB.mkv", kind: "series" },
];
const STATUS = {
  series: ["S01E04 · classified series — target resolved", "season folder matched — queued as move", "SxxEyy locked — replace existing"],
  movie: ["title + year matched — queued as move", "movie pattern confirmed — new home ready", "classified movie — target resolved"],
  skip: ["in-progress marker detected — skipping", "trailer, not an episode — skipping", "sample file — skipping"],
};
const IDLE = ["scan complete — nothing pending", "waiting for new files…", "all planned. confirm when ready."];

const sorter = document.getElementById("sorter");
const tray = document.getElementById("tray");
const trayFiles = document.getElementById("trayFiles");
const statusEl = document.getElementById("sorterStatus");
const folderEls = new Map([...document.querySelectorAll(".folder")].map((f) => [f.dataset.kind, f]));
const counts = {};
folderEls.forEach((_, kind) => { counts[kind] = 0; });

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let queue = [];
let scheduleId = null;
let seen = false;
let running = false;

const rand = (arr) => arr[Math.floor(Math.random() * arr.length)];

function renderTray() {
  trayFiles.innerHTML = "";
  queue.slice(0, 4).forEach((f) => {
    const li = document.createElement("li");
    li.className = "file";
    li.textContent = f.name;
    trayFiles.appendChild(li);
  });
  if (!queue.length) {
    const li = document.createElement("li");
    li.className = "tray-empty";
    li.textContent = "— empty —";
    trayFiles.appendChild(li);
  }
}

function setStatus(text) {
  statusEl.textContent = text;
}

function bump(kind) {
  counts[kind]++;
  const c = folderEls.get(kind).querySelector(".count");
  c.textContent = counts[kind];
  c.classList.remove("pop");
  void c.offsetWidth;
  c.classList.add("pop");
}

function seed(append) {
  queue = append ? queue.concat(FILE_QUEUE.map((f) => ({ ...f }))) : FILE_QUEUE.map((f) => ({ ...f }));
  renderTray();
}

function schedule(fn, delay) {
  scheduleId = setTimeout(() => {
    if (running && seen) fn();
  }, delay);
}

function flyNext() {
  if (!queue.length) return finishBatch();
  const item = queue.shift();
  renderTray();

  const chip = document.createElement("div");
  chip.className = "file-fly";
  chip.setAttribute("kind", item.kind);
  chip.textContent = item.name;
  document.body.appendChild(chip);

  const start = tray.getBoundingClientRect();
  const target = folderEls.get(item.kind).getBoundingClientRect();
  const sx = start.left + start.width / 2 - chip.offsetWidth / 2;
  const sy = start.top + start.height / 2 - chip.offsetHeight / 2;
  const ex = target.left + target.width / 2 - chip.offsetWidth / 2;
  const ey = target.top + target.height / 2 - chip.offsetHeight / 2;
  const mx = (sx + ex) / 2;
  const my = Math.min(sy, ey) - 70;

  setStatus(rand(STATUS[item.kind]));

  const anim = chip.animate(
    [
      { transform: `translate(${sx}px, ${sy}px) scale(1)`, opacity: 1 },
      { transform: `translate(${mx}px, ${my}px) scale(.96)`, opacity: 1, offset: .55 },
      { transform: `translate(${ex}px, ${ey}px) scale(.82)`, opacity: .9 },
    ],
    { duration: 780, easing: "cubic-bezier(.35,.05,.3,1)" }
  );

  anim.finished.then(() => {
    chip.remove();
    bump(item.kind);
    const pick = document.createElement("span");
    pick.className = "file";
    pick.textContent = item.name;
    folderEls.get(item.kind).querySelector(".picks").appendChild(pick);
    schedule(flyNext, 820);
  }).catch(() => chip.remove());
}

function finishBatch() {
  setStatus(rand(IDLE));
  schedule(() => {
    setStatus("new files detected — scanning…");
    seed(false);
    schedule(flyNext, 600);
  }, 2400);
}

function start() {
  if (reduceMotion || running) return;
  running = true;
  seed(false);
  schedule(flyNext, 600);
}

function stop() {
  running = false;
  clearTimeout(scheduleId);
}

new IntersectionObserver(([e]) => {
  seen = e.isIntersecting;
  if (seen && !running) start();
  else if (!seen && running) stop();
}, { threshold: 0 }).observe(sorter);

tray.addEventListener("click", () => {
  if (reduceMotion) return;
  if (!running) { start(); return; }
  seed(true);
  setStatus("new batch dropped in!");
});

tray.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    tray.click();
  }
});

if (reduceMotion) {
  const perKind = {};
  FILE_QUEUE.forEach((f) => { perKind[f.kind] = (perKind[f.kind] || 0) + 1; });
  counts.series = perKind.series || 0;
  counts.movie = perKind.movie || 0;
  counts.skip = perKind.skip || 0;
  folderEls.forEach((el, kind) => { el.querySelector(".count").textContent = counts[kind]; });
  trayFiles.innerHTML = "";
  const li = document.createElement("li");
  li.className = "tray-empty";
  li.textContent = "all sorted — nothing pending";
  trayFiles.appendChild(li);
  setStatus("reduced motion on — demo paused.");
}