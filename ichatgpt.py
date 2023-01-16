import textwrap
import time
import os, sys, subprocess, threading, psutil
import re
import json
import math
import numpy as np
from ast import literal_eval
from difflib import SequenceMatcher
from pprint import pprint
import nltk
import shlex
from queue import Queue


from prompt_toolkit import prompt, PromptSession, ANSI
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.validation import Validator, ValidationError
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.completion import NestedCompleter

#import seleniumwire.undetected_chromedriver as uc
import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException


from pygments import highlight
from pygments.lexers import PythonLexer
from pygments.formatters import TerminalFormatter

from bs4 import BeautifulSoup
import html2text


# Some global variables to carry data across resets
last_flag_update = float('inf')
working_code = ''
completing_code = False
user_killed = False
safe_continue = False
cookies = []
conversation_id = ''
session_history = InMemoryHistory()

# Constant global variables
chatgpt_streaming = (By.CLASS_NAME, 'result-streaming')
chatgpt_chat_selects_list_first_node = (
    By.XPATH,
    '//div[substring(@class, string-length(@class) - string-length("text-sm") + 1)  = "text-sm"]//a',
)
chatgpt_chat_selects_list = (
    By.XPATH,
    '//div[substring(@class, string-length(@class) - string-length("text-sm") + 1)  = "text-sm"]//a'
)
chatgpt_big_response = (By.XPATH, '//div[@class="flex-1 overflow-hidden"]//div[p]')
chatgpt_small_response = (
    By.XPATH,
    '//div[starts-with(@class, "markdown prose w-full break-words")]',
)
chatgpt_textbox = (By.CSS_SELECTOR, "textarea.m-0")
chatgpt_regen_response = (By.XPATH, "//button[contains(text(), 'Regenerate response')]")
chatgpt_stop_response = (By.XPATH, "//button[contains(text(), 'Stop generating')]")
chatgpt_last_message_edit = (By.CSS_SELECTOR, "button.p-1.rounded-md")
chatgpt_save_and_submit = (By.XPATH, "//button[contains(text(), 'Save & Submit')]")
cloudflare_verify_button = (By.XPATH, '''//*[@id="cf-stage"]/div[6]/label/span''')


# Specific noad by number
#def chatgpt_chat_selects_list_node(i):
#    return (
#        By.XPATH,
#        str(f'//div[substring(@class, string-length(@class) - string-length("text-sm") + {i})  = "text-sm"]//a'),
#    )

cookies_dict = {}
NUM_COOKIES = 3
for i in range(1,NUM_COOKIES+1):
    try:
        with open(f'cookie_{i}.json', 'r') as f:
            cookies_dict[str(i)] = json.load(f)
    except:
        pass

session_token = ''
if len(cookies_dict) > 0:
    while True:
        option = str(input("Select cookie_{i}.json: "))
        if option in cookies_dict.keys():
            cookies = cookies_dict[option]
            break
        else:
            print("Invalid cokkie selection.")
    
    # Unpack session token from cookies
    for cookie in cookies:
        if cookie['name'] == '__Secure-next-auth.session-token':
            session_token = cookie['value']
            break


