from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from playwright.sync_api import Page, Playwright, TimeoutError as PlaywrightTimeoutError, sync_playwright


DEFAULT_PAGE_URL = "https://www.namesilo.com/phishing-report"
TWO_CAPTCHA_IN_URL = "https://2captcha.com/in.php"
TWO_CAPTCHA_RES_URL = "https://2captcha.com/res.php"
SECURITY_VERIFY_TEXT = "Performing security verification"


@dataclass
class RecorderInput:
    email: str
    real_website: str
    phishing_website: str
    report_text: str
    proof_image: str = ""


class TwoCaptchaError(RuntimeError):
    pass


class TwoCaptchaClient:
    def __init__(self, api_key: str, timeout_seconds: int = 180, poll_interval_seconds: int = 5) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    def solve_recaptcha_v2(self, *, page_url: str, site_key: str) -> str:
        with httpx.Client(timeout=30.0) as client:
            submit_resp = client.post(
                TWO_CAPTCHA_IN_URL,
                data={
                    "key": self.api_key,
                    "method": "userrecaptcha",
                    "googlekey": site_key,
                    "pageurl": page_url,
                    "json": 1,
                },
            )
            submit_resp.raise_for_status()
            submit_payload = submit_resp.json()
            if int(submit_payload.get("status", 0)) != 1:
                raise TwoCaptchaError(f"2Captcha submit failed: {submit_payload}")

            captcha_id = str(submit_payload["request"])
            deadline = time.monotonic() + self.timeout_seconds

            while time.monotonic() < deadline:
                time.sleep(self.poll_interval_seconds)
                result_resp = client.get(
                    TWO_CAPTCHA_RES_URL,
                    params={
                        "key": self.api_key,
                        "action": "get",
                        "id": captcha_id,
                        "json": 1,
                    },
                )
                result_resp.raise_for_status()
                result_payload = result_resp.json()

                if int(result_payload.get("status", 0)) == 1:
                    return str(result_payload["request"])

                if result_payload.get("request") == "CAPCHA_NOT_READY":
                    continue

                raise TwoCaptchaError(f"2Captcha result failed: {result_payload}")

        raise TwoCaptchaError("2Captcha result timeout")


def _first_non_empty(values: list[str | None]) -> str:
    for value in values:
        if value:
            return value
    return ""


def detect_recaptcha_site_key(page: Page, timeout_seconds: int = 20) -> str:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        site_key_nodes = page.locator("[data-sitekey]")
        if site_key_nodes.count() > 0:
            site_key = site_key_nodes.first.get_attribute("data-sitekey")
            if site_key:
                return site_key

        frame_nodes = page.locator("iframe[src*='recaptcha']")
        if frame_nodes.count() > 0:
            frame_src = frame_nodes.first.get_attribute("src") or ""
            query_key = parse_qs(urlparse(frame_src).query).get("k", [""])[0]
            if query_key:
                return query_key

        page.wait_for_timeout(300)

    raise RuntimeError("Could not detect reCAPTCHA sitekey within timeout")


def inject_recaptcha_token(page: Page, token: str) -> None:
    page.evaluate(
        """
        (recaptchaToken) => {
          const targets = document.querySelectorAll(
            'textarea[name="g-recaptcha-response"], textarea#g-recaptcha-response'
          );

          targets.forEach((el) => {
            el.value = recaptchaToken;
            el.innerHTML = recaptchaToken;
            el.dispatchEvent(new Event("input", { bubbles: true }));
            el.dispatchEvent(new Event("change", { bubbles: true }));
          });

          const maybeCfg = window.___grecaptcha_cfg;
          if (!maybeCfg || !maybeCfg.clients) {
            return;
          }

          for (const client of Object.values(maybeCfg.clients)) {
            if (!client || typeof client !== "object") {
              continue;
            }
            for (const value of Object.values(client)) {
              if (!value || typeof value !== "object") {
                continue;
              }
              if (typeof value.callback === "function") {
                value.callback(recaptchaToken);
                return;
              }
              if (value.callback && typeof value.callback.callback === "function") {
                value.callback.callback(recaptchaToken);
                return;
              }
            }
          }
        }
        """,
        token,
    )


def maybe_click_cookie_accept(page: Page) -> None:
    accept_all = page.get_by_role("button", name="Accept All")
    if accept_all.count() > 0:
        accept_all.first.click()


def collect_form_state(page: Page) -> dict:
    return page.evaluate(
        """
        () => {
          const email = document.querySelector("input[name='email']");
          const realWebsite = document.querySelector("input[name='realWebsite']");
          const phishingWebsite = document.querySelector("input[name='phishingWebsite']");
          const report = document.querySelector("textarea[placeholder='Report']");
          const upload = document.querySelector("input[type='file']");
          const recaptchaTextarea = document.querySelector("textarea[name='g-recaptcha-response']");
          const recaptchaIframes = Array.from(document.querySelectorAll("iframe[src*='recaptcha']"));

          return {
            email_value: email ? email.value : "",
            real_website_value: realWebsite ? realWebsite.value : "",
            phishing_website_value: phishingWebsite ? phishingWebsite.value : "",
            report_length: report ? report.value.length : 0,
            file_name: upload && upload.files && upload.files.length > 0 ? upload.files[0].name : "",
            recaptcha_textarea_present: !!recaptchaTextarea,
            recaptcha_textarea_length: recaptchaTextarea ? recaptchaTextarea.value.length : 0,
            recaptcha_iframe_count: recaptchaIframes.length,
          };
        }
        """
    )


