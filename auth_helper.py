import asyncio
import time
import os
from playwright.async_api import async_playwright
from playwright_stealth.stealth import Stealth

class AuthSession:
    def __init__(self, user_id):
        self.user_id = user_id
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.step = "init"  # init, email, password, otp, done, captcha
        self.last_activity = time.time()
        self.error_msg = None

    async def take_screenshot(self, name_prefix="auth_step"):
        if not os.path.exists("downloads/screenshots"):
            os.makedirs("downloads/screenshots", exist_ok=True)
        path = f"downloads/screenshots/{self.user_id}_{name_prefix}_{int(time.time())}.png"
        try:
            if self.page:
                await self.page.screenshot(path=path)
                return path
        except Exception as e:
            print(f"Screenshot failed: {e}")
        return None

    async def start(self):
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            self.context = await self.browser.new_context()
            self.page = await self.context.new_page()

            # Apply stealth
            stealth = Stealth()
            await stealth.apply_stealth_async(self.page)

            await self.page.goto("https://accounts.google.com/ServiceLogin?service=youtube", timeout=60000)
            self.step = "email"
            return True, "Launched browser. Please enter your Email."
        except Exception as e:
            return False, f"Failed to start browser: {str(e)}"

    async def enter_email(self, email):
        try:
            await self.page.fill('input[type="email"]', email)
            await self.page.click('#identifierNext')

            # Wait for either password input, error, or captcha
            try:
                # Increased timeout to 60s for Render
                # Also watching for captcha inputs
                await self.page.wait_for_selector(
                    'input[type="password"], div[aria-live="assertive"], div[jsname="B34EJ"], input[name="ca"], input[id="ca"], #captcha-box',
                    timeout=60000
                )

                # Check for CAPTCHA
                if await self.page.locator('input[name="ca"]').count() > 0 or await self.page.locator('input[id="ca"]').count() > 0 or await self.page.locator('#captcha-box').count() > 0:
                    self.step = "captcha"
                    screenshot = await self.take_screenshot("captcha_detected")
                    return True, "CAPTCHA detected. Please enter the characters you see in the image.", "captcha", screenshot

                # Check for "Type the text you hear or see" text as fallback
                content = await self.page.content()
                if "Type the text you hear or see" in content:
                    self.step = "captcha"
                    screenshot = await self.take_screenshot("captcha_text_detected")
                    return True, "CAPTCHA detected. Please enter the characters you see in the image.", "captcha", screenshot

                # Check for error message
                if "Couldn't find your Google Account" in content or "Enter a valid email" in content:
                    screenshot = await self.take_screenshot("email_error")
                    return False, "Error: Couldn't find your Google Account or invalid email.", "error", screenshot

                # Verify password field is actually visible before proceeding
                try:
                    await self.page.wait_for_selector('input[type="password"]', state='visible', timeout=10000)
                except:
                    if "Enter a valid email" in await self.page.content():
                        screenshot = await self.take_screenshot("email_invalid")
                        return False, "Error: Invalid email.", "error", screenshot

                    # Fallback check
                    if await self.page.locator('input[type="password"]').count() == 0:
                         screenshot = await self.take_screenshot("email_unknown_error")
                         return False, "Email accepted, but password field not found/visible.", "error", screenshot

                self.step = "password"
                return True, "Email accepted. Please enter password.", "password", None
            except Exception as e:
                screenshot = await self.take_screenshot("email_timeout")
                return False, f"Timeout or error waiting for password field: {str(e)}", "error", screenshot

        except Exception as e:
            return False, f"Error entering email: {str(e)}", "error", None

    async def enter_captcha(self, code):
        try:
            # Try to find captcha input
            if await self.page.locator('input[name="ca"]').count() > 0:
                 await self.page.fill('input[name="ca"]', code)
            elif await self.page.locator('input[id="ca"]').count() > 0:
                 await self.page.fill('input[id="ca"]', code)
            else:
                 # Try blind typing
                 await self.page.keyboard.type(code)

            await self.page.click('#identifierNext') # Usually same button

            # Now wait for next step (likely password, or error, or another captcha)
            try:
                await self.page.wait_for_selector(
                    'input[type="password"], div[aria-live="assertive"], input[name="ca"]',
                    timeout=60000
                )

                # Check for captcha again (wrong code)
                if await self.page.locator('input[name="ca"]').count() > 0:
                    self.step = "captcha"
                    screenshot = await self.take_screenshot("captcha_retry")
                    return False, "Wrong CAPTCHA. Please try again.", "captcha", screenshot

                # Check for password
                if await self.page.locator('input[type="password"]').count() > 0:
                     self.step = "password"
                     return True, "CAPTCHA accepted. Please enter password.", "password", None

                # Check for error
                content = await self.page.content()
                if "Enter a valid email" in content:
                     screenshot = await self.take_screenshot("captcha_email_error")
                     return False, "Error: Invalid email after CAPTCHA.", "error", screenshot

                screenshot = await self.take_screenshot("captcha_unknown")
                return False, "Unknown state after CAPTCHA.", "error", screenshot

            except Exception as e:
                 screenshot = await self.take_screenshot("captcha_timeout")
                 return False, f"Timeout after CAPTCHA: {str(e)}", "error", screenshot

        except Exception as e:
             return False, f"Error entering CAPTCHA: {str(e)}", "error", None

    async def enter_password(self, password):
        try:
            await self.page.fill('input[type="password"]:visible', password)
            await self.page.click('#passwordNext')

            # Wait for navigation or 2FA prompt
            try:
                # Wait for multiple possible states: logged in, error, or 2FA challenge
                # We use a longer timeout (60s)
                await self.page.wait_for_load_state('networkidle', timeout=60000)

                # Check for specific indicators
                # 1. Logged in (URL check)
                if "myaccount.google.com" in self.page.url or "youtube.com" in self.page.url:
                     self.step = "done"
                     return True, "Logged in!", "done", None

                # 2. Wrong password
                content = await self.page.content()
                if "Wrong password" in content or "Enter a password" in content:
                     screenshot = await self.take_screenshot("wrong_password")
                     return False, "Error: Wrong password.", "password", screenshot

                # 3. 2FA / Challenge
                if "challenge" in self.page.url or await self.page.locator('input[type="tel"]').count() > 0 or "metadata" in self.page.url:
                     self.step = "otp"
                     screenshot = await self.take_screenshot("2fa_challenge")
                     return True, "2FA/Verification detected. Please enter the code if you have one.", "otp", screenshot

                # 4. CAPTCHA or "Verify it's you"
                if "Verify it's you" in content or "captcha" in content.lower():
                     self.step = "otp" # Treat as OTP step to allow user to input or just see screenshot
                     screenshot = await self.take_screenshot("verify_its_you")
                     return True, "Google is asking to verify it's you. Check the screenshot.", "otp", screenshot

                # Fallback: take a screenshot and assume OTP/Waiting
                self.step = "otp"
                screenshot = await self.take_screenshot("unknown_state")
                return True, "Verification needed (Unknown State). Check screenshot.", "otp", screenshot

            except Exception as e:
                 screenshot = await self.take_screenshot("password_wait_error")
                 return False, f"Error waiting after password: {str(e)}", "error", screenshot

        except Exception as e:
            return False, f"Error entering password: {str(e)}", "error", None

    async def enter_otp(self, otp):
        try:
            # Try to identify the input field for OTP
            filled = False

            # Using wait_for_function-like logic by checking multiple selectors
            selectors = ['input[type="tel"]', 'input[name="pin"]', 'input[id="idvPin"]', 'input[name="code"]']

            for selector in selectors:
                if await self.page.locator(selector).count() > 0:
                    try:
                         await self.page.fill(selector, otp)
                         filled = True
                         break
                    except:
                        pass

            if not filled:
                 # Try just typing it globally if focused
                 await self.page.keyboard.type(otp)

            await self.page.keyboard.press("Enter")

            # Wait
            await self.page.wait_for_load_state('networkidle', timeout=60000)

            # Check success
            if "myaccount.google.com" in self.page.url or "youtube.com" in self.page.url:
                 self.step = "done"
                 return True, "Logged in!", None

            # If still on same page, maybe error
            if "challenge" in self.page.url:
                 screenshot = await self.take_screenshot("otp_failed")
                 return False, "Still on verification page. Code might be wrong or additional step needed.", screenshot

            self.step = "done"
            return True, "Logged in (assumed)!", None

        except Exception as e:
            return False, str(e), None

    async def get_cookies_netscape(self):
        try:
            cookies = await self.context.cookies()
            netscape_lines = ["# Netscape HTTP Cookie File"]
            for cookie in cookies:
                domain = cookie['domain']
                flag = "TRUE" if domain.startswith('.') else "FALSE"
                path = cookie['path']
                secure = "TRUE" if cookie['secure'] else "FALSE"
                expiration = int(cookie['expires'])
                name = cookie['name']
                value = cookie['value']
                netscape_lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expiration}\t{name}\t{value}")
            return "\n".join(netscape_lines)
        except Exception as e:
            return f"# Error getting cookies: {str(e)}"

    async def close(self):
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except:
            pass
