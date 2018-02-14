import re
import json
import httplib
import database
import sqlite3

from irc import *
from util import *
from urllib2 import urlopen
from urllib2 import URLError
from random import randint as rint
from urllib import urlencode as ue
from urllib import quote as urlencode

# support utf-8
import sys
reload(sys)
sys.setdefaultencoding('utf8')

'''

TODO SHIT:
=============

* write a custom logger of some sort to hook to the irc class (use 'logging')
* add a system to implement admin only hooks (some sort of whitelist)

'''

# load database
db = None
db_path = 'db.gz'

try:
    db = database.load(db_path)
except IOError:
    db = {}

create_database_services(db, [
    'lfm',
    'youtube',
    'intro',
    'tell'
])

# joined channels?
not_joined_channels = True

# bot hooks
def pong_hook(irc_con):
    host = irc_con.matches[3]
    irc_con.pong(host)

def nick_hook(irc_con):
    raise IRC_Conn.exceptions['nick_in_use']

def pingout_hook(irc_con):
    global not_joined_channels

    not_joined_channels = True
    irc_con.reconnect_to_server()

def on_notice_join_hook(irc_con):
    global not_joined_channels

    if not_joined_channels:
        not_joined_channels = False
        irc_con.join_configured_channels()

def ch_hook(irc_con):
    target = irc_con.matches[2]
    host = irc_con.matches[0]

    if target[0] != '#':
        target = parse_nick(host)

    if irc_con.msg_matches[0] == irc_con.cmd('join'):
        try:
            if host not in irc_con.extern['admin_hosts']:
                irc_con.privmsg(target, irc_con.extern['msg_error'])
            else:
                irc_con.join(irc_con.msg_matches[1])
        except IndexError:
            irc_con.privmsg(target, 'usage: ' + irc_con.cmd('join') + ' [channel_1, [, ...]]')
    elif irc_con.msg_matches[0] == irc_con.cmd('part'):
        try:
            if host not in irc_con.extern['admin_hosts']:
                irc_con.privmsg(target, irc_con.extern['msg_error'])
            else:
                irc_con.part(irc_con.msg_matches[1])
        except IndexError:
            if target[0] == '#':
                irc_con.part(target)
            else:
                irc_con.privmsg(target, 'usage: ' + irc_con.cmd('part') + ' [channel_1, [, ...]]')

def quit_hook(irc_con):
    if irc_con.msg_matches[0] == irc_con.cmd('q'):
        host = irc_con.matches[0]

        if host not in irc_con.extern['admin_hosts']:
            target = irc_con.matches[2]

            if target[0] != '#':
                target = parse_nick(host)

            irc_con.privmsg(target, irc_con.extern['msg_error'])
        else:
            irc_con.quit('later hoes!')
            raise IRC_Conn.exceptions['exit']

def recon_hook(irc_con):
    if irc_con.msg_matches[0] == irc_con.cmd('reconnect'):
        host = irc_con.matches[0]

        if host not in irc_con.extern['admin_hosts']:
            target = irc_con.matches[2]

            if target[0] != '#':
                target = parse_nick(host)

            irc_con.privmsg(target, irc_con.extern['msg_error'])
        else:
            global not_joined_channels

            irc_con.quit('reconnecting to server...')
            not_joined_channels = True
            irc_con.reconnect_to_server()

def lfm_np_hook(irc_con):
    target = irc_con.matches[2]

    if target[0] != '#':
        host = irc_con.matches[0]
        target = parse_nick(host)

    if irc_con.msg_matches[0] == irc_con.cmd('np'):
        host = irc_con.matches[0]
        nick = parse_nick(host)
        user = None
        save_user = True

        try:
            user = irc_con.msg_matches[1]
        except IndexError:
            try:
                host = irc_con.matches[0]
                user = db['lfm'][nick]
                save_user = False
            except KeyError:
                irc_con.privmsg(target, 'usage: ' + irc_con.cmd('np') + ' [lfm_user]')
                return

        rsp = None
        conn = None

        try:
            conn = httplib.HTTPConnection('ws.audioscrobbler.com')
            fmt = '/2.0/?method=user.getrecenttracks&user=%s&api_key=%s&format=json'
            req = fmt % (user, irc_con.extern['lfm_key'])
            conn.request('GET', req)
            rsp = conn.getresponse()
        except socket.gaierror:
            irc_con.privmsg(target, 'the last.fm API is down')
            return

        if rsp.status != 200:
            irc_con.privmsg(target, 'could not fetch response')
        else:
            lfm = json.loads(rsp.read())

            try:
                irc_con.privmsg(target, lfm['message'])
            except KeyError:
                if save_user:
                    usr = db['lfm'].get(nick) or None

                    if not (usr or usr == user):
                        try:
                            db['lfm'][nick] = user
                            database.write(db, db_path)
                        except IOError:
                            print 'error saving database'

                track = lfm['recenttracks']['track'][0]
                artist = track['artist']['#text']
                title = track['name']
                album = track['album']['#text']

                try:
                    date = track['date']
                    msg = rp('**%s** last played **%s - %s**, from the album **%s**, on **%s**'
                        % (user, artist, title, album, date['#text']))
                    irc_con.privmsg(target, msg)
                except KeyError:
                    msg = rp('**%s** is playing **%s - %s**, from the album **%s**'
                        % (user, artist, title, album))
                    irc_con.privmsg(target, msg)

            del lfm

