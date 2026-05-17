const form = document.querySelector("[data-login-form]");
const statusNode = document.querySelector("[data-login-status]");

function nextUrl() {
  const raw = new URLSearchParams(window.location.search).get("next") || "index.html";
  if (/^https?:\/\//i.test(raw) || raw.startsWith("//")) return "index.html";
  return raw;
}

async function login(body) {
  const response = await fetch("/api/v1/auth/login", {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = "登录失败";
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (error) {
      // Keep the generic message when the server did not return JSON.
    }
    throw new Error(detail);
  }
  return response.json();
}

form?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button[type='submit']");
  const data = new FormData(form);
  button.disabled = true;
  statusNode.textContent = "正在登录...";
  statusNode.className = "login-status loading";
  try {
    await login({
      username: String(data.get("username") || "").trim(),
      password: String(data.get("password") || ""),
    });
    statusNode.textContent = "登录成功";
    statusNode.className = "login-status success";
    window.location.href = nextUrl();
  } catch (error) {
    statusNode.textContent = error.message || "登录失败";
    statusNode.className = "login-status error";
    button.disabled = false;
  }
});
