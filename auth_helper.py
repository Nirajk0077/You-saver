import asyncio
import time
import os
from playwright.async_api import async_playwright
from playwright_stealth.stealth import Stealth
import os

class AuthSession:
    def __init__(self, user_id):
        self.user_id = user_id
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.step = "init"  # init, email, password, otp, done
        self.last_activity = time.time()
        self.error_msg = None

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

            await self.page.goto("https://accounts.google.com/ServiceLogin?service=youtube")
            self.step = "email"
            return True, "Launched browser. Please enter your Email."
        except Exception as e:
            return False, f"Failed to start browser: {str(e)}"

    async def enter_email(self, email):
        try:
            # Check if email field is present, if not, reload
            try:
                await self.page.wait_for_selector('input[type="email"]', state='visible', timeout=10000)
            except:
                try:
                    await self.page.reload()
                    await self.page.wait_for_selector('input[type="email"]', state='visible', timeout=30000)
                except Exception as e:
                    return False, f"Error loading login page: {str(e)}"

            await self.page.fill('input[type="email"]', email)

            # Attempt to click Next button using multiple selectors
            next_clicked = False
            try:
                # Try explicit ID first
                if await self.page.locator('#identifierNext').is_visible():
                    await self.page.click('#identifierNext')
                    next_clicked = True
                # Try finding button by text "Next"
                elif await self.page.get_by_role("button", name="Next").is_visible():
                    await self.page.get_by_role("button", name="Next").click()
                    next_clicked = True
            except:
                pass

            if not next_clicked:
                # Fallback to Enter key
                await self.page.keyboard.press("Enter")

            # Polling loop for Password Field or Errors
            # Increased total wait time to 90s for very slow renders
            start_time = time.time()
            while time.time() - start_time < 90:
                # 1. Check for Password Field
                if await self.page.locator('input[type="password"]').is_visible():
                    # Wait a tiny bit for animation
                    await asyncio.sleep(1)
                    self.step = "password"
                    return True, "Email accepted. Please enter password."

                # 2. Check for Common Error Messages (Text Content)
                content = await self.page.content()
                if "Couldn't find your Google Account" in content:
                    return False, "Error: Couldn't find your Google Account."
                if "Enter a valid email" in content:
                    return False, "Error: Invalid email."
                if "CAPTCHA" in content or "Verify it's you" in content:
                    return False, "Error: CAPTCHA or Verification requested. Cannot proceed automatically."

                # 3. Aggressive Retry Logic
                # If email input is still visible and enabled, we might be stuck.
                # Every 10 seconds, try to kick it.
                if await self.page.locator('input[type="email"]').is_visible():
                    elapsed = time.time() - start_time
                    if elapsed > 10 and int(elapsed) % 10 == 0:
                        # Try pressing Enter again
                        try:
                            await self.page.keyboard.press("Enter")
                            # Or try clicking the button again if found
                            if await self.page.locator('#identifierNext').is_visible():
                                await self.page.click('#identifierNext', timeout=1000)
                        except:
                            pass

                await asyncio.sleep(1)

            return False, "Timeout waiting for password field."

        except Exception as e:
            return False, f"Error entering email: {str(e)}"

    async def enter_password(self, password):
        try:
            await self.page.fill('input[type="password"]:visible', password)
            await self.page.keyboard.press("Enter")
            # await self.page.click('#passwordNext')

            # Wait for navigation or 2FA prompt
            await self.page.wait_for_load_state('networkidle')
            await asyncio.sleep(3) # Extra wait for redirects

            # Check if we are logged in
            if "myaccount.google.com" in self.page.url or "youtube.com" in self.page.url:
                 self.step = "done"
                 return True, "Logged in!", "done"

            # Check for error (wrong password)
            content = await self.page.content()
            if "Wrong password" in content or "Enter a password" in content:
                 return False, "Error: Wrong password.", "password"

            # Check for 2FA
            # Common 2FA indicators
            if "challenge" in self.page.url or await self.page.locator('input[type="tel"]').count() > 0 or await self.page.locator('input[name="pin"]').count() > 0:
                 self.step = "otp"
                 return True, "2FA detected. Please enter the code.", "otp"

            # Check if it's asking for recovery email or something else
            if "metadata" in self.page.url:
                 # Just treat as OTP or waiting step
                 self.step = "otp"
                 return True, "Verification needed (Metadata). Please enter code if asked, or just wait.", "otp"

            # If we are here, we might be logged in or in a weird state.
            # Let's assume 2FA if not obviously logged in
            self.step = "otp"
            return True, "Verification needed. Please enter code if you have one.", "otp"

        except Exception as e:
            return False, f"Error entering password: {str(e)}", "error"

    async def enter_otp(self, otp):
        try:
            # Try to identify the input field for OTP
            # It varies: idvPin, specific name, type tel

            filled = False
            if await self.page.locator('input[type="tel"]').count() > 0:
                 await self.page.fill('input[type="tel"]', otp)
                 filled = True
            elif await self.page.locator('input[name="pin"]').count() > 0:
                 await self.page.fill('input[name="pin"]', otp)
                 filled = True
            elif await self.page.locator('input[id="idvPin"]').count() > 0:
                 await self.page.fill('input[id="idvPin"]', otp)
                 filled = True
            elif await self.page.locator('input[name="code"]').count() > 0:
                 await self.page.fill('input[name="code"]', otp)
                 filled = True

            if not filled:
                 # Try just typing it?
                 await self.page.keyboard.type(otp)

            await self.page.keyboard.press("Enter")

            # Wait
            await self.page.wait_for_load_state('networkidle')
            await asyncio.sleep(5)

            if "myaccount.google.com" in self.page.url or "youtube.com" in self.page.url:
                 self.step = "done"
                 return True, "Logged in!"

            # If still on same page, maybe error
            if "challenge" in self.page.url:
                 return False, "Still on verification page. Code might be wrong or additional step needed."

            self.step = "done"
            return True, "Logged in (assumed)!"

        except Exception as e:
            return False, str(e)

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