# Custom Threaded web-driver
class WebDriverThread(threading.Thread):
    def __init__(self):
        super().__init__()
        self.platform = os.name
        self.user_data_dir = self._set_user_data_dir()
        self.session_token = ''
        self.driver = None
        self.cookies = globals()['cookies']
        self.session_token = globals()['session_token']
        self.command_queue = Queue()
        self.result_queue = Queue()
        self.url = 'https://chat.openai.com/chat/'
        self.conversation_id = globals()['conversation_id']
        self.working_url = self.url + self.conversation_id
        
    def run(self):
        self.create_driver()
        while True:
            command = self.command_queue.get()
            if command == "get":
                globals()['last_flag_update'] = time.time()
                url = self.command_queue.get()
                self.driver.get(url)
                self.result_queue.put("success")
                globals()['safe_continue'] = True
                globals()['last_flag_update'] = float('inf')
            elif command == 'find_elements':
                globals()['last_flag_update'] = time.time()
                src = self.command_queue.get()
                try:
                    elements = self.driver.find_elements(*src)
                except:
                    print('Elements not found...')
                    elements = None
                self.result_queue.put(elements)
                globals()['last_flag_update'] = float('inf')
            elif command == 'wait_until':
                globals()['last_flag_update'] = time.time()
                src = self.command_queue.get()
                timeout = self.command_queue.get()
                try:
                    button = WebDriverWait(self.driver, timeout).until(src)
                except:
                    button = None
                self.result_queue.put(button)
                globals()['last_flag_update'] = float('inf')
            elif command == 'actions':
                globals()['last_flag_update'] = time.time()
                # Hover over the button
                actions = ActionChains(self.driver)
                self.result_queue.put(actions)
                globals()['last_flag_update'] = float('inf')
            elif command == "quit":
                globals()['last_flag_update'] = time.time()
                self.driver.close()
                self.driver.quit()
                globals()['last_flag_update'] = float('inf')
                #kill_chrome()
                self.result_queue.put("success")
                sys.exit()
                
                return
            elif command == 'reset_driver':
                globals()['last_flag_update'] = time.time()
                self.driver.close()
                self.driver.quit()
                globals()['last_flag_update'] = float('inf')
                #kill_chrome()
                self.create_driver()
                self.result_queue.put("success")
                
            elif command == 'refresh':
                globals()['last_flag_update'] = time.time()
                self.driver.refresh()
                self.result_queue.put("success")
                globals()['last_flag_update'] = float('inf')
            elif command == 'get_conversation_id':
                globals()['last_flag_update'] = time.time()
                pattern = re.compile(
                    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
                )
                current_url = self.driver.current_url
                #id_matches = pattern.search(current_url)
                #if not id_matches:
                #    self.driver.refresh()
                #    try:
                #        button = WebDriverWait(self.driver, 5).until(
                #            EC.element_to_be_clickable(chatgpt_chat_selects_list_first_node)
                #        )
                #    except:
                #        button = None
                #    if button:
                #        button.click()
                id_matches = pattern.search(current_url)
                if id_matches:
                    self.conversation_id = id_matches.group()
                    globals()['conversation_id'] = self.conversation_id
                    self.working_url = 'https://chat.openai.com/chat/'+self.conversation_id
                    self.result_queue.put("success")
                else:
                    self.result_queue.put("failure")
                globals()['last_flag_update'] = float('inf')
            time.sleep(0.01)
    
    def create_driver(self):
        options = webdriver.ChromeOptions()
        #ptions.add_argument("--headless")
        options.add_argument("--disable-extensions")
        #options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        #options.add_argument("disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--disable-hang-monitor")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-sync")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--disable-plugins-discovery')
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(f"--user-data-dir={self.user_data_dir}")
        options.add_argument("--remote-debugging-port=13379")
        options.add_experimental_option("debuggerAddress", "0.0.0.0:13379")
        #options.binary_location = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
        globals()['last_flag_update'] = time.time()
        self.driver = uc.Chrome(use_subprocess=True, options=options)
        #self.driver.minimize_window()
        #self.driver.set_page_load_timeout(10)
        if self.session_token != '':
            self.driver.execute_cdp_cmd(
                'Network.setCookie',
                {
                    'domain': 'chat.openai.com',
                    'path': '/',
                    'name': '__Secure-next-auth.session-token',
                    'value': self.session_token,
                    'httpOnly': True,
                    'secure': True,
                },
            )
        self.driver.get(self.working_url)
        #globals()['last_flag_update'] = time.time()
        #verify_button = self.wait_until(
        #    EC.presence_of_element_located(cloudflare_verify_button), 3
        #)
        background_thread(self.verify)
        globals()['safe_continue'] = True
        globals()['last_flag_update'] = float('inf')
    # Background verification thread for clicking Cloudflare verify button
    def verify(self):
        try:
            verify_button = WebDriverWait(self.driver, 15).until(EC.presence_of_element_located(cloudflare_verify_button))
        except:
            verify_button = None
        if verify_button:
            verify_button.click()
    def get(self, url):
        self.command_queue.put("get")
        self.command_queue.put(url)
        return self.result_queue.get()
    def find_elements(self, src):
        self.command_queue.put('find_elements')
        self.command_queue.put(src)
        return self.result_queue.get()
    def wait_until(self, src, timeout=3):
        self.command_queue.put('wait_until')
        self.command_queue.put(src)
        self.command_queue.put(timeout)
        return self.result_queue.get()
    def actions(self):
        self.command_queue.put('actions')
        return self.result_queue.get()
    def quit(self):
        self.command_queue.put("quit")
        return self.result_queue.get()
    # Scrape the conversation id
    def get_conversation_id(self):
        self.command_queue.put('get_conversation_id')
        return self.result_queue.get()
    # Reset the driver
    def reset_driver(self):
        self.command_queue.put('reset_driver')
        return self.result_queue.get()
    def refresh(self):
        self.command_queue.put('refresh')
        return self.result_queue.get()
    # Set chrome user profile path
    def _set_user_data_dir(self):
        username = os.environ['USER']
        if self.platform == 'nt':
            # Windows
            return r"C:\Users\{username}\AppData\Local\Google\Chrome\User Data"
        else:
            # MacOS and Linux
            return f"/Users/{username}/Library/Application Support/Google/Chrome"


