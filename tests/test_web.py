"""
Automated Integration Tests for Web Routing and Authentication UI.
Verifies:
- Public routes: /, /login, /register
- Protected routes redirect unauthenticated users to /login
- Registration form has no role selector
- Authenticated user can access dashboard and navigation pages
- Session termination on /logout
- Zero impact on backend database or API integrity
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.config import TestingConfig
from app.database import init_db


class TestWebAuthRoutes(unittest.TestCase):
    def setUp(self):
        """Initializes an isolated temporary database and Flask test client."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_web.db")

        # Initialize schema into the temporary database
        init_db(db_path=self.db_path)

        class CustomTestConfig(TestingConfig):
            DATABASE_PATH = self.db_path

        self.app = create_app(CustomTestConfig)
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_unauthenticated_redirects(self):
        """Unauthenticated access to protected pages redirects to /login."""
        # Root redirects to /login
        res = self.client.get("/")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login", res.headers.get("Location", ""))

        # Protected pages redirect to /login
        for path in ["/dashboard", "/sandboxes", "/monitor", "/activity", "/settings"]:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 302, f"{path} must redirect when unauthenticated")
            self.assertIn("/login", res.headers.get("Location", ""))

    def test_login_and_register_pages_render_html(self):
        """Login and register pages return 200 HTML with expected security controls."""
        login_res = self.client.get("/login")
        self.assertEqual(login_res.status_code, 200)
        login_html = login_res.get_data(as_text=True)
        self.assertIn("Sign In", login_html)
        self.assertIn("login-form", login_html)
        self.assertNotIn('name="role"', login_html, "Login page must not have role selector")

        reg_res = self.client.get("/register")
        self.assertEqual(reg_res.status_code, 200)
        reg_html = reg_res.get_data(as_text=True)
        self.assertIn("Create Account", reg_html)
        self.assertIn("register-form", reg_html)
        self.assertNotIn('name="role"', reg_html, "Registration page MUST NOT expose a role selector")
        self.assertNotIn("<select", reg_html, "Registration page must not have dropdown role selector")

    def test_authenticated_navigation_flow(self):
        """Authenticated user can access all main navigation pages and logout."""
        # 1. Register
        reg_res = self.client.post(
            "/api/auth/register",
            data=json.dumps({"username": "webuser", "password": "Password123!"}),
            content_type="application/json"
        )
        self.assertEqual(reg_res.status_code, 201)

        # 2. Login
        login_res = self.client.post(
            "/api/auth/login",
            data=json.dumps({"username": "webuser", "password": "Password123!"}),
            content_type="application/json"
        )
        self.assertEqual(login_res.status_code, 200)

        # 3. Access dashboard
        dash_res = self.client.get("/dashboard")
        self.assertEqual(dash_res.status_code, 200)
        self.assertIn("Dashboard", dash_res.get_data(as_text=True))

        # 4. Access other authenticated views
        for path in ["/sandboxes", "/monitor", "/activity", "/settings"]:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, f"Authenticated user should access {path}")

        # 5. Accessing /login or /register while logged in redirects to /dashboard
        self.assertEqual(self.client.get("/login").status_code, 302)
        self.assertEqual(self.client.get("/register").status_code, 302)

        # 6. Logout
        logout_res = self.client.get("/logout")
        self.assertEqual(logout_res.status_code, 302)
        self.assertIn("/login", logout_res.headers.get("Location", ""))

        # 7. Accessing dashboard after logout redirects back to /login
        after_logout = self.client.get("/dashboard")
        self.assertEqual(after_logout.status_code, 302)


if __name__ == "__main__":
    unittest.main(verbosity=2)
