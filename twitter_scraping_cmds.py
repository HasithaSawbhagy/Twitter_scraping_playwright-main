# pip install playwright pandas
# playwright install

from playwright.sync_api import sync_playwright, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError
import json
import time
import os
import pandas as pd
import shutil # For rmtree

# --- CONFIGURATION ---
USERNAMES_FILE = "usernames.txt"
PROBLEMATIC_USERNAMES_FILE = "problematic_usernames.txt"
NUM_POSTS_TO_RETRIEVE = 200

# Local retries within scrape_twitter_info for a single user operation
MAX_LOCAL_OPERATION_RETRIES = 3  # Updated from S2
LOCAL_OPERATION_RETRY_BASE_DELAY_SECONDS = 180  # Updated from S2 (3 minutes for 1st retry)
LOCAL_OPERATION_RETRY_INCREMENT_SECONDS = 60   # Updated from S2 (Additional 1 min for subsequent retries)

# Global retries in main if a user fails repeatedly due to rate limits
MAX_GLOBAL_USER_RETRIES = 1 # Updated from S2 (How many times to restart browser & re-login for one user)
GLOBAL_RETRY_DELAY_SECONDS = 300 # Updated from S2 (5 minutes delay for global retry)

PRIMARY_COLUMN_WAIT_TIMEOUT = 15000 # Max time to wait for primary column selector specifically

# --- X.COM LOGIN CREDENTIALS (IMPORTANT: Replace with your actual credentials) ---
X_USERNAME = "Replace with your X username/email/phone"  # Replace with your X username/email/phone
X_PASSWORD = "Replace with your X password"  # Replace with your X password
# --- END CONFIGURATION ---

class RateLimitException(Exception):
    """Custom exception for rate limit errors."""
    pass

class AccountUnavailableException(Exception):
    """Custom exception for account unavailable/suspended/non-existent issues."""
    pass

def login_to_x(page: Page):
    if not X_USERNAME or X_USERNAME == "YOUR_X_USERNAME_HERE" or \
       not X_PASSWORD or X_PASSWORD == "YOUR_X_PASSWORD_HERE":
        print("X Username or Password not configured. Skipping login.")
        return False
    print("Attempting to log in to X.com...")
    try:
        page.goto("https://x.com/login", timeout=60000, wait_until="domcontentloaded")
        time.sleep(3) # Increased sleep after goto
        username_input_selector = "//input[@name='text']"
        page.wait_for_selector(username_input_selector, timeout=30000)
        page.fill(username_input_selector, X_USERNAME)
        next_button_selectors = ["//span[contains(text(),'Next')]/ancestor::button[1]", "//div[@role='button'][.//span[contains(text(),'Next')]]"]
        next_button_clicked = False
        for selector in next_button_selectors:
            try: page.click(selector, timeout=5000); next_button_clicked = True; print("Username entered, clicked Next."); break
            except PlaywrightTimeoutError: continue
        if not next_button_clicked: print("Could not find 'Next' button after username."); return False
        time.sleep(3) # Increased sleep after next
        password_input_selector = "//input[@name='password']"
        try:
            page.wait_for_selector(password_input_selector, timeout=15000)
            page.fill(password_input_selector, X_PASSWORD)
        except PlaywrightTimeoutError:
            alt_verification_selector = "//input[@data-testid='ocfEnterTextTextInput']"
            try:
                if page.is_visible(alt_verification_selector, timeout=3000):
                    print("X asking for additional verification.")
                    page_text_content_lower = page.text_content("body", timeout=2000).lower()
                    if "username" in page_text_content_lower or "phone" in page_text_content_lower:
                        print(f"Attempting to fill verification with: {X_USERNAME}")
                        page.fill(alt_verification_selector, X_USERNAME); page.keyboard.press("Enter"); time.sleep(2.5)
                        page.wait_for_selector(password_input_selector, timeout=10000)
                        page.fill(password_input_selector, X_PASSWORD)
                    else: print("Cannot auto-handle this verification."); return False
            except PlaywrightTimeoutError: print("Password field/alt verification not found."); return False
            except Exception as e_verif: print(f"Error in alt verification: {e_verif}"); return False
        login_button_selectors = ["//span[contains(text(),'Log in')]/ancestor::button[1]", "//div[@data-testid='LoginForm_Login_Button']"]
        login_button_clicked = False
        for selector in login_button_selectors:
            try: page.click(selector, timeout=10000); login_button_clicked = True; print("Password entered, clicked Log in."); break
            except PlaywrightTimeoutError: continue
        if not login_button_clicked: print("Could not find 'Log in' button."); return False
        time.sleep(6) # Increased sleep after login click
        if "home" in page.url.lower() or page.is_visible("[data-testid='AppTabBar_Home_Link']", timeout=5000): print("Login successful."); return True
        elif "login" in page.url.lower() or page.query_selector("//span[contains(text(),'Something went wrong')]") or page.query_selector("//*[contains(text(),'incorrect')]"): print("Login failed."); return False
        else: print("Login status uncertain (may require manual check or consider it a soft fail)."); return True # Or False depending on desired strictness
    except PlaywrightTimeoutError as pte: print(f"Timeout during login: {pte}"); return False
    except Exception as e: print(f"Error during login: {e}"); return False