# iChatGPTBot Class
class iChatGPTBot:
    def __init__(self):
        # flags
        self.reloaded = False
        self.user_killed = globals()['user_killed']
        self.network_error = False
        self.stop_speech = False
        # web-related attributes
        self.response_text = ''
        self.desired_response = ''
        self.last_flag_update = float('inf')
        # session and platform information
        self.platform = os.name
        # code-related attributes
        self.current_code = globals()['working_code']
        self.code_set = set()
        self.last_line = None
        # commands
        self.commands = {}
        self.commands_list = []
        self.session_completer = None
        self.session = None
        
        #self.web_driver_thread = None
        self.web_driver_thread = WebDriverThread()
        
        
    # Help may be outdated, needs revision
    def _show_help(self):
        print("\n=========")
        print("Commands:")
        print("=========")
        print("\thelp        Prints this help page.")
        print("\tcode        Prints the current code.")
        print("\tclear       Clears the current code.")
        print("\trun         Runs the current code.")
        print("\tupload      Uploads the current code.")
        print("\tsave        Saves the current code.")
        print("\tchat [num]  Selects a chat by index.")
        print("\tstream      Streams the conversation.")
        print("\tstop        Stops the conversation.")
        print("\tquit        Exits the program.")
        print("\treload      Reloads the page.")
        print("")
    
    # Show the currently loaded code
    def _show_code(self):
        if not (self.current_code is None) and self.current_code.strip() != '':
            print("==============\n Code Section \n==============")
            print(highlight(self.current_code, PythonLexer(), TerminalFormatter()))
    # Reset the driver
    def _reset_driver(self):
        globals()['last_flag_update'] = time.time()
        kill_chrome()
        self.web_driver_thread.reset_driver()
        globals()['last_flag_update'] = float('inf')
    def _exit(self):
        globals()['last_flag_update'] = time.time()
        try:
            self.web_driver_thread.quit()
        except:
            pass
        sys.exit()
    # Regenerate the response
    def _regenerate_response(self):
        button_element_1 = self.web_driver_thread.wait_until(EC.presence_of_element_located(chatgpt_regen_response), 3)
        if not button_element_1 is None and not isinstance(button_element_1, str):
            globals()['last_flag_update'] = time.time()
            button_element_1.click()
            globals()['last_flag_update'] = float('inf')
            self.conversation()
        else:
            globals()['last_flag_update'] = time.time()
            button_element_2 = self.web_driver_thread.wait_until(EC.presence_of_element_located(chatgpt_last_message_edit), 3)
            if not button_element_2 is None and not isinstance(button_element_2, str):
                # Hover over the button
                actions = self.web_driver_thread.actions()
                globals()['last_flag_update'] = time.time()
                actions.move_to_element(button_element_2).perform()
                button_element_2.click()
                globals()['last_flag_update'] = float('inf')
                button_element_3 = self.web_driver_thread.wait_until(EC.presence_of_element_located(chatgpt_save_and_submit), 3)
                if not button_element_3 is None and not isinstance(button_element_3, str):
                    globals()['last_flag_update'] = time.time()
                    button_element_3.click()
                    globals()['last_flag_update'] = float('inf')
                    self.conversation()
    
    # Regenerate the response
    def _stop_response(self):
        still_streaming = self.web_driver_thread.wait_until(
            EC.presence_of_element_located(chatgpt_streaming), 5
        )
        if still_streaming:
            button_element = self.web_driver_thread.wait_until(
                EC.presence_of_element_located(chatgpt_stop_response), 25
            )
            if not button_element is None:
                globals()['last_flag_update'] = time.time()
                button_element.click()
                globals()['last_flag_update'] = float('inf')
    # Write then run the current code
    def _run_code(self):
        with open("test_code.py", "w") as f:
            f.write(self.current_code)
        result = subprocess.run(["python3", "test_code.py"], stderr=subprocess.PIPE)
        if result.returncode != 0:
            error_output = result.stderr.decode()
            if "KeyboardInterrupt" not in error_output:
                self.enter_message(f'Error: {repr(error_output)}')
                self.conversation()
    # upload code
    def _upload_code(self):
        
        # Prep bot for accepting code.
        self.enter_message("I have some code.")
        self._stop_response()
        
        with open("test_code.py", "r") as f:
            data = f.readlines()
        
        #print(data)
        num_chunks = int(len(data)/200)+1
        for i in range(num_chunks):
            code_block = data[i*200:min(len(data),(i+1)*200)]
            #print(code_block)
            #print(''.join(code_block))
            self.enter_message(repr(''.join(code_block)).strip("'"))
            #time.sleep(3)
            self._stop_response()
            print(f"Part {i+1} of {num_chunks} haas been uploaded!")
    
    # Write the current code
    def _save_code(self):
        with open("test_code.py", "w") as f:
            f.write(self.current_code)
    
    def _select_chat(self, node=None):
        while True:
            try:
                if not node:
                    node = int(prompt("Enter a chat number: "))
                self._refresh()
                while True:
                    buttons = self.web_driver_thread.wait_until(EC.presence_of_all_elements_located(chatgpt_chat_selects_list), 2)
                    if not buttons:
                        self._refresh()
                    else:
                        break
                if buttons:
                    try:
                        title = markdownify(buttons[int(node)].get_attribute('innerHTML'), False)[0].rstrip()
                        print("Selection:",title)
                    except:
                        continue
                    buttons[int(node)].click()
                    time.sleep(0.5)
                    while True:
                        buttons = self.web_driver_thread.wait_until(EC.presence_of_all_elements_located(chatgpt_chat_selects_list), 2)
                        if not buttons:
                            self._refresh()
                        else:
                            break
                    
                    break
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(e)
        time.sleep(1)
        #self._refresh()
    
    # Enter a message on the chat website
    def enter_message(self, message):
        # identify the text area, then send the message and submit it
        input_element = self.web_driver_thread.wait_until(
            EC.presence_of_element_located(chatgpt_textbox), 10
        )
        if input_element:
            input_element.send_keys(message)
            input_element.submit()
    # Speech message queue processor
    def speech_queue(self):
        stated_sentences = []
        punctuation = {'.', '?', '!'} 
        #punctuation = {'.', '?', '!', ':'} 
        
        while True:
            if self.response_text != '':
                all_sentences = [
                    i.strip() for i in nltk.sent_tokenize(self.response_text) if \
                    (i.strip() not in stated_sentences) and \
                    (i.strip()[-1] in punctuation or (len(i.strip())>1 and i.strip()[-1] == '"' and i.strip()[-2] in punctuation))
                ]
            else:
                all_sentences = []
            for sentence in all_sentences:
                clean_sentence = remove_formatting(sentence)
                if clean_sentence not in stated_sentences:
                    say(clean_sentence)
                    stated_sentences.append(clean_sentence)
                if self.stop_speech:
                    self.response_text = ''
                    self.stop_speech = False
                    break
            if self.stop_speech:
                self.response_text = ''
                self.stop_speech = False
            time.sleep(0.01)
    # For Hushing the bot.
    def _quiet(self):
        self.stop_speech = True
    def _refresh(self):
        self.web_driver_thread.refresh()
        #self.driver.refresh()
    # process the message by making calls to the chat website and reading them, then storing stuff properly.
    def conversation(self, command=''):
        #self.last_flag_update = time.time()
        
        use_color = (command == 'repeat')
        
        TIMEOUT = 60
        last_response_text = None
        response = None
        current_code = None
        self.response_text = ''
        #self.get_conversation_id()
        self.web_driver_thread.get_conversation_id()
        
        print("\n==========")
        print(" Response ")
        print("==========\n")
        
        
        # this loop continues until the desired_response is completed
        while True:
            #if (time.time() - globals()['last_flag_update']) > 15:
            #    raise TimeoutError
            
            #if not self.web_driver_thread.is_alive():
            #    raise TimeoutError
            
            time_in = time.time()
            #self.last_flag_update = time.time()
            if command != 'repeat':
                still_streaming = self.web_driver_thread.wait_until(
                    EC.presence_of_element_located(chatgpt_streaming), 3
                )
                if not still_streaming:
                    break
            
            # Wait until presence of the big response
            responses = self.web_driver_thread.wait_until(
                EC.presence_of_all_elements_located(chatgpt_big_response), 3
            )
            # if found, get the response.  if there is red text, somethings wrong.
            if responses:
                response = responses[-1]
                if 'text-red' in response.get_attribute('class'):
                    # Reset last flag update
                    return print('Response is an error.')
                    #raise ValueError(response.text)
            # Wait until the presence of the small response
            globals()['last_flag_update'] = time.time()
            try:
                self.web_driver_thread.wait_until(
                    EC.presence_of_element_located(chatgpt_small_response), 3
                )
                #WebDriverWait(self.driver, 3).until(
                #    EC.presence_of_element_located(chatgpt_small_response)
                #)
                responses = self.web_driver_thread.find_elements(chatgpt_small_response)
                if responses and len(responses) > 0:
                    response = responses[-1]
                    #response = self.driver.find_elements(*chatgpt_small_response)[-1]
                    if response and not isinstance(response, str) and 'text-red' in response.get_attribute('class'):
                        # Reset last flag update
                        return print('Response is an error.')
                        #raise ValueError(response.text)
                # Wait until the presence of the small response
            except Exception as e:
                print(e)
                # Reset last flag update
                return print("ChatGPT's response not found")
               #raise ValueError("ChatGPT's response not found")
            # If response has been modified
            if not (response is None):
                self.response_text, current_code = markdownify(response.get_attribute('innerHTML'), use_color=use_color)
                #self.response_text = self.response_text.rstrip()
                self.response_text = self.response_text.replace('`','{uncommon_strang}').rstrip().replace('{uncommon_strang}','`')#[:-2].rstrip().strip('`')
                # retreive network error status (might not works still with new markdownify stuff, needs testing)
                self.network_error = 'network error' in self.response_text
            # If time exceeds 20 seconds and there is no changes to the desired response, quit the driver/browser, then spawn a new one.
            if time.time()-time_in > TIMEOUT and not (last_response_text is None) and len(self.response_text) == len(last_response_text):
                #print('6')
                self.web_driver_thread.get(self.url)
                return print("Error, timeout after no new response. Refreshing page.")
                break
            # if last_response_text has been modified
            if not (last_response_text is None):
                new_text = self.response_text[len(last_response_text):]
            else:
                new_text = self.response_text
            
            if len(new_text) != 0:
                print(new_text, end='', flush=True)
                #globals()['last_flag_update'] = time.time()
            # update last response text to the lastest value
            last_response_text = self.response_text
            # this handles a weird error with 1 character not being printed.
            if len(last_response_text) == 1 and not last_response_text.isalpha(): 
                last_response_text = ''
            
            
            # if the command is a 'repeat' command, break early. message shoiuld be complete
            if command == 'repeat':
                break
            
            still_text_box = self.web_driver_thread.wait_until(EC.presence_of_element_located(chatgpt_textbox), 10)
            if not still_text_box:
                break
            
            time.sleep(0.2)
        
        print('\n')
        
        # Reset last flag update
        #globals()['last_flag_update'] = float('inf')
        # update current code
        if not (current_code is None) and current_code.strip() != '':
            self.current_code = textwrap.dedent(current_code).lstrip('\n')
            self.code_set.add(self.current_code)
        
    def handle_commands(self, user_input):
        """
        Handles user commands
        """
        
        
        split_lines = user_input.split(' ')
        line = split_lines[0].lower().strip()
        if line in self.commands:
            if len(split_lines) > 1 and line in ['chat']:
                self.commands[line](split_lines[1].strip())
            else:
                self.commands[line]()
        elif user_input.strip() != "":
            if user_input != 'repeat' and user_input != 'stream':
                self.enter_message(user_input)
            self.conversation(user_input)
            self._show_code()
        else:
            pass
        
        self.web_driver_thread.get_conversation_id()
        #TIMEOUT = 15
        #if (time.time() - globals()['last_flag_update']) > TIMEOUT:
        #    raise TimeoutError

    def handle_complete_command(self):
        """
        Handles complete command entered by the user
        """
        globals()['completing_code'] = True
        self.conversation('repeat')
        if self.current_code.strip() != '':
            globals()['working_code'] = merge_text(globals()['working_code'], self.current_code)
        while True:
            while True:
                if len(self.current_code.split()) > 0:
                    last_line = self.current_code.split()[-1]
                    self.enter_message(f"The most recent line you showed was '''{last_line}'''. Please say only 'yes' if this was the end; if not, give me the missing code continuing exactly from where you left off.")
                    self.conversation()
                    break
                else:
                    print('current code is empty')
                    self.enter_message(f"Then please give me the updated code. No explainations.")
                    self.conversation()
                #self.current_code = textwrap.dedent(self.current_code)
            if 'yes' in self.response_text.lower():
                with open("test_code.py", "w") as f:
                    f.write(globals()['working_code'])
                break

            globals()['working_code'] = merge_text(globals()['working_code'], self.current_code)
            self.current_code = globals()['working_code']
        globals()['completing_code'] = False
        self._show_code()
    
    def driver_persistence(self):
        TIMEOUT = 15
        BUFFER = 0.1
        while True:
            if (time.time() - globals()['last_flag_update']) > TIMEOUT:# or not is_chrome_running():
                print("WARNING: Driver has hit a timeout!")
                globals()['safe_continue'] = False
                #if is_chrome_running():
                kill_chrome(False)
                try:
                    self.web_driver_thread.quit()
                except:
                    pass
                #kill_chrome(False)
                self.web_driver_thread.join(timeout=0)
                self.web_driver_thread = WebDriverThread()
                self.web_driver_thread.start()
                self.web_driver_thread.get(self.web_driver_thread.working_url)
                time.sleep(BUFFER)
                self._refresh()
                globals()['last_flag_update'] = float('inf')
                self.reloaded = True
            time.sleep(BUFFER)
    
    # Persistence for URL grabboing
    def persistent_url(self):
        TIMEOUT = 15
        BUFFER = 0.5
        pattern = re.compile(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
        )
        
        while True:
            globals()['last_flag_update'] = time.time()
            try:
                current_url = self.web_driver_thread.current_url
            except:
                current_url = ''
            #id_matches = pattern.search(current_url)
            #if not id_matches:
            #    self.driver.refresh()
            #    try:
            #        nodes = WebDriverWait(self.driver, 5).until(
            #            EC.presence_of_all_elements_located(chatgpt_chat_selects_list)
            #        )
            #    except:
            #        nodes = None
            #    if nodes:
            #        button.click()
            id_matches = pattern.search(current_url)
            if id_matches:
                self.conversation_id = id_matches.group()
                globals()['conversation_id'] = self.conversation_id
                self.working_url = 'https://chat.openai.com/chat/'+self.conversation_id
            if (time.time() - globals()['last_flag_update']) > TIMEOUT:# or not is_chrome_running():
                break
            globals()['last_flag_update'] = float('inf')
            time.sleep(BUFFER)
    
    def run(self):
        """
        Main loop for the script. Handles user input and calls the appropriate functions.
        """
        # commands
        self.commands = {
            "run": self._run_code,
            'save': self._save_code,
            "help": self._show_help,
            "code": self._show_code,
            'upload': self._upload_code,
            "clear": clear,
            'quiet': self._quiet,
            "chat": self._select_chat,
            'regenerate': self._regenerate_response,
            'stop': self._stop_response,
            "refresh": self._refresh,
            "reset": self._reset_driver,
            "exit": self._exit,
            "complete": self.handle_complete_command
        }
        self.commands_list = list(self.commands.keys())
        self.session_completer = NestedCompleter.from_nested_dict(dict.fromkeys(self.commands_list,None))
        self.session = PromptSession(history=globals()['session_history'],completer=self.session_completer)
        
        # Start web driver thread
        self.web_driver_thread.start()
        # Start background helper functions
        background_thread(self.persistent_url)
        background_thread(self.driver_persistence)
        background_thread(self.speech_queue)
        
        while True:
            try:
                #globals()['last_flag_update'] = time.time()
                #self.web_driver_thread.get(self.web_driver_thread.working_url)
                #globals()['last_flag_update'] = float('inf')
                while True:
                    while not globals()['safe_continue']:
                        #print('not safe yet...')
                        time.sleep(1)
                    
                    #print('Sheezus')
                    if self.network_error:
                        self._regenerate_response()
                        self.network_error = False
                        #break
                    if self.reloaded and not self.user_killed:
                        user_input = "repeat"
                        self.reloaded = False
                    else:
                        if self.user_killed:
                            self.user_killed = False
                            globals()['user_killed'] = self.user_killed
                        user_input = self.session.prompt(ANSI(F.U+C.BD+"ChatGPT"+F.E+C.BD+" > "+F.E))
                    #self.last_flag_update = time.time()
                    self.handle_commands(user_input)
                    
                    #self.last_flag_update = float('inf')
            except KeyboardInterrupt:
                print("Kill thread request has been sent.")
                self.running_speech = True
                self.user_killed = True
                globals()['user_killed'] = self.user_killed
                self._reset_driver()
            except Exception as e:
                print(e)
                self._reset_driver()
                self.network_error = True

