import re
import json
import httplib
import database

from irc import *
from util import *
from urllib2 import urlopen
from urllib2 import URLError
from urllib import urlencode as ue
from urllib import quote_plus as urlencode
from BeautifulSoup import BeautifulSoup

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

try:
    db['lfm']
except KeyError:
    db['lfm'] = {}

try:
    db['youtube']
except KeyError:
    db['youtube'] = {}

# regular expressions
regex = [(re.compile(r), rr) for (r, rr) in [
    (r'\*\*([^*]+)\*\*', r'%c\1%c' % ('\x02', '\x0f')), # bold
    (r'__([^_]+)__', r'%c\1%c' % ('\x1f', '\x0f')),     # underline
    (r'\*([^*]+)\*', r'%c\1%c' % ('\x1d', '\x0f'))      # italic
]]

def rp(s):
    for (r, rr) in regex:
        s = r.sub(rr, s)
    return s

# bot hooks
def pong_hook(irc_con):
    host = irc_con.matches[3]
    irc_con.pong(host)

def nick_hook(irc_con):
    raise IRC_Conn.exceptions['nick_in_use']

def pingout_hook(irc_con):
    irc_con.reconnect_to_server()

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
            irc_con.quit('reconnecting to server...')
            irc_con.reconnect_to_server()
            irc_con.join_configured_channels()

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

        terms = ' '.join(_terms)

        if terms in db['youtube']:
            what = db['youtube'][terms]
            irc_con.privmsg(target, '%s | %s' % (what[0], what[1]))
        else:
            rsp = None
            htmlfile = None

            try:
                htmlfile = urlopen('https://youtube.com/results?search_query=%s'
                    % urlencode(terms))
            except URLError:
                irc_con.privmsg(target, 'YouTube is down')
                return

            soup = BeautifulSoup(htmlfile.read())
            results = soup.findAll('div', {'class': 'yt-lockup-content'})

            if len(results) == 0:
                irc_con.privmsg(target, 'no results found')
            else:
                a = results[0].find('a')
                title = a['title']
                url = 'https://youtube.com%s' % a['href']

                irc_con.privmsg(target, '%s | %s' % (title, url))

                db['youtube'][terms] = (title, url)
                database.write(db, db_path)

                del results

            del soup

# the bot will load these hooks
exports = {
    'PING'    : {'pong':pong_hook},
    'PRIVMSG' : {'ch':ch_hook, 'q':quit_hook, 'np':lfm_np_hook,
                 'ud':ud_hook, 'rc':recon_hook, 'yt':yt_hook},
    'ERROR'   : {'error':pingout_hook},
    '433'     : {'nick':nick_hook}
}
