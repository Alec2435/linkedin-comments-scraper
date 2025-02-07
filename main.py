import csv
import json
import argparse
from time import time, sleep
from datetime import datetime
from urllib.parse import urljoin
import pickle
import os
from pathlib import Path
from seleniumwire import webdriver

from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException
from bs4 import BeautifulSoup as BSoup

from utils import (
    check_post_url,
    login_details,
    load_more,
    extract_emails,
    download_avatars,
    # write_data2csv,   # No longer needed
)

parser = argparse.ArgumentParser(description="Linkedin Scraping.")

parser.add_argument(
    "--headless", dest="headless", action="store_true", help="Go headless browsing"
)
parser.set_defaults(headless=False)
parser.add_argument(
    "--show-replies", dest="show_replies", action="store_true", help="Load all replies to comments"
)
parser.set_defaults(show_replies=False)

parser.add_argument(
    "--download-pfp",
    dest="download_avatars",
    action="store_true",
    help="Download profile pictures of commentors",
)
parser.set_defaults(download_avatars=False)

parser.add_argument(
    "--save-page-source",
    dest="save_page_source",
    action="store_true",
    help="Save page source for debugging",
)
parser.set_defaults(save_page_source=False)

parser.add_argument(
    "--zenrows-username",
    dest="zenrows_username",
    help="Zenrows username",
)
parser.add_argument(
    "--zenrows-password",
    dest="zenrows_password",
    help="Zenrows password",
)

# New flag to disable auto reply functionality if desired
parser.add_argument("--no-reply", dest="no_reply", action="store_true", help="Disable auto reply functionality")
parser.set_defaults(no_reply=False)

args = parser.parse_args()

now = datetime.now()
unique_suffix = now.strftime("-%m-%d-%Y--%H-%M")

with open("config.json") as f:
    Config: dict[str, str] = json.load(f)

# Setup cookies directory
COOKIES_DIR = Path("cookies")
COOKIES_FILE = COOKIES_DIR / "linkedin_cookies.pkl"
COOKIES_DIR.mkdir(exist_ok=True)

post_url = check_post_url(Config["post_url"])

# Initialize CSV file with header.
csv_filename = Config["filename"] + unique_suffix + ".csv"
csvfile = open(csv_filename, "w", encoding="utf-8", newline="")
writer = csv.writer(csvfile)
writer.writerow(["Name", "Headline", "Profile Picture", "Email", "Comment"])
csvfile.flush()  # flush header

linkedin_username, linkedin_password = login_details()

start = time()  # Starting time
print("Initiating the process....")

##### Selenium Chrome Driver
options = Options()
options.headless = args.headless
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("enable-automation")
options.add_argument("--disable-infobars")
options.add_argument("--disable-dev-shm-usage")
# To help mitigate crashes for large sets of comments, you could disable image loading:
# prefs = {"profile.managed_default_content_settings.images": 2}
# options.add_experimental_option("prefs", prefs)

seleniumwire_options = {}
if args.zenrows_username and args.zenrows_password:
    print("Using Zenrows proxy")
    proxy_url = f"http://{args.zenrows_username}:{args.zenrows_password}@superproxy.zenrows.com:1337"
    seleniumwire_options = {
        "proxy": {
            "http": f"{proxy_url}",
            "https": f"{proxy_url}",
        },
    }

driver = webdriver.Chrome(
    options=options, service=Service(ChromeDriverManager().install()), seleniumwire_options=seleniumwire_options
)
# driver = webdriver.Safari()
# driver.maximize_window()
# driver.get("https://www.linkedin.com")

def save_cookies(driver, filename):
    """Save cookies to file"""
    with open(filename, 'wb') as file:
        pickle.dump(driver.get_cookies(), file)
    print("Cookies saved successfully")

def load_cookies(driver, filename):
    """Load cookies from file and add them to driver"""
    if not os.path.exists(filename):
        return False
    
    # Prompt user if they want to load cookies
    choice = input("Do you want to load cookies? (y/N) : ")
    if choice.lower() != "y":
        return False
    
    with open(filename, 'rb') as file:
        cookies = pickle.load(file)
        for cookie in cookies:
            driver.add_cookie(cookie)
    print("Cookies loaded successfully")
    return True

driver.get("https://www.linkedin.com")

cookies_loaded = load_cookies(driver, COOKIES_FILE)

if cookies_loaded:
    driver.refresh()
    sleep(2)  # Wait for refresh
    
    if "feed" in driver.current_url or "login" not in driver.current_url:
        print("Successfully logged in using cookies")
    else:
        print("Cookies expired, logging in manually")
        cookies_loaded = False