def ud_hook(irc_con):
    target = irc_con.matches[2]

    if target[0] != '#':
        host = irc_con.matches[0]
        target = parse_nick(host)

    if irc_con.msg_matches[0] == irc_con.cmd('ud'):
        term = None

        try:
            term = irc_con.msg_matches[1]
        except IndexError:
            irc_con.privmsg(target, 'usage: ' + irc_con.cmd('ud') + ' [search term]')
            return

        rsp = None
        conn = None

        try:
            conn = httplib.HTTPSConnection('mashape-community-urban-dictionary.p.mashape.com')
            conn.request('GET', '/define?%s' % ue({'term': term}), headers={
                'X-Mashape-Key': irc_con.extern['mash_key'],
                'Accept': 'text/plain'
            })
            rsp = conn.getresponse()
        except socket.gaierror:
            irc_con.privmsg(target, 'the Mashall API is down')
            return

        if rsp.status != 200:
            irc_con.privmsg(target, 'error fetching resources')
        else:
            ud = json.loads(rsp.read())

            if ud['result_type'] != 'exact':
                irc_con.privmsg(target, 'could not find a suitable description')
            else:
                try:
                    irc_con.privmsg(target, ud['list'][0]['definition'])
                except (KeyError, IndexError):
                    irc_con.privmsg(target, 'error fetching resources')

            del ud

def yt_hook(irc_con):
    target = irc_con.matches[2]

    if target[0] != '#':
        host = irc_con.matches[0]
        target = parse_nick(host)

    if irc_con.msg_matches[0] == irc_con.cmd('yt'):
        terms = None
        _terms = irc_con.msg_matches[1:]

        if len(_terms) == 0:
            irc_con.privmsg(target, 'usage: ' + irc_con.cmd('yt') + ' [search string]')
            return

        rsp = None
        conn = None

        try:
            host = 'www.googleapis.com'
            path = '/youtube/v3/search'
            conn = httplib.HTTPSConnection(host, 443)
            terms = ' '.join(_terms)

            params = {
                'key': irc_con.extern['yt_key'],
                'part': 'id,snippet',
                'type': 'video',
                'maxResults': '1',
                'order': 'viewCount',
                'q': terms
            }

            conn.request('GET', '%s?%s' % (path, ue(params)))
            rsp = conn.getresponse()
        except socket.gaierror:
            irc_con.privmsg(target, 'couldn not perform youtube API request')
            return

        if not rsp:
            irc_con.privmsg(target, 'could not perform youtube API request')
            return

        q = None

        try:
            q = json.loads(rsp.read())['items'][0]
        except IndexError:
            irc_con.privmsg(target, "nothing found for: %s" % terms)
            return

        url = 'https://youtu.be/%s' % q['id']['videoId']
        title = q['snippet']['title']

        irc_con.privmsg(target, '%s | %s' % (title, url))

        del rsp
        del q

def help_hook(irc_con):
    if irc_con.msg_matches[0] == irc_con.cmd('help'):
        target = irc_con.matches[2]

        if target[0] != '#':
            host = irc_con.matches[0]
            target = parse_nick(host)

        irc_con.privmsg(target, ' '.join(exports['PRIVMSG'].keys()))

def intro_hook(irc_con):
    try:
        host = irc_con.matches[0]
        nick = parse_nick(host)
        msg = db['intro'][nick]
        chan = irc_con.matches[3].replace('\r', '')
        irc_con.privmsg(chan, msg)
    except KeyError:
        pass

