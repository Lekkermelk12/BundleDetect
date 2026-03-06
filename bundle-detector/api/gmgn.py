from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional



@dataclass(frozen=True)
class GMGNToken:
    value: str
    acquired_at: float


class GmgnSessionManager:
    """Manages GMGN login sessions and Bearer token lifecycle via Playwright."""

    def __init__(
        self,
        email: Optional[str] = None,
        password: Optional[str] = None,
        *,
        login_url: str = "https://gmgn.ai/login",
        app_url: str = "https://gmgn.ai/?chain=sol",
        token_ttl_seconds: int = 3300,
        headless: bool = True,
        playwright_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.email = email or os.getenv("GMGN_EMAIL", "")
        self.password = password or os.getenv("GMGN_PASSWORD", "")
        self.login_url = login_url
        self.app_url = app_url
        self.token_ttl_seconds = token_ttl_seconds
        self.headless = headless
        self.playwright_factory = playwright_factory

        self._token: Optional[GMGNToken] = None
        self._lock = threading.Lock()

    def _is_token_valid(self) -> bool:
        if self._token is None:
            return False
        age = time.time() - self._token.acquired_at
        return age < self.token_ttl_seconds

    def get_bearer_token(self, *, force_refresh: bool = False) -> str:
        with self._lock:
            if not force_refresh and self._is_token_valid():
                return self._token.value

            token = self._login_and_extract_token()
            self._token = GMGNToken(value=token, acquired_at=time.time())
            return token

    def _perform_login(self, page: Any) -> None:
        if not self.email or not self.password:
            # If credentials are absent, still allow token extraction from
            # an already-authenticated browser profile/cookies.
            return

        page.goto(self.login_url, wait_until="networkidle")

        email_selectors = [
            "input[type='email']",
            "input[name='email']",
            "input[placeholder*='Email']",
        ]
        password_selectors = [
            "input[type='password']",
            "input[name='password']",
            "input[placeholder*='Password']",
        ]

        for selector in email_selectors:
            locator = page.locator(selector)
            if locator.count() > 0:
                locator.first.fill(self.email)
                break

        for selector in password_selectors:
            locator = page.locator(selector)
            if locator.count() > 0:
                locator.first.fill(self.password)
                break

        login_buttons = [
            "button:has-text('Log in')",
            "button:has-text('Login')",
            "button:has-text('Sign in')",
            "button[type='submit']",
        ]
        for selector in login_buttons:
            locator = page.locator(selector)
            if locator.count() > 0:
                locator.first.click()
                break

        page.wait_for_load_state("networkidle")

    @staticmethod
    def _token_from_storage(page: Any) -> Optional[str]:
        storage_values = page.evaluate(
            """
            () => {
              const vals = [];
              for (const key of Object.keys(localStorage)) {
                vals.push(String(localStorage.getItem(key) || ''));
              }
              for (const key of Object.keys(sessionStorage)) {
                vals.push(String(sessionStorage.getItem(key) || ''));
              }
              return vals;
            }
            """
        )

        token_pattern = re.compile(r"Bearer\s+([A-Za-z0-9\-._~+/]+=*)", re.IGNORECASE)
        jwt_pattern = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")

        for value in storage_values:
            if not value:
                continue
            bearer_match = token_pattern.search(value)
            if bearer_match:
                return bearer_match.group(1)

            jwt_match = jwt_pattern.search(value)
            if jwt_match:
                return jwt_match.group(0)

        return None

    @staticmethod
    def _token_from_cookies(context: Any) -> Optional[str]:
        cookie_candidates = {"token", "access_token", "auth_token", "authorization"}
        for cookie in context.cookies():
            name = cookie.get("name", "").lower()
            if name in cookie_candidates and cookie.get("value"):
                value = str(cookie["value"])
                if value.lower().startswith("bearer "):
                    return value.split(" ", 1)[1]
                return value
        return None

    def _login_and_extract_token(self) -> str:
        captured_auth: Dict[str, str] = {}

        def request_listener(request: Any) -> None:
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer ") and "token" not in captured_auth:
                captured_auth["token"] = auth.split(" ", 1)[1]

        playwright_factory = self.playwright_factory
        if playwright_factory is None:
            from playwright.sync_api import sync_playwright

            playwright_factory = sync_playwright

        with playwright_factory() as playwright:
            browser = playwright.chromium.launch(headless=self.headless)
            context = browser.new_context()
            page = context.new_page()
            page.on("request", request_listener)

            page.goto(self.app_url, wait_until="networkidle")
            self._perform_login(page)
            page.goto(self.app_url, wait_until="networkidle")

            token = captured_auth.get("token")
            if not token:
                token = self._token_from_storage(page)
            if not token:
                token = self._token_from_cookies(context)

            browser.close()

        if not token:
            raise RuntimeError("Unable to extract GMGN Bearer token from Playwright session")
        return token


class GMGNClient:
    def __init__(
        self,
        session_manager: GmgnSessionManager,
        *,
        base_url: str = "https://gmgn.ai/tapi/v1",
        timeout_seconds: int = 20,
        http_session: Optional[Any] = None,
    ) -> None:
        self.session_manager = session_manager
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        if http_session is None:
            import requests

            self.http_session = requests.Session()
        else:
            self.http_session = http_session

    def _get(self, endpoint: str, wallet_address: str, extra_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"chain": "sol", "address": wallet_address}
        if extra_params:
            params.update(extra_params)

        token = self.session_manager.get_bearer_token()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{self.base_url}/{endpoint}"

        response = self.http_session.get(url, params=params, headers=headers, timeout=self.timeout_seconds)
        if response.status_code == 401:
            refreshed_token = self.session_manager.get_bearer_token(force_refresh=True)
            headers = {"Authorization": f"Bearer {refreshed_token}"}
            response = self.http_session.get(url, params=params, headers=headers, timeout=self.timeout_seconds)

        response.raise_for_status()
        return response.json()

    def wallet_daily_profits(self, wallet_address: str) -> Dict[str, Any]:
        return self._get("wallet/daily_profits", wallet_address)

    def wallet_holdings(self, wallet_address: str) -> Dict[str, Any]:
        return self._get("wallet/holdings", wallet_address)

    def wallet_activity(self, wallet_address: str) -> Dict[str, Any]:
        return self._get("wallet/activity", wallet_address, extra_params={"type": ["buy", "sell"]})