def fill_report_form(page: Page, data: RecorderInput) -> None:
    page.locator("input[name='email']").fill(data.email)
    page.locator("input[name='realWebsite']").fill(data.real_website)
    page.locator("input[name='phishingWebsite']").fill(data.phishing_website)
    page.get_by_placeholder("Report").fill(data.report_text)
    if data.proof_image:
        file_input = page.locator("input[type='file']").first
        file_input.set_input_files(data.proof_image)


def ensure_recaptcha_mounted(page: Page, timeout_seconds: int = 25) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if page.locator("iframe[src*='recaptcha']").count() > 0:
            return
        page.wait_for_timeout(300)


def ensure_form_values(page: Page, data: RecorderInput) -> dict:
    state = collect_form_state(page)
    if (
        state.get("email_value") == data.email
        and state.get("real_website_value") == data.real_website
        and state.get("phishing_website_value") == data.phishing_website
        and int(state.get("report_length", 0)) > 0
    ):
        return state

    fill_report_form(page, data)
    page.wait_for_timeout(300)
    return collect_form_state(page)


def inspect_submit_button(page: Page) -> dict:
    button = page.get_by_role("button", name="Submit").first
    info = {
        "present": False,
        "visible": False,
        "enabled": False,
        "text": "",
    }
    if button.count() == 0:
        return info

    info["present"] = True
    info["visible"] = button.is_visible()
    info["enabled"] = button.is_enabled()
    info["text"] = (button.text_content() or "").strip()
    return info


def can_submit_with_captcha_guard(
    *,
    submit_requested: bool,
    submit_button: dict,
    form_state_after_captcha: dict,
    captcha_solved: bool,
    min_token_length: int,
) -> tuple[bool, str]:
    if not submit_requested:
        return False, "submit flag not set"

    if not submit_button.get("present", False):
        return False, "submit button not found"
    if not submit_button.get("visible", False):
        return False, "submit button not visible"
    if not submit_button.get("enabled", False):
        return False, "submit button not enabled"

    recaptcha_present = bool(form_state_after_captcha.get("recaptcha_textarea_present"))
    recaptcha_len = int(form_state_after_captcha.get("recaptcha_textarea_length", 0))
    if recaptcha_present:
        if not captcha_solved:
            return False, "captcha not solved"
        if recaptcha_len < min_token_length:
            return False, f"captcha token length too short: {recaptcha_len} < {min_token_length}"

    return True, "allowed"


def ensure_form_ready(page: Page, timeout_ms: int = 30000) -> None:
    try:
        page.wait_for_selector("input[name='email'], input[placeholder='Your Email']", timeout=timeout_ms)
        return
    except PlaywrightTimeoutError as exc:
        title = page.title()
        body_preview = ""
        try:
            body_preview = page.inner_text("body")[:500]
        except Exception:
            body_preview = ""

        if "Just a moment" in title or SECURITY_VERIFY_TEXT in body_preview:
            raise RuntimeError(
                "Detected security verification interstitial (Cloudflare). "
                "Run without --headless and manually pass the challenge first."
            ) from exc
        raise


