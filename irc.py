import re
import json
import socket
import ssl

from sys import stdout
from time import sleep

# irc bot class
class IRC_Conn:
    # create all the exceptions associated with this class
    exceptions = {e:type('IRC_Conn.'+e, (Exception,), {}) for e in [
        'exit',
        'nick_in_use'
    ]}

    # maximum length of each message
    # received on a buffer
    msg_length = 512

    def __init__(self, json_config_path, hook_list=None, logger=stdout):
        if hook_list is not None and not isinstance(hook_list, dict):
            raise TypeError('hook list must be a dictionary')
        else:
            if not all(map(lambda v: isinstance(v, dict), hook_list.values())):
                raise TypeError('hook list must contain dicts of event hooks')

        self.logger = logger
        self.matches = None
        self.msg_matches = None
        self.extern = None
        self.__line__ = None
        self.__conn__ = None
        self.__config__ = None
        self.__hooks__ = hook_list
        self.__re__ = re.compile('^(?:[:](\S+) )?(\S+)(?: ([^:].+?))?(?: [:](.+))?$')

        self.load_config(json_config_path)
        self.extern = self.__config__['extern']

    def __exit__(self, exc_type, exc_value, traceback):
        self.__conn__.close()

    def connect_to_server(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        if self.__config__['server']['use_ssl']:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
            ctx.load_default_certs()
            self.__conn__ = ctx.wrap_socket(s)
        else:
            self.__conn__ = s

        self.__conn__.connect((self.__config__['server']['host'], self.__config__['server']['port']))

    def reconnect_to_server(self):
        self.__conn__.close()
        self.connect_to_server()
        self.auth()

    def load_config(self, json_config_path):
        with open(json_config_path, 'r') as json_file:
            self.__config__ = json.load(json_file)
            json_file.close()

    def cmd(self, which):
        return self.__config__['extern']['cmd_prefix'] + which

    def send_raw(self, buffer):
        self.__conn__.send(buffer + '\r\n')

    def privmsg(self, target, msg):
        self.send_raw('PRIVMSG ' + target + ' :' + msg)

    def pong(self, host):
        self.send_raw('PONG :' + host)

    def join(self, channel):
        self.send_raw('JOIN ' + channel)

    def join_configured_channels(self):
        map(self.join, self.__config__['server']['channels'])

    def quit(self, msg=None):
        if msg is not None:
            self.send_raw('QUIT :' + msg)
        else:
            self.send_raw('QUIT')

    def part(self, msg=None):
        if msg is not None:
            self.send_raw('PART :' + msg)
        else:
            self.send_raw('PART')

    def change_nick(self, nick):
        self.send_raw('NICK ' + nick)

    def auth(self):
        self.change_nick(self.__config__['nick'])

        if self.__config__['name'] is not None:
            self.send_raw('USER ' + self.__config__['nick'] + ' 8 * : ' + self.__config__['name'])
        else:
            self.send_raw('USER ' + self.__config__['nick'] + ' 8 * : An IRC bot')

        if self.__config__['pass'] is not None:
            self.send_raw('PASS ' + self.__config__['pass'])

    def recv(self):
        self.__line__ = self.__conn__.recv(IRC_Conn.msg_length)
        return self.__line__

    def install_hook(self, event, name, hook):
        if self.__hooks__ is None:
            self.__hooks__ = {}
        if self.__hooks__[event] is None:
            self.__hooks__[event] = {}
        self.__hooks__[event][name] = hook

    def uninstall_hook(self, event, name):
        del self.__hooks__[event][name]

    def trigger_hooks(self):
        try:
            self.matches = self.__re__.findall(self.__line__)[0]

            if self.matches[1] == 'PRIVMSG':
                self.msg_matches = re.findall('\S+', self.matches[3])

            event = self.matches[1]
            map(lambda h: h(self), self.__hooks__[event].values())
        except IndexError:
            pass # no line read from socket
        except KeyError:
            pass # event not handled

    def reset_hooks(self, hook_list):
        if hook_list is not None and not isinstance(hook_list, dict):
            raise TypeError('hook list must be a dictionary')
        else:
            if not all(map(lambda v: isinstance(v, dict), hook_list.values())):
                raise TypeError('hook list must contain dicts of event hooks')
            old = self.__hooks__
            self.__hooks__ = hook_list
            del old

    def setup_logger(self, logger):
        self.logger = logger