# Formatting, colors, symbols
class F:
    B='\033[1m'
    U='\033[4m'
    BL='\033[5m'
    E='\033[0m'
class C:
    H='\033[95m'
    F='\033[91m'
    OB='\033[94m'
    W='\033[93m'
    B_W='\u001b[37;1m'
    B_G='\u001b[38;5;42m'
    O='\u001b[38;5;208m'
    B_B='\033[34;1m'
    BD='\033[38;5;75m'
    R="\033[38;5;196m"
    B_R="\033[38;5;203m"
class S:
    A='\u21B3'
    V=f"{C.OB}[+]{F.E}"
    N=f"{C.W}[~]{F.E}"
    IV=f"{C.F}[-]{F.E}"
    R=f'  {C.B_R}{A}{F.E}'


### Text processing functions ###
# Custon html parsing
def markdownify(html, use_color):
    code_snippet = html.strip()
    soup = BeautifulSoup(code_snippet, 'html.parser')
    markdown = html2text.html2text(str(soup)).replace(
        'Copy code', '==============\n     Code Section \n    =============='
    )
    try:
        code_block = get_code_block(markdown)
    except:
        code_block = None
    if code_block and use_color:
        highlighted_code = highlight(code_block, PythonLexer(), TerminalFormatter())
        markdown = markdown.replace(code_block, highlighted_code)
        
    return markdown, code_block