if not cookies_loaded:
    driver.get("https://www.linkedin.com/login")
    username = driver.find_element(By.NAME, Config["username_name"])
    username.send_keys(linkedin_username)

    password = driver.find_element(By.NAME, Config["password_name"])
    password.send_keys(linkedin_password)

    sign_in_button = driver.find_element(By.XPATH, Config["sign_in_button_xpath"])
    sign_in_button.click()
    # wait for navigation to complete
    sleep(4)

    twofa_complete = False
    try:
        app_login_header = driver.find_element(By.CSS_SELECTOR, ".header__content__heading__inapp")
        if not app_login_header.text.lower().contains("linkedin app"):
            raise Exception("Not app based 2fa")
        print("LinkedIn sent a notification to your signed in devices. Open your LinkedIn app and tap Yes to confirm your sign-in attempt.")
        input("Press Enter after completing 2FA")
        twofa_complete = True
    except:
        print("Not app based 2fa")

    try:
        two_step_challenge = driver.find_element(By.ID, "two-step-challenge")
        print("Found sms 2fa challenge")
        two_step_header = driver.find_element(By.CSS_SELECTOR, ".content__header")
        ending_in = two_step_header.text.lower().split("ending with")[1].strip()
        print(f"LinkedIn sent an SMS to your registered phone number (ending in {ending_in}). Enter the code in the prompt below.")
        twofa_code = input("Enter the code: ")
        twofa_input = driver.find_element(By.ID, "input__phone_verification_pin")
        twofa_input.send_keys(twofa_code)
        twofa_input.send_keys(Keys.ENTER)
        twofa_complete = True
    except Exception as e:
        print(f"Error finding sms 2fa challenge: {str(e)}")
        print("Not sms 2fa")

    if not twofa_complete:
        input("No known 2fa method found. It's possible there's no 2fa or you need to manually enter the code. Press Enter to attempt to continue...")
    
    save_cookies(driver, COOKIES_FILE)

