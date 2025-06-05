# Twitter/X Scraping with Playwright

This project scrapes public data from Twitter (X.com) user profiles and their tweets using [Playwright](https://playwright.dev/python/). It supports robust error handling, rate limit management, and engagement analysis of tweets.

## Features

- Scrapes tweets and profile info for a list of usernames
- Handles rate limits, unavailable/suspended accounts, and retries
- Saves results as JSON and analyzed CSV files per user
- Maintains lists of problematic usernames
- Engagement analysis (above-average favorites, retweets, replies)
- Cookie/session management via `state.json` (if needed)

## Prerequisites

- Python 3.8+
- [Playwright for Python](https://playwright.dev/python/)
- pandas

## Setup

1. **Clone the repository:**
   ```sh
   git clone https://github.com/yourusername/Twitter_scraping_playwright.git
   cd Twitter_scraping_playwright-main
   ```

2. **Install dependencies:**
   ```sh
   pip install playwright pandas
   playwright install
   ```

3. **Configure credentials:**
   - Edit `twitter_scraping_cmds.py` and set your X (Twitter) username and password:
     ```python
     X_USERNAME = "your_x_username"
     X_PASSWORD = "your_x_password"
     ```
   - Alternatively, you can use cookies in `state.json` for session management.

4. **Prepare input files:**
   - `usernames.txt`: List of usernames to scrape (one per line, without `@`)
   - `problematic_usernames.txt`: (auto-managed) Usernames that failed or are unavailable

5. **Run the scraper:**
   ```sh
   python twitter_scraping_cmds.py
   ```

6. **Analyze tweets (optional):**
   - Use the included Jupyter notebook `twitter_scraping.ipynb` for further analysis and visualization.

## Output

- For each username, a folder is created containing:
  - `<username>_last_200_tweets.json`: Raw tweets
  - `<username>_last_200_tweets_analyzed.csv`: Analyzed tweet data
  - `<username>_user_profile_info.json`: Profile info

## Notes

- Use responsibly and respect Twitter/X's terms of service.
- This project is for educational and research purposes only.
- If you hit rate limits, the script will automatically retry with delays.

## License

