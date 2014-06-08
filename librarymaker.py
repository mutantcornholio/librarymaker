#!/usr/bin/env python
# -*- coding: utf8 -*-
import pyinotify
import argparse
import pylast
import os
import sys
import logging
import shutil
from time import sleep
import simplejson

parser = argparse.ArgumentParser(description='A python script, that organizes your library in tags, using symlinks.\n\
https://github.com/mutantcornholio/librarymaker')
parser.add_argument('-r', '--rebuild', dest='REBUILD', action='store_true',
                    help='rescan existing library, not only watch for new items')
parser.add_argument('-c', '--config-file', dest='CONFIG_PATH', default='~/.librarymakerrc.json',
                    help='choose a different location for a config file')

CONFIG_PATH = os.path.expanduser(parser.parse_args().CONFIG_PATH)
REBUILD = parser.parse_args().REBUILD

if not os.access(CONFIG_PATH, os.R_OK):
    if CONFIG_PATH == os.path.expanduser('~/.librarymakerrc.json'):
        sys.stderr.write('Can\'t work without a config file. Consider creating one in %s, \
or run me with --config-file argument\n' % os.path.expanduser('~/.librarymakerrc.json'))
    else:
        sys.stderr.write('%s: No such file or permission was denied\n' % CONFIG_PATH)
    exit()

if not os.access(CONFIG_PATH, os.W_OK):
    sys.stderr.write('%s: you do not seem to have write rights to config file\
located in \n' % CONFIG_PATH)
    exit()

try:
    config = simplejson.loads(open(CONFIG_PATH, 'r').read())
    WATCH_DIR = os.path.normpath(config['WATCH_DIR'])
    DEST_DIR = os.path.normpath(config['DEST_DIR'])
    LOG_FILE = os.path.normpath(config['LOG_FILE'])
    IGNORE_LIST = config['IGNORE_LIST']
    RETRY_INTERVAL = float(config['RETRY_INTERVAL'])
    POPULARITY_THRESHOLD = float(config['POPULARITY_THRESHOLD'])
    COMPILATIONS = bool(config['COMPILATIONS'])
    API_KEY = config['API_KEY']
    DEFAULT_DELIMITER = config['DEFAULT_DELIMITER']
except simplejson.decoder.JSONDecodeError, e:
    sys.stderr.write('Something\'s wrong with your config file: %s. Exiting.\n' % e.message)
    exit()
except KeyError, e:
    sys.stderr.write('%s is missing in your config file. Exiting.\n' % e.message)
    exit()
except ValueError, e:
    sys.stderr.write('There\'s a problem in your config file: %s. Exiting.\n' % e.message)
    exit()

if not os.path.isdir(WATCH_DIR):
    sys.stderr.write('%s do not exist or not a directory, exiting\n' % WATCH_DIR)
    exit()

if not os.path.isdir(DEST_DIR):
    sys.stderr.write('%s do not exist or not a directory, exiting\n' % DEST_DIR)
    exit()

if not os.access(DEST_DIR, os.W_OK):
    sys.stderr.write('you do not seem to have write rights to this destination directory: "%s", exiting \n' % DEST_DIR)
    exit()

if not os.access(LOG_FILE, os.W_OK):
    sys.stderr.write('you do not seem to have write rights to this log file: "%s", exiting \n' % LOG_FILE)
    exit()

network = pylast.LastFMNetwork(api_key=API_KEY)


def config_write():
    dump = {
        'WATCH_DIR': WATCH_DIR,
        'DEST_DIR': DEST_DIR,
        'LOG_FILE': LOG_FILE,
        'IGNORE_LIST': IGNORE_LIST,
        'RETRY_INTERVAL': RETRY_INTERVAL,
        'POPULARITY_THRESHOLD': POPULARITY_THRESHOLD,
        'COMPILATIONS': COMPILATIONS,
        'API_KEY': API_KEY,
        'DEFAULT_DELIMITER': DEFAULT_DELIMITER
    }
    open(CONFIG_PATH, 'w').write(simplejson.dumps(dump))
    logging.info('config file has been updated')


tags = {}
# smth like {'unified_name_1':{'object'=tag_object, 'artists'=[Artist1, Artist2]}}
artists = []


