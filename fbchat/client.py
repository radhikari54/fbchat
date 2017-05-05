# -*- coding: UTF-8 -*-

"""
    fbchat
    ~~~~~~

    Facebook Chat (Messenger) for Python

    :copyright: (c) 2015      by Taehoon Kim.
    :copyright: (c) 2015-2016 by PidgeyL.
    :license: BSD, see LICENSE for more details.
"""

import requests
import logging
from uuid import uuid1
import warnings
from random import choice
from datetime import datetime
from bs4 import BeautifulSoup as bs
from mimetypes import guess_type
from .utils import *
from .models import *
import time
from .event_hook import EventHook


# Python 3 does not have raw_input, whereas Python 2 has and it's more secure
try:
    input = raw_input
except NameError:
    pass

# URLs
LoginURL     ="https://m.facebook.com/login.php?login_attempt=1"
SearchURL    ="https://www.facebook.com/ajax/typeahead/search.php"
SendURL      ="https://www.facebook.com/messaging/send/"
ThreadsURL   ="https://www.facebook.com/ajax/mercury/threadlist_info.php"
ThreadSyncURL="https://www.facebook.com/ajax/mercury/thread_sync.php"
MessagesURL  ="https://www.facebook.com/ajax/mercury/thread_info.php"
ReadStatusURL="https://www.facebook.com/ajax/mercury/change_read_status.php"
DeliveredURL ="https://www.facebook.com/ajax/mercury/delivery_receipts.php"
MarkSeenURL  ="https://www.facebook.com/ajax/mercury/mark_seen.php"
BaseURL      ="https://www.facebook.com"
MobileURL    ="https://m.facebook.com/"
StickyURL    ="https://0-edge-chat.facebook.com/pull"
PingURL      ="https://0-channel-proxy-06-ash2.facebook.com/active_ping"
UploadURL    ="https://upload.facebook.com/ajax/mercury/upload.php"
UserInfoURL  ="https://www.facebook.com/chat/user_info/"
ConnectURL   ="https://www.facebook.com/ajax/add_friend/action.php?dpr=1"
RemoveUserURL="https://www.facebook.com/chat/remove_participants/"
LogoutURL    ="https://www.facebook.com/logout.php"
AllUsersURL  ="https://www.facebook.com/chat/user_info_all"
SaveDeviceURL="https://m.facebook.com/login/save-device/cancel/"
CheckpointURL="https://m.facebook.com/login/checkpoint/"
facebookEncoding = 'UTF-8'

# Log settings
log = logging.getLogger("client")


