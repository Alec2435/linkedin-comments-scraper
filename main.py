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
    write_data2csv,
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
    help="Safe page source for debugging",
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


args = parser.parse_args()

now = datetime.now()
unique_suffix = now.strftime("-%m-%d-%Y--%H-%M")

with open(
    "config.json",
) as f:
    Config: dict[str, str] = json.load(f)

COOKIES_DIR = Path("cookies")
COOKIES_FILE = COOKIES_DIR / "linkedin_cookies.pkl"

COOKIES_DIR.mkdir(exist_ok=True)

post_url = check_post_url(Config["post_url"])

##### Writer csv
writer = csv.writer(
    open(
        Config["filename"] + unique_suffix + ".csv",
        "w",
        encoding="utf-8",
    )
)
writer.writerow(["Name", "Headline", "Profile Picture", "Email", "Comment"])

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
        print(cookies)
        for cookie in cookies:
            print(cookie)
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
        ending_in = two_step_header.text.lower().split("ending in")[1].strip()
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

    # wait for 1 second
    sleep(4)

    # change to most recent comment sort
    sort_button = driver.find_element(By.CSS_SELECTOR, "button.comments-sort-order-toggle__trigger")
    sort_button.click()

    # wait for 1 second
    sleep(1)

    # # find the most recent comment sort option
    most_recent_option = driver.find_element(By.CSS_SELECTOR, '[aria-label="Most recent. See all comments, the most recent comments are first"]')
    most_recent_option.click()

    # input("Press Switch to most recent to continue...")

    # print("Loading comments :", end=" ", flush=True)
    # load_more("comments", Config["load_comments_class"], driver)
    if args.show_replies:
        print("Loading replies :", end=" ", flush=True)
        load_more("replies", Config["load_replies_class"], driver)
    # comments = driver.find_elements(By.XPATH, '//span[@class="ember-view"]')
    # this is bad because in case of comments with mentions or tags, it doesnt work
    # comments = driver.find_elements(By.CLASS_NAME, Config["comment_class"])
    # # print(comments)
    # comments = [comment.text.strip() for comment in comments]

    # headlines = driver.find_elements(By.CLASS_NAME, Config["headline_class"])
    # headlines = [headline.text.strip() for headline in headlines]

    # emails = extract_emails(comments)

    # names = driver.find_elements(By.CLASS_NAME, Config["name_class"])
    # names = [name.text.split("\n")[0] for name in names]

    # avatars = driver.find_elements(By.CLASS_NAME, Config["avatar_class"])
    # avatars = [
    #     avatar.find_element(By.TAG_NAME, "img").get_attribute("src") for avatar in avatars
    # ]

    # safe full page source to file, for post-download processing
    if args.save_page_source:
        with open("page_source.html", "w", encoding='utf-8') as f:
            f.write(driver.page_source)

    bs_obj = BSoup(driver.page_source, "html.parser")

    comments = bs_obj.find_all("span", {"class": Config["comment_class"]})
    print(f"Found {len(comments)} comments")
    comments = [comment.get_text(strip=True) for comment in comments]

    headlines = bs_obj.find_all("span", {"class": Config["headline_class"]})
    headlines = [headline.get_text(strip=True) for headline in headlines]

    emails = extract_emails(comments)

    names = bs_obj.find_all("span", {"class": Config["name_class"]})
    names = [name.get_text(strip=True).split("\n")[0] for name in names]

    BASE_URL = "https://www.linkedin.com/"

    profile_links_set = bs_obj.find_all("a", {"class": Config["avatar_class"]})
    profile_links = [
        urljoin(BASE_URL, profile_link["href"]) for profile_link in profile_links_set
    ]

    avatars = []
    for a in profile_links_set:
        img_link = ""
        try:
            img_link = a.find("img")["src"]
        except:
            pass

        avatars.append(img_link)

    # DEBUGGING
    # DEBUG_LENGTH = 10
    # print(names[:DEBUG_LENGTH])
    # print(profile_links[:DEBUG_LENGTH])
    # print(avatars[:DEBUG_LENGTH])
    # print(headlines[:DEBUG_LENGTH])
    # print(emails[:DEBUG_LENGTH])
    # print(comments[:DEBUG_LENGTH])

    write_data2csv(writer, names, profile_links, avatars, headlines, emails, comments)

    if args.download_avatars:
        download_avatars(avatars, names, Config["dirname"] + unique_suffix)

    # Auto-reply functionality
    if Config.get("auto_reply", {}).get("enabled", False):
        print("\nProcessing auto-replies...")
        selectors = Config["auto_reply"]["selectors"]
        delays = Config["auto_reply"]["delays"]
        
        processed_comments = set()  # Keep track of processed comments
        
        while True:
            # Find all currently visible top-level comments
            comments_section = driver.find_elements(By.CLASS_NAME, selectors["comment_container"])
            current_batch = [c for c in comments_section if c.id not in processed_comments]
            
            if not current_batch:
                print("No new comments to process")
                
                # Try to load more comments
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
                            break  # Success, exit retry loop
                        else:
                            print("No more comments to load")
                            should_continue = False
                            break
                    except:
                        retries += 1
                        if retries < max_retries:
                            print(f"Failed to load more comments. Retry {retries}/{max_retries} after 10 seconds...")
                            sleep(10)
                            continue
                        else:
                            print("Finished processing all comments after maximum retries")
                            should_continue = False
                            break
                
                if not should_continue:
                    break  # Break from parent loop when we're done loading comments
            
            print(f"Processing batch of {len(current_batch)} comments")
            
            for comment_article in current_batch:
                try:
                    # Skip if already processed
                    if comment_article.id in processed_comments:
                        continue
                    
                    # Skip if this is a reply
                    try:
                        if comment_article.find_element(By.CLASS_NAME, "comments-comment-entity--reply"):
                            processed_comments.add(comment_article.id)
                            continue
                    except:
                        pass
                    
                    # Get the comment text
                    comment_text = comment_article.find_element(By.CLASS_NAME, Config["comment_class"])
                    if not comment_text:
                        processed_comments.add(comment_article.id)
                        continue
                        
                    comment_text = comment_text.text.strip().lower()
                    print(f"Processing comment: {comment_text[:50]}...")
                    
                    # Check if comment contains trigger string
                    if Config["auto_reply"]["trigger_string"].lower() in comment_text:
                        # Check for existing replies
                        replies_list = comment_article.find_elements(By.CLASS_NAME, selectors["reply_container"])
                        replies_count = comment_article.find_elements(By.CLASS_NAME, selectors["replies_count"])
                        
                        if not replies_list or len(replies_list) == 0 or (replies_count and len(replies_count) > 0 and "0" in replies_count[0].text):
                            print(f"Found comment with trigger string and no replies: {comment_text[:50]}...")
                            
                            # Rest of the reply logic remains the same
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
                    # Still mark as processed to avoid infinite loops
                    processed_comments.add(comment_article.id)
                    continue

    # Continue with existing scraping logic
    bs_obj = BSoup(driver.page_source, "html.parser")

    end = time()  # Finishing Time
    time_spent = end - start  # Time taken by script

    print(
        "%d linkedin post comments scraped in: %.2f minutes (%d seconds)"
        % (len(names), ((time_spent) / 60), (time_spent))
    )
except Exception as e:
    print(f"Error: {str(e)}")
    # save a screenshot of the error
    driver.save_screenshot("error.png")
finally:
    driver.quit()