def run_recording(
    *,
    page_url: str,
    data: RecorderInput,
    two_captcha_api_key: str,
    submit_form: bool,
    skip_captcha: bool,
    headless: bool,
    min_captcha_token_length: int,
    output_dir: Path,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_tag = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = output_dir / f"namesilo-{run_tag}"
    run_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = run_dir / "after-fill.png"
    captcha_screenshot_path = run_dir / "after-captcha.png"
    form_screenshot_path = run_dir / "form-snapshot.png"
    trace_path = run_dir / "trace.zip"
    result_path = run_dir / "result.json"

    with sync_playwright() as playwright:
        result = _run_with_browser(
            playwright=playwright,
            page_url=page_url,
            data=data,
            two_captcha_api_key=two_captcha_api_key,
            submit_form=submit_form,
            skip_captcha=skip_captcha,
            headless=headless,
            min_captcha_token_length=min_captcha_token_length,
            screenshot_path=screenshot_path,
            captcha_screenshot_path=captcha_screenshot_path,
            form_screenshot_path=form_screenshot_path,
            trace_path=trace_path,
        )
        result["artifacts"] = {
            "run_dir": str(run_dir),
            "screenshot": str(screenshot_path),
            "captcha_screenshot": str(captcha_screenshot_path),
            "form_screenshot": str(form_screenshot_path),
            "trace": str(trace_path),
        }
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result


def _run_with_browser(
    *,
    playwright: Playwright,
    page_url: str,
    data: RecorderInput,
    two_captcha_api_key: str,
    submit_form: bool,
    skip_captcha: bool,
    headless: bool,
    min_captcha_token_length: int,
    screenshot_path: Path,
    captcha_screenshot_path: Path,
    form_screenshot_path: Path,
    trace_path: Path,
) -> dict:
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context()
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()

    try:
        page.goto(page_url, wait_until="domcontentloaded")
        ensure_form_ready(page)
        maybe_click_cookie_accept(page)
        ensure_recaptcha_mounted(page)
        fill_report_form(page, data)
        form_state_after_fill = ensure_form_values(page, data)

        site_key = detect_recaptcha_site_key(page)
        solved = False
        captcha_token = ""

        if not skip_captcha:
            if not two_captcha_api_key:
                raise RuntimeError("2Captcha key is required when --skip-captcha is not set")
            solver = TwoCaptchaClient(api_key=two_captcha_api_key)
            captcha_token = solver.solve_recaptcha_v2(page_url=page_url, site_key=site_key)
            inject_recaptcha_token(page, captcha_token)
            page.wait_for_timeout(800)
            solved = True

        form_state_after_captcha = ensure_form_values(page, data)
        page.screenshot(path=str(screenshot_path), full_page=True)
        form_locator = page.locator("form", has=page.locator("input[name='email']")).first
        if form_locator.count() > 0:
            form_locator.screenshot(path=str(form_screenshot_path))
        if page.locator("iframe[src*='recaptcha']").count() > 0:
            page.locator("iframe[src*='recaptcha']").first.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
        page.screenshot(path=str(captcha_screenshot_path), full_page=False)
        submit_button = inspect_submit_button(page)
        submit_allowed, submit_guard_reason = can_submit_with_captcha_guard(
            submit_requested=submit_form,
            submit_button=submit_button,
            form_state_after_captcha=form_state_after_captcha,
            captcha_solved=solved,
            min_token_length=min_captcha_token_length,
        )

        submitted = False
        if submit_allowed:
            page.get_by_role("button", name="Submit").click()
            page.wait_for_timeout(3000)
            submitted = True

        return {
            "ok": True,
            "submitted": submitted,
            "submit_requested": submit_form,
            "submit_allowed": submit_allowed,
            "submit_guard_reason": submit_guard_reason,
            "captcha_solved": solved,
            "page_url": page.url,
            "site_key": site_key,
            "input": asdict(data),
            "captcha_token_length": len(captcha_token),
            "form_state_after_fill": form_state_after_fill,
            "form_state_after_captcha": form_state_after_captcha,
            "submit_button": submit_button,
        }
    finally:
        context.tracing.stop(path=str(trace_path))
        context.close()
        browser.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record and replay NameSilo phishing report automation with Playwright.",
    )
    parser.add_argument("--page-url", default=DEFAULT_PAGE_URL, help="Target page URL.")
    parser.add_argument("--email", required=True, help="Reporter email.")
    parser.add_argument("--real-website", required=True, help="Legitimate website URL.")
    parser.add_argument("--phishing-website", required=True, help="Phishing website URL.")
    parser.add_argument("--report-text", required=True, help="Report detail text.")
    parser.add_argument("--proof-image", default="", help="Optional proof image path for file upload.")
    parser.add_argument(
        "--two-captcha-key",
        default=_first_non_empty(
            [
                os.getenv("TWO_CAPTCHA_API_KEY"),
                os.getenv("CAPTCHA_API_KEY"),
            ]
        ),
        help="2Captcha key. Defaults to env TWO_CAPTCHA_API_KEY/CAPTCHA_API_KEY.",
    )
    parser.add_argument("--submit", action="store_true", help="Submit form after filling fields.")
    parser.add_argument("--skip-captcha", action="store_true", help="Do not call 2Captcha.")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode.")
    parser.add_argument(
        "--min-captcha-token-length",
        type=int,
        default=100,
        help="Submit guard threshold for g-recaptcha-response token length.",
    )
    parser.add_argument("--output-dir", default="storage/playwright-recordings", help="Artifacts output directory.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    proof_image = args.proof_image.strip()
    if proof_image:
        image_path = Path(proof_image)
        if not image_path.exists():
            raise FileNotFoundError(f"Proof image not found: {proof_image}")
        proof_image = str(image_path.resolve())

    payload = RecorderInput(
        email=args.email.strip(),
        real_website=args.real_website.strip(),
        phishing_website=args.phishing_website.strip(),
        report_text=args.report_text.strip(),
        proof_image=proof_image,
    )

    result = run_recording(
        page_url=args.page_url.strip(),
        data=payload,
        two_captcha_api_key=args.two_captcha_key.strip(),
        submit_form=bool(args.submit),
        skip_captcha=bool(args.skip_captcha),
        headless=bool(args.headless),
        min_captcha_token_length=int(args.min_captcha_token_length),
        output_dir=Path(args.output_dir).resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