def check_page_for_account_issues(page: Page):
    suspended_texts = ["Account suspended", "This account is suspended"]
    non_existent_texts = ["This account doesn’t exist", "Hmm...this page doesn’t exist.", "Profile not found", "These posts aren't available", "This profile is not available"]
    page.wait_for_timeout(1500) # Allow content to settle
    page_content_lower = ""
    try:
        body_element = page.locator("body")
        if body_element.count() > 0: # Ensure body exists
            body_text = body_element.inner_text(timeout=5000) # Wait up to 5s for text
            page_content_lower = body_text.lower()
        else:
            print("Note: Body element not found for status check. Using full page content.")
            page_content_lower = page.content().lower() # Fallback
    except Exception as e:
        print(f"Note: Could not get body text for status check: {e}. Will use full page content.")
        try:
            page_content_lower = page.content().lower()
        except Exception as e_content:
            print(f"Critical: Could not get any page content for status check: {e_content}")
            return # Cannot determine, so don't raise an exception based on this

    for text in suspended_texts:
        if text.lower() in page_content_lower:
            raise AccountUnavailableException(f"Account Issue (Text Match): '{text}'")
    for text in non_existent_texts:
        if text.lower() in page_content_lower:
            raise AccountUnavailableException(f"Account Issue (Text Match): '{text}'")

    current_url = page.url
    if "/i/unavailable" in current_url or "/i/suspend" in current_url or "/notifications/restricted" in current_url:
        raise AccountUnavailableException(f"Account Issue (URL Pattern): {current_url}")

