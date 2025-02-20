# pip install playwright scrapfly-sdk
# playwright install

from playwright.sync_api import sync_playwright
import json
import time
import os
import subprocess
import pandas as pd

# --- CONFIGURATION ---
USERNAMES_FILE = "usernames.txt"
NUM_POSTS_TO_RETRIEVE = 100
# --- END CONFIGURATION ---

def scrape_twitter_info(url: str, is_user_profile: bool, timeout_seconds=60):
    """Scrapes Twitter info with improved timeouts and error handling.

    Args:
        url: The Twitter URL to scrape.
        is_user_profile: True to scrape tweets, False for user profile.
        timeout_seconds: Timeout for the entire scraping process (both page load and data retrieval)

    Returns:
        Tweet data (list) or user data (dict) if successful, None otherwise.
    """
    _xhr_calls = []

    def intercept_response(response):
        if response.request.resource_type == "xhr":
            _xhr_calls.append(response)
        return response

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Consider headless=True
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        page.on("response", intercept_response)

        try:
            start_time = time.time()  # Overall start time

            if is_user_profile:
                try:
                    page.goto(url, timeout=timeout_seconds * 1000)  # Overall timeout
                except Exception as e:
                    print(f"Error loading page {url}: {e}")
                    return None

                selector = "[data-testid='primaryColumn']"
                xhr_condition = "UserTweets"
                try:
                    page.wait_for_selector(selector, timeout=30000)
                except Exception as e:
                    print(f"Error waiting for selector on {url}: {e}")
                    return None

                tweets = []
                found_ids = set()
                processed_xhr_calls = set()

                while len(tweets) < NUM_POSTS_TO_RETRIEVE and time.time() - start_time < timeout_seconds:
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

                    if len(tweets) < NUM_POSTS_TO_RETRIEVE and time.time() - start_time < timeout_seconds :
                        page.mouse.wheel(0, 10000)
                        time.sleep(2)

                return tweets

            else:
                try:
                    page.goto(url, timeout=timeout_seconds * 1000)  # Overall timeout
                except Exception as e:
                    print(f"Error loading page {url}: {e}")
                    return None

                selector = "[data-testid='primaryColumn']"
                xhr_condition = "UserByScreenName"
                try:
                    page.wait_for_selector(selector, timeout=30000)
                except Exception as e:
                     print(f"Error waiting for selector on {url}: {e}")
                     return None

                user_data = None
                # Combined loop for waiting and processing, with overall timeout
                while time.time() - start_time < timeout_seconds and user_data is None:
                    user_calls = [f for f in _xhr_calls if xhr_condition in f.url]
                    for call in user_calls:
                        try:
                            data = call.json()
                            if 'data' in data and 'user' in data['data']:
                                user_data = data['data']['user']['result']
                                if 'rest_id' in user_data and 'errors' not in user_data and 'legacy' in user_data:
                                    return user_data
                        except (KeyError, TypeError, json.JSONDecodeError) as e:
                            print(f"Error processing XHR call: {e}, URL: {call.url}")
                    time.sleep(1)  # Short delay

                return user_data  # Return whatever we have (might be None)

        except Exception as e:
            print(f"An unexpected error occurred during scraping: {e}")
            return None
        finally:
            context.close()
            browser.close()

