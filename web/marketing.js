const steps = [...document.querySelectorAll(".walk-step")];
const dots = [...document.querySelectorAll(".step-dot")];
const fill = document.querySelector("#progress-fill");
const counter = document.querySelector("#step-current");
let activeStep = 0;
let timer;

function showStep(index) {
  activeStep = (index + steps.length) % steps.length;
  steps.forEach((step, i) => {
    step.classList.toggle("active", i === activeStep);
    step.setAttribute("aria-hidden", String(i !== activeStep));
  });
  dots.forEach((dot, i) => dot.classList.toggle("current", i === activeStep));
  counter.textContent = String(activeStep + 1).padStart(2, "0");
  fill.style.transition = "none";
  fill.style.width = `${(activeStep + 1) * 33.333}%`;
  requestAnimationFrame(() => { fill.style.transition = "width 1.9s linear"; });
}
function startTour() {
  clearInterval(timer);
  showStep(activeStep);
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
    timer = setInterval(() => { if (!document.hidden) showStep(activeStep + 1); }, 2200);
  }
}
document.querySelector("#step-back").addEventListener("click", () => { showStep(activeStep - 1); startTour(); });
document.querySelector("#step-next").addEventListener("click", () => { showStep(activeStep + 1); startTour(); });
dots.forEach((dot, i) => dot.addEventListener("click", () => { showStep(i); startTour(); }));
document.querySelector(".menu-toggle").addEventListener("click", (event) => {
  const nav = document.querySelector(".site-nav");
  const open = nav.classList.toggle("open");
  event.currentTarget.setAttribute("aria-expanded", String(open));
  event.currentTarget.textContent = open ? "×" : "☰";
});
startTour();