def scrape_twitter_info(context: BrowserContext, url: str, scrape_tweets_mode: bool, timeout_seconds=120):
    _xhr_calls = []
    page: Page = None
    local_retries = 0

    while local_retries <= MAX_LOCAL_OPERATION_RETRIES:
        current_attempt_tweets = []
        current_attempt_found_ids = set()
        attempt_processed_xhr_urls = set()
        tweet_xhr_processed_count_this_attempt = 0
        profile_xhr_processed_count_this_attempt = 0

        try:
            if page and not page.is_closed():
                try: page.close()
                except Exception as e_pg_close_retry: print(f"Note: Error closing previous page on retry: {e_pg_close_retry}")

            page = context.new_page()
            _xhr_calls = []
            page.on("response", lambda resp: _xhr_calls.append(resp) if (("UserTweets" in resp.url or "UserByScreenName" in resp.url) and resp.request.resource_type == "xhr") else None)

            overall_start_time = time.time()

            print(f"Navigating to profile: {url} (Local Attempt {local_retries + 1})")
            page.goto(url, timeout=min(timeout_seconds * 1000, 60000), wait_until="domcontentloaded")

            try:
                check_page_for_account_issues(page) # Initial check after load
            except AccountUnavailableException:
                if page and not page.is_closed():
                    try: page.close()
                    except Exception: pass
                raise

            if time.time() - overall_start_time >= timeout_seconds:
                print(f"Timeout after page load for {url}")
                if page and not page.is_closed():
                    try: page.close()
                    except Exception: pass
                return None

            primary_column_selector = "[data-testid='primaryColumn']"
            wait_for_primary_column_timeout_ms = 0 # Initialize
            try:
                elapsed_time_current_op = time.time() - overall_start_time
                remaining_time_for_op_ms = max(0, (timeout_seconds - elapsed_time_current_op) * 1000)
                wait_for_primary_column_timeout_ms = min(PRIMARY_COLUMN_WAIT_TIMEOUT, remaining_time_for_op_ms - 1000) # buffer

                if wait_for_primary_column_timeout_ms <= 1000: # If less than 1s, likely not enough time
                    print(f"Not enough time remaining to wait for primary column for {url}. Remaining for selector: {wait_for_primary_column_timeout_ms}ms.")
                    raise PlaywrightTimeoutError("Insufficient time for primary column after load and checks.")

                page.wait_for_selector(primary_column_selector, timeout=wait_for_primary_column_timeout_ms)
            except PlaywrightTimeoutError as pte_selector:
                print(f"Primary column not found for {url} within {wait_for_primary_column_timeout_ms/1000:.1f}s (adaptive). Re-checking for account issues...")
                try:
                    check_page_for_account_issues(page) # Re-check diligently
                except AccountUnavailableException:
                    if page and not page.is_closed():
                        try: page.close()
                        except Exception: pass
                    raise
                print(f"Primary column not found for {url} but no explicit account issue messages. Assuming unavailable.")
                if page and not page.is_closed():
                    try: page.close()
                    except Exception: pass
                raise AccountUnavailableException(f"Primary column not found for {url} ({pte_selector}), and no explicit suspension/non-existent message detected. Assuming unavailable.")
            page.wait_for_timeout(2500) # Static wait after primary column appears

            if scrape_tweets_mode:
                xhr_url_substring = "/UserTweets"
                page.mouse.wheel(0, 800); time.sleep(3) # Initial scroll
                print(f"Starting tweet retrieval for {url}. Target: {NUM_POSTS_TO_RETRIEVE}.")
                no_new_xhr_scroll_count = 0; time_spent_on_user_tweets = 0; user_tweet_loop_start_time = time.time()

                while len(current_attempt_tweets) < NUM_POSTS_TO_RETRIEVE and time_spent_on_user_tweets < (timeout_seconds - (time.time() - overall_start_time) - 10) : # Ensure loop respects overall timeout
                    time_spent_on_user_tweets = time.time() - user_tweet_loop_start_time
                    current_xhr_calls_batch = [call for call in _xhr_calls if xhr_url_substring in call.url and call.url not in attempt_processed_xhr_urls]
                    if not current_xhr_calls_batch:
                        no_new_xhr_scroll_count += 1
                        if no_new_xhr_scroll_count > 6: # Original value from S1
                             print(f"No new XHRs after {no_new_xhr_scroll_count} scrolls for {url}. Found {len(current_attempt_tweets)}."); break
                        page.mouse.wheel(0, 10000); time.sleep(4.5); continue
                    else: no_new_xhr_scroll_count = 0

                    for xhr in current_xhr_calls_batch:
                        response_text = None; json_response = None
                        tweet_xhr_processed_count_this_attempt +=1
                        try:
                            if not xhr.ok:
                                if xhr.status == 429: raise RateLimitException(f"Status 429 on {xhr.url}")
                                err_text = "(Could not get text)";
                                try: err_text = xhr.text()
                                except Exception: pass
                                print(f"XHR not OK: {xhr.status} for {xhr.url}. Text: {err_text[:100]}."); attempt_processed_xhr_urls.add(xhr.url); continue
                            content_type = xhr.headers.get('content-type', '').lower(); response_text = xhr.text()
                            if 'application/json' not in content_type:
                                if response_text and ("rate limit" in response_text.lower() or "too many requests" in response_text.lower() or "temporarily locked" in response_text.lower()):
                                    raise RateLimitException(f"Rate limit text in non-JSON from {xhr.url}. Text: {response_text[:100]}")
                                print(f"XHR not JSON: {content_type} for {xhr.url}. Text: {response_text[:100]}."); attempt_processed_xhr_urls.add(xhr.url); continue
                            if not response_text: print(f"XHR empty for {xhr.url}."); attempt_processed_xhr_urls.add(xhr.url); continue
                            json_response = json.loads(response_text)
                            if "data" not in json_response: attempt_processed_xhr_urls.add(xhr.url); continue # Or errors key
                            user_data_tree = json_response.get("data", {}).get("user", {}).get("result", {})
                            timeline_instructions = []; tl_v1 = user_data_tree.get("timeline", {}).get("timeline", {}); tl_v2 = user_data_tree.get("timeline_v2", {}).get("timeline", {})
                            if tl_v1 and "instructions" in tl_v1: timeline_instructions = tl_v1.get("instructions", [])
                            elif tl_v2 and "instructions" in tl_v2: timeline_instructions = tl_v2.get("instructions", [])
                            for instruction in timeline_instructions:
                                if instruction.get("type") == "TimelineAddEntries":
                                    for entry in instruction.get("entries", []):
                                        content = entry.get("content", {}); item_content = content.get("itemContent", {})
                                        if content.get("entryType") == "TimelineTimelineItem" and item_content.get("itemType") == "TimelineTweet":
                                            tweet_res_cont = item_content.get("tweet_results", {}); tweet_res = tweet_res_cont.get("result", {})
                                            actual_data = None
                                            if tweet_res.get("__typename") == "TweetWithVisibilityResults": actual_data = tweet_res.get("tweet")
                                            elif tweet_res.get("__typename") == "Tweet": actual_data = tweet_res
                                            if actual_data and "rest_id" in actual_data:
                                                tweet_id = actual_data["rest_id"]
                                                if tweet_id not in current_attempt_found_ids:
                                                    current_attempt_tweets.append(actual_data); current_attempt_found_ids.add(tweet_id)
                                                    if len(current_attempt_tweets) % 20 == 0: print(f"Retrieved {len(current_attempt_tweets)} tweets for {url}...")
                                                    if len(current_attempt_tweets) >= NUM_POSTS_TO_RETRIEVE: break
                                    if len(current_attempt_tweets) >= NUM_POSTS_TO_RETRIEVE: break
                            if len(current_attempt_tweets) >= NUM_POSTS_TO_RETRIEVE: break
                            attempt_processed_xhr_urls.add(xhr.url)
                        except json.JSONDecodeError as e:
                            if response_text and ("rate limit" in response_text.lower() or "too many requests" in response_text.lower() or "temporarily locked" in response_text.lower()): raise RateLimitException(f"Rate limit (JSON decode text match) for {xhr.url}. Err: {e}. Text: {response_text[:100]}")
                            print(f"Non-RL JSONErr for {xhr.url}: {e}. Text: {response_text[:100]}."); attempt_processed_xhr_urls.add(xhr.url); continue
                        except RateLimitException: raise
                        except (KeyError, TypeError) as e_d: print(f"Data structure err {xhr.url}: {e_d}."); attempt_processed_xhr_urls.add(xhr.url); continue
                        except Exception as e_i: print(f"Unexpected err XHR {xhr.url}: {e_i}."); attempt_processed_xhr_urls.add(xhr.url); continue
                        if len(current_attempt_tweets) >= NUM_POSTS_TO_RETRIEVE: break
                    if len(current_attempt_tweets) >= NUM_POSTS_TO_RETRIEVE: break

                if tweet_xhr_processed_count_this_attempt == 0 and not current_attempt_tweets and no_new_xhr_scroll_count > 3: # S1 logic
                    if page and not page.is_closed():
                        try: page.close()
                        except Exception: pass
                    raise AccountUnavailableException(f"No UserTweets XHRs processed and no tweets found for {url} after {no_new_xhr_scroll_count} scrolls. Assuming account issue.")

                if not current_attempt_tweets: print(f"No tweets found for {url} in this attempt.")
                elif len(current_attempt_tweets) < NUM_POSTS_TO_RETRIEVE: print(f"Warn: Retrieved {len(current_attempt_tweets)}/{NUM_POSTS_TO_RETRIEVE} for {url}.")

                if page and not page.is_closed():
                    try: page.close()
                    except Exception as e_pg_close_tweet: print(f"Note: Error closing page after tweets: {e_pg_close_tweet}")
                return current_attempt_tweets[:NUM_POSTS_TO_RETRIEVE]

            else: # Profile Scraping
                xhr_url_substring = "/UserByScreenName"; user_profile_data = None; loop_start_time = time.time()
                # Ensure profile_xhr_wait_timeout respects overall operation timeout
                profile_xhr_wait_timeout = max(20, timeout_seconds - (time.time() - overall_start_time) - 10) # 10s buffer
                attempt_profile_processed_xhr_urls = set()
                profile_xhr_found_for_attempt = False
                wait_for_profile_xhr_start = time.time()

                while not profile_xhr_found_for_attempt and (time.time() - wait_for_profile_xhr_start) < profile_xhr_wait_timeout :
                    if any(xhr_url_substring in call.url for call in _xhr_calls):
                        profile_xhr_found_for_attempt = True; break
                    page.wait_for_timeout(500)

                if not profile_xhr_found_for_attempt:
                     if page and not page.is_closed():
                         try: page.close()
                         except Exception: pass
                     raise AccountUnavailableException(f"No UserByScreenName XHR detected for profile {url} within {profile_xhr_wait_timeout:.1f}s. Assuming account issue.")

                while user_profile_data is None and (time.time() - loop_start_time) < profile_xhr_wait_timeout and (time.time() - overall_start_time) < timeout_seconds:
                    profile_api_calls = [xhr for xhr in _xhr_calls if xhr_url_substring in xhr.url and xhr.url not in attempt_profile_processed_xhr_urls]
                    if not profile_api_calls and profile_xhr_processed_count_this_attempt > 0: # All processed calls checked
                        break

                    for call in profile_api_calls:
                        response_text = None; json_response = None
                        profile_xhr_processed_count_this_attempt +=1
                        try:
                            if not call.ok:
                                if call.status == 429: raise RateLimitException(f"Status 429 on profile XHR {call.url}")
                                err_text = "(Could not get text)";
                                try: err_text = call.text()
                                except Exception: pass
                                print(f"Profile XHR not OK: {call.status} for {call.url}. Text: {err_text[:100]}."); attempt_profile_processed_xhr_urls.add(call.url); continue
                            content_type = call.headers.get('content-type', '').lower(); response_text = call.text()
                            if 'application/json' not in content_type:
                                if response_text and ("rate limit" in response_text.lower() or "too many requests" in response_text.lower()): raise RateLimitException(f"Rate limit text in non-JSON profile XHR {call.url}. Text: {response_text[:100]}")
                                print(f"Profile XHR not JSON: {content_type} for {call.url}. Text: {response_text[:100]}."); attempt_profile_processed_xhr_urls.add(call.url); continue
                            if not response_text: print(f"Profile XHR empty for {call.url}."); attempt_profile_processed_xhr_urls.add(call.url); continue
                            json_response = json.loads(response_text)
                            potential_user_data = json_response.get('data', {}).get('user', {}).get('result', {})
                            if potential_user_data.get('rest_id') and 'errors' not in json_response and potential_user_data.get('legacy'):
                                user_profile_data = potential_user_data;
                                if page and not page.is_closed():
                                    try: page.close()
                                    except Exception as e_pg_close_prof_succ: print(f"Note: Error closing page after profile success: {e_pg_close_prof_succ}")
                                return user_profile_data
                            attempt_profile_processed_xhr_urls.add(call.url)
                        except json.JSONDecodeError as e_p_json:
                            if response_text and ("rate limit" in response_text.lower() or "too many requests" in response_text.lower()): raise RateLimitException(f"Rate limit (JSON decode text match) profile {call.url}. Err: {e_p_json}. Text: {response_text[:100]}")
                            print(f"Non-RL JSONErr profile {call.url}: {e_p_json}. Text: {response_text[:100]}."); attempt_profile_processed_xhr_urls.add(call.url)
                        except RateLimitException: raise
                        except (KeyError, TypeError) as e_p_key: print(f"Data structure err profile {call.url}: {e_p_key}."); attempt_profile_processed_xhr_urls.add(call.url)
                        except Exception as e_p_other: print(f"Unexpected err profile XHR {call.url}: {e_p_other}."); attempt_profile_processed_xhr_urls.add(call.url)
                    if user_profile_data is None: time.sleep(0.5)

                if not user_profile_data and profile_xhr_processed_count_this_attempt == 0: # S1 logic
                    if page and not page.is_closed():
                        try: page.close()
                        except Exception: pass
                    raise AccountUnavailableException(f"No UserByScreenName XHRs were successfully processed for profile {url}. Assuming account issue.")

                if user_profile_data:
                    if page and not page.is_closed():
                        try: page.close()
                        except Exception as e_pg_close_prof_succ2: print(f"Note: Error closing page after profile success 2: {e_pg_close_prof_succ2}")
                    return user_profile_data
                else: print(f"Could not find/process profile XHR for {url} in this attempt.");

            if page and not page.is_closed():
                try: page.close()
                except Exception as e_pg_close_final_op: print(f"Note: Error closing page at end of operation: {e_pg_close_final_op}")
            return None
        except AccountUnavailableException: # Catch and re-raise to be handled by main
            if page and not page.is_closed():
                try: page.close()
                except Exception: pass
            raise
        except RateLimitException as rle:
            print(f"RateLimitException (local attempt {local_retries + 1}) for {url}: {rle}")
            local_retries += 1
            if page and not page.is_closed():
                try: page.close()
                except Exception as e_pg_close_rle: print(f"Note: Error closing page on RLE: {e_pg_close_rle}")
            if local_retries <= MAX_LOCAL_OPERATION_RETRIES:
                # Updated delay calculation based on S2's constants
                delay = LOCAL_OPERATION_RETRY_BASE_DELAY_SECONDS
                if local_retries > 1 : # Apply increment for 2nd, 3rd... local retries
                    delay += (local_retries - 1) * LOCAL_OPERATION_RETRY_INCREMENT_SECONDS
                print(f"Pausing for {delay}s before local retry {local_retries}/{MAX_LOCAL_OPERATION_RETRIES} for {url}...")
                time.sleep(delay)
            else:
                print(f"Max local retries for Rate Limits ({MAX_LOCAL_OPERATION_RETRIES}) reached for {url}. Escalating to main.")
                raise # Re-raise to be caught by the main function's global retry logic
        except Exception as e_user_op:
            print(f"Unhandled error during local attempt {local_retries + 1} for {url}: {e_user_op}")
            local_retries += 1
            if page and not page.is_closed():
                try: page.close()
                except Exception as e_pg_close_unhandled: print(f"Note: Error closing page on unhandled ex: {e_pg_close_unhandled}")
            if local_retries <= MAX_LOCAL_OPERATION_RETRIES:
                # Generic delay for other errors before local retry
                print(f"Pausing for 30s due to unhandled error before local retry {local_retries}/{MAX_LOCAL_OPERATION_RETRIES} for {url}...")
                time.sleep(30)
            else:
                print(f"Max local retries for other errors ({MAX_LOCAL_OPERATION_RETRIES}) reached for {url}. Giving up on this operation for this user.")
                if page and not page.is_closed():
                    try: page.close()
                    except Exception: pass
                return None # Give up on this specific scrape_twitter_info call

    print(f"Failed to scrape {url} after {MAX_LOCAL_OPERATION_RETRIES + 1} local attempts.")
    if page and not page.is_closed():
        try: page.close()
        except Exception as e_pg_close_fallthrough: print(f"Note: Error closing page in final fallthrough: {e_pg_close_fallthrough}")
    return None