def analyze_and_save_tweets(json_filename, output_dir):
    """Analyzes tweet data from a JSON file and saves the result to a CSV."""

    def returnValueFromData(data, key):
        temp = data.copy()
        for i in key.split('.'):
            if isinstance(temp, dict) and i in temp:
                temp = temp[i]
            else:
                return None
        return temp

    def analyze_tweets(df):
        avg_favorite = df['favorite_count'].mean()
        avg_retweet = df['retweet_count'].mean()
        avg_reply = df['reply_count'].mean()
        df['above_avg_favorite'] = df['favorite_count'] > avg_favorite
        df['above_avg_retweet'] = df['retweet_count'] > avg_retweet
        df['above_avg_reply'] = df['reply_count'] > avg_reply
        df['above_average_engagement'] = (df['above_avg_favorite'] | df['above_avg_retweet'] | df['above_avg_reply'])
        return df, avg_favorite, avg_retweet, avg_reply

    try: # Added try-except to loading json file
        with open(json_filename, "r") as json_file:
            data_tweets = json.load(json_file)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading or decoding JSON from {json_filename}: {e}")
        return

    if not data_tweets: # Added condition to avoid errors
        print(f"No tweets to analyze in {json_filename}")
        return
    tweet_key_to_key_mapping = {
        "favorite_count": "legacy.favorite_count",
        "full_text": "legacy.full_text",
        "quote_count": "legacy.quote_count",
        "reply_count": "legacy.reply_count",
        "retweet_count": "legacy.retweet_count",
        "name": "core.user_results.result.legacy.name",
        "followers_count": "core.user_results.result.legacy.followers_count"
    }

    tweets_list = []
    for tweet in data_tweets:
        tweet_json = {}
        for key, json_key in tweet_key_to_key_mapping.items():
            tweet_json[key] = returnValueFromData(tweet, json_key)
        tweets_list.append(tweet_json)

    tweets_df = pd.DataFrame(tweets_list)
    if tweets_df.empty: # Added condition to avoid errors
        print(f'No tweets to analyze in {json_filename}')
        return
    tweets_df, avg_favorite, avg_retweet, avg_reply = analyze_tweets(tweets_df)

    tweets_df['average_favorite_count'] = avg_favorite
    tweets_df['average_retweet_count'] = avg_retweet
    tweets_df['average_reply_count'] = avg_reply

    base_filename = os.path.splitext(os.path.basename(json_filename))[0]
    csv_filename = os.path.join(output_dir, f"{base_filename}_analyzed.csv")
    tweets_df.to_csv(csv_filename, index=False)
    print(f"Analyzed data saved to {csv_filename}")


    print("\n--- Average Engagement Metrics ---")
    print(f"Average Favorite Count: {avg_favorite:.2f}")
    print(f"Average Retweet Count: {avg_retweet:.2f}")
    print(f"Average Reply Count: {avg_reply:.2f}")

    print("\nAll Tweets:")
    print(tweets_df[[ "name", "followers_count", "full_text",
                      "favorite_count", "retweet_count", "reply_count", "quote_count"]])

    print("\nTweets with Above-Average Engagement:")
    print(tweets_df[tweets_df['above_average_engagement']][[ "name", "followers_count", "full_text",
                                                            "favorite_count", "retweet_count", "reply_count",
                                                            "quote_count"]])

    print("\nAnalysis Columns (Optional):")
    print(tweets_df[['above_avg_favorite', 'above_avg_retweet', 'above_avg_reply', 'above_average_engagement']])

def main():
    try:
        with open(USERNAMES_FILE, "r") as f:
            usernames = [line.strip() for line in f]
    except FileNotFoundError:
        print(f"Error: Usernames file '{USERNAMES_FILE}' not found.")
        return

    if not usernames:
        print("Error: Usernames file is empty.")
        return

    for username in usernames:
        profile_url = f"https://x.com/{username}"
        print(f"Scraping data for: {username}")

        user_dir = os.path.join(".", username)
        os.makedirs(user_dir, exist_ok=True)

        tweets_filename = os.path.join(user_dir, f"{username}_first_{NUM_POSTS_TO_RETRIEVE}_tweets.json")
        profile_filename = os.path.join(user_dir, f"{username}_user_profile_info.json")

        # Scrape tweets
        tweets_data = scrape_twitter_info(profile_url, True)
        if tweets_data is not None:  # Check if scraping was successful
            with open(tweets_filename, "w") as f:
                json.dump(tweets_data, f, indent=4)

            # Analyze and save tweets (only if tweets were scraped)
            analyze_and_save_tweets(tweets_filename, user_dir)
        else:
            print(f"Skipping analysis for {username} due to scraping failure.")
            # Clean up potentially empty files:
            if os.path.exists(tweets_filename):
                os.remove(tweets_filename)


        # Scrape user profile
        user_data = scrape_twitter_info(profile_url, False)
        if user_data is not None:
            with open(profile_filename, "w") as f:
                json.dump(user_data, f, indent=4)
            print(f"Profile data for {username} saved to {profile_filename}")
        else:
            print(f"Skipping profile saving for {username} due to scraping failure.")
            if os.path.exists(profile_filename):
                os.remove(profile_filename)
        if os.path.exists(tweets_filename) and os.path.exists(profile_filename): # if both exists
             print(f"Data for {username} saved to {user_dir}") # print this line


if __name__ == "__main__":
    main()