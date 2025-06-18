from __future__ import annotations

import json
import csv
import logging
import os
import random
import re
import time
from datetime import datetime, timedelta
import getpass
from pathlib import Path
import requests

import pandas as pd
import pyautogui
import yaml
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from selenium.webdriver.chrome.service import Service as ChromeService
import webdriver_manager.chrome as ChromeDriverManager
ChromeDriverManager = ChromeDriverManager.ChromeDriverManager


log = logging.getLogger(__name__)


def setupLogger() -> None:
    dt: str = datetime.strftime(datetime.now(), "%m_%d_%y %H_%M_%S ")

    if not os.path.isdir('./logs'):
        os.mkdir('./logs')

    # TODO need to check if there is a log dir available or not
    logging.basicConfig(filename=('./logs/' + str(dt) + 'applyJobs.log'), filemode='w',
                        format='%(asctime)s::%(name)s::%(levelname)s::%(message)s', datefmt='./logs/%d-%b-%y %H:%M:%S')
    log.setLevel(logging.DEBUG)
    c_handler = logging.StreamHandler()
    c_handler.setLevel(logging.DEBUG)
    c_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%H:%M:%S')
    c_handler.setFormatter(c_format)
    log.addHandler(c_handler)


class EasyApplyBot:
    setupLogger()
    # MAX_SEARCH_TIME is 10 hours by default, feel free to modify it
    MAX_SEARCH_TIME = 60 * 60

    def __init__(self,
                 username,
                 password,
                 phone_number,
                 # profile_path,
                 salary,
                 rate,
                 uploads={},
                 filename='output.csv',
                 blacklist=[
                     'Senior',
                     'Java',
                     'Oracle',
                     'Scientist',
                 ],
                 blackListTitles=[
                    r"senior",  # will match any case
                    r"oracle\b",  # will match "oracle" but not "oracle's"
                    r"scientist\b",
                    r"\bpromoted\b",
                    r"hiring\s*immediately",  # handles variations
                    r"urgently\s*hiring",
                    r"0\s*experience\s*required", 
                 ],
                 experience_level=[]
                 ) -> None:

        log.info("Welcome to Easy Apply Bot")
        dirpath: str = os.getcwd()
        log.info("current directory is : " + dirpath)
        log.info("Please wait while we prepare the bot for you")
        if experience_level:
            experience_levels = {
                1: "Entry level",
                2: "Associate",
                3: "Mid-Senior level",
                4: "Director",
                5: "Executive",
                6: "Internship"
            }
            applied_levels = [experience_levels[level] for level in experience_level]
            log.info("Applying for experience level roles: " + ", ".join(applied_levels))
        else:
            log.info("Applying for all experience levels")
        

        self.uploads = uploads
        self.salary = salary
        self.rate = rate
        # self.profile_path = profile_path
        past_ids: list | None = self.get_appliedIDs(filename)
        self.appliedJobIDs: list = past_ids if past_ids != None else []
        self.filename: str = filename
        self.options = self.browser_options()

        try:
            self.browser = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), 
                        options=self.options)
            self.wait = WebDriverWait(self.browser, 30)
        except Exception as e:
            log.error(f"Failed to initialize browser: {e}")
            raise
        
         # Attempt login
        if not self.start_linkedin(username, password):
            self.browser.save_screenshot("final_login_failure.png")
            self.browser.quit()
            raise Exception("Critical login failure - check screenshots")
    
        #self.browser = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=self.options)
        #self.wait = WebDriverWait(self.browser, 30)
        self.blacklist = blacklist
        self.blackListTitles = blackListTitles
        self.start_linkedin(username, password)
        self.phone_number = phone_number
        self.experience_level = experience_level


        self.locator = {
            "next": (By.CSS_SELECTOR, "button[aria-label='Continue to next step']"),
            "review": (By.CSS_SELECTOR, "button[aria-label='Review your application']"),
            "submit": (By.CSS_SELECTOR, "button[aria-label='Submit application']"),
            "error": (By.CLASS_NAME, "artdeco-inline-feedback__message"),
            "upload_resume": (By.XPATH, "//*[contains(@id, 'jobs-document-upload-file-input-upload-resume')]"),
            "upload_cv": (By.XPATH, "//*[contains(@id, 'jobs-document-upload-file-input-upload-cover-letter')]"),
            "follow": (By.CSS_SELECTOR, "label[for='follow-company-checkbox']"),
            "upload": (By.NAME, "file"),
            "search": (By.CLASS_NAME, "jobs-search-results-list"),
          #  "links": ("xpath", '//div[@data-job-id]'),
            "links" : (By.CSS_SELECTOR, 'div.job-card-container'),
            "fields": (By.CLASS_NAME, "jobs-easy-apply-form-section__grouping"),
            "radio_select": (By.CSS_SELECTOR, "input[type='radio']"), #need to append [value={}].format(answer)
            "multi_select": (By.XPATH, "//*[contains(@id, 'text-entity-list-form-component')]"),
            "text_select": (By.CLASS_NAME, "artdeco-text-input--input"),
            "2fa_oneClick": (By.ID, 'reset-password-submit-button'),
            "easy_apply_button": (By.XPATH, '//button[contains(@class, "jobs-apply-button")]'),
            "welcome_back_account": (By.XPATH, "//button[contains(@class, 'active-account')]"),
            "welcome_back_account": (By.XPATH, "//button[contains(@class, 'active-account')]"),
            "login_username": (By.ID, "username"),
            "login_password": (By.ID, "password"),
            "login_button": (By.XPATH, "//button[@type='submit' and contains(., 'Sign in')]"),

        }

        #initialize questions and answers file
        self.qa_file = Path("qa.csv")
        self.answers = {}

        #if qa file does not exist, create it
        if self.qa_file.is_file():
            df = pd.read_csv(self.qa_file)
            for index, row in df.iterrows():
                self.answers[row['Question']] = row['Answer']
        #if qa file does exist, load it
        else:
            df = pd.DataFrame(columns=["Question", "Answer"])
            df.to_csv(self.qa_file, index=False, encoding='utf-8')
        
         # Login with retry logic
        login_success = False
        for attempt in range(3):
            try:
                self.start_linkedin(username, password)
                if self.verify_login():
                    login_success = True
                    break
                else:
                    log.warning(f"Login verification failed (attempt {attempt + 1}/3)")
                    self.clear_browser_data()
                    time.sleep(5)
            except Exception as e:
                log.error(f"Login attempt {attempt + 1} failed: {e}")
                self.browser.save_screenshot(f"login_fail_attempt_{attempt + 1}.png")
                if attempt < 2:  # Don't sleep on last attempt
                    time.sleep(10)

        if not login_success:
            log.error("Failed to login after 3 attempts")
            self.browser.save_screenshot("final_login_failure.png")
            self.browser.quit()
            raise Exception("Login failed - please check screenshots and try manually")

        log.info("Login successful, bot is ready")

    def get_appliedIDs(self, filename) -> list | None:
        try:
            df = pd.read_csv(filename,
                             header=None,
                             names=['timestamp', 'jobID', 'job', 'company', 'attempted', 'result'],
                             lineterminator='\n',
                             encoding='utf-8')

            df['timestamp'] = pd.to_datetime(df['timestamp'], format="%Y-%m-%d %H:%M:%S")
            df = df[df['timestamp'] > (datetime.now() - timedelta(days=2))]
            jobIDs: list = list(df.jobID)
            log.info(f"{len(jobIDs)} jobIDs found")
            return jobIDs
        except Exception as e:
            log.info(str(e) + "   jobIDs could not be loaded from CSV {}".format(filename))
            return None

    def browser_options(self):
        options = webdriver.ChromeOptions()
        
        # Set up persistent profile to avoid "new device" emails
        profile_path = os.path.join(os.getcwd(), 'linkedin_profile')
        if not os.path.exists(profile_path):
            os.makedirs(profile_path)
        options.add_argument(f"user-data-dir={profile_path}")
        
        # Anti-detection settings
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # Standard options
        options.add_argument("--start-maximized")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument('--no-sandbox')
        options.add_argument("--disable-extensions")
        
        return options
        
        return options
    def verify_login(self, timeout=15) -> bool:
        """Verify successful login by checking for feed page or profile"""
        try:
            WebDriverWait(self.browser, timeout).until(
                lambda d: any(
                    url in d.current_url 
                    for url in ["feed", "in/", "two-step-verification"]
                )
            )
            return True
        except TimeoutException:
            log.error(f"Login verification timeout. Current URL: {self.browser.current_url}")
            self.browser.save_screenshot("login_verification_failed.png")
            return False
    
    def human_delay(self, min_sec=0.5, max_sec=2.0):
        """Random delay to mimic human behavior"""
        delay = random.uniform(min_sec, max_sec)
        time.sleep(delay)


    def clear_browser_data(self):
        """Clear all browser data to prevent session conflicts"""
        try:
            self.browser.delete_all_cookies()
            self.browser.execute_script("window.localStorage.clear();")
            self.browser.execute_script("window.sessionStorage.clear();")
            log.info("Browser data cleared successfully")
        except Exception as e:
            log.error(f"Failed to clear browser data: {e}")

    def start_linkedin(self, username, password, max_attempts=3) -> bool:
        for attempt in range(1, max_attempts + 1):
            try:
                log.info(f"Attempt {attempt}/{max_attempts}: Loading LinkedIn login page")
                self.browser.get("https://www.linkedin.com/login")
                
                # Check for "Welcome Back" account selection
                try:
                    account_buttons = WebDriverWait(self.browser, 5).until(
                        EC.presence_of_all_elements_located((By.XPATH, "//button[contains(@class, 'active-account')]"))
                    )
                    if account_buttons:
                        log.info("Found 'Welcome Back' account selection")
                        account_buttons[0].click()  # Click the first account
                        time.sleep(2)
                except TimeoutException:
                    pass  # No account selection page found
                
                # Wait for login form (with more flexible waiting)
                try:
                    login_form = WebDriverWait(self.browser, 10).until(
                        EC.presence_of_element_located((By.ID, "username"))
                    )
                except TimeoutException:
                    # Maybe already logged in?
                    if "feed" in self.browser.current_url:
                        log.info("Already logged in from previous session")
                        return True
                    raise
                
                # Fill credentials
                username_field = self.browser.find_element(By.ID, "username")
                password_field = self.browser.find_element(By.ID, "password")
                
                # Clear fields and type slowly
                username_field.clear()
                for char in username:
                    username_field.send_keys(char)
                    time.sleep(random.uniform(0.05, 0.2))
                    
                password_field.clear()
                for char in password:
                    password_field.send_keys(char)
                    time.sleep(random.uniform(0.05, 0.2))
                
                # Find and click login button
                login_button = WebDriverWait(self.browser, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[@type='submit' and contains(., 'Sign in')]"))
                )
                login_button.click()
                
                # Check for 2FA
                try:
                    WebDriverWait(self.browser, 5).until(
                        lambda d: "two-step-verification" in d.current_url
                    )
                    log.info("2FA required - please complete manually")
                    time.sleep(20)  # Give time to complete 2FA
                except TimeoutException:
                    pass
                
                # Verify successful login
                if self.verify_login():
                    log.info("Login successful")
                    return True
                    
            except Exception as e:
                log.error(f"Attempt {attempt} failed: {str(e)}")
                self.browser.save_screenshot(f"login_error_attempt_{attempt}.png")
                if attempt < max_attempts:
                    log.info("Clearing cookies and retrying...")
                    self.clear_browser_data()
                    time.sleep(5)
        
        log.error(f"Failed to login after {max_attempts} attempts")
        return False

    def fill_data(self) -> None:
        self.browser.set_window_size(1, 1)
        self.browser.set_window_position(2000, 2000)

    def start_apply(self, positions, locations, days_old=3, distance=8) -> None:
        start: float = time.time()
        self.fill_data()
        self.positions = positions
        self.locations = locations
        combos: list = []
        
        while len(combos) < len(positions) * len(locations):
            position = positions[random.randint(0, len(positions) - 1)]
            location = locations[random.randint(0, len(locations) - 1)]
            combo: tuple = (position, location)
            
            if combo not in combos:
                combos.append(combo)
                log.info(f"Applying to {position}: {location} (Posted in last {days_old} days, within {distance} km)")
                self.applications_loop(position, location, days_old, distance)
                
            if len(combos) > 500:
                break

    # self.finish_apply() --> this does seem to cause more harm than good, since it closes the browser which we usually don't want, other conditions will stop the loop and just break out

    def applications_loop(self, position, location, days_old=3, distance=8):
        count_application = 0
        count_job = 0
        jobs_per_page = 0
        start_time: float = time.time()
        consecutive_empty_pages = 0  # Track empty pages
        
        while time.time() - start_time < self.MAX_SEARCH_TIME and consecutive_empty_pages < 3:
            try:
                # Your existing code...
                
                if self.is_present(self.locator["links"]):
                    links = self.get_elements("links")
                    jobIDs = {}
                    seen_jobs = set()
                    
                    for link in links:
                        job_hash = hash(link.text)
                        if job_hash not in seen_jobs:
                            seen_jobs.add(job_hash)
                            if 'Applied' not in link.text:
                                job_title = link.text
                                if not self.is_blacklisted(job_title):
                                    jobID = link.get_attribute("data-job-id")
                                    if jobID and jobID != "search":
                                        jobIDs[jobID] = "To be processed"
                    
                    if jobIDs:
                        consecutive_empty_pages = 0  # Reset counter if jobs found
                        self.apply_loop(jobIDs)
                    else:
                        consecutive_empty_pages += 1
                        log.info(f"No new jobs found (empty page {consecutive_empty_pages}/3)")
                        
                    # Only increment page if we found jobs
                    if jobIDs:
                        self.browser, jobs_per_page = self.next_jobs_page(
                            position, location, jobs_per_page, 
                            experience_level=self.experience_level
                        )
                    else:
                        # Try refreshing current page instead of going to next
                        self.browser.refresh()
                        time.sleep(2)
                else:
                    consecutive_empty_pages += 1
                    log.info(f"No job links found (empty page {consecutive_empty_pages}/3)")
                    
                # Break if we've seen too many empty pages
                if consecutive_empty_pages >= 3:
                    log.info("Stopping search - too many consecutive empty pages")
                    break
                    
            except Exception as e:
                log.error(f"Error in applications_loop: {e}")
                consecutive_empty_pages += 1
    
    def get_job_title(self) -> str:
        """More robust job title extraction"""
        try:
            # Try multiple possible selectors for job title
            selectors = [
                ".jobs-unified-top-card__job-title",
                ".job-details-jobs-unified-top-card__job-title",
                "h1",  # Fallback to any h1
                ".t-24"  # LinkedIn often uses t-24 class for titles
            ]
            
            for selector in selectors:
                try:
                    title_element = self.wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    return title_element.text.strip()
                except:
                    continue
                    
            # Final fallback to browser title
            return self.browser.title.split('|')[0].strip()
            
        except Exception as e:
            log.error(f"Failed to extract job title: {str(e)}")
            return "Unknown Position"

    def is_blacklisted(self, title: str) -> bool:
        """More comprehensive blacklist checking"""
        if not title or title == "Unknown Position":
            return False
            
        title_lower = title.lower()
        patterns = [
            r'\bsenior\b',
            r'\bjava\b',
            r'\boracle\b',
            r'\bscientist\b',
            r'\bpromoted\b',
            r'hiring\s*(immediately|urgently)',
            r'0?\s*experience\s*required'
        ]
        
        return any(re.search(pattern, title_lower) for pattern in patterns)

    def apply_loop(self, jobIDs):
        for jobID in jobIDs:
            if jobIDs[jobID] == "To be processed":
                applied = self.apply_to_job(jobID)
                if applied:
                    log.info(f"Applied to {jobID}")
                else:
                    log.info(f"Failed to apply to {jobID}")
                jobIDs[jobID] == applied

    def apply_to_job(self, jobID):
        # #self.avoid_lock() # annoying

        # get job page
        self.get_job_page(jobID)

        # let page load
        time.sleep(1)

        # Check title against blacklist BEFORE proceeding
        title = self.get_job_title()
        if self.is_blacklisted(title):
            log.info(f'Skipping blacklisted job: {title}')
            self.write_to_file(False, jobID, title, False)
            return False

        # get easy apply button
        button = self.get_easy_apply_button()


        # word filter to skip positions not wanted
        if button is not False:
            print("title: {}".format(self.browser.title))
          
            if self.is_blacklisted(self.browser.title):
                log.info('skipping this application, a blacklisted keyword was found in the job position')
                string_easy = "* Contains blacklisted keyword"
                result = False
            else:
                string_easy = "* has Easy Apply Button"
                log.info("Clicking the EASY apply button")
                time.sleep(10)
                button.click()
                clicked = True
                time.sleep(1)
                self.fill_out_fields()
                result: bool = self.send_resume()
                if result:
                    string_easy = "*Applied: Sent Resume"
                else:
                    string_easy = "*Did not apply: Failed to send Resume"
        elif "You applied on" in self.browser.page_source:
            log.info("You have already applied to this position.")
            string_easy = "* Already Applied"
            result = False
        else:
            log.info("The Easy apply button does not exist.")
            string_easy = "* Doesn't have Easy Apply Button"
            result = False


        # position_number: str = str(count_job + jobs_per_page)
        log.info(f"\nPosition {jobID}:\n {self.browser.title} \n {string_easy} \n")

        self.write_to_file(button, jobID, self.browser.title, result)
        return result

    def write_to_file(self, button, jobID, browserTitle, result) -> None:
        def re_extract(text, pattern):
            target = re.search(pattern, text)
            if target:
                target = target.group(1)
            return target

        timestamp: str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        attempted: bool = False if button == False else True
        job = re_extract(browserTitle.split(' | ')[0], r"\(?\d?\)?\s?(\w.*)")
        company = re_extract(browserTitle.split(' | ')[1], r"(\w.*)")

        toWrite: list = [timestamp, jobID, job, company, attempted, result]
        with open(self.filename, 'a+') as f:
            writer = csv.writer(f)
            writer.writerow(toWrite)

    def get_job_page(self, jobID):

        job_url = f'https://www.linkedin.com/jobs/view/{jobID}'
        self.browser.get(job_url)
        
        # Verify page loaded properly
        try:
            self.wait.until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )
            self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".jobs-unified-top-card"))
            )
        except TimeoutException:
            log.error("Job page failed to load properly")
            return False
            
        return self.load_page(sleep=0.5)

    def get_easy_apply_button(self):
        EasyApplyButton = False
        try:
            buttons = self.get_elements("easy_apply_button")
            # buttons = self.browser.find_elements("xpath",
            #     '//button[contains(@class, "jobs-apply-button")]'
            # )
            for button in buttons:
                if "Easy Apply" in button.text:
                    EasyApplyButton = button
                    self.wait.until(EC.element_to_be_clickable(EasyApplyButton))
                else:
                    log.debug("Easy Apply button not found")
            
        except Exception as e: 
            print("Exception:",e)
            log.debug("Easy Apply button not found")


        return EasyApplyButton

    def fill_out_fields(self):
        fields = self.browser.find_elements(By.CLASS_NAME, "jobs-easy-apply-form-section__grouping")
        for field in fields:

            if "Mobile phone number" in field.text:
                field_input = field.find_element(By.TAG_NAME, "input")
                field_input.clear()
                field_input.send_keys(self.phone_number)


        return


    def get_elements(self, type) -> list:
        elements = []
        element = self.locator[type]
        if self.is_present(element):
            elements = self.browser.find_elements(element[0], element[1])
        return elements

    def is_present(self, locator):
        return len(self.browser.find_elements(locator[0],
                                              locator[1])) > 0

    def send_resume(self) -> bool:
        # Check if resume is configured
        if "resumes" not in self.uploads or not self.uploads["resumes"]:
            log.error("No resumes configured in uploads")
            return False
        
        # Default to first resume
        selected_resume = self.uploads["resumes"][-1]["path"]

        #def is_present(button_locator) -> bool:
        #    return len(self.browser.find_elements(*button_locator)) > 0

        try:
            # Get job title for resume selection
            job_title = self.get_job_title().lower()
            
            for resume in self.uploads["resumes"]:
                if any(keyword.lower() in job_title for keyword in resume["keywords"]):
                    selected_resume = resume["path"]
                    log.info(f"Selected resume: {resume['name']}")
                    break
        
        except Exception as e:
            log.warning(f"Could not select resume by keywords: {e}") 

        # Verify resume exists
        if not os.path.exists(selected_resume):
            log.error(f"Resume file not found: {selected_resume}")
            return False 

           

        # Locators
        next_locator = (By.CSS_SELECTOR, "button[aria-label='Continue to next step']")
        review_locator = (By.CSS_SELECTOR, "button[aria-label='Review your application']")
        submit_locator = (By.CSS_SELECTOR, "button[aria-label='Submit application']")
        error_locator = (By.CLASS_NAME, "artdeco-inline-feedback__message")
        upload_resume_locator = (By.XPATH, '//span[text()="Upload resume"]')
        upload_cv_locator = (By.XPATH, '//span[text()="Upload cover letter"]')
        follow_locator = (By.CSS_SELECTOR, "label[for='follow-company-checkbox']")

        submitted = False
        loop = 0
        while loop < 2:
            time.sleep(1)
            
            # Upload resume
            if is_present(upload_resume_locator):
                try:
                    # More reliable way to find upload element
                    upload_element = self.wait.until(
                        EC.presence_of_element_located(
                            (By.XPATH, "//input[@type='file' and contains(@id,'resume')]")
                        )
                    )
                    upload_element.send_keys(self.uploads["Resume"])
                    time.sleep(2)  # Wait for upload to complete
                    
                    # Verify upload succeeded
                    if "Error" in self.browser.page_source:
                        log.error("Resume upload failed")
                        return False
                except Exception as e:
                    log.error(f"Resume upload failed: {e}")
                    log.debug(f"Resume: {selected_resume}")

            # Upload cover letter if available
            if is_present(upload_cv_locator) and "cover_letter" in self.uploads:
                try:
                    cv_locator = self.browser.find_element(
                        By.XPATH, 
                        "//*[contains(@id, 'jobs-document-upload-file-input-upload-cover-letter')]"
                    )
                    cv_locator.send_keys(self.uploads["Cover Letter"])
                except Exception as e:
                    log.error(f"Cover letter upload failed: {e}")

            # Handle follow checkbox if present
            elif len(self.get_elements("follow")) > 0:
                elements = self.get_elements("follow")
                for element in elements:
                    button = self.wait.until(EC.element_to_be_clickable(element))
                    button.click()

            # Submit application if possible
            if len(self.get_elements("submit")) > 0:
                elements = self.get_elements("submit")
                for element in elements:
                    button = self.wait.until(EC.element_to_be_clickable(element))
                    button.click()
                    log.info("Application Submitted")
                    submitted = True
                    break

            # Handle errors or additional questions
            elif len(self.get_elements("error")) > 0:
                elements = self.get_elements("error")
                if "application was sent" in self.browser.page_source:
                    log.info("Application Submitted")
                    submitted = True
                    break
                elif len(elements) > 0:
                    while len(elements) > 0:
                        log.info("Please answer the questions, waiting 5 seconds...")
                        time.sleep(5)
                        elements = self.get_elements("error")

                        for element in elements:
                            self.process_questions()

                        if "application was sent" in self.browser.page_source:
                            log.info("Application Submitted")
                            submitted = True
                            break
                        elif is_present(self.locator["easy_apply_button"]):
                            log.info("Skipping application")
                            submitted = False
                            break
                    continue

                else:
                    log.info("Application not submitted")
                    time.sleep(2)
                    break

            # Continue through application steps
            elif len(self.get_elements("next")) > 0:
                elements = self.get_elements("next")
                for element in elements:
                    button = self.wait.until(EC.element_to_be_clickable(element))
                    button.click()

            elif len(self.get_elements("review")) > 0:
                elements = self.get_elements("review")
                for element in elements:
                    button = self.wait.until(EC.element_to_be_clickable(element))
                    button.click()

            elif len(self.get_elements("follow")) > 0:
                elements = self.get_elements("follow")
                for element in elements:
                    button = self.wait.until(EC.element_to_be_clickable(element))
                    button.click()

            loop += 1

   

        return submitted
        
    def process_questions(self):
        time.sleep(1)
        form = self.get_elements("fields") #self.browser.find_elements(By.CLASS_NAME, "jobs-easy-apply-form-section__grouping")
        for field in form:
            question = field.text
            answer = self.ans_question(question.lower())
            #radio button
            if self.is_present(self.locator["radio_select"]):
                try:
                    input = field.find_element(By.CSS_SELECTOR, "input[type='radio'][value={}]".format(answer))
                    input.execute_script("arguments[0].click();", input)
                except Exception as e:
                    log.error(e)
                    continue
            #multi select
            elif self.is_present(self.locator["multi_select"]):
                try:
                    input = field.find_element(self.locator["multi_select"])
                    input.send_keys(answer)
                except Exception as e:
                    log.error(e)
                    continue
            # text box
            elif self.is_present(self.locator["text_select"]):
                try:
                    input = field.find_element(self.locator["text_select"])
                    input.send_keys(answer)
                except Exception as e:
                    log.error(e)
                    continue

            elif self.is_present(self.locator["text_select"]):
               pass

            if "Yes" or "No" in answer: #radio button
                try: #debug this
                    input = form.find_element(By.CSS_SELECTOR, "input[type='radio'][value={}]".format(answer))
                    form.execute_script("arguments[0].click();", input)
                except:
                    pass


            else:
                input = form.find_element(By.CLASS_NAME, "artdeco-text-input--input")
                input.send_keys(answer)

    def ans_question(self, question): #refactor this to an ans.yaml file
        answer = None
        if "how many" in question:
            answer = "1"
        elif "experience" in question:
            answer = "1"
        elif "sponsor" in question:
            answer = "No"
        elif "visa" in question:
            answer = "No"
        elif 'do you ' in question:
            answer = "Yes"
        elif "have you " in question:
            answer = "Yes"
        elif "US citizen" in question:
            answer = "Yes"
        elif "are you " in question:
            answer = "Yes"
        elif "salary" in question:
            answer = self.salary
        elif "can you" in question:
            answer = "Yes"
        elif "gender" in question:
            answer = "Male"
        elif "race" in question:
            answer = "Wish not to answer"
        elif "lgbtq" in question:
            answer = "Wish not to answer"
        elif "ethnicity" in question:
            answer = "Wish not to answer"
        elif "nationality" in question:
            answer = "Wish not to answer"
        elif "government" in question:
            answer = "I do not wish to self-identify"
        elif "are you legally" in question:
            answer = "Yes"
        else:
            log.info("Not able to answer question automatically. Please provide answer")
            #open file and document unanswerable questions, appending to it
            answer = "user provided"
            time.sleep(15)

            # df = pd.DataFrame(self.answers, index=[0])
            # df.to_csv(self.qa_file, encoding="utf-8")
        log.info("Answering question: " + question + " with answer: " + answer)

        # Append question and answer to the CSV
        if question not in self.answers:
            self.answers[question] = answer
            # Append a new question-answer pair to the CSV file
            new_data = pd.DataFrame({"Question": [question], "Answer": [answer]})
            new_data.to_csv(self.qa_file, mode='a', header=False, index=False, encoding='utf-8')
            log.info(f"Appended to QA file: '{question}' with answer: '{answer}'.")

        return answer

    def load_page(self, sleep=1):
        scroll_page = 0
        while scroll_page < 4000:
            self.browser.execute_script("window.scrollTo(0," + str(scroll_page) + " );")
            scroll_page += 500
            time.sleep(sleep)

        if sleep != 1:
            self.browser.execute_script("window.scrollTo(0,0);")
            time.sleep(sleep)

        page = BeautifulSoup(self.browser.page_source, "lxml")
        return page

    def avoid_lock(self) -> None:
        x, _ = pyautogui.position()
        pyautogui.moveTo(x + 200, pyautogui.position().y, duration=1.0)
        pyautogui.moveTo(x, pyautogui.position().y, duration=0.5)
        pyautogui.keyDown('ctrl')
        pyautogui.press('esc')
        pyautogui.keyUp('ctrl')
        time.sleep(0.5)
        pyautogui.press('esc')

    def next_jobs_page(self, position, location, jobs_per_page, experience_level=[], days_old=3, distance=8):
        """Constructs the URL with proper filters for job search"""
        try:
            # URL encode the position and location
            position_encoded = requests.utils.quote(position)
            
            # Handle special location cases
            #if "remote" in location.lower():
            #    location_param = "&f_WT=2"  # Remote filter
            #else:
            location_encoded = requests.utils.quote(location)
            location_param = f"&location={location_encoded}"
            
            # Base URL
            url = "https://www.linkedin.com/jobs/search/?"
            
            # Add keywords
            url += f"keywords={position_encoded}"
            # Add location
            url += location_param
            #print(f'current url: {url} ')
            # Add pagination
            url += f"&start={jobs_per_page}"
            
            # Add date filter (r259200 means last 3 days in seconds)
            if days_old:
                seconds = days_old * 86400
                url += f"&f_TPR=r{seconds}"
            
            # Add distance filter (only for non-remote locations)
            if distance and "remote" not in location.lower():
                url += f"&distance={distance}"
            
            # Add Easy Apply filter
            url += "&f_AL=true"
            
            # Add experience level filters if specified
            if experience_level:
                url += f"&f_E={','.join(map(str, experience_level))}"
            
            # Add job type filter (Full-time)
            url += "&f_JT=F"
            
            log.info(f"Loading jobs page with URL: {url}")
            
            self.browser.get(url)
            self.load_page()
            
            return (self.browser, jobs_per_page + 25)
        except Exception as e:
            log.error(f"Error in next_jobs_page: {e}")
            return (self.browser, jobs_per_page)


