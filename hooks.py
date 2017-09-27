import re
import json
import httplib
import database

from irc import *
from util import *
from urllib2 import urlopen
from urllib2 import URLError
from random import randint as rint
from urllib import urlencode as ue
from urllib import quote as urlencode
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

create_database_services(db, [
    'lfm',
    'youtube',
    'intro'
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
            irc_con.quit('reconnecting to server...')
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

                # get tags
                try:
                    conn = httplib.HTTPConnection('ws.audioscrobbler.com')
                    fmt = '/2.0/?method=track.getTopTags&artist=%s&track=%s&api_key=%s&format=json'
                    req = fmt % (urlencode(artist), urlencode(title), irc_con.extern['lfm_key'])
                    conn.request('GET', req)
                    rsp = conn.getresponse()
                except socket.gaierror:
                    irc_con.privmsg(target, 'the last.fm API is down')
                    return

                tags = None

                try:
                    _tags = json.loads(rsp.read())
                    _toptags = _tags.get('toptags')
                    __tags = _toptags.get('tag') if _toptags else []

                    tags = [t.get('name') for t in __tags][:5]
                    tags =  ', '.join(tags)

                    del _tags ; del _toptags ; del __tags
                except ValueError:
                    pass

                if tags:
                    try:
                        date = track['date']
                        msg = rp('**%s** last played **%s - %s**, from the album **%s**, tagged as **%s**, on **%s**'
                            % (user, artist, title, album, tags, date['#text']))
                        irc_con.privmsg(target, msg)
                    except KeyError:
                        msg = rp('**%s** is playing **%s - %s**, from the album **%s**, tagged as **%s**'
                            % (user, artist, title, album, tags))
                        irc_con.privmsg(target, msg)
                else:
                    try:
                        date = track['date']
                        msg = rp('**%s** last played **%s - %s**, from the album **%s**, on **%s**'
                            % (user, artist, title, album, date['#text']))
                        irc_con.privmsg(target, msg)
                    except KeyError:
                        msg = rp('**%s** is playing **%s - %s**, from the album **%s**'
                            % (user, artist, title, album))
                        irc_con.privmsg(target, msg)

                del tags

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

        drinks = database.load('recipes.gz')
        d = drinks[rint(0, len(drinks))]

        irc_con.privmsg(target, '%s offers %s: %s: %s | %s' % (nick, who, d[0], d[1], d[2]))

        del drinks
        del d

# the bot will load these hooks
exports = {
    'PING'    : {'pong':pong_hook},
    'PRIVMSG' : {'join/part':ch_hook, 'q':quit_hook, 'np':lfm_np_hook,
                 'ud':ud_hook, 'reconnect':recon_hook, 'yt':yt_hook,
                 'help':help_hook, 'intro':set_intro_hook, '++/--':pplus_hook,
                 'drink':drink_hook},
    'JOIN'    : {'intro':intro_hook},
    'ERROR'   : {'error':pingout_hook},
    'NOTICE'  : {'join':on_notice_join_hook},
    '433'     : {'nick':nick_hook}
}