# Strip formatting
def remove_formatting(text):
    clean_text = re.sub(r'\x1b[^m]*m', '', text)
    clean_text = re.sub(r'[^\x00-\x7F]+', '', clean_text)
    return clean_text


# Custom merging algorithm for combining code blocks (Needs final testing.)
def merge_text(s1, s2):
    m = len(s1)
    n = len(s2)
    # Create a table to store results of sub-problems
    L = [[0]*(n+1) for i in range(m+1)]
    # Build L[m+1][n+1] in bottom up fashion
    for i in range(m+1):
        for j in range(n+1):
            if i == 0 or j == 0 :
                L[i][j] = 0
            elif s1[i-1] == s2[j-1]:
                L[i][j] = L[i-1][j-1]+1
            else:
                L[i][j] = max(L[i-1][j], L[i][j-1])
    # find the LCS
    index = L[m][n]
    lcs = [""] * index
    i = m
    j = n
    while i > 0 and j > 0 :
        if s1[i-1] == s2[j-1]:
            lcs[index-1] = s1[i-1]
            i-=1
            j-=1
            index-=1
        elif L[i-1][j] > L[i][j-1]:
            i-=1
        else:
            j-=1
    if index==0:
        return s1 + s2
    else:
        # merge the two blocks of text
        merged_text = s1 + s2[len(lcs):]
        return merged_text

