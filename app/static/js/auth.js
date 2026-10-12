/**
 * Authentication Form Handling (Login & Register)
 */

document.addEventListener("DOMContentLoaded", () => {
  const loginForm = document.getElementById("login-form");
  const registerForm = document.getElementById("register-form");

  // --------------------------------------------------------------------------
  // LOGIN FLOW
  // --------------------------------------------------------------------------
  if (loginForm) {
    const errorAlert = document.getElementById("auth-error-alert");
    const submitBtn = document.getElementById("login-submit-btn");
    const btnText = submitBtn.querySelector(".btn-text");
    const btnSpinner = submitBtn.querySelector(".btn-spinner");

    loginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlert(errorAlert);

      const usernameInput = document.getElementById("username");
      const passwordInput = document.getElementById("password");

      const username = usernameInput.value.trim();
      const password = passwordInput.value;

      if (!username || !password) {
        showAlert(errorAlert, "Please provide both username and password.");
        return;
      }

      setLoading(submitBtn, btnText, btnSpinner, true);

      try {
        const res = await api.post("/api/auth/login", { username, password });
        showToast("Logged in successfully. Redirecting...", "success");
        setTimeout(() => {
          window.location.href = "/dashboard";
        }, 500);
      } catch (err) {
        setLoading(submitBtn, btnText, btnSpinner, false);
        showAlert(errorAlert, err.message || "Invalid username or password.");
      }
    });
  }

  // --------------------------------------------------------------------------
  // REGISTER FLOW (STRICT ROLE='USER' ENFORCEMENT)
  // --------------------------------------------------------------------------
  if (registerForm) {
    const errorAlert = document.getElementById("auth-error-alert");
    const successAlert = document.getElementById("auth-success-alert");
    const submitBtn = document.getElementById("register-submit-btn");
    const btnText = submitBtn.querySelector(".btn-text");
    const btnSpinner = submitBtn.querySelector(".btn-spinner");

    registerForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      hideAlert(errorAlert);
      hideAlert(successAlert);

      const usernameInput = document.getElementById("username");
      const passwordInput = document.getElementById("password");
      const confirmInput = document.getElementById("confirm_password");

      const username = usernameInput.value.trim();
      const password = passwordInput.value;
      const confirmPassword = confirmInput.value;

      if (!username || username.length < 3) {
        showAlert(errorAlert, "Username must be at least 3 characters long.");
        usernameInput.focus();
        return;
      }

      if (!password || password.length < 6) {
        showAlert(errorAlert, "Password must be at least 6 characters long.");
        passwordInput.focus();
        return;
      }

      if (password !== confirmPassword) {
        showAlert(errorAlert, "Passwords do not match. Please verify.");
        confirmInput.focus();
        return;
      }

      setLoading(submitBtn, btnText, btnSpinner, true);

      try {
        // Enforce strict security: only username and password sent. NO role parameter.
        await api.post("/api/auth/register", { username, password });
        
        showAlert(successAlert, "Account registered successfully! Signing you in...");
        
        // Auto-login newly registered user
        try {
          await api.post("/api/auth/login", { username, password });
          showToast("Welcome! Redirecting to dashboard...", "success");
          setTimeout(() => {
            window.location.href = "/dashboard";
          }, 700);
        } catch {
          // Fallback redirect to login page
          setTimeout(() => {
            window.location.href = "/login";
          }, 1000);
        }
      } catch (err) {
        setLoading(submitBtn, btnText, btnSpinner, false);
        showAlert(errorAlert, err.message || "Registration failed. Username may already be taken.");
      }
    });
  }
});

function showAlert(el, msg) {
  if (!el) return;
  el.textContent = msg;
  el.classList.add("visible");
}

function hideAlert(el) {
  if (!el) return;
  el.textContent = "";
  el.classList.remove("visible");
}

function setLoading(btn, textEl, spinnerEl, isLoading) {
  btn.disabled = isLoading;
  if (isLoading) {
    if (textEl) textEl.style.display = "none";
    if (spinnerEl) spinnerEl.style.display = "inline-block";
  } else {
    if (textEl) textEl.style.display = "inline-block";
    if (spinnerEl) spinnerEl.style.display = "none";
  }
}