class Tag(object):
    def __init__(self, name, weight):
        self.name = name
        self.unified_name = name.replace('-', '').replace(' ', '')
        self.good_name = name
        self.weight = weight
        self.directory = ''
        self.directory_made = False

    @staticmethod
    def __count_valid_name(names):
        """takes possible tag names, to calculate best from them"""
        best = names[0]
        delimeters = [' ','-']
        for name in names[1:]:
            pos = 0
            overhead = 0
            while pos < len(name):
                if len(best) == pos:
                    best += name[pos + overhead]
                elif best[pos] == DEFAULT_DELIMITER:
                    overhead += 1
                elif best[pos] in delimeters:
                    best = best[:pos] + DEFAULT_DELIMITER + best[pos+1:]
                elif len(name) > pos + overhead and name[pos + overhead] in delimeters:
                    best = best[:pos] + DEFAULT_DELIMITER + best[pos:]
                pos += 1

        return best

    def __update_dir(self):
        good_dir = os.path.join(DEST_DIR, self.good_name)

        if good_dir == self.directory:
            return

        if not os.access(good_dir, os.F_OK):
            self.directory = good_dir
            try:
                os.makedirs(self.directory)
                self.directory_made = True
                return
            except Exception as e:
                logging.exception(e)
                raise e
        elif not os.path.isdir(good_dir):
            logging.error('__update_dir() failed: %s exists, but not a directory' % good_dir)
            return
        elif self.directory == '':
            self.directory = good_dir
            return

        for item in os.listdir(self.directory):
            try:
                shutil.move(os.path.join(self.directory, item), os.path.join(good_dir, item))
            except Exception as e:
                logging.exception(e)
                raise e

        try:
            os.rmdir(self.directory)
        except Exception as e:
            logging.exception(e)
            raise e

        self.directory = good_dir
        logging.info('%s is renamed to %s' % (self.name, self.good_name))

    def update_name(self, candidate):
        """takes another name for tag, calculates best, changes directory, if needed"""
        if candidate == self.good_name:
            return
        else:
            possible_name = self.__count_valid_name([self.good_name, candidate])
            if possible_name != self.good_name:
                self.good_name = possible_name
                self.__update_dir()

    def make_dir(self):
        directory = os.path.join(DEST_DIR, self.good_name)
        if os.access(directory, os.F_OK):
            if not (os.path.isdir(directory)
                    and os.access(directory, os.W_OK)):
                logging.warning('%s is already exist, but it is not a directory \
or you don\'t have enough rights. Ignoring' % directory)
                self.directory_made = False
            else:
                self.directory_made = True
        else:
            self.directory = directory
            os.makedirs(self.directory)
            self.directory_made = True
            logging.info('new tag: %s' % self.good_name)


class Artist(object):
    def __tags_fetch(self):
        self.tags = []
        while True:
            try:
                top_tags = self.raw.get_top_tags(limit=10)
                break
            except pylast.WSError as e:
                if e.details == 'The artist you supplied could not be found':
                    logging.info('no such artist in last.fm: "%s"' % self.name)
                    self.tags.append(Tag(name=u'untagged', weight=100))
                    return
                else:
                    raise
            except pylast.NetworkError:
                logging.error('Network error')
                sleep(RETRY_INTERVAL)
        for tag in top_tags:
            self.tags.append(Tag(tag.item.name.lower(), int(tag.weight)))

    def __tags_calculate(self):
        self.popular_tags = []
        previous_weight = 0
        for tag in self.tags:
            if tag.name in IGNORE_LIST:
                continue
            if previous_weight == 0:
                self.popular_tags.append(tag)
                previous_weight = tag.weight
            else:
                if tag.weight < previous_weight * POPULARITY_THRESHOLD:
                    break
                else:
                    self.popular_tags.append(tag)

    def __associate_tags(self):
        self.associated_tags = []
        for tag in self.popular_tags:
            if tag.unified_name in tags.keys():
                tags[tag.unified_name]['artists'].append(self)
                tags[tag.unified_name]['object'].update_name(tag.name)
            else:
                tags[tag.unified_name] = {'object': tag, 'artists': [self]}
            self.associated_tags.append(tags[tag.unified_name]['object'])

    def __make_ln(self):
        for tag in self.associated_tags:
            artist_dir = os.path.join(DEST_DIR, tag.good_name, self.name)
            if tag.directory_made:
                try:
                    os.symlink(os.path.join(WATCH_DIR, self.name), artist_dir)
                except OSError as e:
                    #symlink could already exist, if artist has two similar tags
                    if e.errno != 17:
                        raise
                logging.info('artist %s was tagged as %s' % (self.name, tag.name))
            else:
                tag.make_dir()
                if tag.directory_made:
                    if not os.access(artist_dir, os.F_OK):
                        os.symlink(os.path.join(WATCH_DIR, self.name), artist_dir)
                        logging.info('artist %s was tagged as %s' % (self.name, tag.name))
                    elif os.path.islink(artist_dir):
                        if not os.path.samefile(os.readlink(artist_dir), os.path.join(WATCH_DIR, self.name)):
                            logging.warning('%s is a symlink, but \
it is leading to %s instead of %s' % artist_dir, os.readlink(artist_dir), os.path.join(WATCH_DIR, self.name))
                else:
                    logging.warning('can\'t make directory, something\'s wrong, \
something\'s not quite right: %s' % os.path.join(WATCH_DIR, self.name))

    def __init__(self, name):
        self.name = name
        self.raw = pylast.Artist(name, network)
        self.__tags_fetch()
        self.__tags_calculate()
        self.__associate_tags()
        self.__make_ln()

    def delete(self):
        for tag in self.popular_tags:
            if tag.unified_name in tags.keys():
                tags[tag.unified_name]['artists'].remove(self)
                path = os.path.join(DEST_DIR,
                                    tags[tag.unified_name]['object'].good_name,
                                    self.name)
                try:
                    os.unlink(path)
                except Exception as e:
                    logging.exception(e)
                    logging.error('could not unlink %s' % path)
        artists.remove(self)