if __name__ == '__main__':

    with open("config.yaml", 'r') as stream:
        try:
            parameters = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            raise exc

    assert len(parameters['positions']) > 0
    assert len(parameters['locations']) > 0
    assert parameters['username'] is not None
    assert parameters['password'] is not None
    assert parameters['phone_number'] is not None


    if 'uploads' in parameters.keys() and type(parameters['uploads']) == list:
        raise Exception("uploads read from the config file appear to be in list format" +
                        " while should be dict. Try removing '-' from line containing" +
                        " filename & path")

    log.info({k: parameters[k] for k in parameters.keys() if k not in ['username', 'password']})

    output_filename: list = [f for f in parameters.get('output_filename', ['output.csv']) if f is not None]
    output_filename: list = output_filename[0] if len(output_filename) > 0 else 'output.csv'
    blacklist = parameters.get('blacklist', [])
    blackListTitles = parameters.get('blackListTitles', [])

    uploads = {} if parameters.get('uploads', {}) is None else parameters.get('uploads', {})
    for key in uploads.keys():
        assert uploads[key] is not None

    locations: list = [l for l in parameters['locations'] if l is not None]
    positions: list = [p for p in parameters['positions'] if p is not None]
    # Get filters from config or use defaults
    days_old = parameters.get('days_old', 3)
    distance = parameters.get('distance', 8)

    bot = EasyApplyBot(parameters['username'],
                       parameters['password'],
                       parameters['phone_number'],
                       parameters['salary'],
                       parameters['rate'], 
                       uploads=uploads,
                       filename=output_filename,
                       blacklist=blacklist,
                       blackListTitles=blackListTitles,
                       experience_level=parameters.get('experience_level', [])
                       )
    bot.start_apply(positions, locations)


