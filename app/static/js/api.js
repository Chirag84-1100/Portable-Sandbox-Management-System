
(() => {
  "use strict";

  async function request(url, options = {}) {
    const config = {
      ...options,
      method: options.method || "GET",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(options.body !== undefined
          ? { "Content-Type": "application/json" }
          : {}),
        ...(options.headers || {})
      }
    };

    if (
      config.body !== undefined &&
      typeof config.body !== "string"
    ) {
      config.body = JSON.stringify(config.body);
    }

    const response = await fetch(url, config);

    let result;
    try {
      result = await response.json();
    } catch {
      throw new Error("Server returned an invalid JSON response.");
    }

    if (!response.ok || result?.success === false) {
      const message =
        result?.error?.message ||
        result?.message ||
        result?.error ||
        `Request failed (${response.status})`;

      throw new Error(
        typeof message === "string"
          ? message
          : JSON.stringify(message)
      );
    }

    return result;
  }

  function get(url, options = {}) {
    return request(url, { ...options, method: "GET" });
  }

  function post(url, body = {}, options = {}) {
    return request(url, {
      ...options,
      method: "POST",
      body
    });
  }

  function put(url, body = {}, options = {}) {
    return request(url, {
      ...options,
      method: "PUT",
      body
    });
  }

  function deleteRequest(url, options = {}) {
    return request(url, {
      ...options,
      method: "DELETE"
    });
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    })[character]);
  }

  function showToast(message, type = "info") {
    let toast = document.getElementById("app-toast");

    if (!toast) {
      toast = document.createElement("div");
      toast.id = "app-toast";
      toast.setAttribute("role", "status");

      Object.assign(toast.style, {
        position: "fixed",
        right: "20px",
        bottom: "20px",
        zIndex: "9999",
        maxWidth: "min(400px, calc(100vw - 40px))",
        padding: "14px 18px",
        borderRadius: "10px",
        background: "#242424",
        color: "#fff",
        boxShadow: "0 4px 16px rgba(0,0,0,.2)",
        overflowWrap: "anywhere"
      });

      document.body.appendChild(toast);
    }

    toast.textContent = String(message ?? "");
    toast.style.display = "block";
    toast.style.borderLeft =
      type === "error" ? "4px solid #ef4444" :
        type === "success" ? "4px solid #22c55e" :
          "4px solid #a855f7";

    if (toast._hideTimer) clearTimeout(toast._hideTimer);

    toast._hideTimer = setTimeout(() => {
      toast.style.display = "none";
    }, 3500);
  }

  window.api = {
    request,
    get,
    post,
    put,
    delete: deleteRequest,
    escapeHtml,
    showToast
  };

  window.escapeHtml = escapeHtml;
  window.showToast = showToast;
})();