try:
    driver.get(post_url)

    # Wait for the page to load completely
    sleep(4)

    # Change to most recent comment sort
    sort_button = driver.find_element(By.CSS_SELECTOR, "button.comments-sort-order-toggle__trigger")
    sort_button.click()
    sleep(1)
    most_recent_option = driver.find_element(By.CSS_SELECTOR, '[aria-label="Most recent. See all comments, the most recent comments are first"]')
    most_recent_option.click()

    # Optionally load more comments/replies if requested
    if args.show_replies:
        print("Loading replies :", end=" ", flush=True)
        load_more("replies", Config["load_replies_class"], driver)
    
    if args.save_page_source:
        with open("page_source.html", "w", encoding='utf-8') as f:
            f.write(driver.page_source)

    # ------------------------------------------------------------------
    # NEW: Integrated CSV saving inside the auto-reply/main comment loop.
    # Instead of processing all comments via BeautifulSoup and then writing to CSV,
    # we immediately extract and write each comment as it’s processed.
    # ------------------------------------------------------------------

    # Define a helper function to extract comment data from a Selenium element.
    def extract_comment_data(comment_article, config):
        html = comment_article.get_attribute("innerHTML")
        soup = BSoup(html, "html.parser")
        # Extract name
        name_elem = soup.find("span", {"class": config["name_class"]})
        name = name_elem.get_text(strip=True) if name_elem else ""
        # Extract headline
        headline_elem = soup.find("span", {"class": config["headline_class"]})
        headline = headline_elem.get_text(strip=True) if headline_elem else ""
        # Extract avatar URL from the <a> with avatar class
        avatar = ""
        avatar_elem = soup.find("a", {"class": config["avatar_class"]})
        if avatar_elem:
            img_elem = avatar_elem.find("img")
            if img_elem and img_elem.has_attr("src"):
                avatar = img_elem["src"]
        # Extract comment text
        comment_elem = soup.find("span", {"class": config["comment_class"]})
        comment_text = comment_elem.get_text(strip=True) if comment_elem else ""
        # Extract email (if any) from the comment text
        emails = extract_emails(comment_text)
        email = emails[0] if emails else ""
        return name, headline, avatar, email, comment_text

    # If auto-reply is enabled and not disabled by command-line flag:
    if not args.no_reply and Config.get("auto_reply", {}).get("enabled", False):
        print("\nProcessing auto-replies and saving comments to CSV...")
        selectors = Config["auto_reply"]["selectors"]
        delays = Config["auto_reply"]["delays"]
        
        processed_comments = set()  # Keep track of processed comment element IDs
        
        while True:
            # Find all currently visible top-level comment containers
            comments_section = driver.find_elements(By.CLASS_NAME, selectors["comment_container"])
            current_batch = [c for c in comments_section if c.id not in processed_comments]
            
            if not current_batch:
                print("No new comments to process")
                # Try to load more comments (with limited retries)
                retries = 0
                max_retries = 3
                should_continue = False
                
                while retries < max_retries:
                    try:
                        load_more_button = driver.find_element(By.CLASS_NAME, Config["load_comments_class"])
                        if load_more_button.is_displayed():
                            print("Loading more comments...")
                            driver.execute_script("arguments[0].scrollIntoView(false);", load_more_button)
                            sleep(delays["after_scroll"])
                            load_more_button.click()
                            sleep(delays["after_click"])
                            should_continue = True
                            break
                        else:
                            print("No more comments to load")
                            should_continue = False
                            break
                    except Exception:
                        retries += 1
                        if retries < max_retries:
                            print(f"Failed to load more comments. Retry {retries}/{max_retries} after 10 seconds...")
                            sleep(10)
                        else:
                            print("Finished processing all comments after maximum retries")
                            should_continue = False
                            break
                
                if not should_continue:
                    break  # Exit the main loop when no more comments can be loaded
            
            print(f"Processing batch of {len(current_batch)} comments")
            
            for comment_article in current_batch:
                try:
                    # Skip if already processed
                    if comment_article.id in processed_comments:
                        continue
                    
                    # Skip if this comment is actually a reply (not a top-level comment)
                    try:
                        if comment_article.find_element(By.CLASS_NAME, "comments-comment-entity--reply"):
                            processed_comments.add(comment_article.id)
                            continue
                    except Exception:
                        pass
                    
                    # Extract comment data from the element using the helper function.
                    try:
                        name, headline, avatar, email, comment_text = extract_comment_data(comment_article, Config)
                    except Exception as e:
                        print(f"Error extracting data from comment: {e}")
                        processed_comments.add(comment_article.id)
                        continue

                    # Immediately write this comment's data to CSV and flush
                    writer.writerow([name, headline, avatar, email, comment_text])
                    csvfile.flush()

                    print(f"Processing comment: {comment_text[:50]}...")
                    
                    # Check if the comment contains the trigger string (case-insensitive)
                    if Config["auto_reply"]["trigger_string"].lower() in comment_text.lower():
                        # Check for existing replies
                        replies_list = comment_article.find_elements(By.CLASS_NAME, selectors["reply_container"])
                        replies_count = comment_article.find_elements(By.CLASS_NAME, selectors["replies_count"])
                        
                        # If no replies have been posted, then attempt auto-reply
                        if (not replies_list or len(replies_list) == 0) or (replies_count and len(replies_count) > 0 and "0" in replies_count[0].text):
                            print(f"Found comment with trigger string and no replies: {comment_text[:50]}...")
                            
                            reply_button = comment_article.find_element(By.CSS_SELECTOR, "button.reply")
                            if reply_button:
                                button_id = reply_button.get_attribute("id")
                                if button_id:
                                    driver.execute_script("arguments[0].scrollIntoView(false);", reply_button)
                                    sleep(delays["after_scroll"])
                                    reply_button.click()
                                    sleep(delays["after_click"])

                                    try:
                                        reply_input = comment_article.find_element(By.CSS_SELECTOR, "div.ql-editor")
                                        reply_input.send_keys(Config["auto_reply"]["reply_message"])
                                        sleep(delays["after_type"])
                                        
                                        post_button = comment_article.find_element(By.CLASS_NAME, selectors["post_button"])
                                        if not post_button.is_enabled():
                                            driver.execute_script(
                                                "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));",
                                                reply_input
                                            )
                                            sleep(0.5)
                                        
                                        if post_button.is_enabled():
                                            post_button.click()
                                            sleep(delays["after_post"])
                                            print("Posted reply successfully")
                                        else:
                                            print("Post button is still not enabled")
                                    except Exception as e:
                                        print(f"Error interacting with reply input: {str(e)}")
                    
                    # Mark comment as processed regardless of outcome
                    processed_comments.add(comment_article.id)
                    
                except Exception as e:
                    print(f"Error processing comment: {str(e)}")
                    processed_comments.add(comment_article.id)
                    continue
    else:
        if args.no_reply:
            print("Auto reply functionality disabled via command-line flag (--no-reply).")
        else:
            print("Auto reply functionality is not enabled in config.")
        
        # Optionally, if auto reply is disabled, you could still extract comments
        # from the page using BSoup and write them to CSV here.
        # For brevity, that logic is omitted.
    
    # Continue with any other scraping or final steps if needed
    end = time()  # Finishing Time
    time_spent = end - start  # Time taken by script

    print(
        "%d linkedin post comments scraped in: %.2f minutes (%d seconds)"
        % (len(processed_comments), ((time_spent) / 60), (time_spent))
    )
except Exception as e:
    print(f"Error: {str(e)}")
    driver.save_screenshot("error.png")
finally:
    driver.quit()
    csvfile.close()