def set_intro_hook(irc_con):
    if irc_con.msg_matches[0] == irc_con.cmd('intro'):
        target = irc_con.matches[2]
        host = irc_con.matches[0]
        nick = parse_nick(host)

        if target[0] != '#':
            target = nick

        cmd = None

        try:
            cmd = irc_con.msg_matches[1]
        except IndexError:
            try:
                irc_con.privmsg(target, db['intro'][nick])
            except KeyError:
                irc_con.privmsg(target, 'usage: ' + irc_con.cmd('intro') + ' [add|del] [msg]')
            return

        if cmd == 'add':
            terms = irc_con.msg_matches[2:]

            if len(terms) == 0:
                irc_con.privmsg(target, 'usage: ' + irc_con.cmd('intro') + ' [add|del] [msg]')
                return

            msg = ' '.join(terms)
            db['intro'][nick] = msg

            irc_con.privmsg(target, 'intro message has been saved')
        elif cmd == 'del':
            del db['intro'][nick]
            irc_con.privmsg(target, 'intro message has been deleted')
        else:
            irc_con.privmsg(target, 'usage: ' + irc_con.cmd('intro') + ' [add|del] [msg]')
            return

        database.write(db, db_path)

def tell_hook(irc_con):
    try:
        host = irc_con.matches[0]
        nick = parse_nick(host)
        msgs = db['tell'][nick]
        chan = irc_con.matches[3].replace('\r', '')
        [irc_con.privmsg(nick, '%s told you: %s' % pair) for pair in msgs]

        del db['tell'][nick]
        database.write(db, db_path)
    except KeyError:
        pass

def set_tell_hook(irc_con):
    if irc_con.msg_matches[0] == irc_con.cmd('tell'):
        target = irc_con.matches[2]
        host = irc_con.matches[0]
        nick = parse_nick(host)

        if target[0] != '#':
            target = nick

        who = None

        try:
            who = irc_con.msg_matches[1]
        except IndexError:
            irc_con.privmsg(target, 'usage: ' + irc_con.cmd('tell') + ' [who] [msg]')
            return

        terms = irc_con.msg_matches[2:]

        if len(terms) == 0:
            irc_con.privmsg(target, 'usage: ' + irc_con.cmd('tell') + ' [who] [msg]')
            return

        msg = ' '.join(terms)

        try:
            db['tell'][who].append((nick, msg))
        except KeyError:
            db['tell'][who] = [(nick, msg)]

        irc_con.privmsg(target, '%s will be notified next time he/she is online' % who)

        database.write(db, db_path)

def pplus_hook(irc_con):
    if len(irc_con.msg_matches) == 1:
        target = irc_con.matches[2]
        host = irc_con.matches[0]
        nick = parse_nick(host)
        z = len(irc_con.msg_matches[0]) - 2

        if target[0] != '#':
            target = nick

        if irc_con.msg_matches[0][z:] == '++':
            nick2 = irc_con.msg_matches[0][:z]
            irc_con.privmsg(target, '%s salutes %s!' % (nick, nick2))
        elif irc_con.msg_matches[0][z:] == '--':
            nick2 = irc_con.msg_matches[0][:z]
            irc_con.privmsg(target, '%s boos on %s!' % (nick, nick2))

def drink_hook(irc_con):
    if irc_con.msg_matches[0] == irc_con.cmd('drink'):
        target = irc_con.matches[2]
        host = irc_con.matches[0]
        nick = parse_nick(host)

        if target[0] != '#':
            host = irc_con.matches[0]
            target = parse_nick(host)

        who = None

        try:
            who = irc_con.msg_matches[1]
        except IOError:
            irc_con.privmsg(target, 'usage: ' + irc_con.cmd('drink') + ' [who]')
            return

        drinks = sqlite3.connect('recipes.db')
        cursor = drinks.cursor()
        d = cursor.execute('SELECT * FROM drinks ORDER BY RANDOM() LIMIT 1').fetchone()

        irc_con.privmsg(target, '%s offers %s: %s: %s | %s' % (nick, who, d[0], d[1], d[2]))

        drinks.close()
        del d

# the bot will load these hooks
exports = {
    'PING'    : {'pong':pong_hook},
    'PRIVMSG' : {'join/part':ch_hook, 'q':quit_hook, 'np':lfm_np_hook,
                 'ud':ud_hook, 'reconnect':recon_hook, 'yt':yt_hook,
                 'help':help_hook, 'intro':set_intro_hook, '++/--':pplus_hook,
                 'drink':drink_hook, 'tell':set_tell_hook},
    'JOIN'    : {'intro':intro_hook, 'tell':tell_hook},
    'ERROR'   : {'error':pingout_hook},
    'NOTICE'  : {'join':on_notice_join_hook},
    '433'     : {'nick':nick_hook}
}
