# Twitter Data Scraper and Analyzer

This project provides tools for scraping and analyzing Twitter data using Playwright and Pandas. It automatically scrapes user profile information and a specified number of tweets for multiple Twitter profiles, analyzes the tweet data, and saves the results.

## Table of Contents

*   [Features](#features)
*   [Requirements](#requirements)
*   [Usage](#usage)
*   [Code Structure](#code-structure)
*   [Notes and Considerations](#notes-and-considerations)
*   [Disclaimer](#disclaimer)

## Features

*   **Scrape User Profile Data:** Retrieves comprehensive user profile information, including:
    *   Username
    *   Display name
    *   Bio
    *   Follower/following counts
    *   Verification status
    *   Profile image URL
    *   Banner image URL
    *   Location
    *   Creation date
    *   And more...
*   **Scrape Recent Tweets:** Fetches a configurable number of recent tweets from a user's timeline.
*   **Tweet Analysis:** Analyzes scraped tweets to identify those with above-average engagement (favorites, retweets, replies).
*   **Data Extraction:** Extracts key information from the raw JSON data returned by Twitter's API, including:
    *   Tweet text
    *   Favorite count
    *   Retweet count
    *   Reply count
    *   Quote count
    *   Author name
    *   Author's follower count
*   **Data Output:**
    *   Saves scraped data to JSON files (one for tweets, one for profile info).
    *   Presents analyzed tweet data in a Pandas DataFrame.
    *   Displays results (including averages) in a user-friendly format in the console.
    *   Saves analyzed data (including averages) to a CSV file.
*   **Automated Multi-User Scraping:** Reads a list of usernames from a text file (`usernames.txt`) and automatically scrapes data for each user.
*   **Organized Output:** Creates a separate directory for each user and stores the scraped JSON and analyzed CSV files within that directory.
*   **Dynamic Filenames:** Generates output filenames based on the target Twitter username and the number of tweets requested.
*   **Configurable:** Uses a simple configuration section to set the number of tweets to retrieve and the input file containing usernames.
*   **Robust Error Handling:** Includes comprehensive error handling to deal with network issues, page loading problems, and variations in Twitter's API responses.  Uses timeouts and retries.

## Requirements

*   Python 3.7+
*   `playwright`: `pip install playwright`
*   `scrapfly-sdk`: `pip install scrapfly-sdk` (Optional, but good practice)
*   `pandas`: `pip install pandas`
*   Playwright browsers: `playwright install`

## Usage

1.  **Create `usernames.txt`:**
    *   Create a plain text file named `usernames.txt` in the same directory as the Python script (`twitter_scraping_cmds.py`).
    *   Enter each Twitter username *on a separate line* within the file.  Do *not* include the full URL, just the username.  Example:

        ```
        elonmusk
        JeffBezos
        BillGates
        ```

2.  **Configuration (Optional):**
    *   Open `twitter_scraping_cmds.py` in a text editor.
    *   You can modify the `NUM_POSTS_TO_RETRIEVE` variable to change the number of tweets scraped per user (default is 10).

3.  **Run the Scraper:**
    *   Open a terminal or command prompt.
    *   Navigate to the directory where you saved `twitter_scraping_cmds.py` and `usernames.txt`.
    *   **Activate your virtual environment** (highly recommended):
        *   **Windows (cmd):**  `venv\Scripts\activate.bat`
        *   **Windows (PowerShell):** `venv\Scripts\Activate.ps1`
        *   **macOS/Linux:** `source venv/bin/activate`
    *   Run the script: `python twitter_scraping_cmds.py`

4.  **Output:**

    *   The script will create a directory for *each username* listed in `usernames.txt`.  These directories will be created in the same location as the script.
    *   Inside each user directory, you'll find:
        *   `{username}_first_{N}_tweets.json`:  The raw JSON data for the scraped tweets.
        *   `{username}_user_profile_info.json`: The raw JSON data for the user's profile.
        *   `{username}_first_{N}_tweets_analyzed.csv`:  A CSV file containing the analyzed tweet data, including engagement metrics and averages.
    * The script will also print progress messages and average engagement statistics to the console.

## Code Structure

*   **`scrape_twitter_info(url, is_user_profile)`:** The core scraping function.  Handles both tweet scraping and user profile scraping based on the `is_user_profile` flag. Uses Playwright to interact with the Twitter page, intercept XHR requests, and handle scrolling. Includes robust error handling and timeouts.
*   **`analyze_and_save_tweets(json_filename, output_dir)`:**  Loads tweet data from a JSON file, extracts relevant information, performs engagement analysis (identifies tweets with above-average likes, retweets, and replies), calculates average engagement metrics, and saves the analyzed data to a CSV file in the specified output directory.  Also displays analysis data in the console.
*   **`main()`:**  The main function that reads usernames from `usernames.txt`, constructs the Twitter URLs, calls `scrape_twitter_info` to scrape data for each user, creates user-specific directories, and calls `analyze_and_save_tweets` to process and save the tweet data.
* **Configuration variables:** The script uses configuration variables such as `USERNAMES_FILE` and `NUM_POSTS_TO_RETRIEVE`.

## Notes and Considerations

*   **Twitter's Terms of Service:**  Be aware of and comply with Twitter's Terms of Service and robots.txt regarding scraping.  Automated scraping *can* be against their terms, and excessive scraping *can* lead to account suspension. Use this code responsibly and ethically.
*   **Rate Limiting:** Twitter's API has rate limits.  The code includes delays (`time.sleep`) to help avoid hitting these limits, but you may need to adjust them.
*   **Headless Mode:** For production use or server environments, consider running Playwright in headless mode (`headless=True` in `p.chromium.launch()`). This will run the browser in the background without a visible window.
*   **Dynamic Content:** The scraper relies on intercepting XHR requests.  Changes to Twitter's website structure or API could break the scraper.
*   **Authentication:** This scraper does *not* require login. It accesses only publicly available data. For private data or higher rate limits, you'd need to implement authentication (a much more complex task).

## Disclaimer

This code is provided for educational and informational purposes only. The author is not responsible for any consequences resulting from its use. Use it responsibly, ethically, and in compliance with Twitter's terms of service.