# For merging text
def merge_text2(s1, s2):
    if s1 == '':
        return s2
    # split strings into lines
    s1_lines = s1.splitlines()
    s2_lines = s2.splitlines()
    # join lines into a single string
    s1 = '\n'.join(s1_lines)
    s2 = '\n'.join(s2_lines)
    # find the longest common subsequence
    matcher = SequenceMatcher(None, s1, s2)
    match = matcher.find_longest_match(0, len(s1), 0, len(s2))
    # merge the two blocks of text
    merged_text = s1 + s2[match.size:]
    
    return merged_text


# For isolating the code block
def get_code_block(text):
    start_marker = "==============\n     Code Section \n    =============="
    if text.find(start_marker) == -1:
        return ''
    start_index = text.find(start_marker) + len(start_marker)
    end_index = text.rindex('\n', start_index)
    lines = text[start_index:end_index].split("\n")
    indent_regex = re.compile(r"^\s+")
    code_block = "\n".join(line for line in lines if re.match(indent_regex, line))
    return code_block

### Utility functions ###
def say(sentence):
    # if macos
    if sys.platform == 'darwin':
        escaped_sentence = shlex.quote(sentence)
        os.system(f'say {escaped_sentence}')

def completer(dictionary):
    return NestedCompleter.from_nested_dict(dictionary)