def analyze_and_save_tweets(json_filename, output_dir):
    def returnValueFromData(data_dict, key_path, default=None):
        temp = data_dict;
        for key_part in key_path.split('.'):
            if isinstance(temp, dict) and key_part in temp: temp = temp[key_part]
            elif isinstance(temp, list) and key_part.isdigit() and int(key_part) < len(temp): temp = temp[int(key_part)]
            else: return default
        return temp
    try:
        with open(json_filename, "r", encoding="utf-8") as json_file: data_tweets = json.load(json_file)
    except (FileNotFoundError, json.JSONDecodeError) as e: print(f"Error loading JSON {json_filename}: {e}"); return
    if not data_tweets: print(f"No tweets in {json_filename}"); return
    tweet_key_to_key_mapping = {"tweet_id": "rest_id", "created_at": "legacy.created_at", "favorite_count": "legacy.favorite_count","full_text_legacy": "legacy.full_text", "full_text_note": "note_tweet.note_tweet_results.result.text","quote_count": "legacy.quote_count", "reply_count": "legacy.reply_count", "retweet_count": "legacy.retweet_count","bookmark_count": "legacy.bookmark_count", "views_count": "views.count", "lang": "legacy.lang","user_id_str": "core.user_results.result.rest_id", "name": "core.user_results.result.legacy.name","screen_name": "core.user_results.result.legacy.screen_name", "followers_count": "core.user_results.result.legacy.followers_count","is_blue_verified": "core.user_results.result.is_blue_verified"}
    tweets_list = []
    for tweet_data in data_tweets:
        tweet_json = {};
        for key, json_path in tweet_key_to_key_mapping.items(): tweet_json[key] = returnValueFromData(tweet_data, json_path)
        tweet_json["full_text"] = tweet_json.get("full_text_note") or tweet_json.get("full_text_legacy")
        if "full_text_note" in tweet_json: del tweet_json["full_text_note"]
        if "full_text_legacy" in tweet_json: del tweet_json["full_text_legacy"]
        tweets_list.append(tweet_json)
    tweets_df = pd.DataFrame(tweets_list)
    if tweets_df.empty: print(f'No valid tweet data in {json_filename}'); return
    numeric_cols = ['favorite_count', 'retweet_count', 'reply_count', 'quote_count', 'bookmark_count', 'followers_count', 'views_count']
    for col in numeric_cols: tweets_df[col] = pd.to_numeric(tweets_df[col], errors='coerce')
    tweets_df_for_avg = tweets_df.dropna(subset=['favorite_count', 'retweet_count', 'reply_count'])
    if tweets_df_for_avg.empty:
        print(f'Not enough numeric data for analysis in {json_filename}.')
        if not tweets_df.empty:
            base_filename = os.path.splitext(os.path.basename(json_filename))[0]; csv_filename = os.path.join(output_dir, f"{base_filename}_analyzed_raw.csv")
            tweets_df.to_csv(csv_filename, index=False, encoding="utf-8-sig"); print(f"Saved raw data to {csv_filename}.")
        return
    avg_favorite = tweets_df_for_avg['favorite_count'].mean(); avg_retweet = tweets_df_for_avg['retweet_count'].mean(); avg_reply = tweets_df_for_avg['reply_count'].mean()
    tweets_df['above_avg_favorite'] = tweets_df['favorite_count'] > avg_favorite; tweets_df['above_avg_retweet'] = tweets_df['retweet_count'] > avg_retweet; tweets_df['above_avg_reply'] = tweets_df['reply_count'] > avg_reply
    tweets_df['above_average_engagement'] = (tweets_df['above_avg_favorite'] | tweets_df['above_avg_retweet'] | tweets_df['above_avg_reply'])
    tweets_df['average_favorite_count_overall'] = avg_favorite; tweets_df['average_retweet_count_overall'] = avg_retweet; tweets_df['average_reply_count_overall'] = avg_reply
    base_filename = os.path.splitext(os.path.basename(json_filename))[0]; csv_filename = os.path.join(output_dir, f"{base_filename}_analyzed.csv")
    tweets_df.to_csv(csv_filename, index=False, encoding="utf-8-sig"); print(f"Analyzed data saved to {csv_filename}")
    print(f"\n--- Analysis Summary for {json_filename} ---\nTotal: {len(tweets_df)}, Used for avg: {len(tweets_df_for_avg)}")
    print(f"Avg Fav: {avg_favorite:.2f}, Avg RT: {avg_retweet:.2f}, Avg Reply: {avg_reply:.2f}, Above Avg Engage: {tweets_df['above_average_engagement'].sum()}")