class Client(object):
    """A client for the Facebook Chat (Messenger).

    See http://github.com/carpedm20/fbchat for complete
    documentation for the API.
    """

    def __init__(self, email, password, debug=True, info_log=True, user_agent=None, max_retries=5, do_login=True):
        """A client for the Facebook Chat (Messenger).

        :param email: Facebook `email` or `id` or `phone number`
        :param password: Facebook account password

            import fbchat
            chat = fbchat.Client(email, password)
        """
        if do_login and not (email and password):
            raise Exception("Email and password not found.")

        self.is_def_recipient_set = False
        self.debug = debug
        self.sticky, self.pool = (None, None)
        self._session = requests.session()
        self.req_counter = 1
        self.seq = "0"
        self.payloadDefault={}
        self.client = 'mercury'
        self.listening = False
        self.GENDERS = {
            0: 'unknown',
            1: 'female_singular',
            2: 'male_singular',
            3: 'female_singular_guess',
            4: 'male_singular_guess',
            5: 'mixed',
            6: 'neuter_singular',
            7: 'unknown_singular',
            8: 'female_plural',
            9: 'male_plural',
            10: 'neuter_plural',
            11: 'unknown_plural',
        }

        # Setup event hooks
        self.onLoggingIn = EventHook()
        self.onLoggedIn = EventHook()

        self.onMessage = EventHook(mid=str, author_id=str, message=str, recipient_id=int, msg_type=MsgType, ts=str, metadata=dict)
        self.onColorChange = EventHook(mid=str, author_id=str, new_color=str, changed_for=str, msg_type=MsgType, ts=str)
        self.onTitleChange = EventHook(mid=str, author_id=str, new_title=str, changed_for=str, thread_id=str, ts=str)
        self.onTyping = EventHook(author_id=int, typing_status=TypingStatus)
        self.onSeen = EventHook(seen_by=str, thread_id=str, timestamp=str)

        self.onInbox = EventHook(unseen=int, unread=int, recent_unread=int)
        self.onPeopleAdded = EventHook(added_ids=list, author_id=str, thread_id=str)
        self.onPersonRemoved = EventHook(removed_id=str, author_id=str, thread_id=str)
        self.onFriendRequest = EventHook(from_id=str)

        # Setup event handlers
        self.onLoggingIn += lambda: log.info("Logging in...")
        self.onLoggedIn += lambda: log.info("Login successful.")
        self.onListening += lambda: log.info("Listening...")

        self.onMessage += lambda mid, author_id, message, recipient_id, msg_type, ts, metadata:\
            log.info("Message from %s: %s" % (author_id, message))
        self.onColorChange += lambda mid, author_id, new_color, changed_for, msg_type, ts:\
            log.info("%s changed color to %s" % (author_id, new_color))
        self.onTitleChange += lambda mid, author_id, new_title, changed_for, thread_id, ts:\
            log.info("%s changed title of %s to %s" % (author_id, changed_for, new_title))
        self.onPeopleAdded += lambda added_ids, author_id, thread_id:\
            log.info("%s added: %s" % (author_id, [x for x in added_ids]))
        self.onPersonRemoved += lambda removed_id, author_id, thread_id:\
            log.info("%s removed: %s" % (author_id, removed_id))

        if not user_agent:
            user_agent = choice(USER_AGENTS)

        self._header = {
            'Content-Type' : 'application/x-www-form-urlencoded',
            'Referer' : BaseURL,
            'Origin' : BaseURL,
            'User-Agent' : user_agent,
            'Connection' : 'keep-alive',
        }

        # Configure the logger differently based on the 'debug' parameter
        if debug:
            logging_level = logging.DEBUG
        elif info_log:
            logging_level = logging.INFO
        else:
            logging_level = logging.WARNING

        # Creates the console handler
        handler = logging.StreamHandler()
        handler.setLevel(logging_level)
        log.addHandler(handler)
        log.setLevel(logging.DEBUG)

        if do_login:
            self.login(email, password, max_retries)

        self.threads = []

    def _console(self, msg):
        """Assumes an INFO level and log it.

        This method shouldn't be used anymore.
        Use the log itself:
        >>> import logging
        >>> from fbchat.client import log
        >>> log.setLevel(logging.DEBUG)

        You can do the same thing by adding the 'debug' argument:
        >>> from fbchat import Client
        >>> client = Client("...", "...", debug=True)
        """
        warnings.warn(
                "Client._console shouldn't be used.  Use 'log.<level>'",
                DeprecationWarning)
        log.debug(msg)

    def _generatePayload(self, query):
        """Adds the following defaults to the payload:
          __rev, __user, __a, ttstamp, fb_dtsg, __req
        """
        payload = self.payloadDefault.copy()
        if query:
            payload.update(query)
        payload['__req'] = str_base(self.req_counter, 36)
        payload['seq'] = self.seq
        self.req_counter += 1
        return payload

    def _get(self, url, query=None, timeout=30):
        payload=self._generatePayload(query)
        return self._session.get(url, headers=self._header, params=payload, timeout=timeout)

    def _post(self, url, query=None, timeout=30):
        payload=self._generatePayload(query)
        return self._session.post(url, headers=self._header, data=payload, timeout=timeout)

    def _cleanGet(self, url, query=None, timeout=30):
        return self._session.get(url, headers=self._header, params=query, timeout=timeout)

    def _cleanPost(self, url, query=None, timeout=30):
        self.req_counter += 1
        return self._session.post(url, headers=self._header, data=query, timeout=timeout)

    def _postFile(self, url, files=None, timeout=30):
        payload=self._generatePayload(None)
        return self._session.post(url, data=payload, timeout=timeout, files=files)

    def _postLogin(self):
        self.payloadDefault = {}
        self.client_id = hex(int(random()*2147483648))[2:]
        self.start_time = now()
        self.uid = int(self._session.cookies['c_user'])
        self.user_channel = "p_" + str(self.uid)
        self.ttstamp = ''

        r = self._get(BaseURL)
        soup = bs(r.text, "lxml")
        log.debug(r.text)
        log.debug(r.url)
        self.fb_dtsg = soup.find("input", {'name':'fb_dtsg'})['value']
        self.fb_h = soup.find("input", {'name':'h'})['value']

        for i in self.fb_dtsg:
            self.ttstamp += str(ord(i))
        self.ttstamp += '2'

        # Set default payload
        self.payloadDefault['__rev'] = int(r.text.split('"revision":',1)[1].split(",",1)[0])
        self.payloadDefault['__user'] = self.uid
        self.payloadDefault['__a'] = '1'
        self.payloadDefault['ttstamp'] = self.ttstamp
        self.payloadDefault['fb_dtsg'] = self.fb_dtsg

        self.form = {
            'channel' : self.user_channel,
            'partition' : '-2',
            'clientid' : self.client_id,
            'viewer_uid' : self.uid,
            'uid' : self.uid,
            'state' : 'active',
            'format' : 'json',
            'idle' : 0,
            'cap' : '8'
        }

        self.prev = now()
        self.tmp_prev = now()
        self.last_sync = now()

    def _login(self):
        if not (self.email and self.password):
            raise Exception("Email and password not found.")

        soup = bs(self._get(MobileURL).text, "lxml")
        data = dict((elem['name'], elem['value']) for elem in soup.findAll("input") if elem.has_attr('value') and elem.has_attr('name'))
        data['email'] = self.email
        data['pass'] = self.password
        data['login'] = 'Log In'

        r = self._cleanPost(LoginURL, data)

        # Usually, 'Checkpoint' will refer to 2FA
        if 'checkpoint' in r.url and 'Enter Security Code to Continue' in r.text:
            r = self._2FA(r)

        # Sometimes Facebook tries to show the user a "Save Device" dialog
        if 'save-device' in r.url:
            r = self._cleanGet(SaveDeviceURL)

        if 'home' in r.url:
            self._postLogin()
            return True
        else:
            return False

    def _2FA(self, r):
        soup = bs(r.text, "lxml")
        data = dict()

        s = input('Please enter your 2FA code --> ')
        data['approvals_code'] = s
        data['fb_dtsg'] = soup.find("input", {'name':'fb_dtsg'})['value']
        data['nh'] = soup.find("input", {'name':'nh'})['value']
        data['submit[Submit Code]'] = 'Submit Code'
        data['codes_submitted'] = 0
        log.info('Submitting 2FA code.')

        r = self._cleanPost(CheckpointURL, data)

        if 'home' in r.url:
            return r

        del(data['approvals_code'])
        del(data['submit[Submit Code]'])
        del(data['codes_submitted'])

        data['name_action_selected'] = 'save_device'
        data['submit[Continue]'] = 'Continue'
        log.info('Saving browser.')  # At this stage, we have dtsg, nh, name_action_selected, submit[Continue]
        r = self._cleanPost(CheckpointURL, data)

        if 'home' in r.url:
            return r

        del(data['name_action_selected'])
        log.info('Starting Facebook checkup flow.')  # At this stage, we have dtsg, nh, submit[Continue]
        r = self._cleanPost(CheckpointURL, data)

        if 'home' in r.url:
            return r

        del(data['submit[Continue]'])
        data['submit[This was me]'] = 'This Was Me'
        log.info('Verifying login attempt.')  # At this stage, we have dtsg, nh, submit[This was me]
        r = self._cleanPost(CheckpointURL, data)

        if 'home' in r.url:
            return r

        del(data['submit[This was me]'])
        data['submit[Continue]'] = 'Continue'
        data['name_action_selected'] = 'save_device'
        log.info('Saving device again.')  # At this stage, we have dtsg, nh, submit[Continue], name_action_selected
        r = self._cleanPost(CheckpointURL, data)
        return r

    def saveSession(self, sessionfile):
        """Dumps the session cookies to (sessionfile).
        WILL OVERWRITE ANY EXISTING FILE

        :param sessionfile: location of saved session file
        """

        log.info('Saving session')
        with open(sessionfile, 'w') as f:
            # Grab cookies from current session, and save them as JSON
            f.write(json.dumps(self._session.cookies.get_dict(), ensure_ascii=False))

    def loadSession(self, sessionfile):
        """Loads session cookies from (sessionfile)

        :param sessionfile: location of saved session file
        """

        log.info('Loading session')
        with open(sessionfile, 'r') as f:
            try:
                j = json.load(f)
                if not j or 'c_user' not in j:
                    return False
                # Load cookies into current session
                self._session.cookies = requests.cookies.merge_cookies(self._session.cookies, j)
                self._postLogin()
                return True
            except Exception as e:
                raise Exception('Invalid json in {}, or bad merging of cookies'.format(sessionfile))

    def login(self, email, password, max_retries=5):
        self.onLoggingIn()

        self.email = email
        self.password = password

        for i in range(1, max_retries+1):
            if not self._login():
                log.warning("Attempt #{} failed{}".format(i,{True:', retrying'}.get(i<5,'')))
                time.sleep(1)
                continue
            else:
                self.onLoggedIn()
                break
        else:
            raise Exception("Login failed. Check email/password.")

    def logout(self, timeout=30):
        data = {
            'ref': "mb",
            'h': self.fb_h
        }

        payload=self._generatePayload(data)
        r = self._session.get(LogoutURL, headers=self._header, params=payload, timeout=timeout)
        # reset value
        self.payloadDefault={}
        self._session = requests.session()
        self.req_counter = 1
        self.seq = "0"
        return r

    def setDefaultRecipient(self, recipient_id, is_user=True):
        """Sets default recipient to send messages and images to.
        
        :param recipient_id: the user id or thread id that you want to send a message to
        :param is_user: determines if the recipient_id is for user or thread
        """
        self.def_recipient_id = recipient_id
        self.def_is_user = is_user
        self.is_def_recipient_set = True

    def getAllUsers(self):
        """ Gets all users from chat with info included """

        data = {
            'viewer': self.uid,
        }
        r = self._post(AllUsersURL, query=data)
        if not r.ok or len(r.text) == 0:
            return None
        j = get_json(r.text)
        if not j['payload']:
            return None
        payload = j['payload']
        users = []

        for k in payload.keys():
            try:
                user = User.adaptFromChat(payload[k])
            except KeyError:
                continue

            users.append(User(user))

        return users

    def getUsers(self, name):
        """Find and get user by his/her name

        :param name: name of a person
        """

        payload = {
            'value' : name.lower(),
            'viewer' : self.uid,
            'rsp' : "search",
            'context' : "search",
            'path' : "/home.php",
            'request_id' : str(uuid1()),
        }

        r = self._get(SearchURL, payload)
        self.j = j = get_json(r.text)

        users = []
        for entry in j['payload']['entries']:
            if entry['type'] == 'user':
                users.append(User(entry))
        return users # have bug TypeError: __repr__ returned non-string (type bytes)

    def send(self, recipient_id=None, message=None, is_user=True, like=None, image_id=None, add_user_ids=None):
        """Send a message with given thread id

        :param recipient_id: the user id or thread id that you want to send a message to
        :param message: a text that you want to send
        :param is_user: determines if the recipient_id is for user or thread
        :param like: size of the like sticker you want to send
        :param image_id: id for the image to send, gotten from the UploadURL
        :param add_user_ids: a list of user ids to add to a chat
        """

        if self.is_def_recipient_set:
            recipient_id = self.def_recipient_id
            is_user = self.def_is_user
        elif recipient_id is None:
            raise Exception('Recipient ID is not set.')

        messageAndOTID = generateOfflineThreadingID()
        timestamp = now()
        date = datetime.now()
        data = {
            'client': self.client,
            'author' : 'fbid:' + str(self.uid),
            'timestamp' : timestamp,
            'timestamp_absolute' : 'Today',
            'timestamp_relative' : str(date.hour) + ":" + str(date.minute).zfill(2),
            'timestamp_time_passed' : '0',
            'is_unread' : False,
            'is_cleared' : False,
            'is_forward' : False,
            'is_filtered_content' : False,
            'is_filtered_content_bh': False,
            'is_filtered_content_account': False,
            'is_filtered_content_quasar': False,
            'is_filtered_content_invalid_app': False,
            'is_spoof_warning' : False,
            'source' : 'source:chat:web',
            'source_tags[0]' : 'source:chat',
            'html_body' : False,
            'ui_push_phase' : 'V3',
            'status' : '0',
            'offline_threading_id':messageAndOTID,
            'message_id' : messageAndOTID,
            'threading_id':generateMessageID(self.client_id),
            'ephemeral_ttl_mode:': '0',
            'manual_retry_cnt' : '0',
            'signatureID' : getSignatureID()
        }

        if is_user:
            data["other_user_fbid"] = recipient_id
        else:
            data["thread_fbid"] = recipient_id

        if add_user_ids:
            data['action_type'] = 'ma-type:log-message'
            # It's possible to add multiple users
            for i, add_user_id in enumerate(add_user_ids):
                data['log_message_data[added_participants][' + str(i) + ']'] = "fbid:" + str(add_user_id)
            data['log_message_type'] = 'log:subscribe'
        else:
            data['action_type'] = 'ma-type:user-generated-message'
            data['body'] = message
            data['has_attachment'] = image_id is not None
            data['specific_to_list[0]'] = 'fbid:' + str(recipient_id)
            data['specific_to_list[1]'] = 'fbid:' + str(self.uid)

        if image_id:
            data['image_ids[0]'] = image_id

        if like and not type(like) is Sticker:
            data["sticker_id"] = Sticker.SMALL.value
        else:
            data["sticker_id"] = like.value

        r = self._post(SendURL, data)

        if r.ok:
            log.info('Message sent.')
        else:
            log.info('Message not sent.')

        if isinstance(r._content, str) is False:
            r._content = r._content.decode(facebookEncoding)
        j = get_json(r._content)
        if 'error' in j:
            # 'errorDescription' is in the users own language!
            log.warning('Error #{} when sending message: {}'.format(j['error'], j['errorDescription']))
            return False

        log.debug("Sending {}".format(r))
        log.debug("With data {}".format(data))
        return True

    def sendRemoteImage(self, recipient_id=None, message=None, is_user=True, image=''):
        """Send an image from a URL

        :param recipient_id: the user id or thread id that you want to send a message to
        :param message: a text that you want to send
        :param is_user: determines if the recipient_id is for user or thread
        :param image: URL for an image to download and send
        """
        mimetype = guess_type(image)[0]
        remote_image = requests.get(image).content
        image_id = self.uploadImage({'file': (image, remote_image, mimetype)})
        return self.send(recipient_id, message, is_user, None, image_id)

    def sendLocalImage(self, recipient_id=None, message=None, is_user=True, image=''):
        """Send an image from a file path

        :param recipient_id: the user id or thread id that you want to send a message to
        :param message: a text that you want to send
        :param is_user: determines if the recipient_id is for user or thread
        :param image: path to a local image to send
        """
        mimetype = guess_type(image)[0]
        image_id = self.uploadImage({'file': (image, open(image, 'rb'), mimetype)})
        return self.send(recipient_id, message, is_user, None, image_id)

    def uploadImage(self, image):
        """Upload an image and get the image_id for sending in a message

        :param image: a tuple of (file name, data, mime type) to upload to facebook
        """

        r = self._postFile(UploadURL, image)
        if isinstance(r._content, str) is False:
            r._content = r._content.decode(facebookEncoding)
        # Strip the start and parse out the returned image_id
        return json.loads(r._content[9:])['payload']['metadata'][0]['image_id']

    def getThreadInfo(self, userID, last_n=20, start=None, is_user=True):
        """Get the info of one Thread

        :param userID: ID of the user you want the messages from
        :param last_n: (optional) number of retrieved messages from start
        :param start: (optional) the start index of a thread (Deprecated)
        :param is_user: (optional) determines if the userID is for user or thread
        """

        assert last_n > 0, 'length must be positive integer, got %d' % last_n
        assert start is None, '`start` is deprecated, always 0 offset querry is returned'
        if is_user:
            key = 'user_ids'
        else:
            key = 'thread_fbids'

        # deprecated
        # `start` doesn't matter, always returns from the last
        # data['messages[{}][{}][offset]'.format(key, userID)] = start
        data = {'messages[{}][{}][offset]'.format(key, userID): 0,
                'messages[{}][{}][limit]'.format(key, userID): last_n,
                'messages[{}][{}][timestamp]'.format(key, userID): now()}

        r = self._post(MessagesURL, query=data)
        if not r.ok or len(r.text) == 0:
            return None

        j = get_json(r.text)
        if not j['payload']:
            return None

        messages = []
        for message in j['payload']['actions']:
            messages.append(Message(**message))
        return list(reversed(messages))

    def getThreadList(self, start, length=20):
        """Get thread list of your facebook account.

        :param start: the start index of a thread
        :param length: (optional) the length of a thread
        """

        assert length < 21, '`length` is deprecated, max. last 20 threads are returned'

        data = {
            'client' : self.client,
            'inbox[offset]' : start,
            'inbox[limit]' : length,
        }

        r = self._post(ThreadsURL, data)
        if not r.ok or len(r.text) == 0:
            return None

        j = get_json(r.text)

        # Get names for people
        participants = {}
        try:
            for participant in j['payload']['participants']:
                participants[participant["fbid"]] = participant["name"]
        except Exception as e:
            log.warning(str(j))

        # Prevent duplicates in self.threads
        threadIDs = [getattr(x, "thread_id") for x in self.threads]
        for thread in j['payload']['threads']:
            if thread["thread_id"] not in threadIDs:
                try:
                    thread["other_user_name"] = participants[int(thread["other_user_fbid"])]
                except:
                    thread["other_user_name"] = ""
                t = Thread(**thread)
                self.threads.append(t)

        return self.threads

    def getUnread(self):
        form = {
            'client': 'mercury_sync',
            'folders[0]': 'inbox',
            'last_action_timestamp': now() - 60*1000
            # 'last_action_timestamp': 0
        }

        r = self._post(ThreadSyncURL, form)
        if not r.ok or len(r.text) == 0:
            return None

        j = get_json(r.text)
        result = {
            "message_counts": j['payload']['message_counts'],
            "unseen_threads": j['payload']['unseen_thread_ids']
        }
        return result

    def markAsDelivered(self, userID, threadID):
        data = {
            "message_ids[0]": threadID,
            "thread_ids[%s][0]" % userID: threadID
        }

        r = self._post(DeliveredURL, data)
        return r.ok

    def markAsRead(self, userID):
        data = {
            "watermarkTimestamp": now(),
            "shouldSendReadReceipt": True,
            "ids[%s]" % userID: True
        }

        r = self._post(ReadStatusURL, data)
        return r.ok

    def markAsSeen(self):
        r = self._post(MarkSeenURL, {"seen_timestamp": 0})
        return r.ok

    def friendConnect(self, friend_id):
        data = {
            "to_friend": friend_id,
            "action": "confirm"
        }

        r = self._post(ConnectURL, data)

        return r.ok

    def ping(self, sticky):
        data = {
            'channel': self.user_channel,
            'clientid': self.client_id,
            'partition': -2,
            'cap': 0,
            'uid': self.uid,
            'sticky': sticky,
            'viewer_uid': self.uid
        }
        r = self._get(PingURL, data)
        return r.ok

    def _getSticky(self):
        """Call pull api to get sticky and pool parameter, newer api needs these parameter to work."""

        data = {
            "msgs_recv": 0,
            "channel": self.user_channel,
            "clientid": self.client_id
        }

        r = self._get(StickyURL, data)
        j = get_json(r.text)

        if 'lb_info' not in j:
            raise Exception('Get sticky pool error')

        sticky = j['lb_info']['sticky']
        pool = j['lb_info']['pool']
        return sticky, pool

    def _pullMessage(self, sticky, pool):
        """Call pull api with seq value to get message data."""

        data = {
            "msgs_recv": 0,
            "sticky_token": sticky,
            "sticky_pool": pool,
            "clientid": self.client_id,
        }

        r = self._get(StickyURL, data)
        r.encoding = facebookEncoding
        j = get_json(r.text)

        self.seq = j.get('seq', '0')
        return j

    def _parseMessage(self, content):
        """Get message and author name from content.
        May contains multiple messages in the content.
        """

        if 'ms' not in content: return

        log.debug("Received {}".format(content["ms"]))
        for m in content["ms"]:
            mtype = m.get("type")
            try:
                # Things that directly change chat
                if mtype == "delta":

                    def getRecipientIdAndMsgType(msg_metadata):
                        """Returns a tuple consisting of recipient id and message type"""
                        recipient = None
                        message_type = None
                        if 'threadFbId' in msg_metadata['threadKey']:
                            recipient = msg_metadata['threadKey']['threadFbId']
                            message_type = MsgType.GROUP
                        elif 'otherUserFbId' in msg_metadata['threadKey']:
                            recipient = msg_metadata['threadKey']['otherUserFbId']
                            message_type = MsgType.USER
                        return recipient, message_type

                    delta = m["delta"]
                    delta_type = delta.get("type")
                    metadata = delta.get("messageMetadata")

                    # Added participants
                    if 'addedParticipants' in delta:
                        added_ids = [x['userFbId'] for x in delta['addedParticipants']]
                        author_id = metadata['actorFbId']
                        thread_id = metadata['threadKey']['threadFbId']
                        ts = metadata["timestamp"]
                        self.onPeopleAdded(added_ids=added_ids, author_id=author_id, thread_id=thread_id, ts=ts)

                    # Left/removed participants
                    elif 'leftParticipantFbId' in delta:
                        removed_id = delta['leftParticipantFbId']
                        author_id = metadata['actorFbId']
                        thread_id = metadata['threadKey']['threadFbId']
                        ts = metadata["timestamp"]
                        self.onPersonRemoved(removed_id=removed_id, author_id=author_id, thread_id=thread_id, ts=ts)

                    # Seen
                    elif delta.get("class") == "ReadReceipt":
                        seen_by = delta["actorFbId"] or delta["threadKey"]["otherUserFbId"]
                        thread_id = delta["threadKey"].get("threadFbId")
                        timestamp = delta["actionTimestampMs"]
                        self.onSeen(seen_by=seen_by, thread_id=thread_id, timestamp=timestamp)

                    # Color change
                    elif delta_type == "change_thread_theme":
                        mid = metadata["messageId"]
                        author_id = metadata["actorFbId"]
                        new_color = delta["untypedData"]["theme_color"]
                        changed_for, msg_type = getRecipientIdAndMsgType(metadata)
                        ts = metadata["timestamp"]
                        self.onColorChange(mid=mid, author_id=author_id, new_color=new_color, changed_for=changed_for,
                                           msg_type=msg_type, ts=ts)

                    # Title change
                    elif delta_type == "change_thread_nickname":
                        mid = metadata["messageId"]
                        author_id = metadata["actorFbId"]
                        changed_for = delta["untypedData"]["participant_id"]
                        new_title = delta["untypedData"]["nickanme"]
                        thread_id = metadata["threadKey"].get("threadFbId")
                        ts = metadata["timestamp"]
                        self.onTitleChange(mid=mid, author_id=author_id, changed_for=changed_for, new_title=new_title,
                                           thread_id=thread_id, ts=ts)

                    # New message
                    elif "messageMetadata" in delta:
                        mid = metadata['messageId']
                        message = delta.get('body', '')
                        author_id = metadata['actorFbId']
                        recipient_id, msg_type = getRecipientIdAndMsgType(metadata)
                        ts = metadata["timestamp"]
                        self.onMessage(mid=mid, author_id=author_id, message=message,
                                       recipient_id=recipient_id, msg_type=msg_type, ts=ts, metadata=m)


                if mtype == "inbox":
                    self.onInbox(unseen=m["unseen"], unread=m["unread"], recent_unread=m["recent_unread"])

                # Typing
                # elif mtype == "typ":
                #     author_id = str(m.get("from"))
                #     typing_status = TypingStatus(m.get("st"))
                #     self.onTyping(author_id=author_id, typing_status=typing_status)

                # Seen
                elif mtype == "m_read_receipt":

                    self.onSeen(m.get('realtime_viewer_fbid'), m.get('reader'), m.get('time'))

                # elif mtype in ['jewel_requests_add']:
                #         from_id = m['from']
                #         self.on_friend_request(from_id)

                # Happens on every login
                elif mtype == "qprimer":
                    pass

                # Is sent before any other message
                elif mtype == "deltaflow":
                    pass

                else:
                    log.debug("Unknown type %s" % m)
            except Exception as e:
                log.debug(str(e))

    def startListening(self):
        """Start listening from an external event loop."""
        self.listening = True
        self.sticky, self.pool = self._getSticky()

    def doOneListen(self, markAlive=True):
        """Does one cycle of the listening loop.
        This method is only useful if you want to control fbchat from an
        external event loop."""
        try:
            if markAlive: self.ping(self.sticky)
            try:
                content = self._pullMessage(self.sticky, self.pool)
                if content: self._parseMessage(content)
            except requests.exceptions.RequestException as e:
                pass
        except KeyboardInterrupt:
            self.listening = False
        except requests.exceptions.Timeout:
            pass

    def stopListening(self):
        """Cleans up the variables from start_listening."""
        self.listening = False
        self.sticky, self.pool = (None, None)

    def listen(self, markAlive=True):
        self.startListening()
        self.onListening()

        while self.listening:
            self.doOneListen(markAlive)

        self.stopListening()

    def getUserInfo(self, *user_ids):
        """Get user info from id. Unordered.

        :param user_ids: one or more user id(s) to query
        """

        def fbidStrip(_fbid):
            # Stripping of `fbid:` from author_id
            if type(_fbid) == int:
                return _fbid

            if type(_fbid) == str and 'fbid:' in _fbid:
                return int(_fbid[5:])

        user_ids = [fbidStrip(uid) for uid in user_ids]

        data = {"ids[{}]".format(i):uid for i,uid in enumerate(user_ids)}
        r = self._post(UserInfoURL, data)
        info = get_json(r.text)
        full_data= [details for profile,details in info['payload']['profiles'].items()]
        if len(full_data)==1:
            full_data=full_data[0]
        return full_data

    def removeUserFromChat(self, threadID, userID):
        """Remove user (userID) from group chat (threadID)

        :param threadID: group chat id
        :param userID: user id to remove from chat
        """

        data = {
            "uid" : userID,
            "tid" : threadID
        }

        r = self._post(RemoveUserURL, data)

        return r.ok

    def addUserToChat(self, threadID, userID):
        """Add user (userID) to group chat (threadID)

        :param threadID: group chat id
        :param userID: user id to add to chat
        """
        return self.send(threadID, is_user=False, add_user_ids=[userID])

    def changeThreadTitle(self, threadID, newTitle):
        """Change title of a group conversation

        :param threadID: group chat id
        :param newTitle: new group chat title
        """

        messageAndOTID = generateOfflineThreadingID()
        timestamp = now()
        date = datetime.now()
        data = {
            'client' : self.client,
            'action_type' : 'ma-type:log-message',
            'author' : 'fbid:' + str(self.uid),
            'thread_id' : '',
            'author_email' : '',
            'coordinates' : '',
            'timestamp' : timestamp,
            'timestamp_absolute' : 'Today',
            'timestamp_relative' : str(date.hour) + ":" + str(date.minute).zfill(2),
            'timestamp_time_passed' : '0',
            'is_unread' : False,
            'is_cleared' : False,
            'is_forward' : False,
            'is_filtered_content' : False,
            'is_spoof_warning' : False,
            'source' : 'source:chat:web',
            'source_tags[0]' : 'source:chat',
            'status' : '0',
            'offline_threading_id' : messageAndOTID,
            'message_id' : messageAndOTID,
            'threading_id': generateMessageID(self.client_id),
            'manual_retry_cnt' : '0',
            'thread_fbid' : threadID,
            'log_message_data[name]' : newTitle,
            'log_message_type' : 'log:thread-name'
        }

        r = self._post(SendURL, data)

        return r.ok
