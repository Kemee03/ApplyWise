const form = document.querySelector("#auth-form");
const message = document.querySelector("#form-message");
const button = form.querySelector("button[type=submit]");
const mode = form.dataset.mode;

fetch("/auth/me").then((response) => { if (response.ok) location.replace("/app"); }).catch(() => {});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  message.textContent = "";
  message.classList.remove("success");
  button.disabled = true;
  button.firstChild.textContent = mode === "register" ? "Creating your account… " : "Signing in… ";
  const values = Object.fromEntries(new FormData(form).entries());
  try {
    const response = await fetch(`/auth/${mode}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || "We couldn’t complete that request. Please try again.");
    message.textContent = "Account ready. Opening your workspace…";
    message.classList.add("success");
    location.assign("/app");
  } catch (error) {
    message.textContent = error.message;
    button.disabled = false;
    button.firstChild.textContent = mode === "register" ? "Create account " : "Sign in ";
  }
});