# For making object run in background
def background_thread(target, args_list=[]):
    args = ()
    for i in range(len(args_list)):
        args = args + (args_list[i],)
    pr = threading.Thread(target=target, args=args)
    pr.daemon = True
    pr.start()
    return pr

# Install and import
def ximport(pkg):
    import importlib
    try:
        globals()[pkg] = importlib.import_module(pkg)
    except:
        try:
            import pip
        except:
            print(f"This Python script requires pip for {pkg}.")
            if found_binary('apt'):
                os.system(f"sudo apt install -y python3-pip")
            elif found_binary('apt-get'):
                os.system(f"sudo apt-get install -y python3-pip")
            elif found_binary('yum'):
                os.system('yum install -y epel-release python-pip')
            elif found_binary('dnf'):
                os.system('dnf install -y python3')
            elif found_binary('pacman'):
                os.system('pacman -S --noconfirm python-pip')
            elif found_binary('zypper'):
                os.system("zypper install -y python3-pip")
            else:
                sys.exit()
        os.system(f"python3 -m pip install {pkg} --quiet")
        globals()[pkg] = importlib.import_module(pkg)
# Check if chrome is live
def is_chrome_running():
    for process in psutil.process_iter():
        try:
            if 'chrome' in process.name().strip().lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False
# Kill chrome
def kill_chrome(auto_clear=True):
    #while is_chrome_running():
    if sys.platform == 'win32':  # Windows
        subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'])
    elif sys.platform == 'darwin':  # MacOS
        subprocess.run(['pkill', '-9','Chrome'])
    elif sys.platform == 'linux': # Linux
        subprocess.run(['killall','-9','chrome'])
    if auto_clear:
        clear(); clear()
    time.sleep(2)
    if auto_clear:
        clear(); clear()
# Clear terminal window
def clear():
    if os.name == 'nt':
        os.system("cls")
    else:
        os.system("clear")

# Main script loop
def main():
    bot = iChatGPTBot()
    bot.run()

if __name__ == '__main__':
    main()