def main():
    if not X_USERNAME or X_USERNAME == "YOUR_X_USERNAME_HERE" or not X_PASSWORD or X_PASSWORD == "YOUR_X_PASSWORD_HERE":
        print("!!! X LOGIN CREDENTIALS NOT SET. Edit script. Scraping may fail. !!!"); time.sleep(3)
    try:
        with open(USERNAMES_FILE, "r", encoding="utf-8") as f: usernames_to_scrape = [line.strip() for line in f if line.strip()]
    except FileNotFoundError: print(f"Error: '{USERNAMES_FILE}' not found."); return
    if not usernames_to_scrape: print(f"Error: '{USERNAMES_FILE}' is empty."); return

    playwright_manager = None; browser = None; context = None

    try:
        playwright_manager = sync_playwright().start()
        browser = playwright_manager.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        login_page = context.new_page()
        initial_logged_in = login_to_x(login_page)
        try: login_page.close()
        except Exception as e_login_close: print(f"Note: Could not close login page: {e_login_close}")
        if not initial_logged_in: print("Initial login failed. Results may be severely limited or fail.")
        else: print("Initial login successful.")

        current_user_index = 0
        while current_user_index < len(usernames_to_scrape):
            username_in_file = usernames_to_scrape[current_user_index]
            if not username_in_file:
                current_user_index += 1; continue

            print(f"\n--- Starting processing for user: {username_in_file} ({current_user_index + 1}/{len(usernames_to_scrape)}) ---")
            sanitized_username = username_in_file.lstrip('@')
            profile_url = f"https://x.com/{sanitized_username}"
            user_dir = os.path.join(".", sanitized_username)

            is_problematic_before_scrape = False
            if os.path.exists(PROBLEMATIC_USERNAMES_FILE):
                with open(PROBLEMATIC_USERNAMES_FILE, 'r', encoding='utf-8') as p_check:
                    if any(username_in_file in line for line in p_check):
                        is_problematic_before_scrape = True

            if not is_problematic_before_scrape:
                 os.makedirs(user_dir, exist_ok=True)
            elif os.path.exists(user_dir):
                print(f"User '{username_in_file}' was previously marked problematic, ensuring directory is removed.")
                try: shutil.rmtree(user_dir)
                except Exception as e_rm_pre: print(f"Note: Error removing pre-existing problematic user dir {user_dir}: {e_rm_pre}")


            operation_completed_for_user = False
            global_retry_count_for_user = 0
            tweets_data_for_current_user = None # Initialize before retry loop
            profile_data_for_current_user = None # Initialize before retry loop

            while not operation_completed_for_user and global_retry_count_for_user <= MAX_GLOBAL_USER_RETRIES:
                try:
                    # Attempt to scrape tweets only if not already successfully scraped in a previous global attempt (if applicable)
                    if tweets_data_for_current_user is None: # Only attempt if not already fetched
                        print(f"Attempting to scrape tweets for: {sanitized_username} (Global attempt {global_retry_count_for_user + 1})")
                        tweets_data_for_current_user = scrape_twitter_info(context, profile_url, scrape_tweets_mode=True, timeout_seconds=480)

                    # Attempt to scrape profile only if not already successfully scraped
                    if profile_data_for_current_user is None: # Only attempt if not already fetched
                        print(f"Attempting to scrape profile for: {sanitized_username} (Global attempt {global_retry_count_for_user + 1})")
                        profile_data_for_current_user = scrape_twitter_info(context, profile_url, scrape_tweets_mode=False, timeout_seconds=90)

                    operation_completed_for_user = True # Mark as completed if both ops (or those pending) succeed or return None (no RateLimitException)

                except AccountUnavailableException as auae:
                    print(f"AccountUnavailableException for user {sanitized_username}: {auae}")
                    already_logged_problematic = False
                    if os.path.exists(PROBLEMATIC_USERNAMES_FILE):
                        with open(PROBLEMATIC_USERNAMES_FILE, 'r', encoding='utf-8') as p_check:
                            if any(username_in_file in line for line in p_check): already_logged_problematic = True
                    if not already_logged_problematic:
                        with open(PROBLEMATIC_USERNAMES_FILE, "a", encoding="utf-8") as puf: puf.write(f"{username_in_file}\n")
                        print(f"Added '{username_in_file}' to {PROBLEMATIC_USERNAMES_FILE}.")
                    if os.path.exists(user_dir): # Ensure directory is removed for problematic accounts
                        try: shutil.rmtree(user_dir); print(f"Removed directory due to account issue: {user_dir}")
                        except OSError as e_rm: print(f"Error removing directory {user_dir} for problematic account: {e_rm}")
                    operation_completed_for_user = True # Stop retrying for this user
                    global_retry_count_for_user = MAX_GLOBAL_USER_RETRIES + 1 # Ensure exit from global retry loop

                except RateLimitException as rle_from_scraper:
                    print(f"Persistent RateLimitException for user {sanitized_username} after local retries: {rle_from_scraper}")
                    global_retry_count_for_user += 1
                    if global_retry_count_for_user <= MAX_GLOBAL_USER_RETRIES:
                        print(f"--- Initiating GLOBAL RETRY {global_retry_count_for_user}/{MAX_GLOBAL_USER_RETRIES} for {sanitized_username} ---")
                        print(f"Closing current browser session...")
                        if context:
                            try: context.close(); context = None;
                            except Exception as e: print(f"Err closing context: {e}")
                        if browser:
                            try: browser.close(); browser = None;
                            except Exception as e: print(f"Err closing browser: {e}")

                        print(f"Waiting for {GLOBAL_RETRY_DELAY_SECONDS} seconds before re-initializing browser...")
                        time.sleep(GLOBAL_RETRY_DELAY_SECONDS)
                        try:
                            print("Re-initializing browser and context...")
                            if not playwright_manager: playwright_manager = sync_playwright().start()
                            browser = playwright_manager.chromium.launch(headless=False)
                            context = browser.new_context(viewport={"width": 1920, "height": 1080})
                            temp_login_page = context.new_page()
                            logged_in_after_retry = login_to_x(temp_login_page)
                            try: temp_login_page.close()
                            except Exception as e: print(f"Err closing temp login page: {e}")

                            if not logged_in_after_retry:
                                print("FATAL: Failed to re-login after browser restart. Skipping user.")
                                operation_completed_for_user = True # Give up on this user
                            else:
                                print("Re-login successful. Retrying scraping for current user.")
                                # Do NOT set operation_completed_for_user = True; allow loop to retry operations
                        except Exception as e_reinit:
                            print(f"FATAL: Error during browser re-initialization: {e_reinit}. Skipping user.")
                            operation_completed_for_user = True # Give up on this user
                    else:
                        print(f"Max global retries ({MAX_GLOBAL_USER_RETRIES}) reached for {sanitized_username} due to rate limits. Skipping user.")
                        operation_completed_for_user = True # Give up on this user

                except Exception as e_other_op_error:
                    print(f"Unhandled error during scraping operations for {sanitized_username} in global attempt: {e_other_op_error}")
                    operation_completed_for_user = True # Give up on this user for this cycle

            # After all attempts for the user (either completed, rate-limited out, or other error)
            is_problematic_after_scrape = False
            if os.path.exists(PROBLEMATIC_USERNAMES_FILE):
                with open(PROBLEMATIC_USERNAMES_FILE, 'r', encoding='utf-8') as p_check_file:
                    if any(username_in_file in line for line in p_check_file):
                        is_problematic_after_scrape = True

            if not is_problematic_after_scrape: # Only save if not marked as problematic
                if os.path.exists(user_dir): # Ensure user_dir exists (it might have been removed if problematic was found late)
                    tweets_filename = os.path.join(user_dir, f"{sanitized_username}_last_{NUM_POSTS_TO_RETRIEVE}_tweets.json")
                    if tweets_data_for_current_user:
                        print(f"Final tweet data count for {sanitized_username}: {len(tweets_data_for_current_user)}.")
                        with open(tweets_filename, "w", encoding="utf-8") as f: json.dump(tweets_data_for_current_user, f, indent=4, ensure_ascii=False)
                        print(f"Saved tweets to {tweets_filename}"); analyze_and_save_tweets(tweets_filename, user_dir)
                    else:
                        print(f"No tweet data collected for {sanitized_username} after all attempts.")
                        # Clean up empty file if it was created then failed
                        if os.path.exists(tweets_filename) and os.path.getsize(tweets_filename) == 0:
                            try: os.remove(tweets_filename); print(f"Removed empty tweet file: {tweets_filename}")
                            except OSError as e: print(f"Error removing empty {tweets_filename}: {e}")

                    profile_filename = os.path.join(user_dir, f"{sanitized_username}_user_profile_info.json")
                    if profile_data_for_current_user:
                        with open(profile_filename, "w", encoding="utf-8") as f: json.dump(profile_data_for_current_user, f, indent=4, ensure_ascii=False)
                        print(f"Profile data for {sanitized_username} saved to {profile_filename}")
                    else:
                        print(f"No profile data collected for {sanitized_username} after all attempts.")
                        if os.path.exists(profile_filename) and os.path.getsize(profile_filename) == 0:
                            try: os.remove(profile_filename); print(f"Removed empty profile file: {profile_filename}")
                            except OSError as e: print(f"Error removing empty {profile_filename}: {e}")
                else:
                    print(f"User directory {user_dir} does not exist, skipping file saving for {sanitized_username}.")


            # Final status message for the user
            if not is_problematic_after_scrape:
                tweets_file_exists = os.path.exists(os.path.join(user_dir, f"{sanitized_username}_last_{NUM_POSTS_TO_RETRIEVE}_tweets.json")) and \
                                     os.path.getsize(os.path.join(user_dir, f"{sanitized_username}_last_{NUM_POSTS_TO_RETRIEVE}_tweets.json")) > 0
                profile_file_exists = os.path.exists(os.path.join(user_dir, f"{sanitized_username}_user_profile_info.json")) and \
                                      os.path.getsize(os.path.join(user_dir, f"{sanitized_username}_user_profile_info.json")) > 0

                if tweets_file_exists and profile_file_exists: print(f"Successfully completed for {sanitized_username}.")
                elif tweets_file_exists: print(f"Partially completed for {sanitized_username} (tweets OK, profile failed/not found).")
                elif profile_file_exists: print(f"Partially completed for {sanitized_username} (profile OK, tweets failed/not found).")
                elif os.path.exists(user_dir): # Directory exists but no data
                     print(f"Processing ultimately failed to yield data for {sanitized_username}.")
                # If user_dir was removed (e.g. became problematic late), this won't print, which is fine.
            else:
                print(f"Processing for {sanitized_username} concluded as problematic.")


            print(f"--- Finished all attempts for {username_in_file} ---")
            current_user_index += 1
            if current_user_index < len(usernames_to_scrape):
                print(f"Waiting for 10 seconds before processing next user...")
                time.sleep(10) # Inter-user delay

        print("\nAll users processed.")

    except Exception as e_outer_main:
        print(f"Critical error in script execution: {e_outer_main}")
    finally:
        print("\nCleaning up final browser session...")
        if context:
            try: context.close()
            except Exception as e: print(f"Error closing final context: {e}")
        if browser and browser.is_connected(): # Check if browser is still connected
            try: browser.close()
            except Exception as e: print(f"Error closing final browser: {e}")
        if playwright_manager:
            try: playwright_manager.stop()
            except Exception as e: print(f"Error stopping playwright: {e}")
        print("Script finished.")

if __name__ == "__main__":
    main()