class VA(object):
    def __init__(self, name):
        self.name = name


class EventHandler(pyinotify.ProcessEvent):
    watching_events = pyinotify.IN_CREATE | pyinotify.IN_DELETE

    def tell_me_bout_watch(self, watch_manager, watches):
        self.watch_manager = watch_manager
        self.watches = watches

    def __add_watch(self, path):
        self.watches.update(self.watch_manager.add_watch(path, self.watching_events, rec=False))
        logging.debug('watch added: %s, wd is %s' % (path, self.watches[path]))

    def __untag_artist_manual(self, path):
        pass

    @staticmethod
    def __block_tag(path):
        tag = os.path.basename(path)
        IGNORE_LIST.append(tag)
        logging.info('"%s" tag has been added to ingnore list' % tag)
        config_write()
        tags.pop(tag.replace('-', '').replace(' ', ''), None)

    @staticmethod
    def __del_artist_from_tag(link):
        """used in __artist_delete(), not supposed to be used manually"""
        try:
            os.unlink(link)
            logging.info('%s has been removed from %s' %
                         (os.path.basename(link),
                          os.path.basename(os.path.dirname(link))))
        except Exception, e:
            logging.error('Can\'t remove %s: %s' % (link, e.message))

    def __event_path_determine(self, path):
        if os.path.dirname(path) == WATCH_DIR:
            self.event_type = 'artist'
        elif os.path.dirname(path) == DEST_DIR:
            self.event_type = 'tag'
        elif os.path.dirname(os.path.dirname(path)) == DEST_DIR:
            self.event_type = 'tag-artist'
        else:
            self.event_type = 'invalid'

    @staticmethod
    def __artist_create(path):
        if os.path.isdir(path):
            artists.append(Artist(str.decode(os.path.basename(path), 'utf8')))
        else:
            logging.info('%s appeared, but it is not a directory. Ignoring.'
                         % os.path.basename(path))

    def __artist_delete(self, path):
        logging.info('%s has been deleted' % path)
        for tag in os.listdir(DEST_DIR):
            tag = os.path.join(DEST_DIR, tag)
            if os.path.isdir(tag):
                for artist in os.listdir(tag):
                    artist = os.path.join(tag, artist)
                    if os.path.islink(artist) and \
                            os.path.join(WATCH_DIR, path) == os.readlink(artist):
                        self.__del_artist_from_tag(artist)
        pass

    def process_IN_CREATE(self, event):
        self.__event_path_determine(event.pathname)
        if self.event_type == 'artist':
            self.__artist_create(event.pathname)
        elif self.event_type == 'tag':
            self.__add_watch(event.pathname)

    def process_IN_DELETE(self, event):
        logging.debug('%s has been deleted' % event.pathname)
        self.__event_path_determine(event.pathname)
        if self.event_type == 'artist':
            self.__artist_delete(event.pathname)
        elif self.event_type == 'tag':
            self.__block_tag(event.pathname)
        elif self.event_type == 'tag-artist':
            self.__untag_artist_manual(os.path.basename(event.pathname))


def kill_zombie_musicians(folder):
    for item in os.listdir(folder):
        item = os.path.join(folder, item)
        if os.path.islink(item) and not os.access(os.readlink(item), os.F_OK):
            os.unlink(item)
            logging.info('%s has been removed from %s' % (os.path.basename(item), os.path.basename(folder)))


def rebuild():
    for item in os.listdir(DEST_DIR):
        kill_zombie_musicians(os.path.join(DEST_DIR, item))
    artist_names = map(lambda s: s.decode('utf8', errors='ignore'), os.listdir(WATCH_DIR))
    global artists
    artists = map(Artist, artist_names)
    logging.info('rebuild done')


    logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s', filename=LOG_FILE, level=logging.DEBUG)
watches = {}
watch_manager = pyinotify.WatchManager()
watching_events = pyinotify.IN_CREATE | pyinotify.IN_DELETE
handler = EventHandler()
notifier = pyinotify.Notifier(watch_manager, handler)
handler.tell_me_bout_watch(watch_manager, watches)
watches.update(watch_manager.add_watch(WATCH_DIR, watching_events, rec=False))
watches.update(watch_manager.add_watch(DEST_DIR, watching_events, rec=False))

for path in os.listdir(DEST_DIR):
    path = os.path.join(DEST_DIR, path)
    if os.path.isdir(path):
        watches.update(watch_manager.add_watch(path, watching_events, rec=False))
        #valid_tags.append(Tag(os.path.basename(path), 1))
        logging.debug('watch added: %s, wd is %s' % (path, watches[path]))

if REBUILD:
    rebuild()

notifier.loop()