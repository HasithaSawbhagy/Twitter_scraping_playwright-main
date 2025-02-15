# pip install playwright scrapfly-sdk
# playwright install

from playwright.sync_api import sync_playwright
from pprint import pprint
import json
import time

# --- CONFIGURATION ---
PROFILE_URL = "https://x.com/MrBeast"  # Single place to set the profile URL
NUM_POSTS_TO_RETRIEVE = 10  # Single place to set the number of posts
# --- END CONFIGURATION ---

def scrape_twitter_info(url: str, is_user_profile: bool):

    _xhr_calls = []

    def intercept_response(response):
        if response.request.resource_type == "xhr":
            _xhr_calls.append(response)
        return response

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Consider headless=True for production
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        page.on("response", intercept_response)


        if is_user_profile:
            page.goto(url)
            selector = "[data-testid='primaryColumn']"
            xhr_condition = "UserTweets"
            json_condition = "tweetResult"

            page.wait_for_selector(selector)

            tweets = []
            found_ids = set()
            start_time = time.time()
            timeout_seconds = 60
            processed_xhr_calls = set()

            while len(tweets) < NUM_POSTS_TO_RETRIEVE:
                new_xhr_calls = [f for f in _xhr_calls if xhr_condition in f.url and f not in processed_xhr_calls]

                for xhr_call in new_xhr_calls:
                    processed_xhr_calls.add(xhr_call)
                    try:
                        data = xhr_call.json()
                        instructions = data['data']['user']['result']['timeline_v2']['timeline']['instructions']
                        entries = None
                        for instruction in instructions:
                            if instruction['type'] == 'TimelineAddEntries':
                                entries = instruction['entries']
                                break
                        if entries is None:
                            continue

                        for entry in entries:
                            try:
                                if 'tweet' in entry['content']['itemContent']['itemType'].lower():
                                    result = entry['content']['itemContent']['tweet_results']['result']
                                    if 'rest_id' not in result or 'legacy' not in result:
                                        continue
                                    tweet_id = result['rest_id']
                                    if tweet_id not in found_ids:
                                        tweets.append(result)
                                        found_ids.add(tweet_id)
                                        if len(tweets) >= NUM_POSTS_TO_RETRIEVE:
                                             break
                            except (KeyError, TypeError):
                                continue
                        if len(tweets) >= NUM_POSTS_TO_RETRIEVE:
                            break

                    except (KeyError, TypeError, json.JSONDecodeError) as e:
                        continue

                if time.time() - start_time > timeout_seconds:
                    print("Timeout reached. Collected ", len(tweets), " tweets.")
                    break

                if len(tweets) < NUM_POSTS_TO_RETRIEVE:
                    page.mouse.wheel(0, 10000)
                    time.sleep(2)

            return tweets
        else:
            # User profile details retrieval
            try:
                page.goto(url, timeout=60000)
            except Exception as e:
                print(f"Error loading page: {e}")
                return None
            selector = "[data-testid='primaryColumn']"
            xhr_condition = "UserByScreenName"
            page.wait_for_selector(selector, timeout=30000)

            # Wait for UserByScreenName XHR calls, process, and return on success
            start_time = time.time()
            user_data = None  # Initialize user_data
            while time.time() - start_time < 30 and user_data is None: # Modified condition
                user_calls = [f for f in _xhr_calls if xhr_condition in f.url]
                for call in user_calls:
                    try:
                        data = call.json()
                        user_data = data['data']['user']['result']
                        if 'rest_id' in user_data and 'errors' not in user_data: # Corrected condition
                            return user_data  # Return as soon as valid data is found
                    except (KeyError, TypeError, json.JSONDecodeError) as e:
                        print(f"Error processing XHR call: {e}, URL: {call.url}")
                        # No 'continue' here

                time.sleep(1)

            return user_data # return the user_data


# --- Helper function to extract username ---
def get_username(url):
    return url.split('/')[-1]

# --- Dynamically generate filenames ---
username = get_username(PROFILE_URL)
tweets_filename = f"{username}_first_{NUM_POSTS_TO_RETRIEVE}_tweets.json"
profile_filename = f"{username}_user_profile_info.json"


# Example usage for user profile (first N tweets)
with open(tweets_filename, "w") as f:
    json.dump(scrape_twitter_info(PROFILE_URL, True), f, indent=4)


# Example usage for user profile details
with open(profile_filename, "w") as f:
    json.dump(scrape_twitter_info(PROFILE_URL, False), f, indent=4)