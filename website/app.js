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
const heroLogo = document.querySelector(".hero-logo");
if (nav && heroLogo && "IntersectionObserver" in window) {
  new IntersectionObserver(
    ([entry]) => nav.classList.toggle("scrolled", !entry.isIntersecting),
    { threshold: 0 }
  ).observe(heroLogo);
} else if (nav) {
  nav.classList.add("scrolled");
}

// Report preview tabs (Series / Movies)
document.querySelectorAll(".mini-tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".mini-tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("report-series").hidden = btn.dataset.report !== "series";
    document.getElementById("report-movies").hidden = btn.dataset.report !== "movies";
  });
});

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
